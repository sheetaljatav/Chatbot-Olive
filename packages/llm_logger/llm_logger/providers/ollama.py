"""Ollama adapter — local-model fallback. Zero API cost, useful for offline dev."""
from __future__ import annotations

import json
import os
from typing import AsyncIterator

import httpx

from .base import LLMStreamChunk, Message


class OllamaProvider:
    name = "ollama"
    default_model = os.getenv("OLLAMA_MODEL", "llama3.2")

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self._base = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        if model:
            self.default_model = model
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0))

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        **kwargs,
    ) -> AsyncIterator[LLMStreamChunk]:
        model_name = model or self.default_model
        payload = {
            "model": model_name,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        async with self._client.stream("POST", f"{self._base}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                obj = json.loads(line)
                msg = (obj.get("message") or {}).get("content", "")
                if msg:
                    yield LLMStreamChunk(text=msg)
                if obj.get("done"):
                    yield LLMStreamChunk(
                        text="",
                        prompt_tokens=obj.get("prompt_eval_count"),
                        completion_tokens=obj.get("eval_count"),
                        total_tokens=(
                            (obj.get("prompt_eval_count") or 0) + (obj.get("eval_count") or 0)
                        ),
                        finish_reason=obj.get("done_reason") or "stop",
                    )
