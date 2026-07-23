"""OpenAI-compatible LLM client for ScholarPilot.

Supports DeepSeek, OpenAI, Qwen, and any OpenAI-compatible provider.
Works with both the `openai` package (if installed) and a built-in
urllib-based fallback that requires no extra dependencies.

Usage:
    client = LLMClient.from_env()
    response = client.chat([{"role": "user", "content": "Hello"}])
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Literal

from .config import LLMConfig, get_config


Role = Literal["system", "user", "assistant"]


@dataclass(slots=True)
class Message:
    role: Role
    content: str


@dataclass(slots=True)
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int] | None = None
    elapsed_ms: int = 0


class LLMError(RuntimeError):
    """Raised when the LLM provider returns an error."""


class LLMClient:
    """OpenAI-compatible chat completion client."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or get_config().llm
        self._last_call_ms: int = 0

    @classmethod
    def from_env(cls) -> LLMClient:
        return cls(LLMConfig.from_env())

    def chat(
        self,
        messages: list[dict[str, str]] | list[Message],
        **overrides: Any,
    ) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: List of {"role": ..., "content": ...} dicts or Message objects.
            **overrides: Override any LLMConfig field (model, temperature, etc.).

        Returns:
            LLMResponse with generated text and metadata.
        """
        # Convert Message objects to dicts if needed
        dict_messages: list[dict[str, str]] = []
        for msg in messages:
            if isinstance(msg, dict):
                dict_messages.append(msg)
            else:
                dict_messages.append({"role": msg.role, "content": msg.content})

        model = overrides.get("model", self.config.model)
        temperature = overrides.get("temperature", self.config.temperature)
        max_tokens = overrides.get("max_tokens", self.config.max_tokens)

        # First try the openai package if available
        result = self._try_openai_package(
            dict_messages, model, temperature, max_tokens
        )
        if result is not None:
            return result

        # Fallback: use urllib directly
        return self._urllib_chat(
            dict_messages, model, temperature, max_tokens
        )

    def _try_openai_package(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse | None:
        """Try using the 'openai' package for the request."""
        try:
            from openai import OpenAI  # type: ignore[import-untyped]

            client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
            )
            started = time.perf_counter()
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=self.config.timeout_seconds,
            )
            elapsed = int((time.perf_counter() - started) * 1000)
            choice = response.choices[0] if response.choices else None
            usage = None
            if hasattr(response, "usage") and response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens or 0,
                    "completion_tokens": response.usage.completion_tokens or 0,
                    "total_tokens": response.usage.total_tokens or 0,
                }
            return LLMResponse(
                content=choice.message.content if choice else "",
                model=model,
                usage=usage,
                elapsed_ms=elapsed,
            )
        except Exception:
            return None

    def _urllib_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Fallback: use urllib for the OpenAI-compatible API call."""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )

        started = time.perf_counter()
        try:
            with urllib.request.urlopen(
                request, timeout=self.config.timeout_seconds
            ) as response:
                result = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        elapsed = int((time.perf_counter() - started) * 1000)
        choice = result.get("choices", [{}])[0]
        usage = result.get("usage")
        usage_dict: dict[str, int] | None = None
        if usage:
            usage_dict = {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }

        content = choice.get("message", {}).get("content", "")
        return LLMResponse(
            content=content,
            model=model,
            usage=usage_dict,
            elapsed_ms=elapsed,
        )

    def count_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars ≈ 1 token for English/Chinese mixed)."""
        return len(text) // 3 + 1

    @property
    def last_call_ms(self) -> int:
        return self._last_call_ms


# Convenience factory
def create_llm_client() -> LLMClient:
    return LLMClient.from_env()
