"""Provider abstraction.

Every adapter exposes the same shape: a typed `Message` list goes in, an async
iterator of `LLMStreamChunk` comes out. This keeps the chat-api provider-agnostic
and makes it trivial to add a new backend.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant"]


@dataclass
class Message:
    role: Role
    content: str


@dataclass
class LLMStreamChunk:
    text: str = ""
    # Set on the final chunk if the provider reports it.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    finish_reason: str | None = None
    raw: dict | None = field(default=None, repr=False)


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    finish_reason: str | None = None


@runtime_checkable
class Provider(Protocol):
    name: str
    default_model: str

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        **kwargs,
    ) -> AsyncIterator[LLMStreamChunk]:
        ...
