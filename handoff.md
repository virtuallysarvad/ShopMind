# ShopMind — Handoff: real local LLM via LM Studio or Ollama (FakeLLM kept as fallback)

**Date**: 2026-10-13
**Author**: Buffy (Freebuff coding agent), on the DeepSeek V4.1 Flash model
**Scope**: replace the template-only `FakeLLM` with a real local LLM through Ollama, keeping `FakeLLM` as the fallback — without touching any segmentation, issue-detection or approval logic.
**Status**: `pytest` → **84 passed** (42 original + 21 Ollama + 21 LM Studio). Providers: `fake` (default), `lmstudio` (recommended real path), `ollama`. Real-model HTTP paths are verified with mocked tests and a local stub only; a genuine live LM Studio run is still to be done and logged (see §7).
**Phase 5 (review fixes)**: deprecated `on_event` → lifespan, `debug` now defaults to `False` (unsigned webhooks rejected), frontend `API_BASE` configurable via `VITE_API_BASE`, `llm.py` cleanup (shared prompt helper used by both providers, no per-call state on `LMStudioLLM`, dead code removed).

---

## 1. The design rule this change encodes

> Deterministic rules make **every** decision (segment, trigger, issue type). The LLM writes **only** the human-readable parts: the segment explanation, the follow-up email draft, and the issue explanation. Every proposal still requires human approval before execution.

Two consequences that are enforced in code, not just documented:

- `proposal.is_llm_generated` is always set **from the result object**, never hardcoded, so template output is never presented as model output.
- `proposal.evidence["llm_model"]` records the model that actually produced the text (`null` for the deterministic fallback), so the provenance is auditable after the fact.

---

## 2. Plan that was executed

1. `config.py` + new `agents/llm.py` — provider settings; `LLMResult`, `LLMClient` Protocol, `FakeLLM`, `OllamaLLM`, `FallbackLLM`, `get_llm()`.
2. Agent call sites — injectable `llm` client (pipeline resolves it once and passes it down); `is_llm_generated` and `evidence["llm_model"]` from the result.
3. `/health` — report `llm_provider` plus `ollama_reachable` when the provider is `ollama`.
4. Tests — new `tests/test_llm.py` with mocked httpx (no network) plus a pipeline-level test with an injected stub LLM.
5. Docs + UI — README section and assumption, `AI_USAGE.md` entry, sidebar footer driven by `/health`.

---

## 3. Phase 3 — Files touched

### New
| Path | Purpose |
|---|---|
| `backend/app/agents/llm.py` | `LLMResult`, `LLMClient` Protocol, `FakeLLM`, `OllamaLLM`, `FallbackLLM`, `get_llm()`, `ollama_reachable()`; system prompts as module-level constants. |
| `backend/tests/test_llm.py` | 21 tests, all HTTP mocked — no network, Ollama not required. |

### Removed
| Path | Why |
|---|---|
| `backend/app/agents/fake_llm.py` | Folded into `llm.py` so there is exactly one `FakeLLM`. Verified nothing else imported it. |

### Modified
| Path | Change |
|---|---|
| `backend/app/config.py` | `llm_provider` (`"fake"` \| `"ollama"`, default `"fake"`), `ollama_base_url`, `ollama_model`, `llm_timeout_seconds`; `openai_api_key` / `"openai"` deleted. |
| `backend/app/agents/segment_agent.py` | Optional injected `llm`; explanation comes from the result. `classify_customer` untouched. |
| `backend/app/agents/follow_up_agent.py` | Optional injected `llm`; draft comes from the result. Trigger logic untouched. |
| `backend/app/agents/issue_watcher.py` | Optional injected `llm`, threaded to `_create_issue_proposal`. Detection rules untouched. |
| `backend/app/services/pipeline.py` | Resolves the LLM client once and passes it to all three agents (so tests can inject). Proposals still committed at the end. |
| `backend/app/main.py` | `/health` adds `llm_provider` and, for ollama, `ollama_reachable`. |
| `backend/tests/conftest.py` | Shared `client` TestClient fixture (moved out of `test_integration.py` so `test_llm.py` can use it too). |
| `backend/tests/test_integration.py` | Fixture removed; tests themselves unchanged. |
| `frontend/src/App.jsx` | Sidebar footer reads the active provider from `/health`. |
| `README.md` | "Running with a real LLM" section + the design rule under Assumptions. |
| `AI_USAGE.md` | Phase 3 section (prompt, work, mistakes and fixes, limits, next-model notes). |

---

## 3b. Phase 4 — LM Studio provider (Ollama stays; LM Studio is now the recommended real-provider path)

### New
| Path | Purpose |
|---|---|
| `backend/tests/test_lmstudio.py` | 21 tests, all HTTP mocked — no network, LM Studio not required. |

### Modified
| Path | Change |
|---|---|
| `backend/app/config.py` | Added `llm_provider: "fake" | "ollama" | "lmstudio"` (still `"fake"` default), `lmstudio_base_url = http://localhost:1234/v1`, `lmstudio_model = qwen2.5-7b-instruct`, reused `llm_timeout_seconds`. Ollama keys unchanged. |
| `backend/app/agents/llm.py` | Extracted shared `_chat_messages(system_prompt, customer_data, task, context)` so Ollama and LM Studio build **identical** prompts (same system-prompt constants, same JSON-evidence shape). Added `LMStudioLLM` (OpenAI-compatible `POST /chat/completions`, `temperature=0.3`, `stream=false`; `response_format` with the `follow_up_email` JSON Schema for drafts; text from `choices[0].message.content`; `model` from the response's own `"model"` field, falling back to the configured `lmstudio_model`). Added `lmstudio_reachable()` (`GET /models`). `get_llm()` returns `FallbackLLM(LMStudioLLM, FakeLLM)` for the `lmstudio` provider. OllamaLLM, FakeLLM, FallbackLLM left as-is. |
| `backend/app/main.py` | `/health` now reports `lmstudio_reachable` + `lmstudio_models` (ids from `GET /v1/models`) when the provider is `lmstudio`. Imports `httpx` in `main.py` (this was missing and caused a `NameError`). |
| `frontend/src/App.jsx` | Sidebar footer now shows `LM Studio • Local Model` / `LM Studio • Local Model (unreachable)` (amber dot when down). |
| `frontend/src/pages/Proposals.jsx` | Added `renderDraft(text)`: when the proposal's `proposed_action.draft` is a valid `{subject, body}` JSON string, it renders as a readable email (Subject + body); plain-text FakeLLM drafts still render verbatim. |
| `README.md` | "Running with a real LLM" rewritten — LM Studio is the primary/recommended path (load Qwen2.5 7B Instruct, start the LM Studio server, `$env:SHOPMIND_LLM_PROVIDER="lmstudio"`); Ollama is the one-line alternative. |
| `AI_USAGE.md` | Phase 4 section appended (prompt, what was done, mistakes and fixes, limits, files touched, **not touched**). |
| `handoff.md` | LM Studio added to the provider list, config keys, `/health`, verification, and the "mistakes during this work" section. |

---

## 4. Interfaces, as implemented

### `backend/app/agents/llm.py`

```python
@dataclass
class LLMResult:
    text: str
    is_llm_generated: bool
    model: str | None = None

class LLMClient(Protocol):
    def explain_segment(self, customer_data: dict, new_segment: str) -> LLMResult: ...
    def draft_follow_up(self, customer_data: dict, trigger: str, context: dict) -> LLMResult: ...
    def explain_issue(self, issue_type: str, order_data: dict) -> LLMResult: ...

def get_llm() -> LLMClient: ...              # FallbackLLM(OllamaLLM, FakeLLM) when provider == "ollama", else FakeLLM
def ollama_reachable(base_url=None, timeout=2.0) -> bool: ...   # GET {base_url}/api/tags
```

- `OllamaLLM` — `httpx.post("{base_url}/api/chat", json=..., timeout=llm_timeout_seconds)` with `stream: false` and `options: {"temperature": 0.3}`; `format: "json"` for `draft_follow_up`. The user message is the deterministic evidence as JSON (`customer` name/order_count/total_spent/last_order_date, `new_segment`, `trigger`, `issue_type`, order data); the system prompts forbid inventing numbers, discounts or order details.
- `draft_follow_up` validates the model output and raises `ValueError` on bad JSON, a non-object, or missing `subject`/`body`. On success `LLMResult.text` is the validated `{"subject": ..., "body": ...}` JSON.
- `FallbackLLM(primary, fallback)` catches `httpx.HTTPError` (connection, timeout, 4xx/5xx), `ValueError`, `KeyError`, `TypeError`; logs `logger.warning(...)` and returns the fallback's result (`is_llm_generated=False`, `model=None`).

### Config keys (env prefix `SHOPMIND_`, also readable from `backend/.env`)

| Key | Default |
|---|---|
| `SHOPMIND_LLM_PROVIDER` | `fake` |
| `SHOPMIND_OLLAMA_BASE_URL` | `http://localhost:11434` |
| `SHOPMIND_OLLAMA_MODEL` | `qwen2.5:7b` |
| `SHOPMIND_LMSTUDIO_BASE_URL` | `http://localhost:1234/v1` |
| `SHOPMIND_LMSTUDIO_MODEL` | `qwen2.5-7b-instruct` (must match an id from `GET /v1/models`) |
| `SHOPMIND_LLM_TIMEOUT_SECONDS` | `30` (shared by both real providers) |
| `SHOPMIND_DEBUG` | `false` (set `true` only to accept unsigned webhooks locally) |

Frontend: `VITE_API_BASE` (default `http://localhost:8000`), e.g. in `frontend/.env.local`.

### `/health`

```json
{ "status": "healthy", "app": "ShopMind", "llm_provider": "ollama", "ollama_reachable": true }
```

```json
{ "status": "healthy", "app": "ShopMind", "llm_provider": "lmstudio", "lmstudio_reachable": true, "lmstudio_models": ["qwen2.5-7b-instruct"] }
```

`ollama_reachable` is only present when `llm_provider == "ollama"`; `lmstudio_reachable` and `lmstudio_models` only when it is `"lmstudio"`.

---

## 5. Verification actually performed

| Check | Command | Result |
|---|---|---|
| Backend suite | `cd backend && python -m pytest tests/ -q` | **exit 0 — 84 passed** (42 original, 21 `test_llm.py`, 21 `test_lmstudio.py`). After Phase 5 the `on_event` deprecation warning is gone. |
| Frontend build | `cd frontend && npm run build` | **exit 0** (Vite 8.3.4, `dist/` emitted). |
| Fallback on a live server | `SHOPMIND_LLM_PROVIDER=ollama` with no Ollama running, POST a signed webhook order | `/health` → `ollama_reachable:false`; webhook `200`; proposal `is_llm_generated=False`, `evidence.llm_model=null`; approve → `executed`. Ingestion never breaks. |
| Real HTTP path on a live server | same, with a local stub implementing Ollama's `/api/chat` + `/api/tags` | `/health` → `ollama_reachable:true`; proposal `is_llm_generated=True`, `evidence.llm_model="qwen2.5:7b"`, draft = validated `{subject, body}` JSON; approve → `executed`. |
| Frontend footer (headless Chrome) | `--dump-dom http://localhost:5173/` in all three states | `Ollama • Local Model` → `Ollama • Local Model (unreachable)` + `LLM Offline` → `FakeLLM Active • Rule-Based`. |
| Provenance in the UI | `--dump-dom http://localhost:5173/proposals` | one `🧠 LLM Generated` badge (stub-model proposal) and one `📏 Rule-based` badge (fallback proposal). |
| Seed script | `python -m app.seed` | exit 0, `[OK] Database seeded…`. |
| Stale references | search for `fake_llm` / `openai_api_key` in source (excluding `dist/` and `*.md`) | 0 matches. |

Servers were stopped afterwards; ports 8000, 5173, 8011 and 11434 are free. The seeded SQLite database is left in place for a ready demo.

### Tests added (`backend/tests/test_llm.py`)

- `OllamaLLM` parses a valid chat response → `is_llm_generated=True`, `model="qwen2.5:7b"`; the prompt carries the deterministic evidence; drafts request `format="json"`; bad JSON, missing fields and an empty response each raise.
- `FallbackLLM` returns the `FakeLLM` result for bad JSON, connection error, read timeout and a 500 status — no exception escapes — and does **not** replace a successful model response.
- `get_llm()` returns `FakeLLM` for `fake` and unknown providers, `FallbackLLM(OllamaLLM, FakeLLM)` for `ollama`; `ollama_reachable()` true/false; `/health` reports the provider.
- Pipeline-level: with an injected stub LLM the **webhook** produces a proposal with `is_llm_generated=True` and `evidence.llm_model` set, and approve → execute still reaches `executed`.

---

## 6. Mistakes made during this work (and the fixes)

1. The first pipeline test asserted `llm_explanation.startswith("Stub")`, but the only pending proposal after a first order is the follow-up email, whose explanation is the validated draft JSON. Fixed the assertion (`"Stub subject" in llm_explanation`) rather than weakening the code.
2. While drafting the sidebar footer I left a dead `pendingLabel` variable and referenced an `ollama_model` field `/health` does not return. Both removed; the footer only uses fields the endpoint actually sends.
3. The `client` TestClient fixture was duplicated in `test_integration.py`; moved to `tests/conftest.py` so both test modules share it. No behavioural change to any existing test.

---

## 7. Remaining limitations (honest)

- **No real model has been executed yet.** Ollama is not installed and LM Studio was not running during verification, so both HTTP paths are verified only through mocked httpx tests (plus a local stub for Ollama). Next step: load Qwen2.5 7B Instruct in LM Studio, start the server, run with `SHOPMIND_LLM_PROVIDER=lmstudio`, check `/health`, send one signed webhook order, and record the result in `AI_USAGE.md`.
- **`SHOPMIND_LLM_PROVIDER` defaults to `fake`**, so nothing changes for the demo unless that variable is set. This is deliberate — it keeps tests deterministic and offline.
- **Draft shape differs by provider**: Ollama and LM Studio drafts are pretty-printed `{subject, body}` JSON stored in `proposed_action.draft`, while `FakeLLM` drafts are plain text. The Approval Inbox renders `{subject, body}` as a readable email and plain text as-is.
- Stretch features from the original brief (cross-agent suggestion de-duplication, "Ask-your-CRM") remain unbuilt.

---

## 8. Notes for the next model

1. All LLM text goes through `app/agents/llm.py::get_llm()`. Never instantiate a client directly inside an agent — accept the `llm` parameter so tests can inject a stub.
2. Keep `is_llm_generated` and `evidence["llm_model"]` honest; they are the "verifiable AI" requirement. Set them from the result, never hardcode.
3. To add a provider, implement the three `LLMClient` methods and extend `get_llm()`, always behind `FallbackLLM` so order processing can never be broken by a model.
4. Before claiming anything works: `cd backend && python -m pytest tests/ -v`, then `cd frontend && npm run build`, then a live `curl /health` and one signed webhook order.
5. `AI_USAGE.md` is the running log of AI-assisted work; keep appending to it rather than rewriting history.
