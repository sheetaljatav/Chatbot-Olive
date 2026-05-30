"""Redis Streams consumer.

Loop: XREADGROUP a batch → for each entry, parse → PII-redact previews → upsert
into Postgres → XACK. If processing fails, XACK is skipped and Redis re-delivers
after the visibility timeout (claimed via XAUTOCLAIM). After max retries, the
event is sent to the DLQ stream and acked off the main stream so it doesn't loop
forever.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from llm_logger.schema import InferenceEvent

from .config import settings
from .db import make_engine, make_sessionmaker, upsert_event
from .pii import Redactor

log = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


async def _ensure_group(redis: Redis) -> None:
    try:
        await redis.xgroup_create(
            settings.event_stream,
            settings.event_group,
            id="0",
            mkstream=True,
        )
        log.info("created consumer group %s on %s", settings.event_group, settings.event_stream)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _redact_event(event: InferenceEvent, redactor: Redactor) -> InferenceEvent:
    if event.input_preview:
        event.input_preview = redactor.redact(event.input_preview)
    if event.output_preview:
        event.output_preview = redactor.redact(event.output_preview)
    return event


async def _process_entry(
    redis: Redis,
    session_maker,
    redactor: Redactor,
    entry_id: str,
    fields: dict,
) -> bool:
    raw = fields.get("event")
    if raw is None:
        log.warning("entry %s missing 'event' field", entry_id)
        return False
    try:
        event = InferenceEvent.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("entry %s failed validation: %s", entry_id, exc)
        return False

    event = _redact_event(event, redactor)

    async with session_maker() as session:
        async with session.begin():
            await upsert_event(session, event)
    return True


async def _send_to_dlq(redis: Redis, entry_id: str, fields: dict, reason: str) -> None:
    payload = dict(fields)
    payload["_dlq_reason"] = reason
    payload["_original_id"] = entry_id
    await redis.xadd(settings.event_dlq, payload, maxlen=10000, approximate=True)
    log.error("event %s moved to DLQ: %s", entry_id, reason)


async def _reclaim_pending(redis: Redis, session_maker, redactor: Redactor) -> None:
    """Pick up entries other consumers crashed on (idle > 30s)."""
    cursor = "0-0"
    while True:
        result = await redis.xautoclaim(
            settings.event_stream,
            settings.event_group,
            settings.consumer_name,
            min_idle_time=30_000,
            start_id=cursor,
            count=settings.batch_count,
        )
        if not result:
            return
        cursor, entries = result[0], result[1]
        if not entries:
            return
        for entry_id, fields in entries:
            await _handle(redis, session_maker, redactor, entry_id, fields)


async def _handle(redis: Redis, session_maker, redactor: Redactor, entry_id: str, fields: dict) -> None:
    # Track per-entry retry count via Redis pending info.
    delivered = await redis.xpending_range(
        settings.event_stream, settings.event_group, min=entry_id, max=entry_id, count=1
    )
    attempt = delivered[0]["times_delivered"] if delivered else 1

    try:
        ok = await _process_entry(redis, session_maker, redactor, entry_id, fields)
        if not ok:
            await _send_to_dlq(redis, entry_id, fields, "parse_failed")
            await redis.xack(settings.event_stream, settings.event_group, entry_id)
            return
        await redis.xack(settings.event_stream, settings.event_group, entry_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("processing failed (attempt=%s) for %s: %s", attempt, entry_id, exc)
        if attempt >= settings.max_retries:
            await _send_to_dlq(redis, entry_id, fields, f"max_retries: {exc}")
            await redis.xack(settings.event_stream, settings.event_group, entry_id)


async def run() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    engine = make_engine(settings.database_url)
    session_maker = make_sessionmaker(engine)
    redactor = Redactor(enabled=settings.pii_enabled, entities=settings.pii_entities)

    await _ensure_group(redis)
    log.info("worker %s consuming %s", settings.consumer_name, settings.event_stream)

    stop = asyncio.Event()

    def _on_signal(*_):
        log.info("shutdown signal received")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            pass  # Windows

    try:
        # On boot, sweep entries that previous workers might have left pending.
        await _reclaim_pending(redis, session_maker, redactor)

        while not stop.is_set():
            try:
                resp = await redis.xreadgroup(
                    groupname=settings.event_group,
                    consumername=settings.consumer_name,
                    streams={settings.event_stream: ">"},
                    count=settings.batch_count,
                    block=settings.block_ms,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("xreadgroup error: %s", exc)
                await asyncio.sleep(1.0)
                continue
            if not resp:
                # Periodic sweep of stuck entries.
                await _reclaim_pending(redis, session_maker, redactor)
                continue
            for _stream, entries in resp:
                for entry_id, fields in entries:
                    await _handle(redis, session_maker, redactor, entry_id, fields)
    finally:
        await redis.aclose()
        await engine.dispose()
        log.info("worker exited cleanly")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
