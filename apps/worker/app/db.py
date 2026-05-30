"""Async SQLAlchemy engine + the single upsert the worker needs."""
from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from llm_logger.schema import InferenceEvent

log = logging.getLogger("worker.db")


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_size=5, max_overflow=10, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False)


_UPSERT = text("""
    INSERT INTO inference_logs (
        request_id, conversation_id, message_id,
        provider, model, status, error_code, error_message,
        started_at, ended_at, ttfb_ms,
        prompt_tokens, completion_tokens, total_tokens,
        input_preview, output_preview, metadata
    )
    VALUES (
        :request_id, :conversation_id, :message_id,
        :provider, :model, :status, :error_code, :error_message,
        :started_at, :ended_at, :ttfb_ms,
        :prompt_tokens, :completion_tokens, :total_tokens,
        :input_preview, :output_preview, CAST(:metadata AS JSONB)
    )
    ON CONFLICT (request_id) DO UPDATE SET
        status            = EXCLUDED.status,
        error_code        = EXCLUDED.error_code,
        error_message     = EXCLUDED.error_message,
        ended_at          = EXCLUDED.ended_at,
        ttfb_ms           = EXCLUDED.ttfb_ms,
        prompt_tokens     = EXCLUDED.prompt_tokens,
        completion_tokens = EXCLUDED.completion_tokens,
        total_tokens      = EXCLUDED.total_tokens,
        input_preview     = EXCLUDED.input_preview,
        output_preview    = EXCLUDED.output_preview,
        metadata          = EXCLUDED.metadata
""")


async def upsert_event(session, event: InferenceEvent) -> None:
    await session.execute(
        _UPSERT,
        {
            "request_id": str(event.request_id),
            "conversation_id": str(event.conversation_id) if event.conversation_id else None,
            "message_id": str(event.message_id) if event.message_id else None,
            "provider": event.provider,
            "model": event.model,
            "status": event.status.value,
            "error_code": event.error_code,
            "error_message": event.error_message,
            "started_at": event.started_at,
            "ended_at": event.ended_at,
            "ttfb_ms": event.ttfb_ms,
            "prompt_tokens": event.prompt_tokens,
            "completion_tokens": event.completion_tokens,
            "total_tokens": event.total_tokens,
            "input_preview": event.input_preview,
            "output_preview": event.output_preview,
            "metadata": json.dumps(event.metadata),
        },
    )
