"""Webhook endpoint for WooCommerce order events.

Validates HMAC-SHA256 signature, parses the payload, ingests the order,
and triggers the agent pipeline.
"""

import hashlib
import hmac

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas import WooOrderPayload
from app.services.order_service import ingest_order
from app.services.pipeline import run_post_order_pipeline
from app.models import Order

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify WooCommerce webhook HMAC-SHA256 signature."""
    if not signature:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/woocommerce/order")
async def receive_order_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive and process a WooCommerce order webhook."""
    body = await request.body()

    # Verify signature (skip in debug mode if no signature present)
    signature = request.headers.get("X-WC-Webhook-Signature", "")
    if signature:
        if not verify_webhook_signature(body, signature, settings.woo_webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    elif not settings.debug:
        raise HTTPException(status_code=401, detail="Missing webhook signature")

    # Parse payload
    try:
        payload = WooOrderPayload.model_validate_json(body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    # Ingest order
    order = ingest_order(db, payload)

    # Get the customer for pipeline
    customer = order.customer

    # Run agent pipeline
    pipeline_results = run_post_order_pipeline(db, customer, order)

    return {
        "status": "ok",
        "order_id": order.id,
        "woo_order_id": order.woo_order_id,
        "customer_id": customer.id,
        "pipeline": pipeline_results,
    }
