"""ShopMind FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db

import logging
import httpx

from app.agents.llm import lmstudio_reachable, ollama_reachable
from app.routes.webhooks import router as webhook_router
from app.routes.api import router as api_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables on startup (replaces deprecated on_event)."""
    init_db()
    if settings.debug:
        logger.warning(
            "SHOPMIND_DEBUG is on: unsigned webhooks are accepted. "
            "Never run like this in production."
        )
    yield


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    description="AI-powered CRM layer for WooCommerce",
    version="0.1.0",
)

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(webhook_router)
app.include_router(api_router)


@app.get("/health")
def health_check():
    """Liveness plus which LLM provider is active and whether its server answers."""
    health = {
        "status": "healthy",
        "app": settings.app_name,
        "llm_provider": settings.llm_provider,
    }
    if settings.llm_provider == "ollama":
        health["ollama_reachable"] = ollama_reachable()
    if settings.llm_provider == "lmstudio":
        try:
            health["lmstudio_reachable"] = lmstudio_reachable()
            health["lmstudio_models"] = _list_lmstudio_models()
        except Exception:
            # Best-effort: log and report the failure.
            logger.exception("failed to probe LM Studio from /health")
            health["lmstudio_reachable"] = False
            health["lmstudio_models"] = []
    return health


def _list_lmstudio_models(base_url: str | None = None, timeout: float = 2.0) -> list[str]:
    """Return the ids of the models loaded in LM Studio."""
    url = (base_url or settings.lmstudio_base_url).rstrip("/")
    data = httpx.get(f"{url}/models", timeout=timeout).json()
    return [m["id"] for m in (data.get("data") or []) if str(m.get("id", "")).strip()]
