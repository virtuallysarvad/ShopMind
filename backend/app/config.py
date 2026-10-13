"""ShopMind configuration via environment variables with sensible defaults."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///./shopmind.db"

    # WooCommerce
    # "mock" -> demo data from MockWooClient / `python -m app.seed` (default, offline)
    # "live" -> real store over the REST API (wc/v3): sync + write-back
    woo_mode: str = "mock"
    woo_store_url: str = "https://mock-store.example.com"
    woo_consumer_key: str = "ck_mock_key"
    woo_consumer_secret: str = "cs_mock_secret"
    woo_webhook_secret: str = "whsec_mock_webhook_secret"
    woo_writeback: bool = True          # mirror approved proposals into the store (live mode)
    woo_verify_ssl: bool = True
    woo_timeout_seconds: int = 20

    # LLM
    # "fake"     -> deterministic templates (default, keeps tests offline)
    # "ollama"   -> local model via the Ollama HTTP API, FakeLLM as fallback
    # "lmstudio" -> local model via the LM Studio OpenAI-compatible API, FakeLLM as fallback
    llm_provider: str = "fake"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    lmstudio_base_url: str = "http://localhost:1234/v1"
    lmstudio_model: str = "qwen2.5-7b-instruct"
    # "openai"   -> ChatGPT via the OpenAI API (needs SHOPMIND_OPENAI_API_KEY), FakeLLM as fallback
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: int = 30

    # App
    app_name: str = "ShopMind"
    # Off by default so unsigned webhooks are rejected. Set SHOPMIND_DEBUG=true
    # only for local poking with curl (unsigned webhooks are then accepted).
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    model_config = {"env_prefix": "SHOPMIND_", "env_file": ".env"}


settings = Settings()
