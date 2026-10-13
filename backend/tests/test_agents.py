"""Tests for agents: segmentation, follow-up, issue detection, and proposals."""

from datetime import datetime, timezone, timedelta

import pytest

from app.models import (
    Customer, Order, CustomerSegment, OrderStatus,
    Proposal, ProposalStatus, ProposalType, TimelineEvent,
)
from app.agents.segment_agent import classify_customer, run_segment_agent
from app.agents.follow_up_agent import run_follow_up_agent
from app.agents.issue_watcher import run_issue_watcher
from app.services.proposal_service import review_proposal, create_proposal


# ── Deterministic Segmentation Tests ─────────────────────────────────────

class TestSegmentClassification:
    def test_new_customer(self, db):
        c = Customer(email="new@test.com", order_count=0, total_spent=0)
        assert classify_customer(c) == CustomerSegment.NEW

    def test_new_one_order(self, db):
        c = Customer(email="one@test.com", order_count=1, total_spent=50)
        assert classify_customer(c) == CustomerSegment.NEW

    def test_regular_customer(self, db):
        c = Customer(
            email="regular@test.com", order_count=3, total_spent=200,
            last_order_date=datetime.now(timezone.utc),
        )
        assert classify_customer(c) == CustomerSegment.REGULAR

    def test_vip_customer(self, db):
        c = Customer(email="vip@test.com", order_count=5, total_spent=500)
        assert classify_customer(c) == CustomerSegment.VIP

    def test_vip_high_orders_low_spend(self, db):
        """VIP requires BOTH thresholds."""
        c = Customer(email="almost@test.com", order_count=10, total_spent=100)
        assert classify_customer(c) != CustomerSegment.VIP

    def test_at_risk_customer(self, db):
        old_date = datetime.now(timezone.utc) - timedelta(days=90)
        c = Customer(
            email="atrisk@test.com", order_count=3, total_spent=200,
            last_order_date=old_date,
        )
        assert classify_customer(c) == CustomerSegment.AT_RISK


class TestSegmentAgent:
    def test_creates_proposal_on_change(self, db, sample_customer):
        sample_customer.order_count = 5
        sample_customer.total_spent = 600
        db.commit()
        created = run_segment_agent(db, sample_customer)
        assert created is True
        proposals = db.query(Proposal).filter(
            Proposal.customer_id == sample_customer.id
        ).all()
        assert len(proposals) == 1
        assert proposals[0].proposal_type == ProposalType.SEGMENT_CHANGE

    def test_no_proposal_when_segment_matches(self, db, sample_customer):
        """NEW customer with 0 orders should stay NEW — no proposal."""
        created = run_segment_agent(db, sample_customer)
        assert created is False

    def test_dedup_prevents_duplicate(self, db, sample_customer):
        """Running segment agent twice should only create one proposal."""
        sample_customer.order_count = 5
        sample_customer.total_spent = 600
        db.commit()
        first = run_segment_agent(db, sample_customer)
        db.commit()
        second = run_segment_agent(db, sample_customer)
        assert first is True
        assert second is False  # dedup


# ── Follow-up Agent Tests ────────────────────────────────────────────────

class TestFollowUpAgent:
    def test_welcome_email(self, db, sample_customer):
        created = run_follow_up_agent(db, sample_customer, "new_customer_welcome")
        db.commit()
        assert created is True
        p = db.query(Proposal).filter(
            Proposal.customer_id == sample_customer.id,
            Proposal.proposal_type == ProposalType.FOLLOW_UP_EMAIL,
        ).first()
        assert p is not None
        assert "Welcome" in p.proposed_action.get("draft", "")

    def test_dedup_follow_up(self, db, sample_customer):
        run_follow_up_agent(db, sample_customer, "new_customer_welcome")
        db.commit()
        second = run_follow_up_agent(db, sample_customer, "new_customer_welcome")
        assert second is False


# ── Issue Watcher Tests ──────────────────────────────────────────────────

class TestIssueWatcher:
    def test_detects_failed_payment(self, db, sample_customer):
        order = Order(
            woo_order_id=9001, customer_id=sample_customer.id,
            status=OrderStatus.FAILED, total=50.0,
        )
        db.add(order)
        db.commit()
        issues = run_issue_watcher(db, sample_customer, order)
        assert "failed_payment" in issues

    def test_no_issue_on_completed(self, db, sample_customer):
        order = Order(
            woo_order_id=9002, customer_id=sample_customer.id,
            status=OrderStatus.COMPLETED, total=50.0,
        )
        db.add(order)
        db.commit()
        issues = run_issue_watcher(db, sample_customer, order)
        assert "failed_payment" not in issues

    def test_detects_repeated_returns(self, db, sample_customer):
        for i in range(3):
            db.add(Order(
                woo_order_id=9100 + i, customer_id=sample_customer.id,
                status=OrderStatus.REFUNDED, total=30.0,
            ))
        db.commit()
        latest = db.query(Order).filter(Order.woo_order_id == 9102).first()
        issues = run_issue_watcher(db, sample_customer, latest)
        assert "repeated_return" in issues


# ── Approval State Machine Tests ─────────────────────────────────────────

class TestApprovalStateMachine:
    def _create_test_proposal(self, db, customer):
        return create_proposal(
            db,
            customer_id=customer.id,
            proposal_type=ProposalType.SEGMENT_CHANGE,
            title="Test proposal",
            summary="Test",
            evidence={"test": True},
            proposed_action={"action": "test"},
            agent_name="test_agent",
            dedup_key=f"test:{customer.id}:{id(self)}",
        )

    def test_approve_proposal(self, db, sample_customer):
        p = self._create_test_proposal(db, sample_customer)
        db.commit()
        result = review_proposal(db, p.id, "approve", "admin")
        assert result.status == ProposalStatus.APPROVED
        assert result.reviewed_by == "admin"

    def test_reject_proposal(self, db, sample_customer):
        p = self._create_test_proposal(db, sample_customer)
        db.commit()
        result = review_proposal(db, p.id, "reject", "admin")
        assert result.status == ProposalStatus.REJECTED

    def test_cannot_review_non_pending(self, db, sample_customer):
        p = self._create_test_proposal(db, sample_customer)
        db.commit()
        review_proposal(db, p.id, "approve", "admin")
        with pytest.raises(ValueError, match="cannot review"):
            review_proposal(db, p.id, "reject", "admin")

    def test_invalid_action_raises(self, db, sample_customer):
        p = self._create_test_proposal(db, sample_customer)
        db.commit()
        with pytest.raises(ValueError, match="Invalid action"):
            review_proposal(db, p.id, "maybe", "admin")
