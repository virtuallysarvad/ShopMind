"""MockWooClient: simulates WooCommerce REST API and webhook delivery.

Generates realistic-looking orders for development without requiring
a real WordPress/WooCommerce instance.
"""

import random
import hashlib
import hmac
import json
from datetime import datetime, timezone, timedelta

from app.schemas import WooOrderPayload, WooBilling, WooShipping, WooLineItem


# Sample data for realistic mock orders
SAMPLE_CUSTOMERS = [
    {"first_name": "Alice", "last_name": "Johnson", "email": "alice@example.com", "phone": "555-0101"},
    {"first_name": "Bob", "last_name": "Smith", "email": "bob@example.com", "phone": "555-0102"},
    {"first_name": "Carol", "last_name": "Williams", "email": "carol@example.com", "phone": "555-0103"},
    {"first_name": "David", "last_name": "Brown", "email": "david@example.com", "phone": "555-0104"},
    {"first_name": "Eve", "last_name": "Davis", "email": "eve@example.com", "phone": "555-0105"},
]

SAMPLE_PRODUCTS = [
    {"id": 101, "name": "Wireless Bluetooth Headphones", "price": "2499.00"},
    {"id": 102, "name": "Organic Green Tea (50 bags)", "price": "399.00"},
    {"id": 103, "name": "Laptop Stand - Aluminum", "price": "1299.00"},
    {"id": 104, "name": "Running Shoes - Pro Series", "price": "3999.00"},
    {"id": 105, "name": "Ceramic Coffee Mug Set (4)", "price": "899.00"},
    {"id": 106, "name": "USB-C Hub 7-in-1", "price": "1499.00"},
    {"id": 107, "name": "Yoga Mat - Premium", "price": "1199.00"},
    {"id": 108, "name": "Stainless Steel Water Bottle", "price": "599.00"},
]


class MockWooClient:
    """Simulates a WooCommerce store for development and testing."""

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)
        self._order_counter = 1000

    def generate_order(
        self,
        customer_idx: int | None = None,
        status: str = "processing",
        num_items: int | None = None,
    ) -> WooOrderPayload:
        """Generate a single mock WooCommerce order."""
        self._order_counter += 1

        if customer_idx is None:
            customer_idx = self._rng.randint(0, len(SAMPLE_CUSTOMERS) - 1)
        cust = SAMPLE_CUSTOMERS[customer_idx % len(SAMPLE_CUSTOMERS)]

        if num_items is None:
            num_items = self._rng.randint(1, 3)

        products = self._rng.sample(SAMPLE_PRODUCTS, min(num_items, len(SAMPLE_PRODUCTS)))
        line_items = []
        total = 0.0
        for p in products:
            qty = self._rng.randint(1, 2)
            item_total = float(p["price"]) * qty
            total += item_total
            line_items.append(WooLineItem(
                id=self._rng.randint(1, 9999),
                name=p["name"],
                product_id=p["id"],
                quantity=qty,
                total=f"{item_total:.2f}",
            ))

        return WooOrderPayload(
            id=self._order_counter,
            status=status,
            total=f"{total:.2f}",
            currency="INR",
            payment_method="stripe",
            billing=WooBilling(**cust),
            shipping=WooShipping(first_name=cust["first_name"], last_name=cust["last_name"]),
            line_items=line_items,
            date_created=datetime.now(timezone.utc).isoformat(),
            customer_id=0,  # guest order
        )

    def generate_order_batch(self, count: int = 10) -> list[WooOrderPayload]:
        """Generate a batch of diverse orders for seeding the database."""
        orders = []
        statuses = ["processing", "completed", "completed", "completed", "pending", "failed"]

        for i in range(count):
            status = statuses[i % len(statuses)]
            order = self.generate_order(
                customer_idx=i % len(SAMPLE_CUSTOMERS),
                status=status,
            )
            orders.append(order)

        return orders

    def compute_webhook_signature(self, payload_bytes: bytes, secret: str) -> str:
        """Compute HMAC-SHA256 signature matching WooCommerce webhook format."""
        return hmac.new(
            secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()


# Singleton
mock_woo_client = MockWooClient()
