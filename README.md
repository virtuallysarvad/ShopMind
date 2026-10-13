# ShopMind — AI-Powered WooCommerce CRM

An intelligent CRM layer for WooCommerce that automatically segments customers, detects order issues, drafts personalized follow-ups, and provides human-in-the-loop approval for all AI-driven actions.

## Demo videos

- **Plan video (2 min):** _add link here_
- **Result video (2 min):** _add link here_

## What it does (Kilowott brief: CRM System Integration with WooCommerce)

| Brief | ShopMind |
|---|---|
| Customer data management | Customers are built from orders and matched by email or phone. Auto-segments (New / Regular / VIP / At Risk), lifetime spend in ₹, a full timeline per customer |
| Order tracking | REST sync + signed real-time webhooks, an Orders board by status, and failed-payment and repeat-refund detection |
| Communication workflows | AI-drafted follow-up emails, hand-written emails, or emails asked for in Copilot chat. Approve one and it goes out through WooCommerce's own mailer |
| Agentic AI | The Shop Copilot runs a tool-calling loop over 8 CRM tools. Its writes only become pending proposals |
| Human in the loop | Every agent output lands in the Approval Inbox. Approve and it executes and writes back to WooCommerce |

Scope, assumptions, design patterns, testing strategy and operations: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.
How AI tools were used to build it, prompt by prompt: **[AI_USAGE.md](AI_USAGE.md)**.

## Architecture

```
 WooCommerce ──REST sync──▶ ┌──────────── ShopMind API (FastAPI) ────────────┐
   store     ──webhooks───▶ │ ingest ─▶ Segment agent ─┐                     │
      ▲                     │        ─▶ Follow-up agent├─▶ Approval Inbox ─┐ │
      │                     │        ─▶ Issue watcher ─┘   (pending)       │ │
      │                     │ Shop Copilot (LLM tool loop) ─▶ pending ─────┤ │
      │                     │ Human "+ New proposal"       ─▶ pending ─────┤ │
      │                     │                    approve ─▶ execute ◀──────┘ │
      └── order notes, customer meta (write-back) ◀─────────┘ + timeline     │
                            └────────────────────────────────────────────────┘
                                        ▲  React dashboard (boards, inbox, copilot)
 LLM strategy: FakeLLM (offline) · Groq (free) · LM Studio / Ollama (local) · OpenAI
```

## Tech Stack
- **Backend**: Python 3.12, FastAPI, SQLAlchemy + SQLite, Pydantic, httpx
- **Frontend**: React 19 + Vite, React Router, vanilla CSS
- **AI in the product**: deterministic rules decide, and an LLM writes the text and drives the Copilot. Providers are Groq (free, `openai/gpt-oss-120b`), LM Studio, Ollama and OpenAI, with an offline `FakeLLM` fallback
- **Integration**: WooCommerce REST API v3 (OAuth 1.0a over HTTP, Basic over HTTPS) + HMAC-signed webhooks
- **Testing**: pytest (unit, integration, end-to-end), Vitest + Testing Library, GitHub Actions CI
- **Deploy**: Docker Compose (API + nginx-served dashboard)

## Quick Start

### One command (Docker)

```bash
docker compose up --build
# Dashboard: http://localhost:3000   API docs: http://localhost:8000/docs
```

The first start seeds demo data and uses the offline LLM, so no keys are needed. For a real free LLM, put `SHOPMIND_LLM_PROVIDER=groq` and `SHOPMIND_GROQ_API_KEY=...` in `backend/.env` and run it again.

### Dev mode

```bash
# Backend
cd backend
python -m venv venv
venv\Scripts\activate          # Windows (source venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
python -m app.seed              # demo data (mock mode)
uvicorn app.main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

## Testing

```bash
cd backend
pytest tests      # 149 unit + integration tests
pytest e2e        # 18 end-to-end tests: real API + fake WooCommerce store over HTTP

cd frontend
npm test          # 12 Vitest + Testing Library tests
```

The end-to-end suite starts two real servers (ShopMind in live WooCommerce mode, plus `e2e/fake_store.py`). It then walks the whole loop: connect (OAuth1-signed), sync 25 orders, re-sync without duplicates, reject unsigned webhooks, raise a failed payment as an issue, approve → private order note in the store, hand-written email → customer note, segment change → `shopmind_segment` customer meta, reject → nothing written, and Copilot → pending only.
CI (`.github/workflows/ci.yml`) runs all of it, plus the production build and the Docker build, on every push.

## Local LLMs (LM Studio / Ollama)

By default ShopMind runs with `FakeLLM` — deterministic templates, no network, so tests and demos stay reproducible. To use a real local model, load a model into **LM Studio** (recommended), start its local API server, and tell ShopMind to use it:

```powershell
# Windows PowerShell
# 1. In LM Studio: open the model, load Qwen2.5 7B Instruct, then open the Developer tab
#    and start the local server (or run `lms server start` from the LM Studio CLI).
# 2. Tell ShopMind to use LM Studio:
$env:SHOPMIND_LLM_PROVIDER = "lmstudio"

# 3. Start the backend as usual
cd backend
venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

If you prefer the Ollama path instead:

```bash
ollama pull qwen2.5:7b
# set SHOPMIND_LLM_PROVIDER=ollama
```

Optional overrides:

| Env var | Default | Provider |
|---|---|---|
| `SHOPMIND_LLM_PROVIDER` | `fake` | chooses `fake` / `ollama` / `lmstudio` |
| `SHOPMIND_LMSTUDIO_BASE_URL` | `http://localhost:1234/v1` | LM Studio |
| `SHOPMIND_LMSTUDIO_MODEL` | `qwen2.5-7b-instruct` | LM Studio — must match a model id from `GET /v1/models` |
| `SHOPMIND_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama |
| `SHOPMIND_OLLAMA_MODEL` | `qwen2.5:7b` | Ollama |
| `SHOPMIND_LLM_TIMEOUT_SECONDS` | `30` | both real providers |
| `SHOPMIND_DEBUG` | `false` | set `true` only to accept unsigned webhooks while testing locally |
| `VITE_API_BASE` | `http://localhost:8000` | frontend: backend URL (put it in `frontend/.env.local`) |

`GET /health` reports the active provider and, when it is a real provider, whether that server is reachable:

```json
{ "status": "healthy", "app": "ShopMind", "llm_provider": "lmstudio", "lmstudio_reachable": true, "lmstudio_models": ["qwen2.5-7b-instruct"] }
```

If the local server is down, slow, or returns malformed output, ShopMind logs a warning and falls back to the deterministic templates — ingestion and the approval flow never break.

## Assumptions

- **Deterministic rules make every decision.** The segment, the follow-up trigger and the issue type are always computed by plain Python rules (`classify_customer`, the pipeline trigger checks, the issue watcher).
- **The LLM only writes the human-readable parts**: the segment explanation, the follow-up email draft and the issue explanation. It is given the deterministic evidence as structured JSON and told to invent no numbers, discounts or order details.
- **Every proposal still needs human approval** before execution, regardless of which LLM produced the text.
- **Provenance is recorded honestly**: each proposal stores `is_llm_generated` and `evidence.llm_model` from the actual call, so fallback/template output is never presented as model output.
- `FakeLLM` is the default (`SHOPMIND_LLM_PROVIDER=fake`) to keep tests deterministic and offline; no paid services or API keys are used anywhere.

## Key Concepts
- **Customer Resolution**: Match guest orders to existing customers via email/phone
- **Segment Agent**: Classify customers (VIP, At-Risk, New, Regular) using deterministic rules
- **Follow-up Agent**: Draft personalized communications based on order events
- **Order-Issue Watcher**: Detect failed payments, delayed shipping, repeated returns
- **Shop Copilot**: Chat agent (like an AI CRM operator) that answers questions about the shop and acts through tools; every write becomes a pending proposal
- **WooCommerce integration (two-way)**: REST API sync + verified webhooks in, approved actions written back out (see below)
- **Approval Inbox**: All AI proposals require human approval before execution. **+ New proposal** lets a person add an email, segment change or order issue by hand (`POST /api/proposals`, agent `manual`, tagged "You"); it goes through the same approve → execute → WooCommerce write-back path.
- **Timeline**: Every action is recorded as an auditable event

## Shop Copilot (agentic chat)

Open **Copilot** in the top bar, or the floating **Ask Copilot** button on any page.

- **How it works**: with `SHOPMIND_LLM_PROVIDER=lmstudio` (or `ollama`), the local model runs a function-calling loop over 8 tools via the OpenAI-compatible `/v1/chat/completions` API (max 6 steps). With `fake`, or when the model is unreachable, a keyword router answers with the same tools and the reply is labelled "Built-in rules".
- **Read tools**: `shop_stats`, `search_customers`, `get_customer`, `list_orders`, `list_pending_proposals`.
- **Write tools**: `propose_segment_change`, `draft_follow_up_email`, `flag_order_issue`. These only create **pending proposals** (agent `shop_copilot`) in the Approval Inbox. No tool can approve, reject or execute, so the human stays in charge.
- **Transparency**: each reply shows which model answered and the tool calls it made.
- **API**: `POST /api/copilot/chat` with `{"messages": [{"role": "user", "content": "Who are my top customers?"}]}`.
- **Try**: "How is my shop doing?", "Show failed orders", "Draft a thank-you email to Alice", "Make David VIP".
- Code: `backend/app/agents/copilot.py`, `copilot_tools.py`, `frontend/src/components/Copilot.jsx`; tests in `backend/tests/test_copilot.py`.

## WooCommerce integration (live store)

ShopMind runs on demo data by default (`SHOPMIND_WOO_MODE=mock`). Set it to `live` to connect a real store.

| Direction | How | What |
|---|---|---|
| Store → ShopMind (backfill) | REST API `GET /wp-json/wc/v3/orders`, paginated via `X-WP-TotalPages` | **Sync now** on the dashboard or `POST /api/woocommerce/sync` (optional `modified_after`). Idempotent; agents only re-run when an order is new or its status changed. |
| Store → ShopMind (real time) | Webhooks `order.created` / `order.updated` → `POST /webhooks/woocommerce/order` | Signature checked as WooCommerce sends it: base64 HMAC-SHA256 in `X-WC-Webhook-Signature`. The `webhook_id=` ping is acknowledged; `order.deleted` is ignored. |
| ShopMind → Store | Runs when you **approve** a proposal | Segment change → customer meta `shopmind_segment`. Email → customer order note (WooCommerce emails it to the customer). Order issue → private order note. Failures are logged on the timeline and never block the approval. |

In wp-admin, the segment ShopMind writes back shows as a **ShopMind segment** column on Users, on the user profile, and under the billing address on each order (`woocommerce/mu-plugins/shopmind-segment.php`).

Auth follows the WooCommerce docs: Basic auth over HTTPS, OAuth 1.0a (HMAC-SHA256) over plain HTTP (local stores). `GET /api/woocommerce/status` checks the credentials.

### Local demo store (Docker, free)

```powershell
# 1. Start the ShopMind backend first (port 8000), so WooCommerce's webhook ping succeeds
# 2. Start WordPress + WooCommerce
docker compose -f docker-compose.woocommerce.yml up -d
# 3. Install WooCommerce, INR settings, products, 3 customers + a guest, 12 orders, webhooks, API key
docker compose -f docker-compose.woocommerce.yml run --rm wpcli bash /scripts/setup.sh
```

The script prints five `SHOPMIND_...` lines (also saved to `woocommerce/scripts/shopmind-woo.env`). Put them in `backend/.env`, restart the backend, open the dashboard and press **Sync now**. Store at http://localhost:8080, admin at `/wp-admin` (admin / admin). New orders and status changes in wp-admin then arrive through webhooks.

Code: `backend/app/woo_client.py`, `backend/app/services/woo_sync.py`, `backend/app/routes/webhooks.py`; tests in `backend/tests/test_woocommerce.py` (a fake store that checks OAuth signatures the way WooCommerce's PHP does).

## ChatGPT (OpenAI API)

Set three lines in `backend/.env` and restart the backend:

```
SHOPMIND_LLM_PROVIDER=openai
SHOPMIND_OPENAI_API_KEY=sk-...
SHOPMIND_OPENAI_MODEL=gpt-5.4-mini
```

ChatGPT then writes the segment explanations, follow-up emails (strict JSON schema) and issue notes, and drives Shop Copilot's tool calls. Rules still make every decision and every action still needs approval. With a missing or bad key, or if the API is down, ShopMind falls back to the templates and labels that text as not AI-written. `/health` shows `openai_reachable`, and the status pill reads `ChatGPT · <model>`. Any OpenAI-compatible endpoint works too, via `SHOPMIND_OPENAI_BASE_URL`.

## Groq (free)

Free API key from console.groq.com/keys. It runs OpenAI's open-weight `gpt-oss-120b` with strict JSON schema and tool calling.

```
SHOPMIND_LLM_PROVIDER=groq
SHOPMIND_GROQ_API_KEY=gsk_...
SHOPMIND_GROQ_MODEL=openai/gpt-oss-120b
```

The free tier is rate limited (about 30 requests a minute and 8K tokens a minute for gpt-oss-120b, per Groq's docs). When it hits the limit (HTTP 429), ShopMind falls back to the templates for that one proposal.
