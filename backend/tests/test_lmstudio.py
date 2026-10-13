"""Tests for the LM Studio LLM client (all HTTP is mocked; no real network).

Covered:
  * LMStudioLLM parses a valid /chat/completions response and records the model
  * the prompt carries the deterministic evidence (via the shared helper)
  * draft_follow_up asks for the JSON Schema, parses the response and validates
    {subject, body}
  * bad JSON / missing fields from the draft agent raise ValueError
  * FallbackLLM degrades to FakeLLM on connection error / timeout / HTTP errors
    / bad JSON, with no exception escaping
  * get_llm() returns FallbackLLM(LMStudioLLM, FakeLLM) for provider "lmstudio"
  * lmstudio_reachable() reports true/false
  * /health reports lmstudio_reachable and the loaded model ids when provider is
    "lmstudio"
"""

import hashlib
import hmac
import json

import httpx
import pytest

from app.agents import llm as llm_module
from app.agents.llm import (
    FakeLLM,
    FallbackLLM,
    LMStudioLLM,
    LLMResult,
    get_llm,
    lmstudio_reachable,
)
from app.config import settings
from app.services import pipeline as pipeline_module


COMPLETIONS_URL = "http://localhost:1234/v1/chat/completions"
MODELS_URL = "http://localhost:1234/v1/models"


# ── Helpers ───────────────────────────────────────────────────────────────

def _chat_response(content: str, model: str | None = None) -> httpx.Response:
    """A fake successful /chat/completions response carrying ``content``."""
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-demo",
            "object": "chat.completion",
            "created": 1,
            "model": model or "qwen2.5-7b-instruct",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
        request=httpx.Request("POST", COMPLETIONS_URL),
    )


def _fake_chat(content: str, calls: list | None = None):
    def _post(url, json=None, timeout=None, response_format=None):  # noqa: A002
        assert url == COMPLETIONS_URL
        assert json["model"] == settings.lmstudio_model
        assert json["temperature"] == 0.3
        assert json["stream"] is False
        if calls is not None:
            calls.append(json)
        return _chat_response(content)

    return _post


def _raise(error: Exception):
    def _post(*args, **kwargs):
        raise error

    return _post


# ── LMStudioLLM ───────────────────────────────────────────────────────────

class TestLMStudioLLM:
    def test_parses_valid_chat_completion(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "post", _fake_chat("Alice is a loyal VIP shopper."))

        result = LMStudioLLM().explain_segment(
            {"name": "Alice", "order_count": 6, "total_spent": 900.0}, "vip"
        )

        assert isinstance(result, LLMResult)
        assert result.text == "Alice is a loyal VIP shopper."
        assert result.is_llm_generated is True
        assert result.model == "qwen2.5-7b-instruct"

    def test_response_model_field_wins(self, monkeypatch):
        def _post(url, json=None, timeout=None, response_format=None):  # noqa: A002
            assert url == COMPLETIONS_URL
            return _chat_response("ok", model="lm-studio-custom-model")

        monkeypatch.setattr(llm_module.httpx, "post", _post)

        result = LMStudioLLM().explain_segment({"name": "Alice", "order_count": 1, "total_spent": 0}, "vip")

        # The stub's response carries its own "model" field, and the real LM
        # Studio path reads that trace from the chat completion body.
        assert result.model == "lm-studio-custom-model"

    def test_prompt_carries_deterministic_evidence(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(llm_module.httpx, "post", _fake_chat("ok", calls))

        LMStudioLLM().explain_segment(
            {"name": "Alice", "order_count": 6, "total_spent": 900.0}, "vip"
        )

        prompt = calls[0]["messages"]
        assert prompt[0]["role"] == "system"
        assert prompt[1]["role"] == "user"
        ctx = json.loads(prompt[1]["content"])
        assert ctx["new_segment"] == "vip"
        assert ctx["customer"] == {
            "name": "Alice",
            "order_count": 6,
            "total_spent": 900.0,
        }

    def test_prompt_reuses_shared_helper(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(llm_module.httpx, "post", _fake_chat("ok", calls))

        LMStudioLLM().explain_segment({"name": "Alice", "order_count": 1, "total_spent": 0}, "vip")

        # The helper is the same object used by both providers and is the only
        # code path that formats the user message, so the message produced here
        # must match a call to the same helper constructed independently.
        from app.agents.llm import _chat_messages

        expected = _chat_messages(
            "You write short notes for a WooCommerce store owner. The customer's "
            "segment has ALREADY been decided by deterministic rules; you only explain "
            "it. Use only the facts given in the JSON context and never invent numbers, "
            "orders, dates, discounts or offers. Do not question or change the segment. "
            "Reply with 2-3 sentences of plain prose, no headings or markdown.",
            {"name": "Alice", "order_count": 1, "total_spent": 0},
            "explain_segment",
            {"new_segment": "vip"},
        )
        assert calls[0]["messages"][1]["content"] == expected[1]["content"]


    def test_draft_follow_up_asks_for_json_schema(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(llm_module.httpx, "post", _fake_chat('{"subject": "s", "body": "b"}', calls))

        LMStudioLLM().draft_follow_up({"name": "Alice"}, "win_back", {})

        assert calls[0]["response_format"] == {
            "type": "json_schema",
            "json_schema": {
                "name": "follow_up_email",
                "strict": True,
                "schema": {"type": "object", "properties": {"subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["subject", "body"], "additionalProperties": False},
            },
        }

    def test_draft_follow_up_returns_validated_json(self, monkeypatch):
        monkeypatch.setattr(
            llm_module.httpx,
            "post",
            _fake_chat('{"subject": "Welcome, Alice!", "body": "Thanks for your order."}'),
        )

        result = LMStudioLLM().draft_follow_up({"name": "Alice"}, "new_customer_welcome", {})

        draft = json.loads(result.text)
        assert draft["subject"] == "Welcome, Alice!"
        assert draft["body"] == "Thanks for your order."
        assert result.is_llm_generated is True
        assert result.model == "qwen2.5-7b-instruct"

    def test_draft_follow_up_raises_on_bad_json(self, monkeypatch):
        monkeypatch.setattr(
            llm_module.httpx,
            "post",
            _fake_chat("Sure! Here is your email..."),
        )

        with pytest.raises(ValueError, match="invalid JSON"):
            LMStudioLLM().draft_follow_up({"name": "Alice"}, "win_back", {})

    def test_draft_follow_up_raises_on_missing_fields(self, monkeypatch):
        monkeypatch.setattr(
            llm_module.httpx,
            "post",
            _fake_chat('{"subject": "only a subject"}'),
        )

        with pytest.raises(ValueError, match="subject"):
            LMStudioLLM().draft_follow_up({"name": "Alice"}, "win_back", {})

    def test_empty_response_raises(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "post", _fake_chat("   "))

        with pytest.raises(ValueError, match="empty"):
            LMStudioLLM().explain_segment({"name": "Alice"}, "vip")


# ── FallbackLLM ───────────────────────────────────────────────────────────

class TestLmStudioFallback:
    def _client(self) -> FallbackLLM:
        return FallbackLLM(primary=LMStudioLLM(), fallback=FakeLLM())

    def test_bad_json_falls_back_to_fake(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "post", _fake_chat("not json at all"))

        result = self._client().draft_follow_up(
            {"name": "Test User"}, "new_customer_welcome", {}
        )

        assert result.is_llm_generated is False
        assert result.model is None
        assert "Welcome" in result.text
        assert "Deterministic" in result.text

    def test_connection_error_falls_back_for_every_method(self, monkeypatch):
        monkeypatch.setattr(
            llm_module.httpx,
            "post",
            _raise(httpx.ConnectError("connection refused")),
        )
        client = self._client()

        results = [
            client.explain_segment({"name": "Test User"}, "vip"),
            client.draft_follow_up({"name": "Test User"}, "win_back", {}),
            client.explain_issue("failed_payment", {"woo_order_id": 1}),
        ]

        assert all(r.is_llm_generated is False for r in results)
        assert all(r.model is None for r in results)
        assert all("Deterministic" in r.text for r in results)

    def test_timeout_falls_back(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "post", _raise(httpx.ReadTimeout("timed out")))

        result = self._client().explain_segment({"name": "Test User"}, "at_risk")

        assert result.is_llm_generated is False
        assert result.model is None

    def test_http_error_status_falls_back(self, monkeypatch):
        def _post(url, json=None, timeout=None, response_format=None):  # noqa: A002
            return httpx.Response(
                500,
                text="model not found",
                request=httpx.Request("POST", COMPLETIONS_URL),
            )

        monkeypatch.setattr(llm_module.httpx, "post", _post)

        result = self._client().explain_issue("repeated_return", {"woo_order_id": 7})

        assert result.is_llm_generated is False
        assert "Deterministic" in result.text

    def test_successful_call_is_not_replaced(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "post", _fake_chat("Real model output."))

        result = self._client().explain_issue("failed_payment", {"woo_order_id": 1})

        assert result.text == "Real model output."
        assert result.is_llm_generated is True
        assert result.model == "qwen2.5-7b-instruct"


# ── Factory & reachability ────────────────────────────────────────────────

class TestFactory:
    def test_lmstudio_provider_wraps_lmstudio_with_fake_fallback(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "lmstudio")

        client = get_llm()

        assert isinstance(client, FallbackLLM)
        assert isinstance(client.primary, LMStudioLLM)
        assert isinstance(client.fallback, FakeLLM)

    def test_unknown_provider_is_fake(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "something-else")

        assert isinstance(get_llm(), FakeLLM)


class TestLmStudioReachability:
    def test_true_when_lm_study_answers(self, monkeypatch):
        def _get(url, timeout=None):
            assert url == MODELS_URL
            assert timeout == 2.0
            return httpx.Response(
                200,
                json={"object": "list", "data": [{"id": "qwen2.5-7b-instruct"}]},
                request=httpx.Request("GET", MODELS_URL),
            )

        monkeypatch.setattr(llm_module.httpx, "get", _get)

        assert lmstudio_reachable() is True

    def test_false_when_lm_study_is_down(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "get", _raise(httpx.ConnectError("refused")))

        assert lmstudio_reachable() is False


class TestHealthEndpoint:
    def test_reports_lmstudio_provider(self, client):
        body = client.get("/health").json()

        assert body["status"] == "healthy"
        assert body["llm_provider"] == "fake"
        assert "lmstudio_reachable" not in body  # only probed for the lmstudio provider

    def test_reports_lmstudio_reachability_and_models(self, client, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "lmstudio")
        monkeypatch.setattr(llm_module.httpx, "get", lambda url, timeout=None: httpx.Response(
            200,
            json={"object": "list", "data": [{"id": "qwen2.5-7b-instruct"}, {"id": "qwen2.5-3b"}]},
            request=httpx.Request("GET", MODELS_URL),
        ))

        body = client.get("/health").json()

        assert body["llm_provider"] == "lmstudio"
        assert body["lmstudio_reachable"] is True
        assert body["lmstudio_models"] == ["qwen2.5-7b-instruct", "qwen2.5-3b"]

    def test_reports_unreachable_when_probe_fails(self, client, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "lmstudio")
        monkeypatch.setattr(llm_module.httpx, "get", _raise(httpx.ConnectError("refused")))

        body = client.get("/health").json()

        assert body["llm_provider"] == "lmstudio"
        assert body["lmstudio_reachable"] is False
        assert body["lmstudio_models"] == []
