import time

import pytest

from app.llm.ratelimit import TokenBucket


@pytest.mark.asyncio
async def test_initial_capacity_is_immediate():
    bucket = TokenBucket(rate_per_minute=60)
    start = time.monotonic()
    # Bucket starts full, so the first few acquires should not block meaningfully.
    for _ in range(5):
        await bucket.acquire()
    assert time.monotonic() - start < 0.5


@pytest.mark.asyncio
async def test_blocks_when_exhausted():
    # 60/min = 1 token/sec; capacity 1 after draining forces a wait.
    bucket = TokenBucket(rate_per_minute=60)
    bucket._tokens = 0.0  # drain
    start = time.monotonic()
    await bucket.acquire()
    assert time.monotonic() - start >= 0.4
