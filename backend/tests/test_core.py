"""Tests for webhook signature validation, order ingestion, and customer resolution."""

import hashlib
import hmac
import json

import pytest

from app.models import Customer, Order, OrderStatus, CustomerSegment, TimelineEvent
from app.schemas import WooOrderPayload, WooBilling, WooLineItem
from app.services.customer_service import resolve_customer
from app.services.order_service import ingest_order
from app.routes.webhooks import verify_webhook_signature


# ── Webhook Signature Tests ───────────────────────────────────────────────

class TestWebhookSignature:
    def test_valid_signature(self):
        payload = b'{"id": 123}'
        secret = "test_secret"
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(payload, sig, secret) is True

    def test_invalid_signature(self):
        payload = b'{"id": 123}'
        assert verify_webhook_signature(payload, "wrong_sig", "test_secret") is False

    def test_empty_signature(self):
        assert verify_webhook_signature(b'{}', "", "secret") is False

    def test_tampered_payload(self):
        secret = "test_secret"
        original = b'{"id": 123}'
        sig = hmac.new(secret.encode(), original, hashlib.sha256).hexdigest()
        tampered = b'{"id": 456}'
        assert verify_webhook_signature(tampered, sig, secret) is False


# ── Customer Resolution Tests ────────────────────────────────────────────

class TestCustomerResolution:
    def test_creates_new_customer(self, db):
        customer = resolve_customer(db, email="new@example.com", first_name="New")
        db.commit()
        assert customer.id is not None
        assert customer.email == "new@example.com"
        assert customer.first_name == "New"

    def test_resolves_existing_by_email(self, db):
        c1 = resolve_customer(db, email="same@example.com", first_name="First")
        db.commit()
        c2 = resolve_customer(db, email="same@example.com", first_name="Updated")
        db.commit()
        assert c1.id == c2.id  # same customer

    def test_merges_info_on_resolve(self, db):
        c1 = resolve_customer(db, email="merge@example.com", first_name="Jane")
        db.commit()
        assert c1.phone == ""
        resolve_customer(db, email="merge@example.com", phone="555-1234")
        db.commit()
        assert c1.phone == "555-1234"

    def test_guest_order_matching(self, db):
        """Guest orders (woo_customer_id=0) should match by email."""
        c1 = resolve_customer(db, email="guest@example.com", woo_customer_id=None)
        db.commit()
        c2 = resolve_customer(db, email="guest@example.com", woo_customer_id=None)
        db.commit()
        assert c1.id == c2.id

    def test_email_case_insensitive(self, db):
        c1 = resolve_customer(db, email="Alice@Example.COM")
        db.commit()
        c2 = resolve_customer(db, email="alice@example.com")
        db.commit()
        assert c1.id == c2.id

    def test_requires_email(self, db):
        with pytest.raises(ValueError, match="email"):
            resolve_customer(db, email="")


# ── Order Ingestion Tests ────────────────────────────────────────────────

class TestOrderIngestion:
    def _make_payload(self, order_id=1001, email="buyer@example.com",
                      status="processing", total="99.99"):
        return WooOrderPayload(
            id=order_id,
            status=status,
            total=total,
            currency="INR",
            payment_method="stripe",
            billing=WooBilling(
                first_name="Test", last_name="Buyer",
                email=email, phone="555-0001",
            ),
            line_items=[WooLineItem(name="Widget", product_id=1, quantity=1, total=total)],
            date_created="2026-10-13T10:00:00Z",
            customer_id=0,
        )

    def test_ingests_new_order(self, db):
        payload = self._make_payload()
        order = ingest_order(db, payload)
        assert order.woo_order_id == 1001
        assert order.total == 99.99
        assert order.customer.email == "buyer@example.com"

    def test_idempotent_upsert(self, db):
        """Re-ingesting same order_id updates rather than duplicates."""
        p1 = self._make_payload(order_id=2001, total="50.00")
        o1 = ingest_order(db, p1)
        assert o1.total == 50.00

        p2 = self._make_payload(order_id=2001, total="75.00")
        o2 = ingest_order(db, p2)
        assert o1.id == o2.id  # same DB row
        assert o2.total == 75.00

    def test_customer_aggregates_updated(self, db):
        payload = self._make_payload(order_id=3001, total="100.00")
        order = ingest_order(db, payload)
        customer = order.customer
        assert customer.order_count == 1
        assert customer.total_spent == 100.00
        assert customer.first_order_date is not None

    def test_timeline_event_created(self, db):
        payload = self._make_payload(order_id=4001)
        order = ingest_order(db, payload)
        events = db.query(TimelineEvent).filter(
            TimelineEvent.customer_id == order.customer_id
        ).all()
        assert len(events) >= 1
        assert any("created" in e.title.lower() for e in events)

    def test_multiple_orders_same_customer(self, db):
        p1 = self._make_payload(order_id=5001, email="multi@example.com", total="50.00")
        p2 = self._make_payload(order_id=5002, email="multi@example.com", total="75.00")
        o1 = ingest_order(db, p1)
        o2 = ingest_order(db, p2)
        assert o1.customer_id == o2.customer_id
        customer = o1.customer
        assert customer.order_count == 2
        assert customer.total_spent == 125.00
