"""Pipeline orchestrator: connects webhook ingestion to agent evaluation.

After an order is ingested, the orchestrator:
  1. Runs the Segment Agent on the customer
  2. Runs the Follow-up Agent if triggers apply
  3. Runs the Order-Issue Watcher
"""

from sqlalchemy.orm import Session

from app.models import Customer, Order, CustomerSegment
from app.agents.llm import LLMClient, get_llm
from app.agents.segment_agent import run_segment_agent, classify_customer
from app.agents.follow_up_agent import run_follow_up_agent
from app.agents.issue_watcher import run_issue_watcher


def run_post_order_pipeline(
    db: Session,
    customer: Customer,
    order: Order,
    llm: LLMClient | None = None,
) -> dict:
    """Run all agents after an order is ingested.

    The LLM client is resolved once here and shared by every agent, so a
    caller (or a test) can inject one.  Returns a summary of what happened.
    """
    llm = llm or get_llm()

    results = {
        "segment_proposal_created": False,
        "follow_up_proposal_created": False,
        "issues_detected": [],
    }

    # 1. Segment Agent
    results["segment_proposal_created"] = run_segment_agent(db, customer, llm=llm)

    # 2. Follow-up Agent — check triggers
    new_segment = classify_customer(customer)

    # Welcome email for first-time customer
    if customer.order_count == 1:
        created = run_follow_up_agent(
            db, customer, "new_customer_welcome",
            context={"woo_order_id": order.woo_order_id},
            llm=llm,
        )
        results["follow_up_proposal_created"] = created or results["follow_up_proposal_created"]

    # VIP thank-you when customer reaches VIP
    if new_segment == CustomerSegment.VIP and customer.segment != CustomerSegment.VIP:
        created = run_follow_up_agent(
            db, customer, "vip_thank_you",
            context={"woo_order_id": order.woo_order_id},
            llm=llm,
        )
        results["follow_up_proposal_created"] = created or results["follow_up_proposal_created"]

    # Win-back for at-risk customers
    if new_segment == CustomerSegment.AT_RISK:
        created = run_follow_up_agent(
            db, customer, "win_back",
            context={"woo_order_id": order.woo_order_id},
            llm=llm,
        )
        results["follow_up_proposal_created"] = created or results["follow_up_proposal_created"]

    # 3. Order-Issue Watcher
    issues = run_issue_watcher(db, customer, order, llm=llm)
    results["issues_detected"] = issues

    # If issues found, also trigger follow-up
    if issues:
        created = run_follow_up_agent(
            db, customer, "order_issue",
            context={"issues": issues, "woo_order_id": order.woo_order_id},
            llm=llm,
        )
        results["follow_up_proposal_created"] = created or results["follow_up_proposal_created"]

    # Persist every proposal and timeline event the agents produced.  The
    # order ingestion commits earlier, but the agent work above is only
    # flushed; without this commit it would be rolled back when the request
    # session closes (e.g. the webhook handler).
    db.commit()

    return results
