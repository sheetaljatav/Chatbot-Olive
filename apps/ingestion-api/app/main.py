"""Ingestion API.

Responsibility kept tight: validate the payload (Pydantic does this for us by
typing the route), publish each event to a Redis Stream, return 202. The worker
does all the heavy lifting (PII redaction, DB writes). This means the API can
absorb spikes and stays responsive even if the DB is slow.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from redis.asyncio import Redis

from llm_logger.schema import IngestRequest, IngestResponse

from .config import settings

log = logging.getLogger("ingestion-api")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await app.state.redis.ping()
        log.info("connected to redis at %s", settings.redis_url)
        yield
    finally:
        await app.state.redis.aclose()


app = FastAPI(title="LLM Ingestion API", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    try:
        await app.state.redis.ping()
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(503, f"redis unreachable: {exc}")


@app.post("/v1/logs", status_code=status.HTTP_202_ACCEPTED, response_model=IngestResponse)
async def ingest_logs(body: IngestRequest) -> IngestResponse:
    redis: Redis = app.state.redis
    pipe = redis.pipeline(transaction=False)
    for event in body.events:
        # Stream entries are flat dicts; we send the whole event as one JSON field
        # so workers parse with one round-trip through Pydantic and we don't have
        # to flatten/round-trip every column.
        pipe.xadd(
            settings.event_stream,
            {"event": event.model_dump_json()},
            maxlen=settings.stream_maxlen,
            approximate=True,
        )
    await pipe.execute()
    return IngestResponse(accepted=len(body.events))
