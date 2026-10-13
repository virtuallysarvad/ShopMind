"""Timeline service: records every significant action as an auditable event."""

from sqlalchemy.orm import Session

from app.models import TimelineEvent, TimelineEventType


def record_event(
    db: Session,
    customer_id: int,
    event_type: TimelineEventType,
    title: str,
    description: str = "",
    metadata: dict | None = None,
) -> TimelineEvent:
    """Append an event to the customer's timeline."""
    event = TimelineEvent(
        customer_id=customer_id,
        event_type=event_type,
        title=title,
        description=description,
        metadata_json=metadata or {},
    )
    db.add(event)
    db.flush()
    return event


def get_customer_timeline(
    db: Session, customer_id: int, limit: int = 50
) -> list[TimelineEvent]:
    """Get recent timeline events for a customer, newest first."""
    return (
        db.query(TimelineEvent)
        .filter(TimelineEvent.customer_id == customer_id)
        .order_by(TimelineEvent.created_at.desc())
        .limit(limit)
        .all()
    )
