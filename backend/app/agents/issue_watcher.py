"""Order-Issue Watcher: detects problematic order patterns.

Detects:
  - Failed payments
  - Repeated returns/refunds  (3+ refunded orders)
  - Stuck orders              (processing for too long — checked via status)

Raises issue alerts as proposals for human review.
The LLM only writes the explanation; detection itself stays rule-based.
"""

from sqlalchemy.orm import Session

from app.models import Customer, Order, OrderStatus, ProposalType, TimelineEventType
from app.services.proposal_service import create_proposal
from app.services.timeline_service import record_event
from app.agents.llm import LLMClient, get_llm


def run_issue_watcher(
    db: Session, customer: Customer, order: Order, llm: LLMClient | None = None
) -> list[str]:
    """Check an order for issues.  Returns list of detected issue types.

    ``llm`` may be injected (tests); defaults to the configured client.
    """
    llm = llm or get_llm()
    issues_found = []

    # 1. Failed payment
    if order.status == OrderStatus.FAILED:
        _create_issue_proposal(
            db, customer, order, "failed_payment",
            "Failed payment detected",
            f"Order #{order.woo_order_id} has a failed payment status.",
            llm=llm,
        )
        issues_found.append("failed_payment")

    # 2. Repeated returns — check customer's refund history
    refund_count = (
        db.query(Order)
        .filter(
            Order.customer_id == customer.id,
            Order.status.in_([OrderStatus.REFUNDED, OrderStatus.CANCELLED]),
        )
        .count()
    )
    if refund_count >= 3:
        dedup_key = f"issue:repeated_return:{customer.id}"
        _create_issue_proposal(
            db, customer, order, "repeated_return",
            "Repeated returns detected",
            f"Customer has {refund_count} refunded/cancelled orders.",
            dedup_key=dedup_key,
            llm=llm,
        )
        issues_found.append("repeated_return")

    return issues_found


def _create_issue_proposal(
    db: Session,
    customer: Customer,
    order: Order,
    issue_type: str,
    title: str,
    summary: str,
    dedup_key: str | None = None,
    llm: LLMClient | None = None,
) -> None:
    """Create an issue alert proposal and record a timeline event."""
    llm = llm or get_llm()
    result = llm.explain_issue(
        issue_type,
        {"woo_order_id": order.woo_order_id, "status": order.status.value, "total": order.total},
    )

    if dedup_key is None:
        dedup_key = f"issue:{issue_type}:{order.woo_order_id}"

    # Record the issue detection on the timeline
    record_event(
        db,
        customer_id=customer.id,
        event_type=TimelineEventType.ISSUE_DETECTED,
        title=title,
        description=summary,
        metadata={"issue_type": issue_type, "woo_order_id": order.woo_order_id},
    )

    create_proposal(
        db,
        customer_id=customer.id,
        proposal_type=ProposalType.ISSUE_ALERT,
        title=f"{title} — {customer.full_name}",
        summary=summary,
        evidence={
            "issue_type": issue_type,
            "woo_order_id": order.woo_order_id,
            "order_status": order.status.value,
            "order_total": order.total,
            "customer_refund_count": (
                db.query(Order)
                .filter(
                    Order.customer_id == customer.id,
                    Order.status.in_([OrderStatus.REFUNDED, OrderStatus.CANCELLED]),
                )
                .count()
            ),
            "llm_model": result.model,
        },
        proposed_action={
            "action": "investigate_issue",
            "issue_type": issue_type,
            "woo_order_id": order.woo_order_id,
        },
        agent_name="order_issue_watcher",
        llm_explanation=result.text,
        is_llm_generated=result.is_llm_generated,
        dedup_key=dedup_key,
    )
