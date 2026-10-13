"""Shop Copilot: a chat agent that answers questions about the shop and acts
through tools, with every write going to the human Approval Inbox.

Two brains, same tools:
  * ``ChatModel`` - a local LLM (LM Studio or Ollama, both via their
    OpenAI-compatible ``/v1/chat/completions`` endpoint) that picks tools
    itself in a loop (function calling).
  * ``RuleCopilot`` - a keyword router used when the provider is ``fake`` or
    the model is unreachable, so the demo never breaks.  Its answers are
    honestly marked ``mode="rules"``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Customer
from app.agents.copilot_tools import TOOLS, run_tool, inr

logger = logging.getLogger(__name__)

MAX_STEPS = 6
MAX_HISTORY = 12

COPILOT_SYSTEM_PROMPT = (
    "You are ShopMind Copilot, an assistant for the owner of an Indian WooCommerce "
    "store. Answer questions about customers, orders and revenue by calling the "
    "tools; never guess numbers. All money is Indian rupees: write amounts with "
    "the ₹ symbol and Indian grouping (₹1,23,456). You cannot change data "
    "directly: propose_segment_change, draft_follow_up_email and flag_order_issue "
    "only create pending proposals that the owner approves in the Approval Inbox. "
    "Say so when you use them. Look up a customer_id with search_customers before "
    "acting on a customer. Keep replies short and plain, no markdown tables."
)


# ── Result types ──────────────────────────────────────────────────────────

@dataclass
class Step:
    tool: str
    args: dict
    result: dict

    def to_dict(self) -> dict:
        return {"tool": self.tool, "args": self.args, "result": self.result,
                "writes": bool(TOOLS.get(self.tool) and TOOLS[self.tool].writes)}


@dataclass
class CopilotReply:
    reply: str
    steps: list[Step] = field(default_factory=list)
    mode: str = "rules"          # "llm" or "rules"
    model: str | None = None
    note: str | None = None      # e.g. why we fell back to rules

    @property
    def proposals_created(self) -> list[int]:
        return [s.result["proposal_id"] for s in self.steps
                if isinstance(s.result, dict) and s.result.get("created") and s.result.get("proposal_id")]

    def to_dict(self) -> dict:
        return {
            "reply": self.reply,
            "steps": [s.to_dict() for s in self.steps],
            "proposals_created": self.proposals_created,
            "mode": self.mode,
            "model": self.model,
            "note": self.note,
        }


# ── LLM brain ─────────────────────────────────────────────────────────────

class ChatModel(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> tuple[dict, str | None]:
        """Return (assistant message dict, model id)."""
        ...


class OpenAICompatChat:
    """POST /chat/completions with tools; works for LM Studio and Ollama /v1."""

    def __init__(self, base_url: str, model: str, timeout: int | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout or max(settings.llm_timeout_seconds, 60)

    def complete(self, messages, tools):
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            json={"model": self.model, "messages": messages, "tools": tools,
                  "tool_choice": "auto", "temperature": 0.2, "stream": False},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        return msg, data.get("model") or self.model


def get_chat_model() -> ChatModel | None:
    """The configured tool-calling model, or None for rules-only mode."""
    if settings.llm_provider == "lmstudio":
        return OpenAICompatChat(settings.lmstudio_base_url, settings.lmstudio_model)
    if settings.llm_provider == "ollama":
        return OpenAICompatChat(settings.ollama_base_url.rstrip("/") + "/v1", settings.ollama_model)
    return None


def _parse_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw or "{}")
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {}


def run_llm_copilot(db: Session, history: list[dict], model: ChatModel) -> CopilotReply:
    messages = [{"role": "system", "content": COPILOT_SYSTEM_PROMPT}, *history]
    tools = [t.schema() for t in TOOLS.values()]
    steps: list[Step] = []
    model_id = None
    for _ in range(MAX_STEPS):
        msg, model_id = model.complete(messages, tools)
        calls = msg.get("tool_calls") or []
        if not calls:
            text = (msg.get("content") or "").strip()
            if not text:
                raise ValueError("model returned an empty reply")
            return CopilotReply(reply=text, steps=steps, mode="llm", model=model_id)
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for i, call in enumerate(calls):
            fn = call.get("function") or {}
            name, args = fn.get("name", ""), _parse_args(fn.get("arguments"))
            result = run_tool(db, name, args)
            steps.append(Step(name, args, result))
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id") or f"call_{len(steps)}_{i}",
                "name": name,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })
    return CopilotReply(
        reply="I ran out of steps on that one. Try asking a narrower question.",
        steps=steps, mode="llm", model=model_id,
    )


# ── Rules brain (offline fallback) ────────────────────────────────────────

STATUS_WORDS = {
    "failed": "failed", "refund": "refunded", "cancel": "cancelled",
    "on hold": "on-hold", "on-hold": "on-hold", "pending order": "pending",
    "processing": "processing", "completed": "completed",
}
SEGMENT_WORDS = {"vip": "vip", "at risk": "at_risk", "at-risk": "at_risk", "regular": "regular", "new": "new"}


def _mentioned_customer(db: Session, text: str) -> Customer | None:
    low = text.lower()
    for c in db.query(Customer).all():
        names = [c.email.lower(), c.full_name.lower(), (c.first_name or "").lower()]
        if any(n and re.search(rf"\b{re.escape(n)}\b", low) for n in names):
            return c
    return None


class RuleCopilot:
    """Keyword intent router over the same tools; no model needed."""

    def run(self, db: Session, text: str) -> CopilotReply:
        low = text.lower()
        steps: list[Step] = []

        def call(name, **args):
            res = run_tool(db, name, args)
            steps.append(Step(name, args, res))
            return res

        who = _mentioned_customer(db, low)

        # Writes first: they are the most specific intents.
        if who and re.search(r"\b(email|mail|write|draft|message)\b", low):
            first = who.first_name or who.full_name
            thanks = "thank" in low
            res = call("draft_follow_up_email", customer_id=who.id,
                       subject=f"Thank you, {first}!" if thanks else f"A quick hello from our store, {first}",
                       body=(f"Hi {first},\n\nThank you for shopping with us. We'd love to hear how your "
                             f"recent order went, and if anything wasn't right, just reply to this email.\n\n"
                             f"Warm regards,\nThe Store Team"),
                       reason=f"Requested in copilot chat: {text.strip()[:120]}")
            return self._done(steps, self._write_text(res, f"an email draft for {who.full_name}"))

        seg = next((v for k, v in SEGMENT_WORDS.items() if re.search(rf"\b{k}\b", low)), None)
        if who and seg and re.search(r"\b(make|move|mark|set|change|upgrade|promote)\b", low):
            res = call("propose_segment_change", customer_id=who.id, new_segment=seg,
                       reason=f"Requested in copilot chat: {text.strip()[:120]}")
            return self._done(steps, self._write_text(res, f"a proposal to move {who.full_name} to {seg}"))

        order_no = re.search(r"#?(\d{3,})", low)
        if order_no and re.search(r"\b(flag|investigate|check)\b", low):
            res = call("flag_order_issue", woo_order_id=int(order_no.group(1)), issue_type="manual_review",
                       note=f"Requested in copilot chat: {text.strip()[:120]}")
            return self._done(steps, res.get("error") or self._write_text(res, f"a review request for order #{order_no.group(1)}"))

        if who:
            res = call("get_customer", customer_id=who.id)
            last = res["recent_orders"][0] if res["recent_orders"] else None
            txt = (f"{res['name']} is {res['segment']} with {res['order_count']} orders and "
                   f"{inr(res['total_spent_inr'])} spent.")
            if last:
                txt += f" Latest order #{last['woo_order_id']} is {last['status']} ({inr(last['total_inr'])})."
            if res["pending_proposals"]:
                txt += f" {len(res['pending_proposals'])} proposal(s) for them are waiting for approval."
            return self._done(steps, txt)

        status = next((v for k, v in STATUS_WORDS.items() if k in low), None)
        if status and "order" in low or status in ("failed", "refunded", "cancelled"):
            res = call("list_orders", status=status, limit=10)
            if not res["count"]:
                return self._done(steps, f"No {status} orders right now.")
            lines = "; ".join(f"#{o['woo_order_id']} {o['customer']} {inr(o['total_inr'])}" for o in res["orders"][:5])
            return self._done(steps, f"{res['count']} {status} order(s), {inr(res['total_inr'])} in total: {lines}.")

        if re.search(r"\b(top|best|biggest|highest|vip|at risk|at-risk|customers?)\b", low):
            res = call("search_customers", segment=seg if seg in ("vip", "at_risk") else None,
                       sort_by="total_spent", limit=5)
            if not res["count"]:
                return self._done(steps, "No customers match that yet.")
            lines = "; ".join(f"{c['name']} {inr(c['total_spent_inr'])} ({c['segment']})" for c in res["customers"])
            return self._done(steps, f"Top customers by spend: {lines}.")

        if re.search(r"\b(approv|pending|inbox|proposal)", low):
            res = call("list_pending_proposals", limit=5)
            lines = "; ".join(p["title"] for p in res["proposals"])
            return self._done(steps, f"{res['total_pending']} proposal(s) waiting for you. Newest: {lines}." if res["total_pending"] else "Your Approval Inbox is empty.")

        res = call("shop_stats")
        return self._done(steps, (
            f"{res['orders']} orders and {inr(res['revenue_inr'])} revenue so far "
            f"(avg order {inr(res['avg_order_inr'])}), {res['customers']} customers, "
            f"{res['pending_approvals']} proposals waiting for approval."
        ))

    @staticmethod
    def _write_text(res: dict, what: str) -> str:
        if res.get("error"):
            return res["error"]
        if res.get("created"):
            return f"Done. I sent {what} to your Approval Inbox (proposal #{res['proposal_id']}). Nothing changes until you approve it."
        return res.get("note", "Nothing to do.")

    @staticmethod
    def _done(steps, text) -> CopilotReply:
        return CopilotReply(reply=text, steps=steps, mode="rules")


# ── Entry point ───────────────────────────────────────────────────────────

def chat(db: Session, history: list[dict], model: ChatModel | None = "default") -> CopilotReply:
    """Answer the last user message in ``history`` ([{role, content}, ...])."""
    history = [m for m in history if m.get("role") in ("user", "assistant") and m.get("content")][-MAX_HISTORY:]
    if not history or history[-1]["role"] != "user":
        raise ValueError("The last message must be from the user.")
    if model == "default":
        model = get_chat_model()
    if model is not None:
        try:
            return run_llm_copilot(db, history, model)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            logger.warning("Copilot LLM failed (%s: %s); using rules", type(e).__name__, e)
            db.rollback()
            out = RuleCopilot().run(db, history[-1]["content"])
            out.note = "Local model unreachable, answered with built-in rules."
            return out
    return RuleCopilot().run(db, history[-1]["content"])
