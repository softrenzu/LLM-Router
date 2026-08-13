"""Small in-process circuit breaker; upstream load balancers remain supported."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class _CircuitState:
    failures: int = 0
    open_until: float = 0.0


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_seconds: int = 30) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._states: dict[str, _CircuitState] = {}
        self._lock = threading.Lock()

    def allow(self, model_id: str) -> bool:
        with self._lock:
            state = self._states.setdefault(model_id, _CircuitState())
            if state.open_until <= time.monotonic():
                if state.open_until:
                    state.failures = 0
                    state.open_until = 0.0
                return True
            return False

    def success(self, model_id: str) -> None:
        with self._lock:
            self._states[model_id] = _CircuitState()

    def failure(self, model_id: str) -> None:
        with self._lock:
            state = self._states.setdefault(model_id, _CircuitState())
            state.failures += 1
            if state.failures >= self.failure_threshold:
                state.open_until = time.monotonic() + self.recovery_seconds

    def snapshot(self) -> dict[str, dict[str, float | int | bool]]:
        now = time.monotonic()
        with self._lock:
            return {
                model_id: {
                    "failures": state.failures,
                    "open": state.open_until > now,
                    "retry_after_seconds": max(0.0, state.open_until - now),
                }
                for model_id, state in self._states.items()
            }

