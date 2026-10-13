"""A stand-in WooCommerce store for end-to-end tests.

Speaks the small slice of the WooCommerce REST API v3 that ShopMind uses
(list orders with X-WP-Total / X-WP-TotalPages paging, add order notes,
update customer meta) and records every write so tests can assert what
ShopMind sent back. Orders come from MockWooClient, in rupees.

Run on its own:  uvicorn e2e.fake_store:app --port 8081
"""

import json

from fastapi import FastAPI, Request, Response

from app.mock_woo_client import MockWooClient

API = "/wp-json/wc/v3"


def _build_orders(count: int = 25) -> list[dict]:
    orders = [json.loads(o.model_dump_json()) for o in MockWooClient(seed=7).generate_order_batch(count)]
    emails = sorted({o["billing"]["email"] for o in orders})
    for o in orders:
        o["date_created_gmt"] = (o.get("date_created") or "").replace("+00:00", "")
        # Registered customers get a WooCommerce id (100, 101, ...) so segment write-back has a target.
        o["customer_id"] = 100 + emails.index(o["billing"]["email"])
    return orders


app = FastAPI(title="Fake WooCommerce store")
app.state.orders = _build_orders()
app.state.writes = []
app.state.auth_seen = []


def _record_auth(request: Request) -> None:
    q = request.query_params
    app.state.auth_seen.append({
        "oauth1": "oauth_signature" in q and q.get("oauth_signature_method") == "HMAC-SHA256",
        "consumer_key": q.get("oauth_consumer_key"),
    })


@app.get(f"{API}/orders")
def list_orders(request: Request, response: Response, per_page: int = 10, page: int = 1):
    _record_auth(request)
    orders = app.state.orders
    response.headers["X-WP-Total"] = str(len(orders))
    response.headers["X-WP-TotalPages"] = str(max(1, -(-len(orders) // per_page)))
    return orders[(page - 1) * per_page: page * per_page]


@app.post(f"{API}/orders/{{order_id}}/notes")
async def add_note(order_id: int, request: Request):
    _record_auth(request)
    body = await request.json()
    note = {"id": len(app.state.writes) + 1, **body}
    app.state.writes.append({"kind": "order_note", "order_id": order_id, **body})
    return note


@app.put(f"{API}/customers/{{customer_id}}")
async def update_customer(customer_id: int, request: Request):
    _record_auth(request)
    body = await request.json()
    app.state.writes.append({"kind": "customer_meta", "customer_id": customer_id, **body})
    return {"id": customer_id, **body}


# ── test helpers (not part of WooCommerce) ──────────────────────────────

@app.get("/_test/writes")
def writes():
    return app.state.writes


@app.get("/_test/auth")
def auth():
    return app.state.auth_seen
