"""OpenAI adapter."""
from __future__ import annotations

import os
from typing import AsyncIterator

from .base import LLMStreamChunk, Message


class OpenAIProvider:
    name = "openai"
    default_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        from openai import AsyncOpenAI  # optional dep

        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        self._client = AsyncOpenAI(api_key=api_key)
        if model:
            self.default_model = model

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        **kwargs,
    ) -> AsyncIterator[LLMStreamChunk]:
        model_name = model or self.default_model
        stream = await self._client.chat.completions.create(
            model=model_name,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            stream=True,
            stream_options={"include_usage": True},
        )
        finish_reason: str | None = None
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    yield LLMStreamChunk(text=delta)
                fr = chunk.choices[0].finish_reason
                if fr:
                    finish_reason = fr
            if chunk.usage:
                yield LLMStreamChunk(
                    text="",
                    prompt_tokens=chunk.usage.prompt_tokens,
                    completion_tokens=chunk.usage.completion_tokens,
                    total_tokens=chunk.usage.total_tokens,
                    finish_reason=finish_reason,
                )
