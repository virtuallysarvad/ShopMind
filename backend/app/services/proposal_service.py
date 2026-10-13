"""Proposal service: CRUD and state machine for agent proposals.

Proposals go through: PENDING → APPROVED/REJECTED → EXECUTED (if approved).
Each state transition is recorded as a timeline event.
"""

from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import Proposal, ProposalStatus, ProposalType, TimelineEventType
from app.services.timeline_service import record_event


def create_proposal(
    db: Session,
    customer_id: int,
    proposal_type: ProposalType,
    title: str,
    summary: str,
    evidence: dict,
    proposed_action: dict,
    agent_name: str,
    llm_explanation: str = "",
    is_llm_generated: bool = False,
    dedup_key: str | None = None,
) -> Proposal | None:
    """Create a new proposal.  Returns None if dedup_key already exists."""
    proposal = Proposal(
        customer_id=customer_id,
        proposal_type=proposal_type,
        title=title,
        summary=summary,
        evidence=evidence,
        proposed_action=proposed_action,
        agent_name=agent_name,
        llm_explanation=llm_explanation,
        is_llm_generated=is_llm_generated,
        dedup_key=dedup_key,
    )
    db.add(proposal)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return None  # duplicate

    # Record timeline event
    record_event(
        db,
        customer_id=customer_id,
        event_type=TimelineEventType.PROPOSAL_CREATED,
        title=f"Proposal: {title}",
        description=summary,
        metadata={"proposal_id": proposal.id, "agent": agent_name, "type": proposal_type.value},
    )
    return proposal


def review_proposal(
    db: Session,
    proposal_id: int,
    action: str,
    reviewed_by: str = "admin",
) -> Proposal:
    """Approve or reject a pending proposal."""
    proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not proposal:
        raise ValueError(f"Proposal {proposal_id} not found")
    if proposal.status != ProposalStatus.PENDING:
        raise ValueError(
            f"Proposal {proposal_id} is {proposal.status.value}, cannot review"
        )

    now = datetime.now(timezone.utc)
    if action == "approve":
        proposal.status = ProposalStatus.APPROVED
        event_type = TimelineEventType.PROPOSAL_APPROVED
    elif action == "reject":
        proposal.status = ProposalStatus.REJECTED
        event_type = TimelineEventType.PROPOSAL_REJECTED
    else:
        raise ValueError(f"Invalid action: {action}")

    proposal.reviewed_by = reviewed_by
    proposal.reviewed_at = now
    db.flush()

    record_event(
        db,
        customer_id=proposal.customer_id,
        event_type=event_type,
        title=f"Proposal {action}d: {proposal.title}",
        description=f"Reviewed by {reviewed_by}",
        metadata={"proposal_id": proposal.id, "action": action},
    )
    db.commit()
    return proposal


def execute_proposal(db: Session, proposal_id: int) -> Proposal:
    """Mark an approved proposal as executed."""
    proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not proposal:
        raise ValueError(f"Proposal {proposal_id} not found")
    if proposal.status != ProposalStatus.APPROVED:
        raise ValueError(
            f"Proposal {proposal_id} is {proposal.status.value}, must be approved first"
        )

    proposal.status = ProposalStatus.EXECUTED
    proposal.executed_at = datetime.now(timezone.utc)
    db.flush()

    record_event(
        db,
        customer_id=proposal.customer_id,
        event_type=TimelineEventType.PROPOSAL_EXECUTED,
        title=f"Proposal executed: {proposal.title}",
        description=f"Action: {proposal.proposed_action}",
        metadata={"proposal_id": proposal.id},
    )
    db.commit()
    return proposal


def get_pending_proposals(db: Session, limit: int = 50) -> list[Proposal]:
    """Get all pending proposals, newest first."""
    return (
        db.query(Proposal)
        .filter(Proposal.status == ProposalStatus.PENDING)
        .order_by(Proposal.created_at.desc())
        .limit(limit)
        .all()
    )


def get_all_proposals(db: Session, limit: int = 100) -> list[Proposal]:
    """Get all proposals, newest first."""
    return (
        db.query(Proposal)
        .order_by(Proposal.created_at.desc())
        .limit(limit)
        .all()
    )
