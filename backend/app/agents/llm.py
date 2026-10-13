"""LLM clients: the human-readable text layer of ShopMind.

Design rule
-----------
Deterministic rules make every decision (segment, trigger, issue type).  The
LLM only writes the human-readable parts:

  * the segment explanation   -> ``explain_segment``
  * the follow-up email draft -> ``draft_follow_up``
  * the issue explanation     -> ``explain_issue``

Every proposal still requires human approval before execution.  Each call
returns an :class:`LLMResult` that records whether the text really came from a
model (``is_llm_generated``) and which model wrote it (``model``), so
rule-based fallback output is never presented as AI content.

Clients
-------
* :class:`FakeLLM`  — deterministic templates, no network (default).
* :class:`OllamaLLM` — local model served by Ollama, no API keys.
* :class:`LMStudioLLM` — local model served by LM Studio's OpenAI-compatible
  API (``/v1/chat/completions``), no API keys.
* :class:`FallbackLLM` — tries a real model, degrades to ``FakeLLM`` on any
  network/timeout/invalid-output error.
* :func:`get_llm` — factory returning the client selected by ``llm_provider``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# ── Result type & client contract ─────────────────────────────────────────

@dataclass
class LLMResult:
    """Text produced for a proposal, with provenance for the audit trail."""

    text: str
    is_llm_generated: bool
    model: str | None = None


class LLMClient(Protocol):
    """Contract implemented by both the real and the fallback LLM."""

    def explain_segment(self, customer_data: dict, new_segment: str) -> LLMResult: ...

    def draft_follow_up(
        self, customer_data: dict, trigger: str, context: dict
    ) -> LLMResult: ...

    def explain_issue(self, issue_type: str, order_data: dict) -> LLMResult: ...


# ── System prompts (kept at module level so they are easy to review) ──────

SEGMENT_SYSTEM_PROMPT = (
    "You write short notes for a WooCommerce store owner. The customer's "
    "segment has ALREADY been decided by deterministic rules; you only explain "
    "it. Use only the facts given in the JSON context and never invent numbers, "
    "orders, dates, discounts or offers. Do not question or change the segment. "
    "Reply with 2-3 sentences of plain prose, no headings or markdown."
)

DRAFT_SYSTEM_PROMPT = (
    "You draft short, warm customer emails for a WooCommerce store. The "
    "follow-up trigger has ALREADY been chosen by deterministic rules. Use only "
    "the facts given in the JSON context and never invent numbers, discounts, "
    "order details, refunds or promises. "
    'Reply with JSON only, exactly of the form {"subject": "...", "body": "..."}.'
)

ISSUE_SYSTEM_PROMPT = (
    "You write short notes for a WooCommerce store owner. A deterministic rule "
    "has ALREADY detected an order issue; you only explain it. Use only the "
    "facts given in the JSON context and never invent numbers or causes beyond "
    "the stated issue type. Reply with 2-3 sentences of plain prose, no headings "
    "or markdown."
)


# ── FakeLLM: deterministic templates ──────────────────────────────────────

class FakeLLM:
    """Deterministic LLM substitute for development and testing.

    Never claims to be model-generated (``is_llm_generated=False``).
    """

    def explain_segment(self, customer_data: dict, new_segment: str) -> LLMResult:
        """Generate a deterministic explanation for a segment classification."""
        name = customer_data.get("name", "Customer")
        order_count = customer_data.get("order_count", 0)
        total_spent = customer_data.get("total_spent", 0)

        explanations = {
            "vip": (
                f"[Deterministic] {name} qualifies as VIP based on "
                f"{order_count} orders totaling ${total_spent:.2f}. "
                f"This exceeds the VIP thresholds of 5+ orders and $500+ total spend."
            ),
            "at_risk": (
                f"[Deterministic] {name} is classified as At-Risk. "
                f"They have prior purchase history but haven't ordered recently, "
                f"indicating potential churn risk."
            ),
            "regular": (
                f"[Deterministic] {name} is a Regular customer with "
                f"{order_count} orders and ${total_spent:.2f} total spend. "
                f"They show consistent but moderate engagement."
            ),
            "new": (
                f"[Deterministic] {name} is a New customer with "
                f"{order_count} order(s). Welcome engagement is recommended."
            ),
        }
        text = explanations.get(new_segment, f"[Deterministic] Segment: {new_segment}")
        return LLMResult(text=text, is_llm_generated=False, model=None)

    def draft_follow_up(
        self, customer_data: dict, trigger: str, context: dict
    ) -> LLMResult:
        """Generate a deterministic follow-up email draft."""
        name = customer_data.get("name", "Valued Customer")

        templates = {
            "new_customer_welcome": (
                f"Subject: Welcome to our store, {name}!\n\n"
                f"Hi {name},\n\n"
                f"Thank you for your first order! We're thrilled to have you.\n"
                f"Your order is being processed and we'll keep you updated.\n\n"
                f"If you have any questions, don't hesitate to reach out.\n\n"
                f"Best regards,\nThe ShopMind Team\n\n"
                f"[Deterministic draft — not generated by a language model]"
            ),
            "vip_thank_you": (
                f"Subject: Thank you for being a VIP, {name}!\n\n"
                f"Hi {name},\n\n"
                f"We truly appreciate your continued loyalty and support. "
                f"As one of our most valued customers, we wanted to personally thank you.\n\n"
                f"Keep an eye out for exclusive offers coming your way!\n\n"
                f"Warmly,\nThe ShopMind Team\n\n"
                f"[Deterministic draft — not generated by a language model]"
            ),
            "order_issue": (
                f"Subject: We're looking into your recent order, {name}\n\n"
                f"Hi {name},\n\n"
                f"We noticed an issue with your recent order and wanted to reach out proactively. "
                f"Our team is looking into it and will follow up shortly.\n\n"
                f"We apologize for any inconvenience.\n\n"
                f"Sincerely,\nThe ShopMind Team\n\n"
                f"[Deterministic draft — not generated by a language model]"
            ),
            "win_back": (
                f"Subject: We miss you, {name}!\n\n"
                f"Hi {name},\n\n"
                f"It's been a while since your last order. "
                f"We'd love to have you back! Check out what's new in our store.\n\n"
                f"As a returning customer, enjoy a special welcome-back offer.\n\n"
                f"Hope to see you soon,\nThe ShopMind Team\n\n"
                f"[Deterministic draft — not generated by a language model]"
            ),
        }
        text = templates.get(
            trigger,
            f"Subject: Following up, {name}\n\n"
            f"Hi {name},\n\nWe wanted to check in regarding your recent activity. "
            f"Please let us know if there's anything we can help with.\n\n"
            f"Best,\nThe ShopMind Team\n\n"
            f"[Deterministic draft — not generated by a language model]"
        )
        return LLMResult(text=text, is_llm_generated=False, model=None)

    def explain_issue(self, issue_type: str, order_data: dict) -> LLMResult:
        """Generate a deterministic explanation for a detected order issue."""
        order_id = order_data.get("woo_order_id", "?")
        explanations = {
            "failed_payment": (
                f"[Deterministic] Order #{order_id} has a failed payment status. "
                f"This typically indicates a payment gateway decline or insufficient funds. "
                f"Proactive outreach is recommended to help the customer complete their purchase."
            ),
            "repeated_return": (
                f"[Deterministic] Customer has multiple refunded/cancelled orders. "
                f"This pattern may indicate product quality issues, sizing problems, "
                f"or unmet expectations. Consider personalized support."
            ),
            "stuck_processing": (
                f"[Deterministic] Order #{order_id} has been in processing status "
                f"without progressing. This may indicate a fulfillment bottleneck."
            ),
        }
        text = explanations.get(
            issue_type,
            f"[Deterministic] Issue detected on order #{order_id}: {issue_type}",
        )
        return LLMResult(text=text, is_llm_generated=False, model=None)


# ── OllamaLLM: real local model over HTTP ─────────────────────────────────

class OllamaLLM:
    """Local LLM via the Ollama HTTP API (no API keys, no paid services).

    Prompts always carry the deterministic evidence as structured JSON and
    instruct the model to use only those facts.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout or settings.llm_timeout_seconds

    def _chat(self, system_prompt: str, context: dict, json_mode: bool = False) -> str:
        """POST /api/chat and return the assistant message content."""
        payload: dict = {
            "model": self.model,
            "messages": _chat_messages(
                system_prompt,
                context.get("customer") or {},
                context.get("task", ""),
                {k: v for k, v in context.items() if k not in {"task", "customer"}},
            ),
            "stream": False,
            "options": {"temperature": 0.3},
        }
        if json_mode:
            payload["format"] = "json"

        response = httpx.post(
            f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
        )
        response.raise_for_status()

        content = (response.json().get("message") or {}).get("content", "")
        if not content or not content.strip():
            raise ValueError("Ollama returned an empty response")
        return content.strip()

    def _result(self, text: str) -> LLMResult:
        return LLMResult(text=text, is_llm_generated=True, model=self.model)

    def explain_segment(self, customer_data: dict, new_segment: str) -> LLMResult:
        context = {
            "task": "explain_segment",
            "customer": customer_data,
            "new_segment": new_segment,
        }
        return self._result(self._chat(SEGMENT_SYSTEM_PROMPT, context))

    def draft_follow_up(
        self, customer_data: dict, trigger: str, context: dict
    ) -> LLMResult:
        prompt_context = {
            "task": "draft_follow_up",
            "customer": customer_data,
            "trigger": trigger,
            "context": context,
        }
        raw = self._chat(DRAFT_SYSTEM_PROMPT, prompt_context, json_mode=True)

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Ollama returned invalid JSON for the email draft: {e}") from e

        if not isinstance(parsed, dict):
            raise ValueError("Ollama draft must be a JSON object")
        subject = str(parsed.get("subject") or "").strip()
        body = str(parsed.get("body") or "").strip()
        if not subject or not body:
            raise ValueError('Ollama draft must contain "subject" and "body"')

        draft = json.dumps({"subject": subject, "body": body}, ensure_ascii=False, indent=2)
        return self._result(draft)

    def explain_issue(self, issue_type: str, order_data: dict) -> LLMResult:
        context = {
            "task": "explain_issue",
            "issue_type": issue_type,
            "order": order_data,
        }
        return self._result(self._chat(ISSUE_SYSTEM_PROMPT, context))


# ── LMStudioLLM: OpenAI-compatible local API ──────────────────────────────

_FOLLOW_UP_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["subject", "body"],
}


class LMStudioLLM:
    """Local LLM via the LM Studio OpenAI-compatible API (no API keys).

    Uses `POST /chat/completions` with `response_format=\"json_schema\"` for the
    follow-up draft.  The same deterministic prompts and evidence as Ollama are
    reused through :func:`_chat_messages`.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        self.base_url = (base_url or settings.lmstudio_base_url).rstrip("/")
        self.model = model or settings.lmstudio_model
        self.timeout = timeout or settings.llm_timeout_seconds

    def _chat(
        self, system_prompt: str, context: dict, json_mode: bool = False
    ) -> tuple[str, str | None]:
        messages = _chat_messages(
            system_prompt,
            context.get("customer") or {},
            context.get("task", ""),
            {k: v for k, v in context.items() if k not in {"task", "customer"}},
        )
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "follow_up_email",
                    "strict": True,
                    "schema": _FOLLOW_UP_JSON_SCHEMA,
                },
            }

        response = httpx.post(
            f"{self.base_url}/chat/completions", json=payload, timeout=self.timeout
        )
        response.raise_for_status()

        completion = response.json()
        message = (completion.get("choices") or [{}])[0].get("message", {})
        content = (message or {}).get("content", "")
        if not content or not content.strip():
            raise ValueError("LM Studio returned an empty response")
        # Return the model the server says produced the text alongside it, so
        # no per-call state is kept on the (shared) client instance.
        return content.strip(), completion.get("model")

    def _result(self, text: str, response_model: str | None = None) -> LLMResult:
        # Prefer the model carried by the chat completion response (the best
        # observable trace of which model produced the text); fall back to the
        # configured model id when the response omits it.
        return LLMResult(
            text=text,
            is_llm_generated=True,
            model=response_model or self.model,
        )

    def explain_segment(self, customer_data: dict, new_segment: str) -> LLMResult:
        context = {
            "task": "explain_segment",
            "customer": customer_data,
            "new_segment": new_segment,
        }
        text, model = self._chat(SEGMENT_SYSTEM_PROMPT, context)
        return self._result(text, model)

    def draft_follow_up(
        self, customer_data: dict, trigger: str, context: dict
    ) -> LLMResult:
        prompt_context = {
            "task": "draft_follow_up",
            "customer": customer_data,
            "trigger": trigger,
            "context": context,
        }
        raw, model = self._chat(DRAFT_SYSTEM_PROMPT, prompt_context, json_mode=True)

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"LM Studio returned invalid JSON for the email draft: {e}"
            ) from e

        if not isinstance(parsed, dict):
            raise ValueError("LM Studio draft must be a JSON object")
        subject = str(parsed.get("subject") or "").strip()
        body = str(parsed.get("body") or "").strip()
        if not subject or not body:
            raise ValueError(
                'LM Studio draft must contain "subject" and "body"'
            )

        draft = json.dumps(
            {"subject": subject, "body": body}, ensure_ascii=False, indent=2
        )
        return self._result(draft, model)

    def explain_issue(self, issue_type: str, order_data: dict) -> LLMResult:
        context = {
            "task": "explain_issue",
            "issue_type": issue_type,
            "order": order_data,
        }
        text, model = self._chat(ISSUE_SYSTEM_PROMPT, context)
        return self._result(text, model)



# ── FallbackLLM: never let the model break order processing ───────────────

class FallbackLLM:
    """Try the primary (real) LLM, fall back to deterministic templates.

    Any HTTP error, timeout, malformed model output or bad JSON is caught,
    logged as a warning and served by the fallback instead — so a stopped
    Ollama or LM Studio server never breaks ingestion or the approval flow, and the proposal is
    honestly flagged as not model-generated.
    """

    def __init__(self, primary: LLMClient, fallback: LLMClient):
        self.primary = primary
        self.fallback = fallback

    def _call(self, method: str, *args) -> LLMResult:
        try:
            return getattr(self.primary, method)(*args)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            logger.warning(
                "LLM call '%s' failed (%s: %s); using deterministic fallback",
                method, type(e).__name__, e,
            )
            return getattr(self.fallback, method)(*args)

    def explain_segment(self, customer_data: dict, new_segment: str) -> LLMResult:
        return self._call("explain_segment", customer_data, new_segment)

    def draft_follow_up(
        self, customer_data: dict, trigger: str, context: dict
    ) -> LLMResult:
        return self._call("draft_follow_up", customer_data, trigger, context)

    def explain_issue(self, issue_type: str, order_data: dict) -> LLMResult:
        return self._call("explain_issue", issue_type, order_data)


# ── Factory & health helper ───────────────────────────────────────────────

def get_llm() -> LLMClient:
    """Return the configured LLM client.

    Defaults to :class:`FakeLLM` so tests and demos stay deterministic and
    offline; ``ollama`` and ``lmstudio`` wrap their respective client with
    ``FakeLLM`` as the fallback.
    """
    if settings.llm_provider == "ollama":
        return FallbackLLM(primary=OllamaLLM(), fallback=FakeLLM())
    if settings.llm_provider == "lmstudio":
        return FallbackLLM(primary=LMStudioLLM(), fallback=FakeLLM())
    return FakeLLM()


def _chat_messages(
    system_prompt: str, customer_data: dict, task: str, context: dict | None = None
) -> list[dict]:
    """Build the two-message payload (system + user) shared by Ollama and LM Studio.

    The user message is the deterministic evidence as JSON, identical for both
    providers so the prompts are byte-for-byte reusable.
    """
    ctx: dict = {
        "task": task,
        "customer": customer_data,
        **(context or {}),
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(ctx, ensure_ascii=False, default=str)},
    ]


def ollama_reachable(base_url: str | None = None, timeout: float = 2.0) -> bool:
    """Cheap liveness probe for the Ollama server (used by /health)."""
    url = (base_url or settings.ollama_base_url).rstrip("/")
    try:
        return httpx.get(f"{url}/api/tags", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


def lmstudio_reachable(base_url: str | None = None, timeout: float = 2.0) -> bool:
    """Cheap liveness probe for an LM Studio server (used by /health)."""
    url = (base_url or settings.lmstudio_base_url).rstrip("/")
    try:
        return httpx.get(f"{url}/models", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False
