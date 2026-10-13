"""Webhook endpoint for WooCommerce order events.

WooCommerce signs each delivery with X-WC-Webhook-Signature: the base64 of
an HMAC-SHA256 of the raw body keyed with the webhook secret.  When a webhook
is first saved, WooCommerce sends a form-encoded "webhook_id=N" ping that must
get a 2xx or the webhook is disabled.
"""

import base64
import hashlib
import hmac

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas import WooOrderPayload
from app.services.woo_sync import process_payload
from app.models import Order

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify a WooCommerce webhook signature.

    WooCommerce sends base64(HMAC-SHA256(body)); a hex digest is also accepted
    so hand-made test requests (curl, older scripts) still work.
    """
    if not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    candidates = (base64.b64encode(digest).decode(), digest.hex())
    return any(hmac.compare_digest(c, signature.strip()) for c in candidates)


IGNORED_TOPICS = {"order.deleted", "order.restored", "action.woocommerce_order_deleted"}


@router.post("/woocommerce/order")
async def receive_order_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive and process a WooCommerce order webhook."""
    body = await request.body()

    # WooCommerce's "is this URL alive?" ping when the webhook is created.
    if body.startswith(b"webhook_id="):
        return {"status": "ok", "ping": True}

    # Verify signature (skip in debug mode if no signature present)
    signature = request.headers.get("X-WC-Webhook-Signature", "")
    if signature:
        if not verify_webhook_signature(body, signature, settings.woo_webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    elif not settings.debug:
        raise HTTPException(status_code=401, detail="Missing webhook signature")

    topic = request.headers.get("X-WC-Webhook-Topic", "")
    if topic in IGNORED_TOPICS:
        return {"status": "ignored", "topic": topic}

    # Parse payload
    try:
        payload = WooOrderPayload.model_validate_json(body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    if not payload.billing.email:
        return {"status": "ignored", "reason": "order has no billing email yet", "woo_order_id": payload.id}

    # Ingest + agents (agents only run when the order is new or its status changed)
    result = process_payload(db, payload)
    order = db.query(Order).filter(Order.woo_order_id == payload.id).first()

    return {
        "status": "ok",
        "order_id": order.id,
        "woo_order_id": order.woo_order_id,
        "customer_id": order.customer_id,
        "topic": topic or None,
        "pipeline": result["pipeline"],
    }
