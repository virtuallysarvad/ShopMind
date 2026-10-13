"""SQLAlchemy ORM models for ShopMind."""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey,
    Enum as SAEnum, Boolean, JSON, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship

from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


# ── Enums ──────────────────────────────────────────────────────────────────

class CustomerSegment(str, enum.Enum):
    NEW = "new"
    REGULAR = "regular"
    VIP = "vip"
    AT_RISK = "at_risk"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    FAILED = "failed"
    ON_HOLD = "on-hold"


class ProposalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


class ProposalType(str, enum.Enum):
    SEGMENT_CHANGE = "segment_change"
    FOLLOW_UP_EMAIL = "follow_up_email"
    ISSUE_ALERT = "issue_alert"


class TimelineEventType(str, enum.Enum):
    ORDER_CREATED = "order_created"
    ORDER_UPDATED = "order_updated"
    SEGMENT_CHANGED = "segment_changed"
    PROPOSAL_CREATED = "proposal_created"
    PROPOSAL_APPROVED = "proposal_approved"
    PROPOSAL_REJECTED = "proposal_rejected"
    PROPOSAL_EXECUTED = "proposal_executed"
    ISSUE_DETECTED = "issue_detected"
    FOLLOW_UP_DRAFTED = "follow_up_drafted"
    NOTE_ADDED = "note_added"


# ── Models ─────────────────────────────────────────────────────────────────

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    first_name = Column(String(100), default="")
    last_name = Column(String(100), default="")
    phone = Column(String(50), default="")
    woo_customer_id = Column(Integer, nullable=True, unique=True)
    segment = Column(SAEnum(CustomerSegment), default=CustomerSegment.NEW)
    total_spent = Column(Float, default=0.0)
    order_count = Column(Integer, default=0)
    first_order_date = Column(DateTime(timezone=True), nullable=True)
    last_order_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    orders = relationship("Order", back_populates="customer", lazy="selectin")
    timeline_events = relationship("TimelineEvent", back_populates="customer", lazy="selectin")
    proposals = relationship("Proposal", back_populates="customer", lazy="selectin")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    woo_order_id = Column(Integer, unique=True, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    status = Column(SAEnum(OrderStatus), default=OrderStatus.PENDING)
    total = Column(Float, default=0.0)
    currency = Column(String(3), default="USD")
    payment_method = Column(String(100), default="")
    line_items = Column(JSON, default=list)
    billing = Column(JSON, default=dict)
    shipping = Column(JSON, default=dict)
    woo_created_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    customer = relationship("Customer", back_populates="orders")

    __table_args__ = (
        Index("ix_orders_customer_status", "customer_id", "status"),
    )


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    event_type = Column(SAEnum(TimelineEventType), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    customer = relationship("Customer", back_populates="timeline_events")

    __table_args__ = (
        Index("ix_timeline_customer_created", "customer_id", "created_at"),
    )


class Proposal(Base):
    __tablename__ = "proposals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    proposal_type = Column(SAEnum(ProposalType), nullable=False)
    status = Column(SAEnum(ProposalStatus), default=ProposalStatus.PENDING)
    title = Column(String(255), nullable=False)
    summary = Column(Text, default="")
    evidence = Column(JSON, default=dict)      # inputs/data that triggered this
    proposed_action = Column(JSON, default=dict)  # what the agent wants to do
    llm_explanation = Column(Text, default="")   # LLM-generated reasoning
    is_llm_generated = Column(Boolean, default=False)  # flag: was LLM actually used?
    agent_name = Column(String(100), nullable=False)
    dedup_key = Column(String(255), nullable=True, unique=True)  # prevents duplicate proposals
    reviewed_by = Column(String(100), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    customer = relationship("Customer", back_populates="proposals")

    __table_args__ = (
        Index("ix_proposals_status", "status"),
        Index("ix_proposals_customer", "customer_id"),
    )
