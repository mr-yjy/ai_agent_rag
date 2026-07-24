"""Authentication, rate limiting, and concurrency controls for live search."""

from __future__ import annotations

import contextlib
import hmac
import ipaddress
import re
import threading
import time
from dataclasses import dataclass
from typing import Iterator

from .config import SecurityConfig, get_config


class SecurityConfigurationError(RuntimeError):
    """Raised when the backend is not safe to expose."""


class AuthenticationError(RuntimeError):
    """Raised when a request does not carry the internal proxy credential."""


class RateLimitExceeded(RuntimeError):
    """Raised when an IP or user exceeds the configured fixed-window limit."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("搜索请求过于频繁，请稍后重试。")
        self.retry_after_seconds = max(1, retry_after_seconds)


class ConcurrencyLimitExceeded(RuntimeError):
    """Raised when all live-search execution slots are occupied."""


def _normalized_ip(value: str | None) -> str:
    candidate = (value or "").split(",", 1)[0].strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return "unknown"


def request_identity_keys(
    *,
    user_id: str | None,
    forwarded_for: str | None,
    remote_addr: str | None,
) -> list[str]:
    """Return bounded rate-limit keys for both proxy-provided user and IP."""
    ip_value = _normalized_ip(forwarded_for or remote_addr)
    keys = [f"ip:{ip_value}"]
    normalized_user = re.sub(
        r"[^a-zA-Z0-9_.:@-]+", "_", (user_id or "").strip()
    )[:128]
    if normalized_user:
        keys.append(f"user:{normalized_user}")
    return keys


@dataclass(slots=True)
class _Window:
    started_at: float
    count: int


class FixedWindowRateLimiter:
    """Small in-process limiter suitable for the single Python backend."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(1.0, window_seconds)
        self._windows: dict[str, _Window] = {}
        self._lock = threading.Lock()
        self._checks = 0

    def check(self, keys: list[str]) -> None:
        now = time.monotonic()
        unique_keys = list(dict.fromkeys(keys))
        with self._lock:
            self._checks += 1
            windows: dict[str, _Window] = {}
            for key in unique_keys:
                window = self._windows.get(key)
                if window is None or now - window.started_at >= self.window_seconds:
                    window = _Window(started_at=now, count=0)
                    self._windows[key] = window
                windows[key] = window

            blocked = [
                window for window in windows.values() if window.count >= self.limit
            ]
            if blocked:
                retry_after = min(
                    max(
                        1,
                        int(
                            round(
                                self.window_seconds - (now - window.started_at)
                            )
                        ),
                    )
                    for window in blocked
                )
                raise RateLimitExceeded(retry_after)

            for window in windows.values():
                window.count += 1

            if self._checks % 256 == 0:
                expired = [
                    key
                    for key, window in self._windows.items()
                    if now - window.started_at >= self.window_seconds
                ]
                for key in expired:
                    self._windows.pop(key, None)


class SearchSecurity:
    """Shared fail-closed guard used by both HTTP server adapters."""

    def __init__(self, config: SecurityConfig | None = None) -> None:
        self.config = config or get_config().security
        self.rate_limiter = FixedWindowRateLimiter(
            self.config.rate_limit_requests,
            self.config.rate_limit_window_seconds,
        )
        self._semaphore = threading.BoundedSemaphore(
            self.config.max_concurrent_searches
        )
        self._active = 0
        self._active_lock = threading.Lock()

    @property
    def proxy_token_configured(self) -> bool:
        return len(self.config.backend_proxy_token) >= 32

    def authorize(self, authorization: str | None) -> None:
        expected_token = self.config.backend_proxy_token
        if not self.proxy_token_configured:
            raise SecurityConfigurationError(
                "BACKEND_PROXY_TOKEN 未配置或长度不足 32 个字符，"
                "搜索接口已安全关闭。"
            )
        scheme, _, supplied = (authorization or "").partition(" ")
        if (
            scheme.casefold() != "bearer"
            or not supplied
            or not hmac.compare_digest(supplied.strip(), expected_token)
        ):
            raise AuthenticationError("缺少或无效的后端代理凭据。")

    def origin_allowed(self, origin: str | None) -> bool:
        if not origin:
            return True
        normalized = origin.strip().rstrip("/")
        return normalized in self.config.cors_allowed_origins

    @contextlib.contextmanager
    def admit(self, identity_keys: list[str]) -> Iterator[None]:
        self.rate_limiter.check(identity_keys)
        if not self._semaphore.acquire(blocking=False):
            raise ConcurrencyLimitExceeded("实时搜索并发已达上限。")
        with self._active_lock:
            self._active += 1
        try:
            yield
        finally:
            with self._active_lock:
                self._active -= 1
            self._semaphore.release()

    def status(self) -> dict[str, object]:
        with self._active_lock:
            active = self._active
        return {
            "proxyTokenConfigured": self.proxy_token_configured,
            "corsAllowedOrigins": list(self.config.cors_allowed_origins),
            "rateLimitRequests": self.config.rate_limit_requests,
            "rateLimitWindowSeconds": self.config.rate_limit_window_seconds,
            "maxConcurrentSearches": self.config.max_concurrent_searches,
            "activeSearches": active,
        }
