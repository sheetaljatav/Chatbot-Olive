"""Per-conversation cancellation registry.

A conversation can be cancelled in two ways:
- User clicks Stop in the UI -> the SSE response disconnects -> handled by
  FastAPI's request.is_disconnected() check inside the stream loop.
- User hits PUT /conversations/:id/cancel from elsewhere (different tab, API
  client) -> we need to signal the in-flight stream from outside. That's what
  this registry does.

Each active stream registers an asyncio.Event keyed by conversation_id; the
cancel endpoint sets it; the stream loop watches it.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from uuid import UUID


class CancellationRegistry:
    def __init__(self) -> None:
        self._events: dict[UUID, set[asyncio.Event]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def register(self, conv_id: UUID) -> asyncio.Event:
        ev = asyncio.Event()
        async with self._lock:
            self._events[conv_id].add(ev)
        return ev

    async def unregister(self, conv_id: UUID, ev: asyncio.Event) -> None:
        async with self._lock:
            self._events[conv_id].discard(ev)
            if not self._events[conv_id]:
                self._events.pop(conv_id, None)

    async def cancel(self, conv_id: UUID) -> int:
        async with self._lock:
            events = list(self._events.get(conv_id, ()))
        for ev in events:
            ev.set()
        return len(events)
