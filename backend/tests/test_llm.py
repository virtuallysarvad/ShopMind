"""Tests for the LLM layer.

Every HTTP call is mocked — no test here touches the network, and Ollama does
not need to be installed or running.

Covered:
  * OllamaLLM parses a valid /api/chat response and flags it as generated
  * the prompt carries the deterministic evidence and stays non-inventive
  * draft_follow_up validates the {"subject", "body"} JSON and raises on junk
  * FallbackLLM degrades to FakeLLM on bad JSON / connection error / timeout /
    HTTP error status, without letting an exception escape
  * get_llm() picks the right client for each provider
  * the webhook pipeline, with an injected stub LLM, still produces a proposal
    flagged is_llm_generated=True that approve -> execute can carry through
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
    LLMResult,
    OllamaLLM,
    get_llm,
    ollama_reachable,
)
from app.config import settings
from app.services import pipeline as pipeline_module


CHAT_URL = "http://localhost:11434/api/chat"
TAGS_URL = "http://localhost:11434/api/tags"


# ── Helpers ───────────────────────────────────────────────────────────────

def _chat_response(content: str) -> httpx.Response:
    """A fake successful /api/chat response carrying ``content``."""
    return httpx.Response(
        200,
        json={
            "model": "qwen2.5:7b",
            "message": {"role": "assistant", "content": content},
            "done": True,
        },
        request=httpx.Request("POST", CHAT_URL),
    )


def _fake_post(content: str, calls: list | None = None):
    """Return a stand-in for httpx.post that answers /api/chat with ``content``."""

    def _post(url, json=None, timeout=None):  # noqa: A002 - httpx kwarg name
        assert url == CHAT_URL
        assert json["model"] == settings.ollama_model
        assert json["stream"] is False
        assert json["options"] == {"temperature": 0.3}
        if calls is not None:
            calls.append(json)
        return _chat_response(content)

    return _post


def _raise(error: Exception):
    def _post(*args, **kwargs):
        raise error

    return _post


class StubLLM:
    """Injected stand-in for a real model: no network, always 'generated'."""

    def explain_segment(self, customer_data, new_segment):
        return LLMResult("Stub segment explanation", True, "stub-model")

    def draft_follow_up(self, customer_data, trigger, context):
        return LLMResult(
            json.dumps({"subject": "Stub subject", "body": "Stub body"}),
            True,
            "stub-model",
        )

    def explain_issue(self, issue_type, order_data):
        return LLMResult("Stub issue explanation", True, "stub-model")


# ── OllamaLLM ─────────────────────────────────────────────────────────────

class TestOllamaLLM:
    def test_explain_segment_parses_valid_response(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "post", _fake_post("Alice is a loyal VIP shopper."))

        result = OllamaLLM().explain_segment(
            {"name": "Alice", "order_count": 6, "total_spent": 900.0}, "vip"
        )

        assert isinstance(result, LLMResult)
        assert result.text == "Alice is a loyal VIP shopper."
        assert result.is_llm_generated is True
        assert result.model == "qwen2.5:7b"

    def test_prompt_carries_deterministic_evidence(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(llm_module.httpx, "post", _fake_post("ok", calls))

        OllamaLLM().explain_segment(
            {"name": "Alice", "order_count": 6, "total_spent": 900.0}, "vip"
        )

        prompt = calls[0]["messages"][1]["content"]
        context = json.loads(prompt)
        assert context["new_segment"] == "vip"
        assert context["customer"] == {
            "name": "Alice",
            "order_count": 6,
            "total_spent": 900.0,
        }

    def test_draft_follow_up_returns_validated_json(self, monkeypatch):
        monkeypatch.setattr(
            llm_module.httpx,
            "post",
            _fake_post('{"subject": "Welcome, Alice!", "body": "Thanks for your order."}'),
        )

        result = OllamaLLM().draft_follow_up({"name": "Alice"}, "new_customer_welcome", {})

        draft = json.loads(result.text)
        assert draft["subject"] == "Welcome, Alice!"
        assert draft["body"] == "Thanks for your order."
        assert result.is_llm_generated is True

    def test_draft_follow_up_uses_json_format(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(llm_module.httpx, "post", _fake_post('{"subject": "s", "body": "b"}', calls))

        OllamaLLM().draft_follow_up({"name": "Alice"}, "win_back", {})

        assert calls[0]["format"] == "json"

    def test_draft_follow_up_raises_on_bad_json(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "post", _fake_post("Sure! Here is your email..."))

        with pytest.raises(ValueError, match="invalid JSON"):
            OllamaLLM().draft_follow_up({"name": "Alice"}, "win_back", {})

    def test_draft_follow_up_raises_on_missing_fields(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "post", _fake_post('{"subject": "only a subject"}'))

        with pytest.raises(ValueError, match="subject"):
            OllamaLLM().draft_follow_up({"name": "Alice"}, "win_back", {})

    def test_explain_issue_parses_response(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "post", _fake_post("Payment declined."))

        result = OllamaLLM().explain_issue("failed_payment", {"woo_order_id": 42})

        assert result.text == "Payment declined."
        assert result.is_llm_generated is True

    def test_empty_response_raises(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "post", _fake_post("   "))

        with pytest.raises(ValueError, match="empty"):
            OllamaLLM().explain_segment({"name": "Alice"}, "vip")


# ── FallbackLLM ───────────────────────────────────────────────────────────

class TestFallbackLLM:
    def _client(self) -> FallbackLLM:
        return FallbackLLM(primary=OllamaLLM(), fallback=FakeLLM())

    def test_bad_json_falls_back_to_fake(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "post", _fake_post("not json at all"))

        result = self._client().draft_follow_up(
            {"name": "Test User"}, "new_customer_welcome", {}
        )

        assert result.is_llm_generated is False
        assert result.model is None
        assert "Welcome" in result.text
        assert "Deterministic" in result.text

    def test_connection_error_falls_back_for_every_method(self, monkeypatch):
        monkeypatch.setattr(
            llm_module.httpx, "post", _raise(httpx.ConnectError("connection refused"))
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
        def _post(url, json=None, timeout=None):  # noqa: A002 - httpx kwarg name
            return httpx.Response(
                500, text="model not found", request=httpx.Request("POST", CHAT_URL)
            )

        monkeypatch.setattr(llm_module.httpx, "post", _post)

        result = self._client().explain_issue("repeated_return", {"woo_order_id": 7})

        assert result.is_llm_generated is False
        assert "Deterministic" in result.text

    def test_successful_call_is_not_replaced(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "post", _fake_post("Real model output."))

        result = self._client().explain_issue("failed_payment", {"woo_order_id": 1})

        assert result.text == "Real model output."
        assert result.is_llm_generated is True


# ── Factory & health helper ───────────────────────────────────────────────

class TestFactory:
    def test_default_provider_is_fake(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "fake")

        assert isinstance(get_llm(), FakeLLM)

    def test_unknown_provider_is_fake(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "something-else")

        assert isinstance(get_llm(), FakeLLM)

    def test_ollama_provider_wraps_ollama_with_fake_fallback(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "ollama")

        client = get_llm()

        assert isinstance(client, FallbackLLM)
        assert isinstance(client.primary, OllamaLLM)
        assert isinstance(client.fallback, FakeLLM)


class TestReachability:
    def test_true_when_ollama_answers(self, monkeypatch):
        def _get(url, timeout=None):
            assert url == TAGS_URL
            assert timeout == 2.0
            return httpx.Response(200, json={"models": []}, request=httpx.Request("GET", TAGS_URL))

        monkeypatch.setattr(llm_module.httpx, "get", _get)

        assert ollama_reachable() is True

    def test_false_when_ollama_is_down(self, monkeypatch):
        monkeypatch.setattr(llm_module.httpx, "get", _raise(httpx.ConnectError("refused")))

        assert ollama_reachable() is False


class TestHealthEndpoint:
    def test_reports_provider(self, client):
        body = client.get("/health").json()

        assert body["status"] == "healthy"
        assert body["llm_provider"] == "fake"
        assert "ollama_reachable" not in body  # only probed for the ollama provider

    def test_reports_ollama_reachability(self, client, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "ollama")
        monkeypatch.setattr("app.main.ollama_reachable", lambda: False)

        body = client.get("/health").json()

        assert body["llm_provider"] == "ollama"
        assert body["ollama_reachable"] is False


# ── Pipeline with a real (stubbed) LLM ────────────────────────────────────

def _sign(payload: dict):
    body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(
        settings.woo_webhook_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return body, sig


def _order(order_id: int, email: str, total: str = "120.00") -> dict:
    return {
        "id": order_id,
        "status": "processing",
        "total": total,
        "currency": "USD",
        "payment_method": "stripe",
        "billing": {
            "first_name": "Test",
            "last_name": "Buyer",
            "email": email,
            "phone": "555-0000",
        },
        "shipping": {"first_name": "Test", "last_name": "Buyer"},
        "line_items": [
            {"id": 1, "name": "Widget", "product_id": 1, "quantity": 1, "total": total}
        ],
        "date_created": "2026-10-13T10:00:00Z",
        "customer_id": 0,
    }


class TestPipelineWithInjectedLLM:
    def test_webhook_flags_proposal_and_approval_still_executes(self, client, monkeypatch):
        # The webhook resolves its LLM client inside the pipeline module.
        monkeypatch.setattr(pipeline_module, "get_llm", lambda: StubLLM())

        body, sig = _sign(_order(9001, "llm@example.com"))
        resp = client.post(
            "/webhooks/woocommerce/order",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-WC-Webhook-Signature": sig,
            },
        )
        assert resp.status_code == 200

        pending = client.get("/api/proposals", params={"status": "pending"}).json()
        assert len(pending) == 1
        proposal = pending[0]

        # Provenance is recorded honestly and stored for audit
        assert proposal["is_llm_generated"] is True
        assert proposal["evidence"]["llm_model"] == "stub-model"
        assert "Stub subject" in proposal["llm_explanation"]

        # The human approval flow is untouched by the LLM swap
        review = client.post(
            f"/api/proposals/{proposal['id']}/review",
            json={"action": "approve", "reviewed_by": "hackathon-judge"},
        )
        assert review.status_code == 200
        reviewed = review.json()
        assert reviewed["status"] == "executed"
        assert reviewed["executed_at"] is not None
