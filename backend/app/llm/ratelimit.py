"""Async token-bucket rate limiter to stay inside free LLM quotas.

Refills ``rate_per_minute`` tokens evenly over each minute; ``acquire`` waits
until a token is available. Shared across all callers so bursts of concurrent
requests (e.g. best-of-N tailoring) don't trip provider 429s.
"""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    def __init__(self, rate_per_minute: int) -> None:
        self.rate_per_minute = max(1, rate_per_minute)
        self._capacity = float(self.rate_per_minute)
        self._tokens = float(self.rate_per_minute)
        self._refill_per_sec = self.rate_per_minute / 60.0
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_per_sec)
            self._updated = now

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = 1.0 - self._tokens
                wait = deficit / self._refill_per_sec
            await asyncio.sleep(min(wait, 5.0))
