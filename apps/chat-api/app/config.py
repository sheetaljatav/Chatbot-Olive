import os


class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://chatbot:chatbot@localhost:5432/chatbot"
    )
    ingestion_url: str = os.getenv("INGESTION_URL", "http://localhost:8001")
    provider: str = os.getenv("PROVIDER", "gemini")
    context_turn_limit: int = int(os.getenv("CONTEXT_TURN_LIMIT", "12"))
    preview_max_chars: int = int(os.getenv("PREVIEW_MAX_CHARS", "500"))
    sdk_batch_size: int = int(os.getenv("SDK_BATCH_SIZE", "20"))
    sdk_flush_interval_ms: int = int(os.getenv("SDK_FLUSH_INTERVAL_MS", "500"))
    sdk_buffer_max: int = int(os.getenv("SDK_BUFFER_MAX", "1000"))
    cors_origins: list[str] = os.getenv("CORS_ORIGINS", "*").split(",")


settings = Settings()
