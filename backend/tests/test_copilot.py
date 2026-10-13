"""Tests for the Shop Copilot chat agent and its tools."""

import json

import httpx
import pytest

from app.agents import copilot
from app.agents.copilot import RuleCopilot, run_llm_copilot, chat
from app.agents.copilot_tools import TOOLS, run_tool, inr
from app.models import (
    Customer, CustomerSegment, Order, OrderStatus, Proposal, ProposalStatus, ProposalType,
)


@pytest.fixture
def shop(db):
    alice = Customer(email="alice@example.com", first_name="Alice", last_name="Shah",
                     segment=CustomerSegment.REGULAR, order_count=6, total_spent=22000)
    bob = Customer(email="bob@example.com", first_name="Bob", last_name="Naik",
                   segment=CustomerSegment.NEW, order_count=1, total_spent=1299)
    db.add_all([alice, bob])
    db.flush()
    db.add_all([
        Order(woo_order_id=1001, customer_id=alice.id, status=OrderStatus.COMPLETED, total=3999,
              line_items=[{"name": "Running Shoes"}]),
        Order(woo_order_id=1002, customer_id=bob.id, status=OrderStatus.FAILED, total=1299),
    ])
    db.commit()
    return {"alice": alice, "bob": bob}


class ScriptedModel:
    """Fake tool-calling model: replays a fixed list of assistant messages."""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def complete(self, messages, tools):
        self.seen.append(messages)
        return self.script.pop(0), "test-model"


def _call(name, **args):
    return {"tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)}}]}


class TestTools:
    def test_inr_indian_grouping(self):
        assert inr(123456) == "₹1,23,456"
        assert inr(999) == "₹999"
        assert inr(10000000) == "₹1,00,00,000"

    def test_shop_stats_excludes_failed_from_revenue(self, db, shop):
        res = run_tool(db, "shop_stats", {})
        assert res["orders"] == 2
        assert res["revenue_inr"] == 3999

    def test_search_customers_sorted_by_spend(self, db, shop):
        res = run_tool(db, "search_customers", {"sort_by": "total_spent"})
        assert [c["name"] for c in res["customers"]] == ["Alice Shah", "Bob Naik"]

    def test_bad_args_return_error_not_exception(self, db, shop):
        assert "error" in run_tool(db, "list_orders", {"status": "lost"})
        assert "error" in run_tool(db, "nope", {})
        assert "error" in run_tool(db, "get_customer", {"customer_id": 999})

    def test_segment_change_is_only_a_pending_proposal(self, db, shop):
        alice = shop["alice"]
        res = run_tool(db, "propose_segment_change", {"customer_id": alice.id, "new_segment": "vip"})
        assert res["created"] is True
        db.refresh(alice)
        assert alice.segment == CustomerSegment.REGULAR  # unchanged until approval
        p = db.get(Proposal, res["proposal_id"])
        assert p.status == ProposalStatus.PENDING
        assert p.agent_name == "shop_copilot"
        assert p.proposed_action == {"action": "change_segment", "from": "regular", "to": "vip"}

    def test_segment_change_dedup(self, db, shop):
        args = {"customer_id": shop["alice"].id, "new_segment": "vip"}
        assert run_tool(db, "propose_segment_change", args)["created"] is True
        assert run_tool(db, "propose_segment_change", args)["created"] is False

    def test_email_draft_renders_as_subject_body_json(self, db, shop):
        res = run_tool(db, "draft_follow_up_email", {
            "customer_id": shop["bob"].id, "subject": "Payment help", "body": "Hi Bob"})
        p = db.get(Proposal, res["proposal_id"])
        assert p.proposal_type == ProposalType.FOLLOW_UP_EMAIL
        assert json.loads(p.proposed_action["draft"]) == {"subject": "Payment help", "body": "Hi Bob"}

    def test_no_tool_can_approve(self):
        assert not any("approve" in n or "execute" in n for n in TOOLS)


class TestLlmLoop:
    def test_tool_then_answer(self, db, shop):
        model = ScriptedModel([
            _call("search_customers", sort_by="total_spent", limit=1),
            {"content": "Alice Shah is your top customer at ₹22,000."},
        ])
        out = run_llm_copilot(db, [{"role": "user", "content": "top customer?"}], model)
        assert out.mode == "llm" and out.model == "test-model"
        assert out.reply.startswith("Alice")
        assert [s.tool for s in out.steps] == ["search_customers"]
        tool_msg = model.seen[1][-1]
        assert tool_msg["role"] == "tool" and "Alice Shah" in tool_msg["content"]

    def test_write_through_llm_creates_pending_proposal(self, db, shop):
        model = ScriptedModel([
            _call("propose_segment_change", customer_id=shop["alice"].id, new_segment="vip", reason="6 orders"),
            {"content": "Sent to your Approval Inbox."},
        ])
        out = run_llm_copilot(db, [{"role": "user", "content": "make alice vip"}], model)
        assert len(out.proposals_created) == 1
        assert db.query(Proposal).filter_by(status=ProposalStatus.PENDING).count() == 1

    def test_step_limit(self, db, shop):
        model = ScriptedModel([_call("shop_stats")] * copilot.MAX_STEPS)
        out = run_llm_copilot(db, [{"role": "user", "content": "loop"}], model)
        assert len(out.steps) == copilot.MAX_STEPS
        assert "ran out of steps" in out.reply

    def test_model_down_falls_back_to_rules(self, db, shop):
        class Down:
            def complete(self, messages, tools):
                raise httpx.ConnectError("refused")
        out = chat(db, [{"role": "user", "content": "how much revenue?"}], model=Down())
        assert out.mode == "rules" and out.note
        assert "₹3,999" in out.reply


class TestRules:
    def run(self, db, text):
        return RuleCopilot().run(db, text)

    def test_stats(self, db, shop):
        assert "₹3,999" in self.run(db, "how is the shop doing").reply

    def test_top_customers(self, db, shop):
        out = self.run(db, "who are my top customers")
        assert out.reply.index("Alice") < out.reply.index("Bob")

    def test_failed_orders(self, db, shop):
        assert "#1002" in self.run(db, "show failed orders").reply

    def test_customer_lookup(self, db, shop):
        assert "Bob Naik is new" in self.run(db, "tell me about bob").reply

    def test_draft_email(self, db, shop):
        out = self.run(db, "draft an email to bob about his failed payment")
        assert out.proposals_created and "Approval Inbox" in out.reply

    def test_make_vip(self, db, shop):
        out = self.run(db, "make alice vip")
        assert out.proposals_created
        assert db.get(Customer, shop["alice"].id).segment == CustomerSegment.REGULAR


class TestEndpoint:
    def test_chat_endpoint(self, client, shop):
        r = client.post("/api/copilot/chat", json={"messages": [{"role": "user", "content": "failed orders?"}]})
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "rules"
        assert body["steps"][0]["tool"] == "list_orders"

    def test_last_message_must_be_user(self, client, shop):
        r = client.post("/api/copilot/chat", json={"messages": [{"role": "assistant", "content": "hi"}]})
        assert r.status_code == 400
