"""API routes for customers, orders, timeline, proposals, and dashboard."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Customer, Order, TimelineEvent, Proposal, ProposalStatus, CustomerSegment
from app.schemas import (
    CustomerOut, CustomerSummary, OrderOut, TimelineEventOut,
    ProposalOut, ProposalReview, DashboardStats,
)
from app.services.proposal_service import review_proposal, execute_proposal
from app.services.timeline_service import get_customer_timeline
from app.agents.segment_agent import apply_segment_change

router = APIRouter(prefix="/api", tags=["api"])


# ── Dashboard ─────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=DashboardStats)
def get_dashboard(db: Session = Depends(get_db)):
    """Overview statistics for the dashboard."""
    total_customers = db.query(func.count(Customer.id)).scalar() or 0
    total_orders = db.query(func.count(Order.id)).scalar() or 0
    total_revenue = db.query(func.coalesce(func.sum(Order.total), 0)).scalar() or 0
    pending_proposals = (
        db.query(func.count(Proposal.id))
        .filter(Proposal.status == ProposalStatus.PENDING)
        .scalar() or 0
    )

    # Segment distribution
    segment_rows = (
        db.query(Customer.segment, func.count(Customer.id))
        .group_by(Customer.segment)
        .all()
    )
    segment_distribution = {seg.value: count for seg, count in segment_rows}

    # Recent orders
    recent = db.query(Order).order_by(Order.created_at.desc()).limit(5).all()

    return DashboardStats(
        total_customers=total_customers,
        total_orders=total_orders,
        total_revenue=float(total_revenue),
        pending_proposals=pending_proposals,
        segment_distribution=segment_distribution,
        recent_orders=[OrderOut.model_validate(o) for o in recent],
    )


# ── Customers ─────────────────────────────────────────────────────────────

@router.get("/customers", response_model=list[CustomerSummary])
def list_customers(
    segment: str | None = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """List all customers, optionally filtered by segment."""
    q = db.query(Customer)
    if segment:
        q = q.filter(Customer.segment == segment)
    return q.order_by(Customer.created_at.desc()).limit(limit).all()


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    """Get full customer details."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


# ── Orders ────────────────────────────────────────────────────────────────

@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    customer_id: int | None = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """List orders, optionally for a specific customer."""
    q = db.query(Order)
    if customer_id:
        q = q.filter(Order.customer_id == customer_id)
    return q.order_by(Order.created_at.desc()).limit(limit).all()


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    """Get a single order by ID."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


# ── Timeline ──────────────────────────────────────────────────────────────

@router.get("/customers/{customer_id}/timeline", response_model=list[TimelineEventOut])
def get_timeline(customer_id: int, db: Session = Depends(get_db)):
    """Get timeline events for a customer."""
    return get_customer_timeline(db, customer_id)


# ── Proposals (Approval Inbox) ────────────────────────────────────────────

@router.get("/proposals", response_model=list[ProposalOut])
def list_proposals(
    status: str | None = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """List proposals, optionally filtered by status."""
    q = db.query(Proposal)
    if status:
        q = q.filter(Proposal.status == status)
    return q.order_by(Proposal.created_at.desc()).limit(limit).all()


@router.get("/proposals/{proposal_id}", response_model=ProposalOut)
def get_proposal(proposal_id: int, db: Session = Depends(get_db)):
    """Get a single proposal."""
    proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@router.post("/proposals/{proposal_id}/review", response_model=ProposalOut)
def review_proposal_endpoint(
    proposal_id: int,
    review: ProposalReview,
    db: Session = Depends(get_db),
):
    """Approve or reject a proposal."""
    try:
        proposal = review_proposal(db, proposal_id, review.action, review.reviewed_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # If approved, execute the action
    if proposal.status == ProposalStatus.APPROVED:
        _execute_approved_proposal(db, proposal)

    return proposal


def _execute_approved_proposal(db: Session, proposal: Proposal) -> None:
    """Execute the action for an approved proposal."""
    action = proposal.proposed_action or {}
    action_type = action.get("action")

    if action_type == "change_segment":
        customer = db.query(Customer).filter(Customer.id == proposal.customer_id).first()
        if customer:
            apply_segment_change(db, customer, action["to"])

    # For send_email and investigate_issue: mark as executed (simulated)
    execute_proposal(db, proposal.id)
