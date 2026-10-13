# ShopMind — AI-Powered WooCommerce CRM

An intelligent CRM layer for WooCommerce that automatically segments customers, detects order issues, drafts personalized follow-ups, and provides human-in-the-loop approval for all AI-driven actions.

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│  WooCommerce    │────▶│  Webhook API │────▶│  Order Service  │
│  (MockClient)   │     │  (FastAPI)   │     │  (SQLite)       │
└─────────────────┘     └──────────────┘     └─────────────────┘
                                                      │
                              ┌────────────────────────┤
                              ▼                        ▼
                     ┌────────────────┐     ┌──────────────────┐
                     │ Customer       │     │ Timeline Service │
                     │ Resolution     │     │ (Events)         │
                     └────────────────┘     └──────────────────┘
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
             ┌──────────┐ ┌────────┐ ┌──────────────┐
             │ Segment  │ │Follow- │ │ Order-Issue   │
             │ Agent    │ │up Agent│ │ Watcher       │
             └──────────┘ └────────┘ └──────────────┘
                    │         │         │
                    ▼         ▼         ▼
             ┌──────────────────────────────────┐
             │       Approval Inbox             │
             │   (Human-in-the-loop review)     │
             └──────────────────────────────────┘
```

## Tech Stack
- **Backend**: Python 3.11+, FastAPI, SQLite (via SQLAlchemy), Pydantic
- **Frontend**: React (Vite), vanilla CSS
- **AI**: Deterministic rules + LLM for the human-readable text (local Ollama model, `FakeLLM` as fallback)
- **Testing**: pytest

## Quick Start

```bash
# Backend
cd backend
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
python -m pytest tests/ -v
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## Running with a real LLM (default: local LM Studio)

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
- **Approval Inbox**: All AI proposals require human approval before execution
- **Timeline**: Every action is recorded as an auditable event
