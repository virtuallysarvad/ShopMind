"""ChatGPT (OpenAI API) provider: auth header, no temperature, fallback, copilot."""

import json

import httpx
import pytest

from app.agents import copilot as copilot_module
from app.agents import llm as llm_module
from app.agents.llm import FakeLLM, FallbackLLM, OpenAILLM, get_llm
from app.config import settings


def _fake_post(content, calls, status=200):
    def _post(url, json=None, timeout=None, headers=None):
        calls.append({"url": url, "json": json, "headers": headers or {}})
        req = httpx.Request("POST", url)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "bad key"}}, request=req)
        return httpx.Response(200, json={"model": "gpt-5.4-mini-2026-03-17",
                                         "choices": [{"message": {"role": "assistant", "content": content}}]},
                              request=req)
    return _post


@pytest.fixture
def openai_settings(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_model", "gpt-5.4-mini")


def test_factory_returns_openai_with_fallback(openai_settings):
    client = get_llm()
    assert isinstance(client, FallbackLLM) and isinstance(client.primary, OpenAILLM)


def test_sends_bearer_key_and_no_temperature(openai_settings, monkeypatch):
    calls = []
    monkeypatch.setattr(llm_module.httpx, "post", _fake_post("Alice spent ₹18,000 across 7 orders.", calls))
    res = OpenAILLM().explain_segment({"name": "Alice"}, "vip")
    assert calls[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert "temperature" not in calls[0]["json"]
    assert res.is_llm_generated and res.model == "gpt-5.4-mini-2026-03-17"


def test_email_uses_strict_schema(openai_settings, monkeypatch):
    calls = []
    monkeypatch.setattr(llm_module.httpx, "post", _fake_post('{"subject": "Thanks!", "body": "Hi Alice"}', calls))
    res = OpenAILLM().draft_follow_up({"name": "Alice"}, "first_purchase", {})
    schema = calls[0]["json"]["response_format"]["json_schema"]
    assert schema["strict"] is True and schema["schema"]["additionalProperties"] is False
    assert json.loads(res.text) == {"subject": "Thanks!", "body": "Hi Alice"}


def test_bad_key_falls_back_to_templates(openai_settings, monkeypatch):
    monkeypatch.setattr(llm_module.httpx, "post", _fake_post("", [], status=401))
    res = get_llm().explain_segment({"name": "Alice", "total_spent": 20000, "order_count": 6}, "vip")
    assert res.is_llm_generated is False


def test_copilot_uses_openai_with_key(openai_settings):
    model = copilot_module.get_chat_model()
    assert model.api_key == "sk-test" and model.send_temperature is False


def test_copilot_rules_when_no_key(openai_settings, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert copilot_module.get_chat_model() is None


def test_health_reports_openai(client, openai_settings, monkeypatch):
    monkeypatch.setattr("app.main.openai_reachable", lambda: True)
    h = client.get("/health").json()
    assert h["llm_provider"] == "openai" and h["openai_model"] == "gpt-5.4-mini" and h["openai_reachable"] is True


# ── Groq (free tier, OpenAI-compatible) ────────────────────────────────────

from app.agents.llm import GroqLLM


@pytest.fixture
def groq_settings(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "gsk-test")
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-120b")


def test_groq_factory_and_request(groq_settings, monkeypatch):
    client = get_llm()
    assert isinstance(client.primary, GroqLLM)
    calls = []
    monkeypatch.setattr(llm_module.httpx, "post", _fake_post('{"subject": "Hi", "body": "Thanks"}', calls))
    res = client.draft_follow_up({"name": "Alice"}, "first_purchase", {})
    assert calls[0]["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer gsk-test"
    assert calls[0]["json"]["model"] == "openai/gpt-oss-120b"
    assert res.is_llm_generated


def test_groq_rate_limit_falls_back(groq_settings, monkeypatch):
    monkeypatch.setattr(llm_module.httpx, "post", _fake_post("", [], status=429))
    assert get_llm().explain_issue("payment_failed", {"id": 1}).is_llm_generated is False


def test_groq_copilot_and_health(client, groq_settings, monkeypatch):
    assert copilot_module.get_chat_model().base_url == "https://api.groq.com/openai/v1"
    monkeypatch.setattr("app.main.groq_reachable", lambda: True)
    h = client.get("/health").json()
    assert h["groq_reachable"] is True and h["groq_model"] == "openai/gpt-oss-120b"
