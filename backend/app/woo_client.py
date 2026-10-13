"""WooCommerceClient: the real WooCommerce REST API (wc/v3).

Auth, as the WooCommerce REST API docs describe it:
  * HTTPS store  -> HTTP Basic auth with the consumer key / secret.
  * HTTP store   -> one-legged OAuth 1.0a (HMAC-SHA256) in the query string,
                    because WooCommerce refuses Basic auth over plain HTTP.
                    This is what a local Docker store on http://localhost uses.

Only the endpoints ShopMind needs are wrapped: list orders/customers
(paginated via the X-WP-TotalPages header), read one order, add an order
note, and update a customer's meta data.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Any, Iterator
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl

import httpx

from app.config import settings

API_PREFIX = "/wp-json/wc/v3"


class WooCommerceError(RuntimeError):
    """The store answered with an error (or not at all)."""


def _enc(value: Any) -> str:
    """RFC 3986 percent-encoding, as PHP's rawurlencode."""
    return quote(str(value), safe="-._~")


def oauth1_signature(method: str, url: str, params: dict, consumer_secret: str) -> str:
    """Signature exactly as WooCommerce's WC_REST_Authentication::check_oauth_signature
    computes it: params encoded once, sorted, joined with %3D / %26."""
    normalized = sorted((_enc(k), _enc(v)) for k, v in params.items() if k != "oauth_signature")
    query = "%26".join(f"{k}%3D{v}" for k, v in normalized)
    base = f"{method.upper()}&{_enc(url)}&{query}"
    digest = hmac.new(f"{consumer_secret}&".encode(), base.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class WooCommerceClient:
    def __init__(
        self,
        store_url: str | None = None,
        consumer_key: str | None = None,
        consumer_secret: str | None = None,
        timeout: float | None = None,
        verify_ssl: bool | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.store_url = (store_url or settings.woo_store_url).rstrip("/")
        self.key = consumer_key or settings.woo_consumer_key
        self.secret = consumer_secret or settings.woo_consumer_secret
        self.https = self.store_url.lower().startswith("https://")
        self._http = httpx.Client(
            timeout=timeout or settings.woo_timeout_seconds,
            verify=settings.woo_verify_ssl if verify_ssl is None else verify_ssl,
            transport=transport,
            auth=(self.key, self.secret) if self.https else None,
            headers={"Accept": "application/json", "User-Agent": "ShopMind/0.1"},
        )

    # ── low level ─────────────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self.store_url}{API_PREFIX}/{path.lstrip('/')}"

    def _signed_params(self, method: str, url: str, params: dict) -> dict:
        if self.https:
            return params
        parts = urlsplit(url)
        base_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        all_params = {**dict(parse_qsl(parts.query)), **params}
        all_params.update({
            "oauth_consumer_key": self.key,
            "oauth_nonce": secrets.token_hex(16),
            "oauth_signature_method": "HMAC-SHA256",
            "oauth_timestamp": str(int(time.time())),
        })
        all_params["oauth_signature"] = oauth1_signature(method, base_url, all_params, self.secret)
        return all_params

    def request(self, method: str, path: str, params: dict | None = None, json: Any = None) -> httpx.Response:
        url = self._url(path)
        params = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            resp = self._http.request(method, url, params=self._signed_params(method, url, params), json=json)
        except httpx.HTTPError as e:
            raise WooCommerceError(f"Could not reach the store at {self.store_url}: {e}") from e
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("message") or resp.text
            except ValueError:
                detail = resp.text
            raise WooCommerceError(f"WooCommerce {method} {path} failed ({resp.status_code}): {detail[:300]}")
        return resp

    def paginate(self, path: str, params: dict | None = None, per_page: int = 100,
                 max_pages: int = 50) -> Iterator[dict]:
        page = 1
        while page <= max_pages:
            resp = self.request("GET", path, {**(params or {}), "per_page": per_page, "page": page})
            items = resp.json()
            if not isinstance(items, list):
                raise WooCommerceError(f"Expected a list from {path}")
            yield from items
            total_pages = int(resp.headers.get("X-WP-TotalPages", "1") or 1)
            if page >= total_pages or not items:
                return
            page += 1

    # ── endpoints ShopMind uses ───────────────────────────────────────────

    def ping(self) -> dict:
        """Cheap check: credentials work, and how many orders the store has."""
        resp = self.request("GET", "orders", {"per_page": 1})
        return {"ok": True, "store_url": self.store_url, "total_orders": int(resp.headers.get("X-WP-Total", "0") or 0)}

    def list_orders(self, modified_after: str | None = None, status: str | None = None) -> Iterator[dict]:
        return self.paginate("orders", {"orderby": "date", "order": "asc",
                                        "modified_after": modified_after, "status": status})

    def list_customers(self) -> Iterator[dict]:
        return self.paginate("customers", {"orderby": "id", "order": "asc", "role": "all"})

    def get_order(self, order_id: int) -> dict:
        return self.request("GET", f"orders/{int(order_id)}").json()

    def add_order_note(self, order_id: int, note: str, customer_note: bool = False) -> dict:
        """customer_note=True makes WooCommerce email the note to the customer."""
        return self.request("POST", f"orders/{int(order_id)}/notes",
                            json={"note": note, "customer_note": customer_note}).json()

    def update_customer_meta(self, customer_id: int, meta: dict[str, Any]) -> dict:
        return self.request("PUT", f"customers/{int(customer_id)}",
                            json={"meta_data": [{"key": k, "value": v} for k, v in meta.items()]}).json()

    def close(self) -> None:
        self._http.close()


def get_woo_client() -> WooCommerceClient | None:
    """The live client when SHOPMIND_WOO_MODE=live, else None (mock/demo data)."""
    if settings.woo_mode == "live":
        return WooCommerceClient()
    return None
