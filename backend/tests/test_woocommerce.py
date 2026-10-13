"""Tests for the live WooCommerce integration: REST client auth + pagination,
order sync, write-back of approved proposals, and real webhook signatures.

A fake store (httpx.MockTransport) stands in for WordPress, and it checks the
OAuth 1.0a signature the same way WooCommerce's PHP does.
"""

import base64
import hashlib
import hmac
import json
from urllib.parse import quote, unquote, urlsplit, parse_qsl

import httpx
import pytest

from app.config import settings
from app.models import Customer, Order, Proposal, ProposalStatus, ProposalType, CustomerSegment
from app.services.woo_sync import sync_orders, write_back, payload_from_rest
from app.woo_client import WooCommerceClient, WooCommerceError, oauth1_signature

KEY, SECRET = "ck_test", "cs_test"


def _rawurlencode(s):
    return quote(s, safe="-._~")


def woo_php_check_signature(method, url, params, secret):
    """Port of WC_REST_Authentication::check_oauth_signature (HMAC-SHA256)."""
    sig = params["oauth_signature"]
    p = {k: v for k, v in params.items() if k != "oauth_signature"}
    norm = sorted((_rawurlencode(unquote(k)), _rawurlencode(unquote(v))) for k, v in p.items())
    query = "%26".join(f"{k}%3D{v}" for k, v in norm)
    base = f"{method}&{_rawurlencode(url)}&{query}"
    expected = base64.b64encode(hmac.new(f"{secret}&".encode(), base.encode(), hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, sig)


def rest_order(oid, email="asha@example.com", status="processing", total="2499.00", customer_id=0):
    return {
        "id": oid, "status": status, "total": total, "currency": "INR",
        "payment_method": "razorpay", "customer_id": customer_id,
        "date_created": "2026-10-13T14:00:00", "date_created_gmt": "2026-10-13T08:30:00",
        "billing": {"first_name": "Asha", "last_name": "Naik", "email": email, "phone": "9876543210"},
        "shipping": {"first_name": "Asha", "last_name": "Naik"},
        "line_items": [{"id": 1, "name": "Kokum Sherbet", "product_id": 9, "quantity": 1, "total": total}],
    }


class FakeStore:
    def __init__(self, orders, per_page_cap=2, fail=False):
        self.orders = orders
        self.cap = per_page_cap
        self.fail = fail
        self.calls = []
        self.notes = []
        self.customer_updates = []

    def handler(self, request: httpx.Request):
        url = str(request.url)
        parts = urlsplit(url)
        params = dict(parse_qsl(parts.query))
        self.calls.append((request.method, parts.path, params, dict(request.headers)))
        if self.fail:
            return httpx.Response(500, json={"message": "boom"})
        # auth: Basic over https, OAuth over http
        if parts.scheme == "https":
            assert request.headers["authorization"] == "Basic " + base64.b64encode(f"{KEY}:{SECRET}".encode()).decode()
        else:
            base_url = f"{parts.scheme}://{parts.netloc}{parts.path}"
            if not woo_php_check_signature(request.method, base_url, params, SECRET):
                return httpx.Response(401, json={"message": "Invalid signature - provided signature does not match."})
        path = parts.path.replace("/wp-json/wc/v3/", "")
        if request.method == "GET" and path == "orders":
            per = min(int(params.get("per_page", 10)), self.cap)
            page = int(params.get("page", 1))
            chunk = self.orders[(page - 1) * per: page * per]
            pages = max(1, -(-len(self.orders) // per))
            return httpx.Response(200, json=chunk, headers={"X-WP-Total": str(len(self.orders)), "X-WP-TotalPages": str(pages)})
        if request.method == "POST" and path.startswith("orders/") and path.endswith("/notes"):
            body = json.loads(request.content)
            self.notes.append({"order": int(path.split("/")[1]), **body})
            return httpx.Response(201, json={"id": 500 + len(self.notes), **body})
        if request.method == "PUT" and path.startswith("customers/"):
            body = json.loads(request.content)
            self.customer_updates.append({"customer": int(path.split("/")[1]), **body})
            return httpx.Response(200, json={"id": int(path.split("/")[1]), **body})
        return httpx.Response(404, json={"message": "No route"})


def make_client(store, url="http://localhost:8080"):
    return WooCommerceClient(url, KEY, SECRET, transport=httpx.MockTransport(store.handler))


# ── REST client ───────────────────────────────────────────────────────────

class TestClient:
    def test_oauth_over_http_matches_woocommerce_php(self):
        store = FakeStore([rest_order(1)])
        list(make_client(store).list_orders())
        _, _, params, headers = store.calls[0]
        assert params["oauth_signature_method"] == "HMAC-SHA256"
        assert "authorization" not in {k.lower() for k in headers}

    def test_signature_known_vector(self):
        params = {"oauth_consumer_key": "ck", "oauth_nonce": "n", "oauth_signature_method": "HMAC-SHA256",
                  "oauth_timestamp": "1", "per_page": "1"}
        sig = oauth1_signature("GET", "http://x.test/wp-json/wc/v3/orders", params, "cs")
        assert woo_php_check_signature("GET", "http://x.test/wp-json/wc/v3/orders", {**params, "oauth_signature": sig}, "cs")
        assert not woo_php_check_signature("GET", "http://x.test/wp-json/wc/v3/orders", {**params, "oauth_signature": sig}, "wrong")

    def test_basic_auth_over_https(self):
        store = FakeStore([rest_order(1)])
        assert make_client(store, "https://shop.example.in").ping()["total_orders"] == 1

    def test_paginates_with_total_pages_header(self):
        store = FakeStore([rest_order(i, email=f"c{i}@x.in") for i in range(1, 6)], per_page_cap=2)
        ids = [o["id"] for o in make_client(store).list_orders()]
        assert ids == [1, 2, 3, 4, 5]
        assert len([c for c in store.calls if c[1].endswith("/orders")]) == 3

    def test_errors_become_woocommerce_error(self):
        with pytest.raises(WooCommerceError, match="500"):
            make_client(FakeStore([], fail=True)).ping()


# ── Inbound sync ──────────────────────────────────────────────────────────

class TestSync:
    def test_payload_uses_gmt_date(self):
        p = payload_from_rest(rest_order(7))
        assert p.date_created == "2026-10-13T08:30:00Z"

    def test_sync_ingests_and_runs_agents(self, db):
        store = FakeStore([rest_order(1), rest_order(2, email="ravi@example.com", status="failed")])
        stats = sync_orders(db, make_client(store))
        assert stats["fetched"] == 2 and stats["new"] == 2 and not stats["errors"]
        assert db.query(Order).count() == 2
        assert stats["proposals_from_agents"] >= 2  # welcome emails + failed-payment issue

    def test_resync_is_idempotent(self, db):
        store = FakeStore([rest_order(1)])
        sync_orders(db, make_client(store))
        before = db.query(Proposal).count()
        stats = sync_orders(db, make_client(store))
        assert stats["new"] == 0 and stats["updated"] == 1 and stats["proposals_from_agents"] == 0
        assert db.query(Proposal).count() == before
        assert db.query(Customer).one().order_count == 1

    def test_status_change_reruns_agents(self, db):
        store = FakeStore([rest_order(1)])
        sync_orders(db, make_client(store))
        store.orders = [rest_order(1, status="failed")]
        stats = sync_orders(db, make_client(store))
        assert stats["proposals_from_agents"] >= 1
        assert db.query(Order).one().status.value == "failed"

    def test_orders_without_email_are_skipped(self, db):
        store = FakeStore([rest_order(1, email="")])
        assert sync_orders(db, make_client(store))["skipped"] == 1


# ── Outbound write-back ───────────────────────────────────────────────────

def _proposal(db, customer, ptype, action, summary="why"):
    p = Proposal(customer_id=customer.id, proposal_type=ptype, title="t", summary=summary,
                 evidence={}, proposed_action=action, agent_name="test", status=ProposalStatus.APPROVED)
    db.add(p)
    db.commit()
    return p


@pytest.fixture
def woo_customer(db):
    store = FakeStore([rest_order(1001, customer_id=42)])
    sync_orders(db, make_client(store))
    return db.query(Customer).one()


class TestWriteBack:
    def test_segment_sets_customer_meta(self, db, woo_customer):
        store = FakeStore([])
        p = _proposal(db, woo_customer, ProposalType.SEGMENT_CHANGE, {"action": "change_segment", "to": "vip"})
        res = write_back(db, p, make_client(store))
        assert res["status"] == "ok"
        meta = {m["key"]: m["value"] for m in store.customer_updates[0]["meta_data"]}
        assert store.customer_updates[0]["customer"] == 42 and meta["shopmind_segment"] == "vip"
        assert p.evidence["woo_writeback"]["status"] == "ok"

    def test_guest_segment_is_skipped(self, db, sample_customer):
        p = _proposal(db, sample_customer, ProposalType.SEGMENT_CHANGE, {"action": "change_segment", "to": "vip"})
        assert write_back(db, p, make_client(FakeStore([])))["status"] == "skipped"

    def test_email_becomes_customer_note(self, db, woo_customer):
        store = FakeStore([])
        draft = json.dumps({"subject": "Thank you!", "body": "Hi Asha"})
        p = _proposal(db, woo_customer, ProposalType.FOLLOW_UP_EMAIL, {"action": "send_email", "draft": draft})
        assert write_back(db, p, make_client(store))["status"] == "ok"
        assert store.notes == [{"order": 1001, "note": "Thank you!\n\nHi Asha", "customer_note": True}]

    def test_issue_becomes_private_note(self, db, woo_customer):
        store = FakeStore([])
        p = _proposal(db, woo_customer, ProposalType.ISSUE_ALERT,
                      {"action": "investigate_issue", "issue_type": "failed_payment", "woo_order_id": 1001})
        write_back(db, p, make_client(store))
        assert store.notes[0]["customer_note"] is False and "failed_payment" in store.notes[0]["note"]

    def test_store_error_is_recorded_not_raised(self, db, woo_customer):
        p = _proposal(db, woo_customer, ProposalType.SEGMENT_CHANGE, {"action": "change_segment", "to": "vip"})
        res = write_back(db, p, make_client(FakeStore([], fail=True)))
        assert res["status"] == "error"

    def test_mock_mode_skips(self, db, woo_customer):
        p = _proposal(db, woo_customer, ProposalType.SEGMENT_CHANGE, {"action": "change_segment", "to": "vip"})
        assert write_back(db, p, None)["status"] == "skipped"

    def test_approve_endpoint_writes_back_in_live_mode(self, client, db, woo_customer, monkeypatch):
        store = FakeStore([])
        monkeypatch.setattr("app.routes.api.get_woo_client", lambda: make_client(store))
        p = _proposal(db, woo_customer, ProposalType.SEGMENT_CHANGE, {"action": "change_segment", "to": "vip"})
        p.status = ProposalStatus.PENDING
        db.commit()
        r = client.post(f"/api/proposals/{p.id}/review", json={"action": "approve"})
        assert r.status_code == 200 and r.json()["status"] == "executed"
        assert store.customer_updates and db.get(Customer, woo_customer.id).segment == CustomerSegment.VIP


# ── Webhooks as WooCommerce really sends them ─────────────────────────────

def _b64sig(body: bytes) -> str:
    return base64.b64encode(hmac.new(settings.woo_webhook_secret.encode(), body, hashlib.sha256).digest()).decode()


class TestWebhooks:
    def test_accepts_base64_signature(self, client):
        body = json.dumps(rest_order(3001)).encode()
        r = client.post("/webhooks/woocommerce/order", content=body, headers={
            "X-WC-Webhook-Signature": _b64sig(body), "X-WC-Webhook-Topic": "order.created",
            "Content-Type": "application/json"})
        assert r.status_code == 200 and r.json()["woo_order_id"] == 3001

    def test_ping_is_acknowledged(self, client):
        r = client.post("/webhooks/woocommerce/order", content=b"webhook_id=12",
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert r.status_code == 200 and r.json()["ping"] is True

    def test_deleted_topic_ignored(self, client):
        body = json.dumps({"id": 5}).encode()
        r = client.post("/webhooks/woocommerce/order", content=body, headers={
            "X-WC-Webhook-Signature": _b64sig(body), "X-WC-Webhook-Topic": "order.deleted"})
        assert r.json()["status"] == "ignored"

    def test_status_endpoint_mock_mode(self, client):
        assert client.get("/api/woocommerce/status").json()["mode"] == "mock"

    def test_sync_endpoint_refuses_in_mock_mode(self, client):
        assert client.post("/api/woocommerce/sync").status_code == 400
