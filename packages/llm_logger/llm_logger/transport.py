"""Async batched HTTP shipper.

Design constraints:
- enqueue() must never block the caller (the chat hot path).
- A bounded buffer prevents unbounded memory growth if the endpoint is down.
- On overflow we drop the OLDEST event and increment a counter — recent events
  are more useful for debugging the current problem than ancient ones.
- Logging failures must never raise into user code.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Iterable

import httpx

from .schema import InferenceEvent, IngestRequest

log = logging.getLogger("llm_logger.transport")


class BatchedShipper:
    def __init__(
        self,
        endpoint: str,
        *,
        batch_size: int = 20,
        flush_interval_ms: int = 500,
        buffer_max: int = 1000,
        max_retries: int = 3,
        timeout_s: float = 5.0,
    ) -> None:
        self._endpoint = endpoint.rstrip("/") + "/v1/logs"
        self._batch_size = batch_size
        self._flush_interval = flush_interval_ms / 1000.0
        self._buffer: deque[InferenceEvent] = deque(maxlen=buffer_max)
        self._max_retries = max_retries
        self._timeout = timeout_s

        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._client: httpx.AsyncClient | None = None
        self._stopping = False
        self.dropped = 0

    async def start(self) -> None:
        if self._task is not None:
            return
        self._client = httpx.AsyncClient(timeout=self._timeout)
        self._task = asyncio.create_task(self._run(), name="llm_logger-shipper")

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        if self._client is not None:
            await self._client.aclose()

    def enqueue(self, event: InferenceEvent) -> None:
        # deque(maxlen=...) drops the leftmost (oldest) item on overflow.
        if len(self._buffer) == self._buffer.maxlen:
            self.dropped += 1
        self._buffer.append(event)
        if len(self._buffer) >= self._batch_size:
            self._wake.set()

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._flush_interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            await self._flush()
        await self._flush()  # final drain on shutdown

    async def _flush(self) -> None:
        if not self._buffer:
            return
        # Pop up to batch_size atomically.
        batch: list[InferenceEvent] = []
        while self._buffer and len(batch) < self._batch_size:
            batch.append(self._buffer.popleft())
        try:
            await self._post(batch)
        except Exception as exc:  # noqa: BLE001
            # Re-queue on the LEFT so order is preserved and these are tried next.
            for e in reversed(batch):
                self._buffer.appendleft(e)
            log.warning("ingestion ship failed; re-queued %d events: %s", len(batch), exc)

    async def _post(self, batch: Iterable[InferenceEvent]) -> None:
        assert self._client is not None
        payload = IngestRequest(events=list(batch)).model_dump(mode="json")
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.post(self._endpoint, json=payload)
                if resp.status_code < 500:
                    resp.raise_for_status()
                    return
                last_exc = httpx.HTTPStatusError(
                    f"{resp.status_code}", request=resp.request, response=resp
                )
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
            await asyncio.sleep(0.2 * (2**attempt))
        assert last_exc is not None
        raise last_exc
