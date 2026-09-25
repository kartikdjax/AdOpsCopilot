"""Centralized, typed configuration - loaded once from environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ClickHouse - exchange domain only
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_database: str = "adtech"
    clickhouse_username: str = "default"
    clickhouse_password: str = "dev_local_password"

    # MySQL - revive domain only (real local Revive Adserver install)
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_database: str = "revive608"
    mysql_username: str = "root"
    mysql_password: str = ""  # set MYSQL_PASSWORD in .env

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    cache_ttl_seconds: int = 3600

    # LLM provider selection - "groq" (free, default) or "anthropic"
    llm_provider: str = "groq"
    max_concurrent_llm_calls: int = 8

    # Groq (free tier, OpenAI-compatible, no credit card required)
    groq_api_key: str = ""  # set GROQ_API_KEY in .env
    groq_model: str = "openai/gpt-oss-120b"
    # Comma-separated fallback chain tried in order if the primary model is
    # deprecated (404) or rate-limited (429) - Groq rotates its free-tier
    # catalog on its own schedule, not yours, so a hardcoded single model
    # WILL eventually break in production without this.
    groq_fallback_models: str = "openai/gpt-oss-20b"  # llama-3.1-8b-instant, qwen/qwen3-32b: removed by Groq

    # Anthropic (swap in later, or offer as a customer-selectable option)
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"

    # RAG (vector store for policy/knowledge docs)
    chroma_persist_dir: str = "./data/chroma"
    embedding_model_name: str = "all-MiniLM-L6-v2"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()