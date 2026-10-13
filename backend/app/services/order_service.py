"""Order service: ingest WooCommerce orders with idempotent upsert logic.

Each order is identified by its woo_order_id.  Re-processing the same webhook
updates the existing row rather than creating a duplicate.
"""

from datetime import datetime, timezone
from dateutil.parser import parse as parse_date
from sqlalchemy.orm import Session

from app.models import Order, Customer, OrderStatus, TimelineEvent, TimelineEventType
from app.schemas import WooOrderPayload
from app.services.customer_service import resolve_customer
from app.services.timeline_service import record_event


def ingest_order(db: Session, payload: WooOrderPayload) -> Order:
    """Process a WooCommerce order webhook.  Idempotent on woo_order_id.

    Steps:
      1. Resolve customer from billing email
      2. Upsert order
      3. Update customer aggregates
      4. Record timeline event
      5. Return the order
    """
    # 1. Resolve customer
    customer = resolve_customer(
        db,
        email=payload.billing.email,
        first_name=payload.billing.first_name,
        last_name=payload.billing.last_name,
        phone=payload.billing.phone,
        woo_customer_id=payload.customer_id if payload.customer_id > 0 else None,
    )

    # 2. Upsert order
    existing = db.query(Order).filter(Order.woo_order_id == payload.id).first()
    is_new = existing is None

    order_status = _map_status(payload.status)
    order_total = float(payload.total)
    woo_created = None
    if payload.date_created:
        try:
            woo_created = parse_date(payload.date_created)
            if woo_created.tzinfo is None:
                woo_created = woo_created.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

    line_items_data = [li.model_dump() for li in payload.line_items]

    if existing:
        old_total = existing.total
        existing.status = order_status
        existing.total = order_total
        existing.currency = payload.currency
        existing.payment_method = payload.payment_method
        existing.line_items = line_items_data
        existing.billing = payload.billing.model_dump()
        existing.shipping = payload.shipping.model_dump()
        existing.customer_id = customer.id
        order = existing

        # Adjust customer aggregates if total changed
        if old_total != order_total:
            customer.total_spent += (order_total - old_total)
    else:
        order = Order(
            woo_order_id=payload.id,
            customer_id=customer.id,
            status=order_status,
            total=order_total,
            currency=payload.currency,
            payment_method=payload.payment_method,
            line_items=line_items_data,
            billing=payload.billing.model_dump(),
            shipping=payload.shipping.model_dump(),
            woo_created_at=woo_created,
        )
        db.add(order)

        # Update customer aggregates
        customer.order_count += 1
        customer.total_spent += order_total
        now = datetime.now(timezone.utc)
        if not customer.first_order_date:
            customer.first_order_date = woo_created or now
        customer.last_order_date = woo_created or now

    db.flush()

    # 4. Record timeline event
    event_type = TimelineEventType.ORDER_CREATED if is_new else TimelineEventType.ORDER_UPDATED
    record_event(
        db,
        customer_id=customer.id,
        event_type=event_type,
        title=f"Order #{payload.id} {'created' if is_new else 'updated'}",
        description=f"Status: {order_status.value}, Total: {payload.currency} {order_total:.2f}",
        metadata={"woo_order_id": payload.id, "status": order_status.value, "total": order_total},
    )

    db.commit()
    return order


def _map_status(woo_status: str) -> OrderStatus:
    """Map WooCommerce status string to our OrderStatus enum."""
    mapping = {
        "pending": OrderStatus.PENDING,
        "processing": OrderStatus.PROCESSING,
        "completed": OrderStatus.COMPLETED,
        "cancelled": OrderStatus.CANCELLED,
        "refunded": OrderStatus.REFUNDED,
        "failed": OrderStatus.FAILED,
        "on-hold": OrderStatus.ON_HOLD,
    }
    return mapping.get(woo_status.lower(), OrderStatus.PENDING)
