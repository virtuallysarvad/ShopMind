"""ShopMind configuration via environment variables with sensible defaults."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///./shopmind.db"

    # WooCommerce (mock by default)
    woo_store_url: str = "https://mock-store.example.com"
    woo_consumer_key: str = "ck_mock_key"
    woo_consumer_secret: str = "cs_mock_secret"
    woo_webhook_secret: str = "whsec_mock_webhook_secret"

    # LLM
    # "fake"     -> deterministic templates (default, keeps tests offline)
    # "ollama"   -> local model via the Ollama HTTP API, FakeLLM as fallback
    # "lmstudio" -> local model via the LM Studio OpenAI-compatible API, FakeLLM as fallback
    llm_provider: str = "fake"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    lmstudio_base_url: str = "http://localhost:1234/v1"
    lmstudio_model: str = "qwen2.5-7b-instruct"
    llm_timeout_seconds: int = 30

    # App
    app_name: str = "ShopMind"
    debug: bool = True
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    model_config = {"env_prefix": "SHOPMIND_", "env_file": ".env"}


settings = Settings()
