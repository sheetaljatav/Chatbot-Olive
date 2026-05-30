import os


class Settings:
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    event_stream: str = os.getenv("EVENT_STREAM", "llm.events")
    stream_maxlen: int = int(os.getenv("EVENT_STREAM_MAXLEN", "100000"))


settings = Settings()
