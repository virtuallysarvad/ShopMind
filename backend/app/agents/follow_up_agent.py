"""Follow-up Agent: drafts personalized communications based on customer events.

Triggers:
  - New customer welcome  (first order)
  - VIP thank-you         (segment changed to VIP)
  - Win-back             (segment changed to at_risk)
  - Order issue outreach  (triggered by order-issue watcher)

All drafts require human approval before "sending" (simulated).
The LLM only writes the draft; the trigger is chosen by deterministic rules.
"""

from sqlalchemy.orm import Session

from app.models import Customer, CustomerSegment, Order, ProposalType
from app.services.proposal_service import create_proposal
from app.agents.llm import LLMClient, get_llm


def run_follow_up_agent(
    db: Session,
    customer: Customer,
    trigger: str,
    context: dict | None = None,
    llm: LLMClient | None = None,
) -> bool:
    """Draft a follow-up communication and submit as a proposal.

    ``llm`` may be injected (tests); defaults to the configured client.
    Returns True if a new proposal was created.
    """
    llm = llm or get_llm()
    context = context or {}

    customer_data = {
        "name": customer.full_name,
        "email": customer.email,
        "segment": customer.segment.value,
        "order_count": customer.order_count,
        "total_spent": customer.total_spent,
    }

    # Draft written by the configured LLM (fallback-safe)
    result = llm.draft_follow_up(customer_data, trigger, context)

    # Human-readable title
    trigger_titles = {
        "new_customer_welcome": "Welcome email for new customer",
        "vip_thank_you": "VIP appreciation email",
        "win_back": "Win-back campaign email",
        "order_issue": "Order issue outreach email",
    }
    title = trigger_titles.get(trigger, f"Follow-up: {trigger}")

    # Dedup: one pending follow-up per trigger per customer
    dedup_key = f"followup:{customer.id}:{trigger}"

    proposal = create_proposal(
        db,
        customer_id=customer.id,
        proposal_type=ProposalType.FOLLOW_UP_EMAIL,
        title=f"{title} for {customer.full_name}",
        summary=f"Draft {trigger.replace('_', ' ')} communication",
        evidence={
            "trigger": trigger,
            "customer_segment": customer.segment.value,
            "order_count": customer.order_count,
            "context": context,
            "llm_model": result.model,
        },
        proposed_action={
            "action": "send_email",
            "to": customer.email,
            "draft": result.text,
        },
        agent_name="follow_up_agent",
        llm_explanation=result.text,
        is_llm_generated=result.is_llm_generated,
        dedup_key=dedup_key,
    )

    return proposal is not None
