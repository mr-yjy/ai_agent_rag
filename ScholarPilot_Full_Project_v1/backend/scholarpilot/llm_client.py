"""OpenAI-compatible LLM client for ScholarPilot.

Supports DeepSeek, OpenAI, Qwen, and any OpenAI-compatible provider.
Works with both the `openai` package (if installed) and a built-in
urllib-based fallback that requires no extra dependencies.

Usage:
    client = LLMClient.from_env()
    response = client.chat([{"role": "user", "content": "Hello"}])
"""

from __future__ import annotations

import contextvars
import inspect
import json
import logging
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Literal

from .config import LLMConfig, get_config
from .budget import current_deadline, current_stage


Role = Literal["system", "user", "assistant"]
logger = logging.getLogger(__name__)


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


def extract_json_items(content: str) -> list[dict[str, Any]]:
    """Parse a JSON-mode object wrapper while accepting legacy arrays."""
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)

    candidates = [stripped]
    object_match = re.search(r"\{.*\}", stripped, re.DOTALL)
    array_match = re.search(r"\[.*\]", stripped, re.DOTALL)
    if object_match:
        candidates.append(object_match.group(0))
    if array_match:
        candidates.append(array_match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            parsed = parsed.get("items", [])
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


class LLMClient:
    """OpenAI-compatible chat completion client."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or get_config().llm
        self._last_call_ms: int = 0
        self._call_count: int = 0
        self._request_attempt_count: int = 0
        self._failed_call_count: int = 0
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0
        self._estimated_tokens: int = 0
        self._total_tokens: int = 0
        self._total_elapsed_ms: int = 0
        self._metrics_lock = threading.Lock()
        self._request_metrics: contextvars.ContextVar[
            dict[str, int] | None
        ] = contextvars.ContextVar(
            f"scholarpilot_llm_request_metrics_{id(self)}",
            default=None,
        )

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
        thinking_mode = overrides.get(
            "thinking_mode", self.config.thinking_mode
        )
        reasoning_effort = overrides.get(
            "reasoning_effort", self.config.reasoning_effort
        )
        json_mode = bool(overrides.get("json_mode", self.config.json_mode))
        requested_timeout = max(
            0.05,
            float(
                overrides.get(
                    "timeout_seconds",
                    self.config.timeout_seconds,
                )
            ),
        )
        deadline = current_deadline()
        timeout_seconds = (
            deadline.timeout_for(current_stage(), requested_timeout)
            if deadline is not None
            else requested_timeout
        )
        if thinking_mode not in {"enabled", "disabled"}:
            thinking_mode = "disabled"
        if reasoning_effort not in {"high", "max"}:
            reasoning_effort = "high"

        self._increment_metrics("calls")
        try:
            # Use the SDK when installed; urllib is only a dependency fallback.
            # Retrying the same failed API call through a second transport would
            # double cost and distort latency metrics.
            transport_parameters = inspect.signature(
                self._try_openai_package
            ).parameters
            result = (
                self._try_openai_package(
                    dict_messages,
                    model,
                    temperature,
                    max_tokens,
                    thinking_mode,
                    reasoning_effort,
                    json_mode,
                    timeout_seconds,
                )
                if "timeout_seconds" in transport_parameters
                else self._try_openai_package(  # type: ignore[call-arg]
                    dict_messages,
                    model,
                    temperature,
                    max_tokens,
                    thinking_mode,
                    reasoning_effort,
                    json_mode,
                )
            )
            if result is None:
                result = self._urllib_chat(
                    dict_messages,
                    model,
                    temperature,
                    max_tokens,
                    thinking_mode,
                    reasoning_effort,
                    json_mode,
                    timeout_seconds,
                )
        except Exception as exc:
            self._increment_metrics("failedCalls")
            self._record_failure_status(exc)
            logger.warning(
                "LLM call failed for model %s: %s",
                model,
                self._safe_error_message(exc),
            )
            raise

        token_count: int
        if result.usage and result.usage.get("total_tokens"):
            token_count = int(result.usage["total_tokens"])
            self._increment_metrics(
                "promptTokens",
                int(result.usage.get("prompt_tokens", 0)),
            )
            self._increment_metrics(
                "completionTokens",
                int(result.usage.get("completion_tokens", 0)),
            )
        else:
            prompt = " ".join(message["content"] for message in dict_messages)
            token_count = self.count_tokens(prompt + result.content)
            self._increment_metrics("estimatedTokens", token_count)
        with self._metrics_lock:
            self._last_call_ms = result.elapsed_ms
        self._increment_metrics("elapsedMs", result.elapsed_ms)
        self._increment_metrics("totalTokens", token_count)
        return result

    @staticmethod
    def _empty_metrics() -> dict[str, int]:
        return {
            "calls": 0,
            "requestAttempts": 0,
            "failedCalls": 0,
            "lastFailureStatus": 0,
            "promptTokens": 0,
            "completionTokens": 0,
            "estimatedTokens": 0,
            "totalTokens": 0,
            "elapsedMs": 0,
        }

    def begin_request_metrics(
        self,
    ) -> contextvars.Token[dict[str, int] | None]:
        """Start request-local accounting that is isolated across threads."""
        return self._request_metrics.set(self._empty_metrics())

    def request_metrics_snapshot(self) -> dict[str, int]:
        metrics = self._request_metrics.get()
        return dict(metrics) if metrics is not None else self._empty_metrics()

    def end_request_metrics(
        self,
        token: contextvars.Token[dict[str, int] | None],
    ) -> None:
        self._request_metrics.reset(token)

    def _increment_metrics(self, key: str, amount: int = 1) -> None:
        with self._metrics_lock:
            if key == "calls":
                self._call_count += amount
            elif key == "requestAttempts":
                self._request_attempt_count += amount
            elif key == "failedCalls":
                self._failed_call_count += amount
            elif key == "promptTokens":
                self._prompt_tokens += amount
            elif key == "completionTokens":
                self._completion_tokens += amount
            elif key == "estimatedTokens":
                self._estimated_tokens += amount
            elif key == "totalTokens":
                self._total_tokens += amount
            elif key == "elapsedMs":
                self._total_elapsed_ms += amount
        request_metrics = self._request_metrics.get()
        if request_metrics is not None:
            request_metrics[key] = request_metrics.get(key, 0) + amount

    def _record_failure_status(self, exc: Exception) -> None:
        """Keep only a safe HTTP status for request-level diagnostics."""
        status = 0
        current: BaseException | None = exc
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            for attribute in ("status_code", "status", "code"):
                value = getattr(current, attribute, None)
                if isinstance(value, int) and 100 <= value <= 599:
                    status = value
                    break
            if status:
                break
            current = current.__cause__ or current.__context__
        request_metrics = self._request_metrics.get()
        if request_metrics is not None:
            request_metrics["lastFailureStatus"] = status

    @staticmethod
    def _retryable_status(status: int | None) -> bool:
        return status in {408, 425, 429, 500, 502, 503, 504}

    def _is_retryable_exception(self, exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            return self._retryable_status(status)
        error_name = type(exc).__name__.casefold()
        return any(
            marker in error_name
            for marker in ("timeout", "connection", "ratelimit", "internalserver")
        )

    def _safe_error_message(self, exc: Exception) -> str:
        message = str(exc).replace("\r", " ").replace("\n", " ")
        if self.config.api_key:
            message = message.replace(self.config.api_key, "[redacted]")
        message = re.sub(
            r"(?i)(bearer\s+)[^\s,;]+",
            r"\1[redacted]",
            message,
        )
        message = re.sub(
            r"(?i)(api[_-]?key|token)=([^&\s]+)",
            r"\1=[redacted]",
            message,
        )
        return message[:300]

    def _retry_delay(self, retry_index: int) -> float:
        base = self.config.retry_backoff_seconds * (2**retry_index)
        return base * random.uniform(0.85, 1.15)

    @staticmethod
    def _retry_fits_budget(delay_seconds: float) -> bool:
        deadline = current_deadline()
        return deadline is None or deadline.can_wait(delay_seconds)

    @staticmethod
    def _build_payload(
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        thinking_mode: str,
        reasoning_effort: str,
        json_mode: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "thinking": {"type": thinking_mode},
        }
        # DeepSeek V4 ignores sampling parameters while thinking is enabled.
        if thinking_mode == "disabled":
            payload["temperature"] = temperature
        else:
            payload["reasoning_effort"] = reasoning_effort
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _try_openai_package(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        thinking_mode: str,
        reasoning_effort: str,
        json_mode: bool,
        timeout_seconds: float | None = None,
    ) -> LLMResponse | None:
        """Try using the 'openai' package for the request."""
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError:
            return None
        try:
            client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
            )
        except Exception as exc:
            raise LLMError(
                f"LLM SDK initialization failed: {self._safe_error_message(exc)}"
            ) from exc

        payload = self._build_payload(
            messages,
            model,
            temperature,
            max_tokens,
            thinking_mode,
            reasoning_effort,
            json_mode,
        )
        thinking = payload.pop("thinking")
        reasoning = payload.pop("reasoning_effort", None)
        extra_body: dict[str, Any] = {"thinking": thinking}
        if reasoning:
            # extra_body keeps compatibility with older OpenAI SDK versions
            # while placing reasoning_effort at the request root.
            extra_body["reasoning_effort"] = reasoning
        payload["extra_body"] = extra_body
        payload["timeout"] = (
            timeout_seconds
            if timeout_seconds is not None
            else self.config.timeout_seconds
        )

        started = time.perf_counter()
        for retry_index in range(self.config.max_retries + 1):
            self._increment_metrics("requestAttempts")
            try:
                response = client.chat.completions.create(**payload)
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
                    content=(choice.message.content or "") if choice else "",
                    model=getattr(response, "model", None) or model,
                    usage=usage,
                    elapsed_ms=elapsed,
                )
            except Exception as exc:
                if (
                    retry_index < self.config.max_retries
                    and self._is_retryable_exception(exc)
                ):
                    delay = self._retry_delay(retry_index)
                    if not self._retry_fits_budget(delay):
                        raise LLMError(
                            "LLM retry skipped because the search budget "
                            "would be exceeded"
                        ) from exc
                    time.sleep(delay)
                    continue
                raise LLMError(
                    "LLM SDK request failed: "
                    f"{self._safe_error_message(exc)}"
                ) from exc

        raise LLMError("LLM SDK request failed without a response")

    def _urllib_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        thinking_mode: str,
        reasoning_effort: str,
        json_mode: bool,
        timeout_seconds: float | None = None,
    ) -> LLMResponse:
        """Fallback: use urllib for the OpenAI-compatible API call."""
        payload = self._build_payload(
            messages,
            model,
            temperature,
            max_tokens,
            thinking_mode,
            reasoning_effort,
            json_mode,
        )

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
        result: dict[str, Any] | None = None
        for retry_index in range(self.config.max_retries + 1):
            self._increment_metrics("requestAttempts")
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=(
                        timeout_seconds
                        if timeout_seconds is not None
                        else self.config.timeout_seconds
                    ),
                ) as response:
                    result = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                if (
                    retry_index < self.config.max_retries
                    and self._retryable_status(exc.code)
                ):
                    delay = self._retry_delay(retry_index)
                    if not self._retry_fits_budget(delay):
                        raise LLMError(
                            "LLM retry skipped because the search budget "
                            "would be exceeded"
                        ) from exc
                    time.sleep(delay)
                    continue
                raise LLMError(
                    f"LLM request failed with HTTP {exc.code}"
                ) from exc
            except (
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
            ) as exc:
                if retry_index < self.config.max_retries:
                    delay = self._retry_delay(retry_index)
                    if not self._retry_fits_budget(delay):
                        raise LLMError(
                            "LLM retry skipped because the search budget "
                            "would be exceeded"
                        ) from exc
                    time.sleep(delay)
                    continue
                raise LLMError(
                    f"LLM request failed: {self._safe_error_message(exc)}"
                ) from exc

        if result is None:
            raise LLMError("LLM request failed without a response")

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
        with self._metrics_lock:
            return self._last_call_ms

    def metrics_snapshot(self) -> dict[str, int]:
        """Return cumulative counters; callers can subtract two snapshots."""
        with self._metrics_lock:
            return {
                "calls": self._call_count,
                "requestAttempts": self._request_attempt_count,
                "failedCalls": self._failed_call_count,
                "promptTokens": self._prompt_tokens,
                "completionTokens": self._completion_tokens,
                "estimatedTokens": self._estimated_tokens,
                "totalTokens": self._total_tokens,
                "elapsedMs": self._total_elapsed_ms,
            }


# Convenience factory
def create_llm_client() -> LLMClient:
    return LLMClient.from_env()
