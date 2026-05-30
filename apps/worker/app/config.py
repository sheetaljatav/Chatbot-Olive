import os


class Settings:
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://chatbot:chatbot@localhost:5432/chatbot"
    )
    event_stream: str = os.getenv("EVENT_STREAM", "llm.events")
    event_dlq: str = os.getenv("EVENT_DLQ", "llm.events.dlq")
    event_group: str = os.getenv("EVENT_GROUP", "workers")
    consumer_name: str = os.getenv("HOSTNAME", "worker-1")

    block_ms: int = int(os.getenv("WORKER_BLOCK_MS", "5000"))
    batch_count: int = int(os.getenv("WORKER_BATCH_COUNT", "32"))
    max_retries: int = int(os.getenv("WORKER_MAX_RETRIES", "5"))

    pii_enabled: bool = os.getenv("PII_REDACTION_ENABLED", "true").lower() == "true"
    pii_entities: list[str] = os.getenv(
        "PII_ENTITIES",
        "EMAIL_ADDRESS,PHONE_NUMBER,CREDIT_CARD,US_SSN,IP_ADDRESS",
    ).split(",")


settings = Settings()
