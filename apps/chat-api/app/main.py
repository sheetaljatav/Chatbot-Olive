"""FastAPI app: wires DB, provider, SDK logger, cancel registry, and routes."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from llm_logger import LLMLogger
from llm_logger.providers import get_provider

from .cancellation import CancellationRegistry
from .config import settings
from .db.engine import make_engine, make_sessionmaker
from .routes import chat, conversations, metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("chat-api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = make_engine()
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.provider = get_provider(settings.provider)
    app.state.cancel_registry = CancellationRegistry()
    app.state.logger = LLMLogger(
        endpoint=settings.ingestion_url,
        preview_max_chars=settings.preview_max_chars,
        batch_size=settings.sdk_batch_size,
        flush_interval_ms=settings.sdk_flush_interval_ms,
        buffer_max=settings.sdk_buffer_max,
    )
    await app.state.logger.start()
    log.info("chat-api ready (provider=%s)", app.state.provider.name)
    try:
        yield
    finally:
        await app.state.logger.stop()
        await engine.dispose()


app = FastAPI(title="Chat API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(metrics.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "provider": app.state.provider.name}
