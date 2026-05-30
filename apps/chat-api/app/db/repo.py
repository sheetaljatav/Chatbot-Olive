"""All SQL the chat API runs lives here. Plain `text()` queries — no ORM model
classes — because the schema is small and stable, and this stays trivially
greppable.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------- conversations ----------------

async def create_conversation(session: AsyncSession, title: str | None = None) -> dict:
    row = (
        await session.execute(
            text(
                "INSERT INTO conversations (title) VALUES (:title) "
                "RETURNING id, title, status, created_at, updated_at"
            ),
            {"title": title},
        )
    ).mappings().one()
    return dict(row)


async def list_conversations(session: AsyncSession, limit: int = 50) -> list[dict]:
    rows = (
        await session.execute(
            text(
                """
                SELECT c.id, c.title, c.status, c.created_at, c.updated_at,
                       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
                  FROM conversations c
                 ORDER BY c.updated_at DESC
                 LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def get_conversation(session: AsyncSession, conv_id: UUID) -> dict | None:
    row = (
        await session.execute(
            text(
                "SELECT id, title, status, created_at, updated_at "
                "FROM conversations WHERE id = :id"
            ),
            {"id": str(conv_id)},
        )
    ).mappings().one_or_none()
    return dict(row) if row else None


async def set_conversation_status(
    session: AsyncSession, conv_id: UUID, status_value: str
) -> None:
    await session.execute(
        text("UPDATE conversations SET status = :s, updated_at = NOW() WHERE id = :id"),
        {"s": status_value, "id": str(conv_id)},
    )


async def update_conversation_title(
    session: AsyncSession, conv_id: UUID, title: str
) -> None:
    await session.execute(
        text("UPDATE conversations SET title = :t WHERE id = :id AND title IS NULL"),
        {"t": title, "id": str(conv_id)},
    )


# ---------------- messages ----------------

async def list_messages(session: AsyncSession, conv_id: UUID) -> list[dict]:
    rows = (
        await session.execute(
            text(
                "SELECT id, role, content, sequence, created_at "
                "FROM messages WHERE conversation_id = :id "
                "ORDER BY sequence ASC"
            ),
            {"id": str(conv_id)},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def next_sequence(session: AsyncSession, conv_id: UUID) -> int:
    row = (
        await session.execute(
            text(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS seq "
                "FROM messages WHERE conversation_id = :id"
            ),
            {"id": str(conv_id)},
        )
    ).mappings().one()
    return int(row["seq"])


async def insert_message(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    role: str,
    content: str,
    sequence: int,
) -> UUID:
    row = (
        await session.execute(
            text(
                "INSERT INTO messages (conversation_id, role, content, sequence) "
                "VALUES (:cid, :role, :content, :seq) RETURNING id"
            ),
            {
                "cid": str(conversation_id),
                "role": role,
                "content": content,
                "seq": sequence,
            },
        )
    ).mappings().one()
    return UUID(str(row["id"]))


# ---------------- metrics ----------------

async def metrics_summary(session: AsyncSession, window_minutes: int) -> dict[str, Any]:
    """Headline numbers for the dashboard top bar."""
    q = text(
        """
        SELECT
            COUNT(*)                                                      AS total,
            COUNT(*) FILTER (WHERE status = 'success')                    AS success,
            COUNT(*) FILTER (WHERE status = 'error')                      AS errors,
            COUNT(*) FILTER (WHERE status = 'cancelled')                  AS cancelled,
            COALESCE(SUM(total_tokens), 0)                                AS tokens,
            COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms), 0)::INT  AS p50,
            COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0)::INT AS p95,
            COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms), 0)::INT AS p99
          FROM inference_logs
         WHERE created_at > NOW() - make_interval(mins => :w)
        """
    )
    row = (await session.execute(q, {"w": window_minutes})).mappings().one()
    return dict(row)


async def metrics_timeseries(session: AsyncSession, window_minutes: int) -> list[dict]:
    """Per-minute buckets for line charts."""
    q = text(
        """
        SELECT
            date_trunc('minute', created_at) AS bucket,
            COUNT(*)                                              AS requests,
            COUNT(*) FILTER (WHERE status = 'error')              AS errors,
            COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms), 0)::INT AS p50,
            COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0)::INT AS p95
          FROM inference_logs
         WHERE created_at > NOW() - make_interval(mins => :w)
         GROUP BY bucket
         ORDER BY bucket ASC
        """
    )
    rows = (await session.execute(q, {"w": window_minutes})).mappings().all()
    return [dict(r) for r in rows]


async def metrics_by_model(session: AsyncSession, window_minutes: int) -> list[dict]:
    q = text(
        """
        SELECT provider, model,
               COUNT(*)                                                    AS requests,
               COUNT(*) FILTER (WHERE status = 'error')                    AS errors,
               COALESCE(percentile_cont(0.5)  WITHIN GROUP (ORDER BY latency_ms), 0)::INT AS p50,
               COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0)::INT AS p95,
               COALESCE(SUM(prompt_tokens), 0)     AS prompt_tokens,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens
          FROM inference_logs
         WHERE created_at > NOW() - make_interval(mins => :w)
         GROUP BY provider, model
         ORDER BY requests DESC
        """
    )
    rows = (await session.execute(q, {"w": window_minutes})).mappings().all()
    return [dict(r) for r in rows]
