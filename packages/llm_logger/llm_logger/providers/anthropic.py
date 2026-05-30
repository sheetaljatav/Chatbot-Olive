"""Anthropic adapter."""
from __future__ import annotations

import os
from typing import AsyncIterator

from .base import LLMStreamChunk, Message


class AnthropicProvider:
    name = "anthropic"
    default_model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        from anthropic import AsyncAnthropic  # optional dep

        api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self._client = AsyncAnthropic(api_key=api_key)
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
        system_text = "\n".join(m.content for m in messages if m.role == "system") or None
        non_system = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]

        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        finish_reason: str | None = None

        async with self._client.messages.stream(
            model=model_name,
            system=system_text,
            messages=non_system,
            max_tokens=kwargs.get("max_tokens", 1024),
        ) as stream:
            async for text in stream.text_stream:
                yield LLMStreamChunk(text=text)
            final = await stream.get_final_message()
            if final.usage:
                prompt_tokens = final.usage.input_tokens
                completion_tokens = final.usage.output_tokens
            finish_reason = final.stop_reason

        yield LLMStreamChunk(
            text="",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=(
                (prompt_tokens or 0) + (completion_tokens or 0)
                if prompt_tokens is not None or completion_tokens is not None
                else None
            ),
            finish_reason=finish_reason,
        )
