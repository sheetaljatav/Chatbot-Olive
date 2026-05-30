"""Conversation CRUD: list / get / create / cancel."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..db import repo

router = APIRouter(prefix="/conversations", tags=["conversations"])


class CreateConversationBody(BaseModel):
    title: str | None = None


@router.get("")
async def list_conversations(request: Request) -> list[dict]:
    async with request.app.state.sessionmaker() as session:
        return await repo.list_conversations(session)


@router.post("", status_code=201)
async def create_conversation(body: CreateConversationBody, request: Request) -> dict:
    async with request.app.state.sessionmaker() as session:
        async with session.begin():
            return await repo.create_conversation(session, title=body.title)


@router.get("/{conv_id}")
async def get_conversation(conv_id: UUID, request: Request) -> dict:
    async with request.app.state.sessionmaker() as session:
        conv = await repo.get_conversation(session, conv_id)
        if conv is None:
            raise HTTPException(404, "conversation not found")
        messages = await repo.list_messages(session, conv_id)
        return {**conv, "messages": messages}


@router.put("/{conv_id}/cancel")
async def cancel_conversation(conv_id: UUID, request: Request) -> dict:
    cancelled = await request.app.state.cancel_registry.cancel(conv_id)
    async with request.app.state.sessionmaker() as session:
        async with session.begin():
            await repo.set_conversation_status(session, conv_id, "cancelled")
    return {"ok": True, "active_streams_signalled": cancelled}
