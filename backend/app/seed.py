"""Seed script: populate the database with mock WooCommerce orders.

Usage:
    python -m app.seed
"""

from app.database import SessionLocal, init_db
from app.mock_woo_client import MockWooClient
from app.services.order_service import ingest_order
from app.services.pipeline import run_post_order_pipeline
from app.models import Order, OrderStatus


def seed_database(order_count: int = 15):
    """Generate mock orders and run the full pipeline on each."""
    init_db()
    db = SessionLocal()

    client = MockWooClient(seed=42)

    try:
        # Generate diverse orders
        orders = client.generate_order_batch(order_count)

        for i, payload in enumerate(orders):
            print(f"[{i+1}/{order_count}] Ingesting order #{payload.id} "
                  f"for {payload.billing.email} (status: {payload.status})")
            order = ingest_order(db, payload)
            customer = order.customer
            results = run_post_order_pipeline(db, customer, order)
            print(f"  -> Pipeline: segment={results['segment_proposal_created']}, "
                  f"followup={results['follow_up_proposal_created']}, "
                  f"issues={results['issues_detected']}")

        # Add some extra orders for Alice to make her a VIP candidate
        print("\n--- Adding extra orders for Alice (VIP candidate) ---")
        for i in range(6):
            payload = client.generate_order(customer_idx=0, status="completed")
            order = ingest_order(db, payload)
            results = run_post_order_pipeline(db, order.customer, order)
            print(f"  Alice order #{payload.id}: pipeline={results}")

        # Add a failed order for Bob
        print("\n--- Adding failed order for Bob ---")
        failed = client.generate_order(customer_idx=1, status="failed")
        order = ingest_order(db, failed)
        results = run_post_order_pipeline(db, order.customer, order)
        print(f"  Bob failed order #{failed.id}: pipeline={results}")

        # Add refunded orders for Carol (repeated returns)
        print("\n--- Adding refunded orders for Carol ---")
        for i in range(4):
            payload = client.generate_order(customer_idx=2, status="refunded")
            order = ingest_order(db, payload)
            results = run_post_order_pipeline(db, order.customer, order)
            print(f"  Carol refund #{payload.id}: pipeline={results}")

        db.commit()
        print("\n[OK] Database seeded with orders and agent proposals!")

    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
