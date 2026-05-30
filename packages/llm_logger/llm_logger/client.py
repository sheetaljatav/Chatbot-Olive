"""Public SDK surface.

Usage:

    logger = LLMLogger(endpoint="http://ingestion-api:8001")
    await logger.start()

    async with logger.observe(provider="gemini", model="gemini-1.5-flash",
                              conversation_id=conv_id) as obs:
        obs.set_input_preview(prompt)
        async for chunk in provider.stream(prompt):
            obs.mark_first_token()
            yield chunk
            full += chunk.text
        obs.set_output_preview(full)
        obs.set_usage(prompt_tokens=..., completion_tokens=...)

If the body raises, the event is shipped with status=error and the exception
re-raised. If the caller cancels (asyncio.CancelledError), status=cancelled.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .schema import EventStatus, InferenceEvent
from .transport import BatchedShipper

log = logging.getLogger("llm_logger")


class _Observation:
    """Mutable handle the caller updates while a call is in-flight."""

    def __init__(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model
        self.conversation_id: UUID | None = None
        self.message_id: UUID | None = None
        self.input_preview: str | None = None
        self.output_preview: str | None = None
        self.prompt_tokens: int | None = None
        self.completion_tokens: int | None = None
        self.total_tokens: int | None = None
        self.metadata: dict[str, Any] = {}
        self._first_token_perf: float | None = None

    # Setters kept fluent and tiny — the caller's hot path stays readable.
    def set_input_preview(self, text: str | None) -> None:
        self.input_preview = text

    def set_output_preview(self, text: str | None) -> None:
        self.output_preview = text

    def set_usage(
        self,
        *,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        if prompt_tokens is not None:
            self.prompt_tokens = prompt_tokens
        if completion_tokens is not None:
            self.completion_tokens = completion_tokens
        if total_tokens is not None:
            self.total_tokens = total_tokens
        elif prompt_tokens is not None and completion_tokens is not None:
            self.total_tokens = prompt_tokens + completion_tokens

    def set_metadata(self, **kv: Any) -> None:
        self.metadata.update(kv)

    def set_ids(
        self,
        *,
        conversation_id: UUID | None = None,
        message_id: UUID | None = None,
    ) -> None:
        if conversation_id is not None:
            self.conversation_id = conversation_id
        if message_id is not None:
            self.message_id = message_id

    def mark_first_token(self) -> None:
        """Call on the first streamed chunk to capture TTFB."""
        if self._first_token_perf is None:
            self._first_token_perf = time.perf_counter()


class LLMLogger:
    def __init__(
        self,
        endpoint: str,
        *,
        preview_max_chars: int = 500,
        batch_size: int = 20,
        flush_interval_ms: int = 500,
        buffer_max: int = 1000,
    ) -> None:
        self._preview_max = preview_max_chars
        self._shipper = BatchedShipper(
            endpoint,
            batch_size=batch_size,
            flush_interval_ms=flush_interval_ms,
            buffer_max=buffer_max,
        )

    async def start(self) -> None:
        await self._shipper.start()

    async def stop(self) -> None:
        await self._shipper.stop()

    @asynccontextmanager
    async def observe(
        self,
        *,
        provider: str,
        model: str,
        conversation_id: UUID | None = None,
        message_id: UUID | None = None,
        **metadata: Any,
    ):
        obs = _Observation(provider=provider, model=model)
        obs.conversation_id = conversation_id
        obs.message_id = message_id
        obs.metadata.update(metadata)

        started_perf = time.perf_counter()
        started_at = datetime.now(timezone.utc)
        status: EventStatus = EventStatus.SUCCESS
        error_code: str | None = None
        error_message: str | None = None

        try:
            yield obs
        except BaseException as exc:  # noqa: BLE001 — re-raised below
            if isinstance(exc, (KeyboardInterrupt,)):
                raise
            # asyncio.CancelledError inherits from BaseException
            if exc.__class__.__name__ == "CancelledError":
                status = EventStatus.CANCELLED
                error_message = "cancelled"
            else:
                status = EventStatus.ERROR
                error_code = exc.__class__.__name__
                error_message = str(exc)[:500]
            raise
        finally:
            ended_at = datetime.now(timezone.utc)
            ttfb_ms: int | None = None
            if obs._first_token_perf is not None:
                ttfb_ms = int((obs._first_token_perf - started_perf) * 1000)

            try:
                event = InferenceEvent(
                    conversation_id=obs.conversation_id,
                    message_id=obs.message_id,
                    provider=obs.provider,
                    model=obs.model,
                    status=status,
                    error_code=error_code,
                    error_message=error_message,
                    started_at=started_at,
                    ended_at=ended_at,
                    ttfb_ms=ttfb_ms,
                    prompt_tokens=obs.prompt_tokens,
                    completion_tokens=obs.completion_tokens,
                    total_tokens=obs.total_tokens,
                    input_preview=_truncate(obs.input_preview, self._preview_max),
                    output_preview=_truncate(obs.output_preview, self._preview_max),
                    metadata=obs.metadata,
                )
                self._shipper.enqueue(event)
            except Exception:  # noqa: BLE001
                # Logging must never break user code.
                log.exception("failed to enqueue inference event")


def _truncate(text: str | None, n: int) -> str | None:
    if text is None:
        return None
    if len(text) <= n:
        return text
    return text[:n] + "…"
