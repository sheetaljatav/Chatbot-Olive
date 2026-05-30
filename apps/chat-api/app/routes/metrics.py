"""Dashboard backend: summary, per-minute time series, per-model breakdown."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..db import repo

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/summary")
async def summary(request: Request, window: int = Query(60, ge=1, le=1440)) -> dict:
    async with request.app.state.sessionmaker() as session:
        s = await repo.metrics_summary(session, window)
        total = int(s["total"] or 0)
        errors = int(s["errors"] or 0)
        s["error_rate"] = (errors / total) if total else 0.0
        return s


@router.get("/timeseries")
async def timeseries(request: Request, window: int = Query(60, ge=1, le=1440)) -> list[dict]:
    async with request.app.state.sessionmaker() as session:
        return await repo.metrics_timeseries(session, window)


@router.get("/by_model")
async def by_model(request: Request, window: int = Query(60, ge=1, le=1440)) -> list[dict]:
    async with request.app.state.sessionmaker() as session:
        return await repo.metrics_by_model(session, window)
