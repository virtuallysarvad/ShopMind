"""Manual proposals: a human adds a card to the Approval Inbox by hand.

Same three types the agents create, same pending → approve → execute path,
same WooCommerce write-back. Only the author differs (agent_name="manual").
"""

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Customer, CustomerSegment, Order, Proposal, ProposalType
from app.services.proposal_service import create_proposal

MANUAL_AGENT = "manual"
ISSUE_TYPES = {"payment_failed", "stuck_processing", "refund_requested", "delayed_shipping", "other"}


class ManualProposalError(ValueError):
    """Bad input; status says which HTTP code fits (400 or 404)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _name(c: Customer) -> str:
    return f"{c.first_name} {c.last_name}".strip() or c.email


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")


def create_manual_proposal(db: Session, data) -> Proposal:
    """Create a pending proposal from the New proposal form."""
    ptype = data.proposal_type
    note = (data.note or "").strip()
    by = (data.created_by or "admin").strip() or "admin"
    base_evidence = {"source": "manual entry", "created_by": by}

    if ptype == ProposalType.ISSUE_ALERT:
        if data.woo_order_id is None:
            raise ManualProposalError("Pick the order this issue is about.")
        order = db.query(Order).filter(Order.woo_order_id == data.woo_order_id).first()
        if not order:
            raise ManualProposalError(f"Order #{data.woo_order_id} not found.", 404)
        if data.customer_id is not None and order.customer_id != data.customer_id:
            raise ManualProposalError("That order belongs to a different customer.")
        customer = order.customer
        issue = (data.issue_type or "other").strip()
        if issue not in ISSUE_TYPES:
            raise ManualProposalError(f"issue_type must be one of: {', '.join(sorted(ISSUE_TYPES))}.")
        title = f"Order #{order.woo_order_id} flagged: {issue.replace('_', ' ')}"
        return create_proposal(
            db,
            customer_id=order.customer_id,
            proposal_type=ptype,
            title=title,
            summary=note or f"Flagged by hand for review ({issue.replace('_', ' ')}).",
            evidence={**base_evidence, "woo_order_id": order.woo_order_id,
                      "order_status": order.status.value, "order_total": order.total,
                      "customer": _name(customer) if customer else ""},
            proposed_action={"action": "investigate_issue", "issue_type": issue,
                             "woo_order_id": order.woo_order_id},
            agent_name=MANUAL_AGENT,
            llm_explanation=note,
            dedup_key=f"manual:issue:{order.woo_order_id}:{_stamp()}",
        )

    if data.customer_id is None:
        raise ManualProposalError("Pick a customer.")
    customer = db.get(Customer, data.customer_id)
    if not customer:
        raise ManualProposalError(f"Customer {data.customer_id} not found.", 404)
    evidence = {**base_evidence, "customer": _name(customer), "email": customer.email,
                "segment": customer.segment.value, "total_spent": customer.total_spent,
                "order_count": customer.order_count}

    if ptype == ProposalType.SEGMENT_CHANGE:
        try:
            seg = CustomerSegment(str(data.new_segment or "").lower())
        except ValueError:
            raise ManualProposalError("new_segment must be one of: new, regular, vip, at_risk.")
        if customer.segment == seg:
            raise ManualProposalError(f"{_name(customer)} is already {seg.value}.")
        return create_proposal(
            db,
            customer_id=customer.id,
            proposal_type=ptype,
            title=f"Re-segment {_name(customer)}: {customer.segment.value} → {seg.value}",
            summary=note or f"Moved by hand to {seg.value}.",
            evidence=evidence,
            proposed_action={"action": "change_segment", "from": customer.segment.value, "to": seg.value},
            agent_name=MANUAL_AGENT,
            llm_explanation=note,
            dedup_key=f"manual:segment:{customer.id}:{_stamp()}",
        )

    if ptype == ProposalType.FOLLOW_UP_EMAIL:
        subject, body = (data.subject or "").strip(), (data.body or "").strip()
        if not subject or not body:
            raise ManualProposalError("An email needs a subject and a body.")
        return create_proposal(
            db,
            customer_id=customer.id,
            proposal_type=ptype,
            title=f"Email for {_name(customer)}: {subject[:60]}",
            summary=note or "Email written by hand.",
            evidence=evidence,
            proposed_action={"action": "send_email", "to": customer.email,
                             "draft": json.dumps({"subject": subject, "body": body},
                                                 ensure_ascii=False, indent=2)},
            agent_name=MANUAL_AGENT,
            llm_explanation=note,
            dedup_key=f"manual:email:{customer.id}:{_stamp()}",
        )

    raise ManualProposalError(f"Unsupported proposal type: {ptype}")
