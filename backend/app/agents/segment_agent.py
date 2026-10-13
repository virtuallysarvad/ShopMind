"""Segment Agent: classifies customers into segments using deterministic rules.

Rules:
  - NEW:      order_count <= 1
  - VIP:      order_count >= 5  AND  total_spent >= 15000  (rupees)
  - AT_RISK:  order_count >= 2  AND  last_order > 60 days ago
  - REGULAR:  everything else

The agent creates a proposal when a customer's segment should change.
The LLM only writes the human-readable explanation — the classification
above stays deterministic.
"""

from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.models import Customer, CustomerSegment, ProposalType
from app.services.proposal_service import create_proposal
from app.agents.llm import LLMClient, get_llm


# ── Deterministic Classification Rules ────────────────────────────────────

VIP_MIN_ORDERS = 5
VIP_MIN_SPEND_INR = 15000


def classify_customer(customer: Customer) -> CustomerSegment:
    """Pure-function classification.  No side effects, fully testable."""
    now = datetime.now(timezone.utc)

    # VIP: high value
    if customer.order_count >= VIP_MIN_ORDERS and customer.total_spent >= VIP_MIN_SPEND_INR:
        return CustomerSegment.VIP

    # AT_RISK: had orders but gone quiet
    if customer.order_count >= 2 and customer.last_order_date:
        days_since = (now - customer.last_order_date.replace(tzinfo=timezone.utc)).days
        if days_since > 60:
            return CustomerSegment.AT_RISK

    # NEW: first order or no orders
    if customer.order_count <= 1:
        return CustomerSegment.NEW

    # REGULAR: everyone else
    return CustomerSegment.REGULAR


# ── Agent Entry Point ─────────────────────────────────────────────────────

def run_segment_agent(
    db: Session, customer: Customer, llm: LLMClient | None = None
) -> bool:
    """Evaluate a customer and propose a segment change if needed.

    ``llm`` may be injected (tests); defaults to the configured client.
    Returns True if a new proposal was created.
    """
    llm = llm or get_llm()
    new_segment = classify_customer(customer)

    if new_segment == customer.segment:
        return False  # no change needed

    # Build evidence
    evidence = {
        "current_segment": customer.segment.value,
        "proposed_segment": new_segment.value,
        "order_count": customer.order_count,
        "total_spent": customer.total_spent,
        "last_order_date": (
            customer.last_order_date.isoformat() if customer.last_order_date else None
        ),
    }

    # Explanation for the decision above (model-written or deterministic)
    result = llm.explain_segment(
        customer_data={
            "name": customer.full_name,
            "order_count": customer.order_count,
            "total_spent": customer.total_spent,
            "last_order_date": evidence["last_order_date"],
        },
        new_segment=new_segment.value,
    )
    evidence["llm_model"] = result.model

    # Dedup key: only one pending segment-change proposal per customer
    dedup_key = f"segment:{customer.id}:{new_segment.value}"

    proposal = create_proposal(
        db,
        customer_id=customer.id,
        proposal_type=ProposalType.SEGMENT_CHANGE,
        title=f"Re-segment {customer.full_name}: {customer.segment.value} → {new_segment.value}",
        summary=f"Customer meets criteria for {new_segment.value} segment.",
        evidence=evidence,
        proposed_action={
            "action": "change_segment",
            "from": customer.segment.value,
            "to": new_segment.value,
        },
        agent_name="segment_agent",
        llm_explanation=result.text,
        is_llm_generated=result.is_llm_generated,
        dedup_key=dedup_key,
    )

    return proposal is not None


def apply_segment_change(db: Session, customer: Customer, new_segment: str) -> None:
    """Actually apply a segment change after approval."""
    customer.segment = CustomerSegment(new_segment)
    db.flush()
