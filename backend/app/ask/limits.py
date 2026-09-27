import math
import time
from collections.abc import Callable
from threading import Lock

from app.errors import ApiError


class TokenBucket:
    """Process-local per-key token bucket; keys are organisation ids of valid tokens only."""

    def __init__(
        self,
        capacity: int,
        per_seconds: float,
        purpose: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.capacity = capacity
        self.rate = capacity / per_seconds
        self.purpose = purpose
        self.clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = Lock()

    def take(self, key: str) -> None:
        with self._lock:
            now = self.clock()
            tokens, updated = self._buckets.get(key, (float(self.capacity), now))
            tokens = min(float(self.capacity), tokens + (now - updated) * self.rate)
            if tokens < 1:
                self._buckets[key] = (tokens, now)
                wait = math.ceil((1 - tokens) / self.rate)
                raise ApiError(
                    429,
                    "rate_limited",
                    f"Too many {self.purpose} for this assistant. Try again in {wait} seconds.",
                )
            self._buckets[key] = (tokens - 1, now)
