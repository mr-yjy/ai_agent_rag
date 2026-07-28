"""Request-scoped deadline, cancellation, and stage timing controls.

Every live-search operation shares one monotonic deadline.  The object is
thread-safe because OpenAlex and Semantic Scholar run in worker threads, while
``contextvars`` make the same budget visible to nested LLM calls.
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field


class SearchDeadlineExceeded(TimeoutError):
    """Raised before a stage would exceed the request's remaining budget."""

    def __init__(self, stage: str, remaining_ms: int = 0) -> None:
        super().__init__(f"Search deadline exhausted before stage: {stage}")
        self.stage = stage
        self.remaining_ms = max(0, remaining_ms)


class SearchCancelled(RuntimeError):
    """Raised when the caller has cancelled a search request."""

    def __init__(self, stage: str) -> None:
        super().__init__(f"Search cancelled before stage: {stage}")
        self.stage = stage


DEFAULT_STAGE_LIMITS_SECONDS: dict[str, float] = {
    "auth_queue": 1.0,
    "query_understanding": 8.0,
    "subquery_generation": 2.0,
    "openalex_retrieval": 15.0,
    "semantic_scholar_retrieval": 15.0,
    "candidate_merge": 5.0,
    "llm_selector": 6.0,
    "citation_expansion": 10.0,
    "iterative_query_generation": 4.0,
    "llm_rerank": 8.0,
    "counterfactual_verification": 4.0,
    "causal_trust_calibration": 16.0,
    "causal_trust_recovery": 12.0,
    "response_assembly": 2.0,
}


@dataclass(slots=True)
class SearchDeadline:
    """One total deadline shared by every stage of a search request."""

    request_id: str
    total_seconds: float = 50.0
    stage_limits_seconds: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_STAGE_LIMITS_SECONDS)
    )
    cancel_event: threading.Event | None = None
    started_at: float = field(default_factory=time.monotonic)
    _stage_timings_ms: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stop_reason: str = ""

    @property
    def deadline_at(self) -> float:
        return self.started_at + max(0.05, self.total_seconds)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline_at - time.monotonic())

    @property
    def remaining_ms(self) -> int:
        return max(0, int(self.remaining_seconds * 1000))

    @property
    def elapsed_ms(self) -> int:
        return max(0, int((time.monotonic() - self.started_at) * 1000))

    @property
    def cancelled(self) -> bool:
        return bool(self.cancel_event and self.cancel_event.is_set())

    @property
    def stop_reason(self) -> str:
        with self._lock:
            return self._stop_reason

    def set_stop_reason(self, reason: str) -> None:
        if not reason:
            return
        with self._lock:
            if not self._stop_reason:
                self._stop_reason = reason

    def ensure_available(
        self,
        stage: str,
        *,
        minimum_seconds: float = 0.05,
        reserve_seconds: float = 0.0,
    ) -> None:
        if self.cancelled:
            self.set_stop_reason("client_cancelled")
            raise SearchCancelled(stage)
        stage_deadline_at = _CURRENT_STAGE_DEADLINE_AT.get()
        stage_remaining = (
            max(0.0, stage_deadline_at - time.monotonic())
            if stage_deadline_at is not None and current_stage() == stage
            else self.remaining_seconds
        )
        if min(self.remaining_seconds, stage_remaining) <= (
            minimum_seconds + reserve_seconds
        ):
            self.set_stop_reason("deadline_exhausted")
            raise SearchDeadlineExceeded(stage, self.remaining_ms)

    def can_start(
        self,
        stage: str,
        *,
        minimum_seconds: float = 0.25,
        reserve_seconds: float = 0.0,
    ) -> bool:
        try:
            self.ensure_available(
                stage,
                minimum_seconds=minimum_seconds,
                reserve_seconds=reserve_seconds,
            )
        except (SearchDeadlineExceeded, SearchCancelled):
            return False
        return True

    def timeout_for(
        self,
        stage: str,
        requested_seconds: float,
        *,
        reserve_seconds: float = 0.1,
        minimum_seconds: float = 0.05,
    ) -> float:
        """Return a timeout capped by both stage and request budgets."""
        self.ensure_available(
            stage,
            minimum_seconds=minimum_seconds,
            reserve_seconds=reserve_seconds,
        )
        stage_limit = self.stage_limits_seconds.get(
            stage, max(minimum_seconds, requested_seconds)
        )
        stage_deadline_at = _CURRENT_STAGE_DEADLINE_AT.get()
        stage_available = (
            max(0.0, stage_deadline_at - time.monotonic())
            if stage_deadline_at is not None and current_stage() == stage
            else self.remaining_seconds
        )
        available = min(self.remaining_seconds, stage_available) - reserve_seconds
        timeout = min(
            max(minimum_seconds, requested_seconds),
            max(minimum_seconds, stage_limit),
            max(minimum_seconds, available),
        )
        return max(minimum_seconds, timeout)

    def can_wait(self, seconds: float, *, reserve_seconds: float = 0.1) -> bool:
        stage_deadline_at = _CURRENT_STAGE_DEADLINE_AT.get()
        stage_remaining = (
            max(0.0, stage_deadline_at - time.monotonic())
            if stage_deadline_at is not None
            else self.remaining_seconds
        )
        return (
            not self.cancelled
            and seconds >= 0
            and seconds + reserve_seconds
            < min(self.remaining_seconds, stage_remaining)
        )

    def add_stage_timing(self, stage: str, elapsed_ms: int) -> None:
        with self._lock:
            self._stage_timings_ms[stage] = (
                self._stage_timings_ms.get(stage, 0) + max(0, elapsed_ms)
            )

    def stage_timings(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._stage_timings_ms.items()))

    @contextlib.contextmanager
    def measure(
        self,
        stage: str,
        *,
        minimum_seconds: float = 0.05,
        reserve_seconds: float = 0.0,
    ) -> Iterator[None]:
        self.ensure_available(
            stage,
            minimum_seconds=minimum_seconds,
            reserve_seconds=reserve_seconds,
        )
        started = time.perf_counter()
        token = _CURRENT_STAGE.set(stage)
        stage_deadline_token = _CURRENT_STAGE_DEADLINE_AT.set(
            min(
                self.deadline_at,
                time.monotonic()
                + self.stage_limits_seconds.get(stage, self.total_seconds),
            )
        )
        try:
            yield
        finally:
            _CURRENT_STAGE_DEADLINE_AT.reset(stage_deadline_token)
            _CURRENT_STAGE.reset(token)
            self.add_stage_timing(
                stage,
                int((time.perf_counter() - started) * 1000),
            )


_CURRENT_DEADLINE: contextvars.ContextVar[SearchDeadline | None] = (
    contextvars.ContextVar("scholarpilot_search_deadline", default=None)
)
_CURRENT_STAGE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "scholarpilot_search_stage", default=""
)
_CURRENT_STAGE_DEADLINE_AT: contextvars.ContextVar[float | None] = (
    contextvars.ContextVar(
        "scholarpilot_search_stage_deadline_at",
        default=None,
    )
)


def current_deadline() -> SearchDeadline | None:
    return _CURRENT_DEADLINE.get()


def current_stage(default: str = "query_understanding") -> str:
    return _CURRENT_STAGE.get() or default


@contextlib.contextmanager
def bind_deadline(deadline: SearchDeadline) -> Iterator[SearchDeadline]:
    token = _CURRENT_DEADLINE.set(deadline)
    try:
        yield deadline
    finally:
        _CURRENT_DEADLINE.reset(token)


@contextlib.contextmanager
def stage_context(stage: str) -> Iterator[None]:
    token = _CURRENT_STAGE.set(stage)
    try:
        yield
    finally:
        _CURRENT_STAGE.reset(token)
