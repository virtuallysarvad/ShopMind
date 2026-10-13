"""Two-way WooCommerce integration.

Inbound  (store -> ShopMind): `sync_orders` pulls orders through the REST API
          (backfill or incremental) and feeds them through the same
          ingest + agent pipeline that webhooks use. Idempotent.
Outbound (ShopMind -> store): `write_back` runs after a human approves a
          proposal and mirrors the action into WooCommerce:
            change_segment    -> customer meta `shopmind_segment`
            send_email        -> customer order note (WooCommerce emails it)
            investigate_issue -> private order note for the shop team
Write-back never blocks an approval: failures are recorded, not raised.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Customer, Order, Proposal, TimelineEventType
from app.schemas import WooOrderPayload
from app.services.order_service import ingest_order
from app.services.pipeline import run_post_order_pipeline
from app.services.timeline_service import record_event
from app.woo_client import WooCommerceClient, WooCommerceError

logger = logging.getLogger(__name__)


def payload_from_rest(order: dict) -> WooOrderPayload:
    """REST order JSON is the same shape webhooks send; prefer the GMT date."""
    data = dict(order)
    gmt = data.get("date_created_gmt")
    if gmt:
        data["date_created"] = gmt if gmt.endswith("Z") else f"{gmt}Z"
    data["customer_id"] = int(data.get("customer_id") or 0)
    return WooOrderPayload.model_validate(data)


def process_payload(db: Session, payload: WooOrderPayload) -> dict:
    """Ingest one order; run the agents only when it is new or its status changed."""
    if not payload.billing.email:
        return {"woo_order_id": payload.id, "skipped": "no billing email"}
    before = db.query(Order).filter(Order.woo_order_id == payload.id).first()
    old_status = before.status.value if before else None
    order = ingest_order(db, payload)
    changed = old_status is None or old_status != order.status.value
    pipeline = run_post_order_pipeline(db, order.customer, order) if changed else None
    return {"woo_order_id": payload.id, "new": old_status is None, "status_changed": changed, "pipeline": pipeline}


def sync_orders(db: Session, client: WooCommerceClient, modified_after: str | None = None) -> dict:
    """Pull orders from the store. Safe to run repeatedly."""
    stats = {"fetched": 0, "new": 0, "updated": 0, "skipped": 0, "proposals_from_agents": 0, "errors": []}
    for raw in client.list_orders(modified_after=modified_after):
        stats["fetched"] += 1
        try:
            res = process_payload(db, payload_from_rest(raw))
        except Exception as e:  # one bad order must not stop the sync
            db.rollback()
            logger.warning("Sync failed for order %s: %s", raw.get("id"), e)
            stats["errors"].append(f"order {raw.get('id')}: {e}")
            continue
        if res.get("skipped"):
            stats["skipped"] += 1
        elif res["new"]:
            stats["new"] += 1
        else:
            stats["updated"] += 1
        p = res.get("pipeline") or {}
        stats["proposals_from_agents"] += int(bool(p.get("segment_proposal_created"))) \
            + int(bool(p.get("follow_up_proposal_created"))) + len(p.get("issues_detected") or [])
    stats["synced_at"] = datetime.now(timezone.utc).isoformat()
    return stats


def _latest_woo_order(db: Session, customer_id: int) -> Order | None:
    return (db.query(Order).filter(Order.customer_id == customer_id)
            .order_by(Order.woo_created_at.desc(), Order.id.desc()).first())


def _email_note(draft: str) -> str:
    import json
    try:
        d = json.loads(draft)
        if isinstance(d, dict) and d.get("subject") and d.get("body"):
            return f"{d['subject']}\n\n{d['body']}"
    except (TypeError, ValueError):
        pass
    return draft or ""


def write_back(db: Session, proposal: Proposal, client: WooCommerceClient | None) -> dict:
    """Mirror an approved proposal into WooCommerce. Returns what happened."""
    if client is None or not settings.woo_writeback:
        return {"status": "skipped", "reason": "WooCommerce write-back is off (mock mode)"}
    action = proposal.proposed_action or {}
    kind = action.get("action")
    customer = db.get(Customer, proposal.customer_id)
    try:
        if kind == "change_segment":
            if not customer or not customer.woo_customer_id:
                result = {"status": "skipped", "reason": "guest customer has no WooCommerce account"}
            else:
                client.update_customer_meta(customer.woo_customer_id, {
                    "shopmind_segment": action.get("to"),
                    "shopmind_segment_updated": datetime.now(timezone.utc).isoformat(),
                })
                result = {"status": "ok", "did": f"set shopmind_segment={action.get('to')} on customer {customer.woo_customer_id}"}
        elif kind == "send_email":
            order = _latest_woo_order(db, proposal.customer_id)
            if not order:
                result = {"status": "skipped", "reason": "customer has no order to attach the note to"}
            else:
                note = client.add_order_note(order.woo_order_id, _email_note(action.get("draft", "")), customer_note=True)
                result = {"status": "ok", "did": f"customer note #{note.get('id')} on order {order.woo_order_id}; WooCommerce emails it"}
        elif kind == "investigate_issue":
            oid = action.get("woo_order_id")
            text = f"ShopMind flagged this order ({action.get('issue_type', 'issue')}). {proposal.summary}".strip()
            note = client.add_order_note(oid, text, customer_note=False)
            result = {"status": "ok", "did": f"private note #{note.get('id')} on order {oid}"}
        else:
            result = {"status": "skipped", "reason": f"no write-back for action '{kind}'"}
    except WooCommerceError as e:
        logger.warning("Write-back failed for proposal %s: %s", proposal.id, e)
        result = {"status": "error", "error": str(e)}

    if result["status"] != "skipped":
        record_event(
            db, customer_id=proposal.customer_id, event_type=TimelineEventType.NOTE_ADDED,
            title="Synced to WooCommerce" if result["status"] == "ok" else "WooCommerce sync failed",
            description=result.get("did") or result.get("error", ""),
            metadata={"proposal_id": proposal.id, "woo_writeback": result},
        )
    proposal.evidence = {**(proposal.evidence or {}), "woo_writeback": result}
    return result
