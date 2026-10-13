"""End-to-end integration test for the mandatory ShopMind journey.

Exercises the real FastAPI app through TestClient with an isolated in-memory
database, covering:

    signed webhook ingestion
      -> customer resolution + idempotent order upsert
      -> agent proposals persisted
      -> human approval
      -> simulated execution
      -> auditable timeline

Also verifies webhook signature rejection and the segment-upgrade path.
"""

import hashlib
import hmac
import json

import pytest

from app.config import settings
from app.models import (
    Customer,
    CustomerSegment,
    Order,
    ProposalStatus,
    ProposalType,
    TimelineEventType,
)


# ── Helpers (the `client` fixture lives in conftest.py) ───────────────────

def _sign(payload: dict):
    body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(
        settings.woo_webhook_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return body, sig


def _order(
    order_id: int,
    email: str,
    status: str = "processing",
    total: str = "120.00",
    first: str = "Test",
    last: str = "Buyer",
) -> dict:
    return {
        "id": order_id,
        "status": status,
        "total": total,
        "currency": "INR",
        "payment_method": "stripe",
        "billing": {
            "first_name": first,
            "last_name": last,
            "email": email,
            "phone": "555-0000",
        },
        "shipping": {"first_name": first, "last_name": last},
        "line_items": [
            {"id": 1, "name": "Widget", "product_id": 1, "quantity": 1, "total": total}
        ],
        "date_created": "2026-10-13T10:00:00Z",
        "customer_id": 0,
    }


def _post_order(client, payload, signed=True):
    body, sig = _sign(payload)
    headers = {"Content-Type": "application/json"}
    if signed:
        headers["X-WC-Webhook-Signature"] = sig
    return client.post("/webhooks/woocommerce/order", content=body, headers=headers)


# ── Webhook signature enforcement ─────────────────────────────────────────

class TestWebhookSecurity:
    def test_rejects_bad_signature(self, client):
        body = json.dumps(_order(1, "x@example.com")).encode()
        resp = client.post(
            "/webhooks/woocommerce/order",
            content=body,
            headers={"X-WC-Webhook-Signature": "deadbeef"},
        )
        assert resp.status_code == 401

    def test_rejects_missing_signature_when_not_debug(self, client, monkeypatch):
        monkeypatch.setattr(settings, "debug", False)
        resp = client.post(
            "/webhooks/woocommerce/order",
            json=_order(2, "x@example.com"),
        )
        assert resp.status_code == 401

    def test_accepts_valid_signature(self, client):
        resp = _post_order(client, _order(3, "valid@example.com"))
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── The mandatory full journey ────────────────────────────────────────────

class TestFullJourney:
    def test_order_to_approved_communication(self, client, db):
        # 1. Ingest a signed order webhook
        resp = _post_order(client, _order(5001, "alice@example.com", total="120.00"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["woo_order_id"] == 5001
        assert data["pipeline"]["follow_up_proposal_created"] is True

        customer_id = data["customer_id"]
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        assert customer.email == "alice@example.com"
        assert customer.order_count == 1

        # 2. Order is visible through the API
        orders = client.get("/api/orders").json()
        assert any(o["woo_order_id"] == 5001 for o in orders)

        # 3. Dashboard reflects the new data
        dash = client.get("/api/dashboard").json()
        assert dash["total_customers"] == 1
        assert dash["total_orders"] == 1
        assert dash["total_revenue"] == 120.00

        # 4. An agent proposal landed in the approval inbox (persisted!)
        pending = client.get("/api/proposals", params={"status": "pending"}).json()
        assert len(pending) >= 1
        welcome = next(
            p for p in pending if p["proposal_type"] == ProposalType.FOLLOW_UP_EMAIL.value
        )
        assert welcome["is_llm_generated"] is False
        assert "Deterministic" in welcome["llm_explanation"]

        # 5. Human approves -> proposal is approved AND executed (simulated send)
        review = client.post(
            f"/api/proposals/{welcome['id']}/review",
            json={"action": "approve", "reviewed_by": "hackathon-judge"},
        )
        assert review.status_code == 200
        reviewed = review.json()
        assert reviewed["status"] == ProposalStatus.EXECUTED.value
        assert reviewed["reviewed_by"] == "hackathon-judge"
        assert reviewed["executed_at"] is not None

        # 6. The timeline captured the whole story
        timeline = client.get(f"/api/customers/{customer_id}/timeline").json()
        types = {e["event_type"] for e in timeline}
        assert TimelineEventType.ORDER_CREATED.value in types
        assert TimelineEventType.PROPOSAL_CREATED.value in types
        assert TimelineEventType.PROPOSAL_APPROVED.value in types
        assert TimelineEventType.PROPOSAL_EXECUTED.value in types

    def test_rejecting_a_proposal_leaves_it_unexecuted(self, client, db):
        resp = _post_order(client, _order(5101, "bob@example.com"))
        customer_id = resp.json()["customer_id"]

        pending = client.get("/api/proposals", params={"status": "pending"}).json()
        target = pending[0]

        review = client.post(
            f"/api/proposals/{target['id']}/review",
            json={"action": "reject", "reviewed_by": "admin"},
        )
        assert review.status_code == 200
        rejected = review.json()
        assert rejected["status"] == ProposalStatus.REJECTED.value
        assert rejected["executed_at"] is None

        timeline = client.get(f"/api/customers/{customer_id}/timeline").json()
        assert any(
            e["event_type"] == TimelineEventType.PROPOSAL_REJECTED.value for e in timeline
        )

    def test_double_review_is_rejected(self, client, db):
        resp = _post_order(client, _order(5201, "carol@example.com"))
        pending = client.get("/api/proposals", params={"status": "pending"}).json()
        pid = pending[0]["id"]

        first = client.post(f"/api/proposals/{pid}/review", json={"action": "approve"})
        assert first.status_code == 200

        second = client.post(f"/api/proposals/{pid}/review", json={"action": "reject"})
        assert second.status_code == 400


# ── Idempotency ───────────────────────────────────────────────────────────

class TestIdempotency:
    def test_redelivered_order_does_not_duplicate(self, client, db):
        payload = _order(6001, "multi@example.com", total="75.00")

        _post_order(client, payload)
        _post_order(client, payload)  # simulate WooCommerce webhook retry

        orders = db.query(Order).all()
        assert len(orders) == 1  # upserted, not duplicated

        customer = db.query(Customer).filter(Customer.email == "multi@example.com").first()
        assert customer.order_count == 1
        assert customer.total_spent == 75.00

        # The welcome follow-up is de-duplicated across deliveries
        welcome = (
            db.query(Customer)
            .filter(Customer.id == customer.id)
            .first()
        )
        assert welcome is not None
        api_props = client.get("/api/proposals").json()
        follow_ups = [
            p for p in api_props if p["proposal_type"] == ProposalType.FOLLOW_UP_EMAIL.value
        ]
        assert len(follow_ups) == 1


# ── Segment upgrade path ──────────────────────────────────────────────────

class TestSegmentUpgrade:
    def test_becomes_vip_and_approval_applies_change(self, client, db):
        email = "vip@example.com"
        for i in range(5):
            _post_order(client, _order(7000 + i, email, status="completed", total="3500.00"))

        customer = db.query(Customer).filter(Customer.email == email).first()
        assert customer.order_count == 5
        assert customer.total_spent == 17500.00

        # A VIP segment-change proposal exists and is pending
        pending = client.get("/api/proposals", params={"status": "pending"}).json()
        vip_props = [
            p
            for p in pending
            if p["proposal_type"] == ProposalType.SEGMENT_CHANGE.value
            and p["proposed_action"].get("to") == CustomerSegment.VIP.value
        ]
        assert vip_props, "expected a VIP segment proposal"
        vip_prop = vip_props[0]

        # Approve it -> segment is actually applied
        review = client.post(
            f"/api/proposals/{vip_prop['id']}/review",
            json={"action": "approve", "reviewed_by": "admin"},
        )
        assert review.status_code == 200

        db.refresh(customer)
        assert customer.segment == CustomerSegment.VIP


# ── Issue detection path ──────────────────────────────────────────────────

class TestIssueDetection:
    def test_failed_payment_creates_alert(self, client, db):
        resp = _post_order(client, _order(8001, "fail@example.com", status="failed"))
        assert resp.status_code == 200
        assert "failed_payment" in resp.json()["pipeline"]["issues_detected"]

        customer_id = resp.json()["customer_id"]

        proposals = client.get("/api/proposals").json()
        alerts = [
            p for p in proposals if p["proposal_type"] == ProposalType.ISSUE_ALERT.value
        ]
        assert any(p["evidence"].get("issue_type") == "failed_payment" for p in alerts)

        timeline = client.get(f"/api/customers/{customer_id}/timeline").json()
        assert any(
            e["event_type"] == TimelineEventType.ISSUE_DETECTED.value for e in timeline
        )
