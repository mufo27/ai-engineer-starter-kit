"""Per-provider circuit breaker.

Prevents hammering a failing/degraded provider. States:
  closed    -> normal; failures counted.
  open      -> reject immediately (fail fast) for `recovery_timeout`.
  half_open -> allow a probe request; success closes, failure re-opens.

This is a lightweight in-process implementation. For multi-replica deployments
back it with Redis (see ARCHITECTURE.md "Scaling path").
"""
from __future__ import annotations

import threading
import time
from enum import StrEnum


class State(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = State.CLOSED
        self._failure_count = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> State:
        with self._lock:
            if self._state is State.OPEN and (time.monotonic() - self._opened_at) >= self.recovery_timeout:
                self._state = State.HALF_OPEN
            return self._state

    def allow(self) -> bool:
        s = self.state
        return s in (State.CLOSED, State.HALF_OPEN)

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state = State.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold or self._state is State.HALF_OPEN:
                self._state = State.OPEN
                self._opened_at = time.monotonic()

    def snapshot(self) -> dict:
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "threshold": self.failure_threshold,
        }


class BreakerRegistry:
    """One breaker per provider name."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._ft = failure_threshold
        self._rt = recovery_timeout
        self._lock = threading.Lock()

    def get(self, provider: str) -> CircuitBreaker:
        with self._lock:
            if provider not in self._breakers:
                self._breakers[provider] = CircuitBreaker(self._ft, self._rt)
            return self._breakers[provider]

    def snapshot_all(self) -> dict[str, dict]:
        return {name: b.snapshot() for name, b in self._breakers.items()}
