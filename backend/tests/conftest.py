"""Shared test fixtures for ShopMind backend tests."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Customer, Order, CustomerSegment, OrderStatus


@pytest.fixture
def db():
    """Create a fresh in-memory SQLite database for each test."""
    # check_same_thread=False + StaticPool keep this in-memory database on a
    # single shared connection.  The FastAPI TestClient dispatches requests on
    # a separate thread, which would otherwise get its own empty in-memory DB.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db):
    """FastAPI TestClient wired to the test's in-memory DB session.

    Note: not used as a context manager, so app startup (which would create the
    on-disk DB) does not run -- the override supplies the session.
    """

    def _override_get_db():
        return db

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def sample_customer(db):
    """Create a basic customer for testing."""
    customer = Customer(
        email="test@example.com",
        first_name="Test",
        last_name="User",
        phone="555-0100",
        segment=CustomerSegment.NEW,
        total_spent=0,
        order_count=0,
    )
    db.add(customer)
    db.commit()
    return customer


@pytest.fixture
def vip_customer(db):
    """Create a customer who qualifies as VIP."""
    customer = Customer(
        email="vip@example.com",
        first_name="VIP",
        last_name="Customer",
        segment=CustomerSegment.REGULAR,
        total_spent=25000.0,
        order_count=10,
    )
    db.add(customer)
    db.commit()
    return customer
