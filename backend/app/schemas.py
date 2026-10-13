"""Pydantic schemas for request/response validation."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field

from app.models import (
    CustomerSegment, OrderStatus, ProposalStatus,
    ProposalType, TimelineEventType,
)


# ── WooCommerce Webhook Payloads ───────────────────────────────────────────

class WooBilling(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""

    model_config = {"extra": "allow"}


class WooShipping(BaseModel):
    first_name: str = ""
    last_name: str = ""

    model_config = {"extra": "allow"}


class WooLineItem(BaseModel):
    id: int = 0
    name: str = ""
    product_id: int = 0
    quantity: int = 1
    total: str = "0.00"

    model_config = {"extra": "allow"}


class WooOrderPayload(BaseModel):
    """Matches WooCommerce order webhook JSON shape."""
    id: int
    status: str = "pending"
    total: str = "0.00"
    currency: str = "INR"
    payment_method: str = ""
    billing: WooBilling = WooBilling()
    shipping: WooShipping = WooShipping()
    line_items: list[WooLineItem] = []
    date_created: Optional[str] = None
    customer_id: int = 0  # 0 = guest

    model_config = {"extra": "allow"}


# ── Customer Schemas ───────────────────────────────────────────────────────

class CustomerOut(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    phone: str
    segment: CustomerSegment
    total_spent: float
    order_count: int
    first_order_date: Optional[datetime] = None
    last_order_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CustomerSummary(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    segment: CustomerSegment
    total_spent: float
    order_count: int

    model_config = {"from_attributes": True}


# ── Order Schemas ──────────────────────────────────────────────────────────

class OrderOut(BaseModel):
    id: int
    woo_order_id: int
    customer_id: int
    status: OrderStatus
    total: float
    currency: str
    payment_method: str
    line_items: list
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Timeline Schemas ───────────────────────────────────────────────────────

class TimelineEventOut(BaseModel):
    id: int
    customer_id: int
    event_type: TimelineEventType
    title: str
    description: str
    metadata_json: dict
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Proposal Schemas ──────────────────────────────────────────────────────

class ProposalOut(BaseModel):
    id: int
    customer_id: int
    proposal_type: ProposalType
    status: ProposalStatus
    title: str
    summary: str
    evidence: dict
    proposed_action: dict
    llm_explanation: str
    is_llm_generated: bool
    agent_name: str
    dedup_key: Optional[str]
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    executed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class ProposalReview(BaseModel):
    """Request body for approving/rejecting a proposal."""
    action: str = Field(..., pattern="^(approve|reject)$")
    reviewed_by: str = "admin"


# ── Dashboard Schemas ──────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_customers: int
    total_orders: int
    total_revenue: float
    pending_proposals: int
    segment_distribution: dict[str, int]
    recent_orders: list[OrderOut]
