"""End-to-end: store → ShopMind → human approval → store.

Runs top to bottom against real servers (see conftest.py). Each test builds
on the state the previous one left, the way a shop owner would click
through the app.
"""

import base64
import hashlib
import hmac
import json

from e2e.conftest import WEBHOOK_SECRET


def _sign(body: bytes) -> str:
    return base64.b64encode(hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).digest()).decode()


def _pending(api, type_=None):
    items = api.get("/api/proposals", params={"status": "pending", "limit": 200}).json()
    return [p for p in items if type_ is None or p["proposal_type"] == type_]


# 1. Boot and connect ─────────────────────────────────────────────────────

def test_health_reports_provider(api):
    r = api.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
    assert r.json()["llm_provider"] == "fake"


def test_woocommerce_status_connects_to_store(api, store):
    body = api.get("/api/woocommerce/status").json()
    assert body["mode"] == "live" and body["connected"] is True
    assert body["total_orders"] == 25
    # Plain-HTTP store, so ShopMind must sign with OAuth 1.0a HMAC-SHA256.
    assert store.get("/_test/auth").json()[-1] == {"oauth1": True, "consumer_key": "ck_e2e"}


# 2. Customer data management + order tracking ────────────────────────────

def test_sync_pulls_every_order_and_runs_agents(api):
    stats = api.post("/api/woocommerce/sync").json()
    assert stats["fetched"] == 25 and stats["new"] == 25 and not stats["errors"]
    assert stats["proposals_from_agents"] > 0


def test_sync_is_idempotent(api):
    before = len(api.get("/api/proposals", params={"limit": 200}).json())
    stats = api.post("/api/woocommerce/sync").json()
    # Every order is already known with the same status, so no agent re-runs.
    assert stats["fetched"] == 25 and stats["new"] == 0 and stats["proposals_from_agents"] == 0
    assert len(api.get("/api/proposals", params={"limit": 200}).json()) == before


def test_dashboard_and_customers_reflect_the_store(api):
    dash = api.get("/api/dashboard").json()
    assert dash["total_orders"] == 25
    assert dash["total_customers"] == 5
    assert dash["total_revenue"] > 0
    customers = api.get("/api/customers").json()
    assert {c["email"] for c in customers} == {
        "alice@example.com", "bob@example.com", "carol@example.com", "david@example.com", "eve@example.com"}


def test_customer_detail_has_orders_and_timeline(api):
    alice = next(c for c in api.get("/api/customers").json() if c["email"] == "alice@example.com")
    detail = api.get(f"/api/customers/{alice['id']}").json()
    assert detail["order_count"] > 0 and detail["total_spent"] > 0
    orders = api.get("/api/orders", params={"customer_id": alice["id"]}).json()
    assert len(orders) == detail["order_count"]
    timeline = api.get(f"/api/customers/{alice['id']}/timeline").json()
    assert any(e["event_type"] == "order_created" for e in timeline)


# 3. Real-time webhooks ───────────────────────────────────────────────────

def _webhook_order(order_id: int, status: str) -> dict:
    return {
        "id": order_id, "status": status, "total": "8999.00", "currency": "INR",
        "payment_method": "razorpay",
        "billing": {"first_name": "Farah", "last_name": "Khan", "email": "farah@example.com", "phone": "98200 00000"},
        "shipping": {"first_name": "Farah", "last_name": "Khan"},
        "line_items": [{"id": 1, "name": "Running Shoes - Pro Series", "quantity": 1, "total": "8999.00"}],
        "customer_id": 0,
        "date_created": "2026-10-13T10:00:00Z",
    }


def test_webhook_rejects_bad_signature(api):
    body = json.dumps(_webhook_order(5001, "processing")).encode()
    r = api.post("/webhooks/woocommerce/order", content=body,
                  headers={"X-WC-Webhook-Signature": "not-a-real-signature", "Content-Type": "application/json"})
    assert r.status_code == 401


def test_webhook_rejects_missing_signature(api):
    body = json.dumps(_webhook_order(5001, "processing")).encode()
    r = api.post("/webhooks/woocommerce/order", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 401


def test_webhook_ping_is_acknowledged(api):
    r = api.post("/webhooks/woocommerce/order", content=b"webhook_id=12",
                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and r.json()["ping"] is True


def test_signed_webhook_creates_customer_and_order(api):
    body = json.dumps(_webhook_order(5001, "processing")).encode()
    r = api.post("/webhooks/woocommerce/order", content=body, headers={
        "X-WC-Webhook-Signature": _sign(body), "X-WC-Webhook-Topic": "order.created",
        "Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    assert any(c["email"] == "farah@example.com" for c in api.get("/api/customers").json())
    assert any(o["woo_order_id"] == 5001 for o in api.get("/api/orders").json())


def test_failed_payment_webhook_raises_order_issue(api):
    body = json.dumps(_webhook_order(5001, "failed")).encode()
    r = api.post("/webhooks/woocommerce/order", content=body, headers={
        "X-WC-Webhook-Signature": _sign(body), "X-WC-Webhook-Topic": "order.updated",
        "Content-Type": "application/json"})
    assert r.status_code == 200
    order = next(o for o in api.get("/api/orders").json() if o["woo_order_id"] == 5001)
    assert order["status"] == "failed"
    issues = [p for p in _pending(api, "issue_alert") if p["proposed_action"].get("woo_order_id") == 5001]
    assert issues, "a failed payment should put an Order issue card in the inbox"


# 4. Human in the loop: approve → execute → write back to the store ───────

def test_approving_issue_writes_private_note_to_store(api, store):
    issue = next(p for p in _pending(api, "issue_alert") if p["proposed_action"].get("woo_order_id") == 5001)
    r = api.post(f"/api/proposals/{issue['id']}/review", json={"action": "approve"})
    assert r.status_code == 200
    assert api.get(f"/api/proposals/{issue['id']}").json()["status"] == "executed"
    notes = [w for w in store.get("/_test/writes").json() if w["kind"] == "order_note" and w["order_id"] == 5001]
    assert notes and notes[-1]["customer_note"] is False


def test_manual_email_is_approved_and_sent_as_customer_note(api, store):
    bob = next(c for c in api.get("/api/customers").json() if c["email"] == "bob@example.com")
    created = api.post("/api/proposals", json={
        "proposal_type": "follow_up_email", "customer_id": bob["id"],
        "subject": "Thanks for shopping with us", "body": "Hi Bob, here is 10% off your next order: THANKS10",
    })
    assert created.status_code == 201
    p = created.json()
    assert p["status"] == "pending" and p["agent_name"] == "manual"
    writes_before = len(store.get("/_test/writes").json())

    api.post(f"/api/proposals/{p['id']}/review", json={"action": "approve"})
    writes = store.get("/_test/writes").json()[writes_before:]
    assert len(writes) == 1
    assert writes[0]["kind"] == "order_note" and writes[0]["customer_note"] is True
    assert "THANKS10" in writes[0]["note"]


def test_manual_segment_change_updates_crm_and_store(api, store):
    david = next(c for c in api.get("/api/customers").json() if c["email"] == "david@example.com")
    target = "at_risk" if david["segment"] != "at_risk" else "regular"
    p = api.post("/api/proposals", json={
        "proposal_type": "segment_change", "customer_id": david["id"], "new_segment": target}).json()
    api.post(f"/api/proposals/{p['id']}/review", json={"action": "approve"})

    assert api.get(f"/api/customers/{david['id']}").json()["segment"] == target
    meta = [w for w in store.get("/_test/writes").json() if w["kind"] == "customer_meta"][-1]
    assert {"key": "shopmind_segment", "value": target} in meta["meta_data"]
    timeline = api.get(f"/api/customers/{david['id']}/timeline").json()
    assert any(e["title"] == "Synced to WooCommerce" for e in timeline)


def test_rejecting_changes_nothing_in_store(api, store):
    eve = next(c for c in api.get("/api/customers").json() if c["email"] == "eve@example.com")
    p = api.post("/api/proposals", json={
        "proposal_type": "follow_up_email", "customer_id": eve["id"], "subject": "Hi", "body": "Hello Eve"}).json()
    before = len(store.get("/_test/writes").json())
    r = api.post(f"/api/proposals/{p['id']}/review", json={"action": "reject"})
    assert r.json()["status"] == "rejected"
    assert len(store.get("/_test/writes").json()) == before
    # A reviewed proposal can't be reviewed again.
    assert api.post(f"/api/proposals/{p['id']}/review", json={"action": "approve"}).status_code == 400


# 5. Agentic Copilot (offline rules mode here; same tools as the LLM) ─────

def test_copilot_answers_from_crm_data(api):
    r = api.post("/api/copilot/chat", json={"messages": [{"role": "user", "content": "How is my shop doing?"}]})
    assert r.status_code == 200
    out = r.json()
    assert out["reply"] and out["steps"], "copilot should call at least one read tool"
    assert all(s["tool"] not in {"approve", "review_proposal"} for s in out["steps"])


def test_copilot_write_becomes_pending_proposal_only(api):
    carol = next(c for c in api.get("/api/customers").json() if c["email"] == "carol@example.com")
    target = "vip" if carol["segment"] != "vip" else "regular"
    word = "VIP" if target == "vip" else "regular"
    r = api.post("/api/copilot/chat", json={"messages": [{"role": "user", "content": f"Make Carol {word}"}]})
    out = r.json()
    assert out["proposals_created"], out
    p = api.get(f"/api/proposals/{out['proposals_created'][0]}").json()
    assert p["status"] == "pending" and p["agent_name"] == "shop_copilot"
    # Nothing changed yet: the human still has to approve.
    assert api.get(f"/api/customers/{carol['id']}").json()["segment"] == carol["segment"]


def test_dashboard_counts_pending(api):
    dash = api.get("/api/dashboard").json()
    assert dash["pending_proposals"] == len(_pending(api))
