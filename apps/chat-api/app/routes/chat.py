"""Streaming chat endpoint.

POST /chat
  body: { conversation_id?, message, model? }
  resp: text/event-stream; each event a JSON line {type, ...}

Event types streamed to the client:
  - "start"      {conversation_id, message_id}
  - "delta"      {text}
  - "done"       {message_id, finish_reason, usage}
  - "cancelled"  {}
  - "error"      {message}

Lifecycle:
1. Persist the user message immediately.
2. Open observe() context — captures latency, status, ttfb.
3. Stream provider chunks; check for client disconnect + cancel signal every chunk.
4. Persist the assistant message at the end (post-redaction happens server-side
   in the worker; this is the raw text the user sees, kept as-is for UX).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text as sql_text

from llm_logger.providers.base import Message

from ..config import settings
from ..db import repo

log = logging.getLogger("chat-api.chat")
router = APIRouter(tags=["chat"])


class ChatBody(BaseModel):
    conversation_id: UUID | None = None
    message: str
    model: str | None = None


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


def _truncate(text: str | None, n: int) -> str | None:
    if text is None:
        return None
    return text if len(text) <= n else text[:n] + "…"


def _title_from(text: str, max_len: int = 60) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


@router.post("/chat")
async def chat(body: ChatBody, request: Request):
    if not body.message.strip():
        raise HTTPException(400, "message must not be empty")

    app = request.app
    sessionmaker = app.state.sessionmaker
    provider = app.state.provider
    logger = app.state.logger
    registry = app.state.cancel_registry

    assistant_msg_id = uuid4()

    # 1. Resolve or create the conversation; persist user message + load history.
    #    We also pre-insert an EMPTY assistant message row here, while the request
    #    task is healthy. The inference log shipped by observe() references this
    #    row via a FK (message_id); if the stream is cancelled before any content
    #    streams, the cancel handler's async UPDATE may itself be interrupted by
    #    task cancellation — but the row already exists, so the worker's insert
    #    never hits a ForeignKeyViolation. Content is filled in via UPDATE below.
    async with sessionmaker() as session:
        async with session.begin():
            if body.conversation_id is None:
                conv = await repo.create_conversation(session, title=_title_from(body.message))
                conv_id = UUID(str(conv["id"]))
            else:
                conv_id = body.conversation_id
                conv = await repo.get_conversation(session, conv_id)
                if conv is None:
                    raise HTTPException(404, "conversation not found")
                if conv["status"] == "cancelled":
                    raise HTTPException(409, "conversation is cancelled")
                if conv["title"] is None:
                    await repo.update_conversation_title(session, conv_id, _title_from(body.message))

            user_seq = await repo.next_sequence(session, conv_id)
            user_msg_id = await repo.insert_message(
                session,
                conversation_id=conv_id,
                role="user",
                content=body.message,
                sequence=user_seq,
            )
            history_rows = await repo.list_messages(session, conv_id)
            # Pre-insert the assistant placeholder (empty content, next sequence).
            await session.execute(
                sql_text(
                    "INSERT INTO messages (id, conversation_id, role, content, sequence) "
                    "VALUES (:id, :cid, 'assistant', '', :seq)"
                ),
                {"id": str(assistant_msg_id), "cid": str(conv_id), "seq": user_seq + 1},
            )

    # Build the prompt — last N turns by message count (cheap, sufficient).
    # Skip empty-content messages (e.g. an assistant turn cancelled before any
    # token streamed, or the placeholder just inserted) so we never send an
    # empty turn to the provider.
    turns = history_rows[-settings.context_turn_limit :]
    messages = [
        Message(role=m["role"], content=m["content"]) for m in turns if m["content"]
    ]

    cancel_event = await registry.register(conv_id)

    async def stream() -> AsyncIterator[bytes]:
        try:
            yield _sse(
                {
                    "type": "start",
                    "conversation_id": str(conv_id),
                    "user_message_id": str(user_msg_id),
                    "assistant_message_id": str(assistant_msg_id),
                }
            )

            full_text_parts: list[str] = []
            prompt_tokens = completion_tokens = total_tokens = None
            finish_reason: str | None = None

            async with logger.observe(
                provider=provider.name,
                model=body.model or provider.default_model,
                conversation_id=conv_id,
                message_id=assistant_msg_id,
            ) as obs:
                obs.set_input_preview(_truncate(body.message, settings.preview_max_chars))

                async for chunk in provider.stream(messages, model=body.model):
                    # Watch for cancel + disconnect on every chunk.
                    if cancel_event.is_set() or await request.is_disconnected():
                        raise asyncio.CancelledError()

                    if chunk.text:
                        obs.mark_first_token()
                        full_text_parts.append(chunk.text)
                        yield _sse({"type": "delta", "text": chunk.text})

                    if chunk.prompt_tokens is not None:
                        prompt_tokens = chunk.prompt_tokens
                    if chunk.completion_tokens is not None:
                        completion_tokens = chunk.completion_tokens
                    if chunk.total_tokens is not None:
                        total_tokens = chunk.total_tokens
                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason

                full_text = "".join(full_text_parts)
                obs.set_output_preview(_truncate(full_text, settings.preview_max_chars))
                obs.set_usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
                obs.set_metadata(finish_reason=finish_reason)

            # 2. Persist assistant message — fill in the placeholder row that
            #    was pre-inserted in the initial transaction.
            async with sessionmaker() as session:
                async with session.begin():
                    await session.execute(
                        sql_text(
                            "UPDATE messages SET content = :content WHERE id = :id"
                        ),
                        {"id": str(assistant_msg_id), "content": full_text},
                    )

            yield _sse(
                {
                    "type": "done",
                    "message_id": str(assistant_msg_id),
                    "finish_reason": finish_reason,
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    },
                }
            )

        except asyncio.CancelledError:
            # Persist whatever partial output the user saw so the conversation
            # replays consistently on resume. Stop = "stop this generation",
            # not "end the conversation" — the explicit /conversations/:id/cancel
            # endpoint handles the latter.
            partial = "".join(full_text_parts) if "full_text_parts" in locals() else ""
            # Fill in the placeholder row with whatever partial output streamed.
            # The row was pre-inserted in the initial (healthy) transaction, so
            # the inference log shipped by observe() — which references
            # assistant_msg_id via a FK — never hits a ForeignKeyViolation, even
            # if this UPDATE is itself interrupted by task cancellation before it
            # commits. The placeholder (empty content) is a consistent fallback.
            try:
                async with sessionmaker() as session:
                    async with session.begin():
                        await session.execute(
                            sql_text(
                                "UPDATE messages SET content = :content WHERE id = :id"
                            ),
                            {"id": str(assistant_msg_id), "content": partial},
                        )
            except Exception:
                log.exception("failed to persist partial assistant message")
            yield _sse({"type": "cancelled"})
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("chat stream failed")
            yield _sse({"type": "error", "message": str(exc)})
        finally:
            await registry.unregister(conv_id, cancel_event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
