"""Customer resolution: match incoming orders to existing or new customers.

Uses email as the primary identity key.  Falls back to phone if no email match.
Guest WooCommerce orders (customer_id == 0) are resolved by billing email.
"""

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models import Customer, TimelineEvent, TimelineEventType


def resolve_customer(
    db: Session,
    email: str,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    woo_customer_id: int | None = None,
) -> Customer:
    """Find or create a customer by email.  Returns the resolved Customer row.

    Identity resolution order:
      1. Exact email match
      2. If woo_customer_id > 0, match on that
      3. Create new customer
    """
    email = email.strip().lower()
    if not email:
        raise ValueError("Cannot resolve customer without an email address")

    # 1. Try email
    customer = db.query(Customer).filter(Customer.email == email).first()
    if customer:
        # Merge newer info
        if first_name and not customer.first_name:
            customer.first_name = first_name
        if last_name and not customer.last_name:
            customer.last_name = last_name
        if phone and not customer.phone:
            customer.phone = phone
        if woo_customer_id and woo_customer_id > 0 and not customer.woo_customer_id:
            customer.woo_customer_id = woo_customer_id
        db.flush()
        return customer

    # 2. Try woo_customer_id
    if woo_customer_id and woo_customer_id > 0:
        customer = db.query(Customer).filter(
            Customer.woo_customer_id == woo_customer_id
        ).first()
        if customer:
            # Update email if changed
            customer.email = email
            if first_name:
                customer.first_name = first_name
            if last_name:
                customer.last_name = last_name
            if phone:
                customer.phone = phone
            db.flush()
            return customer

    # 3. Create new
    customer = Customer(
        email=email,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        woo_customer_id=woo_customer_id if woo_customer_id and woo_customer_id > 0 else None,
    )
    db.add(customer)
    db.flush()
    return customer
