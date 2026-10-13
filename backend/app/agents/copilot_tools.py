"""Tools the Shop Copilot can call.

Read tools query the CRM. Write tools never change customer data directly:
they only create a *pending proposal* in the Approval Inbox, so a human
approves every action.  There is deliberately no tool that approves,
rejects or executes a proposal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Callable

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import (
    Customer, CustomerSegment, Order, OrderStatus, Proposal, ProposalStatus, ProposalType,
)
from app.services.proposal_service import create_proposal

COPILOT_AGENT = "shop_copilot"


class ToolError(ValueError):
    """Bad tool arguments; the message is shown back to the model."""


def inr(amount: float | int | None) -> str:
    """₹ with Indian digit grouping, no paise: 123456 -> ₹1,23,456."""
    n = int(round(amount or 0))
    sign, s = ("-" if n < 0 else ""), str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return f"{sign}₹{s}"


def _customer_brief(c: Customer) -> dict:
    return {
        "customer_id": c.id,
        "name": c.full_name,
        "email": c.email,
        "segment": c.segment.value if c.segment else None,
        "order_count": c.order_count,
        "total_spent_inr": round(c.total_spent or 0, 2),
        "last_order_date": c.last_order_date.date().isoformat() if c.last_order_date else None,
    }


def _order_brief(o: Order) -> dict:
    return {
        "woo_order_id": o.woo_order_id,
        "customer_id": o.customer_id,
        "customer": o.customer.full_name if o.customer else None,
        "status": o.status.value if o.status else None,
        "total_inr": round(o.total or 0, 2),
        "date": (o.woo_created_at or o.created_at).date().isoformat()
        if (o.woo_created_at or o.created_at) else None,
        "items": [li.get("name") for li in (o.line_items or []) if isinstance(li, dict)],
    }


def _proposal_brief(p: Proposal) -> dict:
    return {
        "proposal_id": p.id,
        "type": p.proposal_type.value,
        "title": p.title,
        "customer_id": p.customer_id,
        "agent": p.agent_name,
        "status": p.status.value,
    }


def find_customer(db: Session, customer_id: Any = None, name_or_email: str | None = None) -> Customer:
    """Resolve a customer by id, email, or (partial) name."""
    if customer_id not in (None, ""):
        try:
            c = db.get(Customer, int(customer_id))
        except (TypeError, ValueError):
            c = None
        if c:
            return c
    q = (name_or_email or "").strip()
    if not q and isinstance(customer_id, str):
        q = customer_id.strip()
    if q:
        like = f"%{q.lower()}%"
        matches = (
            db.query(Customer)
            .filter(or_(
                func.lower(Customer.email) == q.lower(),
                func.lower(Customer.first_name + " " + Customer.last_name).like(like),
                func.lower(Customer.first_name).like(like),
                func.lower(Customer.last_name).like(like),
            ))
            .all()
        )
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(f"{m.full_name} (id {m.id})" for m in matches[:5])
            raise ToolError(f"More than one customer matches '{q}': {names}. Use customer_id.")
    raise ToolError("Customer not found. Use search_customers first to get a customer_id.")


# ── Read tools ────────────────────────────────────────────────────────────

def shop_stats(db: Session, days: int | None = None) -> dict:
    orders_q = db.query(Order)
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=int(days))
        orders_q = orders_q.filter(Order.created_at >= since)
    orders = orders_q.all()
    by_status: dict[str, int] = {}
    for o in orders:
        by_status[o.status.value] = by_status.get(o.status.value, 0) + 1
    good = [o for o in orders if o.status not in (OrderStatus.REFUNDED, OrderStatus.CANCELLED, OrderStatus.FAILED)]
    revenue = sum(o.total or 0 for o in good)
    segments = dict(
        (seg.value, n) for seg, n in
        db.query(Customer.segment, func.count(Customer.id)).group_by(Customer.segment).all()
    )
    pending = db.query(func.count(Proposal.id)).filter(Proposal.status == ProposalStatus.PENDING).scalar() or 0
    return {
        "period": f"last {days} days" if days else "all time",
        "orders": len(orders),
        "orders_by_status": by_status,
        "revenue_inr": round(revenue, 2),
        "revenue_note": "excludes refunded, cancelled and failed orders",
        "avg_order_inr": round(revenue / len(good), 2) if good else 0,
        "customers": db.query(func.count(Customer.id)).scalar() or 0,
        "customers_by_segment": segments,
        "pending_approvals": pending,
    }


def search_customers(
    db: Session, query: str | None = None, segment: str | None = None,
    sort_by: str = "total_spent", limit: int = 5,
) -> dict:
    q = db.query(Customer)
    if segment:
        try:
            q = q.filter(Customer.segment == CustomerSegment(segment.lower()))
        except ValueError:
            raise ToolError(f"Unknown segment '{segment}'. Use one of: new, regular, vip, at_risk.")
    if query:
        like = f"%{query.lower()}%"
        q = q.filter(or_(
            func.lower(Customer.email).like(like),
            func.lower(Customer.first_name + " " + Customer.last_name).like(like),
        ))
    order_col = {
        "total_spent": Customer.total_spent.desc(),
        "order_count": Customer.order_count.desc(),
        "last_order": Customer.last_order_date.desc(),
        "least_recent": Customer.last_order_date.asc(),
    }.get(sort_by, Customer.total_spent.desc())
    rows = q.order_by(order_col).limit(max(1, min(int(limit or 5), 25))).all()
    return {"count": len(rows), "customers": [_customer_brief(c) for c in rows]}


def get_customer(db: Session, customer_id: Any = None, name_or_email: str | None = None) -> dict:
    c = find_customer(db, customer_id, name_or_email)
    recent = sorted(c.orders, key=lambda o: o.created_at or datetime.min, reverse=True)[:5]
    pending = [p for p in c.proposals if p.status == ProposalStatus.PENDING]
    return {
        **_customer_brief(c),
        "recent_orders": [_order_brief(o) for o in recent],
        "pending_proposals": [_proposal_brief(p) for p in pending],
    }


def list_orders(
    db: Session, status: str | None = None, customer_id: Any = None,
    days: int | None = None, limit: int = 10,
) -> dict:
    q = db.query(Order)
    if status:
        try:
            q = q.filter(Order.status == OrderStatus(status.lower()))
        except ValueError:
            valid = ", ".join(s.value for s in OrderStatus)
            raise ToolError(f"Unknown status '{status}'. Use one of: {valid}.")
    if customer_id not in (None, ""):
        q = q.filter(Order.customer_id == find_customer(db, customer_id).id)
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=int(days))
        q = q.filter(Order.created_at >= since)
    rows = q.order_by(Order.created_at.desc()).limit(max(1, min(int(limit or 10), 50))).all()
    return {
        "count": len(rows),
        "total_inr": round(sum(o.total or 0 for o in rows), 2),
        "orders": [_order_brief(o) for o in rows],
    }


def list_pending_proposals(db: Session, type: str | None = None, limit: int = 10) -> dict:
    q = db.query(Proposal).filter(Proposal.status == ProposalStatus.PENDING)
    if type:
        try:
            q = q.filter(Proposal.proposal_type == ProposalType(type))
        except ValueError:
            raise ToolError("Unknown type. Use segment_change, follow_up_email or issue_alert.")
    total = q.count()
    rows = q.order_by(Proposal.created_at.desc()).limit(max(1, min(int(limit or 10), 50))).all()
    return {"total_pending": total, "proposals": [_proposal_brief(p) for p in rows]}


# ── Write tools (proposals only, human approves) ──────────────────────────

def _proposed(db: Session, proposal: Proposal | None, what: str) -> dict:
    if proposal is None:
        return {"created": False, "note": f"A pending {what} like this already exists in the Approval Inbox."}
    db.commit()
    return {
        "created": True,
        "proposal_id": proposal.id,
        "status": "pending",
        "note": f"{what.capitalize()} sent to the Approval Inbox. Nothing changes until a human approves it.",
    }


def propose_segment_change(
    db: Session, customer_id: Any, new_segment: str, reason: str = "",
) -> dict:
    c = find_customer(db, customer_id)
    try:
        seg = CustomerSegment(str(new_segment).lower())
    except ValueError:
        raise ToolError("new_segment must be one of: new, regular, vip, at_risk.")
    if c.segment == seg:
        return {"created": False, "note": f"{c.full_name} is already {seg.value}."}
    p = create_proposal(
        db,
        customer_id=c.id,
        proposal_type=ProposalType.SEGMENT_CHANGE,
        title=f"Re-segment {c.full_name}: {c.segment.value} → {seg.value}",
        summary=reason or f"Copilot suggests moving {c.full_name} to {seg.value}.",
        evidence={"source": "copilot chat", **_customer_brief(c)},
        proposed_action={"action": "change_segment", "from": c.segment.value, "to": seg.value},
        agent_name=COPILOT_AGENT,
        llm_explanation=reason,
        dedup_key=f"copilot:segment:{c.id}:{seg.value}",
    )
    return _proposed(db, p, "segment change")


def draft_follow_up_email(
    db: Session, customer_id: Any, subject: str, body: str, reason: str = "",
) -> dict:
    c = find_customer(db, customer_id)
    subject, body = (subject or "").strip(), (body or "").strip()
    if not subject or not body:
        raise ToolError("subject and body are both required.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    p = create_proposal(
        db,
        customer_id=c.id,
        proposal_type=ProposalType.FOLLOW_UP_EMAIL,
        title=f"Copilot email for {c.full_name}: {subject[:60]}",
        summary=reason or "Email drafted from a copilot chat request.",
        evidence={"source": "copilot chat", "trigger": "copilot_request", **_customer_brief(c)},
        proposed_action={
            "action": "send_email",
            "to": c.email,
            "draft": json.dumps({"subject": subject, "body": body}, ensure_ascii=False, indent=2),
        },
        agent_name=COPILOT_AGENT,
        llm_explanation=reason,
        dedup_key=f"copilot:email:{c.id}:{stamp}",
    )
    return _proposed(db, p, "email draft")


def flag_order_issue(db: Session, woo_order_id: Any, issue_type: str = "other", note: str = "") -> dict:
    try:
        oid = int(str(woo_order_id).lstrip("#"))
    except ValueError:
        raise ToolError("woo_order_id must be an order number like 1023.")
    o = db.query(Order).filter(Order.woo_order_id == oid).first()
    if not o:
        raise ToolError(f"Order #{oid} not found.")
    p = create_proposal(
        db,
        customer_id=o.customer_id,
        proposal_type=ProposalType.ISSUE_ALERT,
        title=f"Copilot flagged order #{oid} — {o.customer.full_name if o.customer else ''}".strip(" —"),
        summary=note or f"Copilot flagged order #{oid} for review ({issue_type}).",
        evidence={"source": "copilot chat", "issue_type": issue_type, **_order_brief(o)},
        proposed_action={"action": "investigate_issue", "issue_type": issue_type, "woo_order_id": oid},
        agent_name=COPILOT_AGENT,
        llm_explanation=note,
        dedup_key=f"copilot:issue:{oid}:{issue_type}",
    )
    return _proposed(db, p, "order issue")


# ── Registry (OpenAI-style function schemas) ──────────────────────────────

@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., dict]
    writes: bool = False

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters,
        }}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


_SEGMENTS = {"type": "string", "enum": ["new", "regular", "vip", "at_risk"]}
_CID = {"type": "integer", "description": "customer_id from search_customers or get_customer"}

TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("shop_stats", "Store overview: orders, revenue in rupees, customers by segment, pending approvals.",
         _obj({"days": {"type": "integer", "description": "Only count the last N days; omit for all time"}}),
         shop_stats),
    Tool("search_customers", "Find customers by name/email and/or segment, sorted. Use for 'top customers' questions.",
         _obj({
             "query": {"type": "string"},
             "segment": _SEGMENTS,
             "sort_by": {"type": "string", "enum": ["total_spent", "order_count", "last_order", "least_recent"]},
             "limit": {"type": "integer"},
         }), search_customers),
    Tool("get_customer", "Full profile of one customer with recent orders and pending proposals.",
         _obj({"customer_id": _CID, "name_or_email": {"type": "string"}}), get_customer),
    Tool("list_orders", "List orders, newest first, filtered by status, customer or recent days.",
         _obj({
             "status": {"type": "string", "enum": [s.value for s in OrderStatus]},
             "customer_id": _CID,
             "days": {"type": "integer"},
             "limit": {"type": "integer"},
         }), list_orders),
    Tool("list_pending_proposals", "What is waiting in the Approval Inbox.",
         _obj({"type": {"type": "string", "enum": [t.value for t in ProposalType]}, "limit": {"type": "integer"}}),
         list_pending_proposals),
    Tool("propose_segment_change", "Propose moving a customer to another segment. Creates a pending proposal; a human must approve.",
         _obj({"customer_id": _CID, "new_segment": _SEGMENTS, "reason": {"type": "string"}},
              ["customer_id", "new_segment"]), propose_segment_change, writes=True),
    Tool("draft_follow_up_email", "Draft an email to a customer. Creates a pending proposal; it is only sent after human approval.",
         _obj({"customer_id": _CID, "subject": {"type": "string"}, "body": {"type": "string"},
               "reason": {"type": "string"}}, ["customer_id", "subject", "body"]),
         draft_follow_up_email, writes=True),
    Tool("flag_order_issue", "Flag an order for investigation. Creates a pending issue alert for a human.",
         _obj({"woo_order_id": {"type": "integer"}, "issue_type": {"type": "string"}, "note": {"type": "string"}},
              ["woo_order_id"]), flag_order_issue, writes=True),
]}


def run_tool(db: Session, name: str, args: dict | None) -> dict:
    """Execute a tool by name; errors come back as {"error": ...} for the model."""
    tool = TOOLS.get(name)
    if not tool:
        return {"error": f"Unknown tool '{name}'."}
    try:
        return tool.fn(db, **(args or {}))
    except ToolError as e:
        return {"error": str(e)}
    except TypeError as e:
        return {"error": f"Bad arguments for {name}: {e}"}
