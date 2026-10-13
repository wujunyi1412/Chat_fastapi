from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class LoginRateLimiter:
    """Small in-memory limiter suitable for the documented single-process deployment."""

    def __init__(self, max_attempts: int = 8, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, values: deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while values and values[0] <= cutoff:
            values.popleft()

    def allowed(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            values = self._attempts[key]
            self._trim(values, now)
            return len(values) < self.max_attempts

    def failed(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            values = self._attempts[key]
            self._trim(values, now)
            values.append(now)

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


login_limiter = LoginRateLimiter()

