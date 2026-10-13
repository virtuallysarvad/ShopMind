"""Manual proposals: POST /api/proposals adds a pending card by hand."""

import json

import pytest

from app.models import Order, OrderStatus, Proposal, ProposalStatus


@pytest.fixture
def order(db, sample_customer):
    o = Order(woo_order_id=2001, customer_id=sample_customer.id, status=OrderStatus.FAILED, total=1499)
    db.add(o)
    db.commit()
    return o


def test_manual_segment_change_is_pending(client, db, sample_customer):
    r = client.post("/api/proposals", json={
        "proposal_type": "segment_change", "customer_id": sample_customer.id,
        "new_segment": "vip", "note": "Big wholesale buyer",
    })
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["status"] == "pending"
    assert p["agent_name"] == "manual"
    assert p["is_llm_generated"] is False
    assert p["proposed_action"] == {"action": "change_segment", "from": "new", "to": "vip"}
    assert p["summary"] == "Big wholesale buyer"


def test_manual_segment_change_approve_executes(client, db, sample_customer):
    pid = client.post("/api/proposals", json={
        "proposal_type": "segment_change", "customer_id": sample_customer.id, "new_segment": "regular",
    }).json()["id"]
    r = client.post(f"/api/proposals/{pid}/review", json={"action": "approve"})
    assert r.status_code == 200
    db.refresh(sample_customer)
    assert sample_customer.segment.value == "regular"
    assert db.get(Proposal, pid).status == ProposalStatus.EXECUTED


def test_manual_segment_same_segment_rejected(client, sample_customer):
    r = client.post("/api/proposals", json={
        "proposal_type": "segment_change", "customer_id": sample_customer.id, "new_segment": "new",
    })
    assert r.status_code == 400
    assert "already" in r.json()["detail"]


def test_manual_email_stores_subject_and_body(client, sample_customer):
    r = client.post("/api/proposals", json={
        "proposal_type": "follow_up_email", "customer_id": sample_customer.id,
        "subject": "Diwali offer", "body": "Hi Test, 10% off this week.",
    })
    assert r.status_code == 201
    action = r.json()["proposed_action"]
    assert action["action"] == "send_email" and action["to"] == "test@example.com"
    assert json.loads(action["draft"]) == {"subject": "Diwali offer", "body": "Hi Test, 10% off this week."}


def test_manual_email_needs_subject_and_body(client, sample_customer):
    r = client.post("/api/proposals", json={
        "proposal_type": "follow_up_email", "customer_id": sample_customer.id, "subject": "Hi",
    })
    assert r.status_code == 400


def test_two_manual_emails_both_created(client, sample_customer):
    body = {"proposal_type": "follow_up_email", "customer_id": sample_customer.id, "subject": "A", "body": "B"}
    assert client.post("/api/proposals", json=body).status_code == 201
    assert client.post("/api/proposals", json=body).status_code == 201


def test_manual_issue_on_order(client, order, sample_customer):
    r = client.post("/api/proposals", json={
        "proposal_type": "issue_alert", "woo_order_id": 2001, "issue_type": "payment_failed",
        "note": "Customer called about a double charge",
    })
    assert r.status_code == 201
    p = r.json()
    assert p["customer_id"] == sample_customer.id
    assert p["proposed_action"]["woo_order_id"] == 2001


def test_manual_issue_unknown_order_404(client):
    r = client.post("/api/proposals", json={"proposal_type": "issue_alert", "woo_order_id": 9999})
    assert r.status_code == 404


def test_manual_issue_wrong_customer(client, order, vip_customer):
    r = client.post("/api/proposals", json={
        "proposal_type": "issue_alert", "woo_order_id": 2001, "customer_id": vip_customer.id,
    })
    assert r.status_code == 400


def test_manual_unknown_customer_404(client):
    r = client.post("/api/proposals", json={
        "proposal_type": "segment_change", "customer_id": 999, "new_segment": "vip",
    })
    assert r.status_code == 404


def test_manual_proposal_on_timeline(client, sample_customer):
    client.post("/api/proposals", json={
        "proposal_type": "segment_change", "customer_id": sample_customer.id, "new_segment": "vip",
    })
    events = client.get(f"/api/customers/{sample_customer.id}/timeline").json()
    assert any(e["event_type"] == "proposal_created" for e in events)
