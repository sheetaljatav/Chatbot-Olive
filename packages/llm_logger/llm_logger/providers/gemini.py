"""Google Gemini adapter (primary provider for this assignment)."""
from __future__ import annotations

import os
from typing import AsyncIterator

from .base import LLMStreamChunk, Message


class GeminiProvider:
    name = "gemini"
    default_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        import google.generativeai as genai  # local import — optional dep

        self._genai = genai
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        genai.configure(api_key=api_key)
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
        system_text, history = _split_system(messages)

        client = self._genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_text or None,
        )

        # Gemini's history format: list of {role, parts}. The "model" role is the
        # assistant. The final user message is sent as the new turn.
        if not history or history[-1].role != "user":
            raise ValueError("Last message must be from user")
        *prior, last_user = history
        chat = client.start_chat(
            history=[{"role": _gemini_role(m.role), "parts": [m.content]} for m in prior]
        )

        stream = await chat.send_message_async(last_user.content, stream=True)

        last_chunk_raw = None
        async for chunk in stream:
            last_chunk_raw = chunk
            text = getattr(chunk, "text", "") or ""
            if text:
                yield LLMStreamChunk(text=text)

        # Final usage/finish info lives on the resolved response.
        try:
            await stream.resolve()
        except Exception:
            pass
        usage = getattr(last_chunk_raw, "usage_metadata", None) if last_chunk_raw else None
        prompt_tokens = getattr(usage, "prompt_token_count", None) if usage else None
        completion_tokens = getattr(usage, "candidates_token_count", None) if usage else None
        total_tokens = getattr(usage, "total_token_count", None) if usage else None
        finish_reason = None
        try:
            finish_reason = str(last_chunk_raw.candidates[0].finish_reason) if last_chunk_raw else None
        except Exception:
            finish_reason = None

        yield LLMStreamChunk(
            text="",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=finish_reason,
        )


def _split_system(messages: list[Message]) -> tuple[str | None, list[Message]]:
    system_chunks = [m.content for m in messages if m.role == "system"]
    rest = [m for m in messages if m.role != "system"]
    return ("\n".join(system_chunks) if system_chunks else None), rest


def _gemini_role(role: str) -> str:
    return "model" if role == "assistant" else "user"
