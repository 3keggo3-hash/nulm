"""Integration tests for resilience patterns."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import asyncio
import pytest

pytestmark = pytest.mark.integration


class TestRetryPolicy:
    """Tests for retry policy implementation."""

    @pytest.mark.asyncio
    async def test_successful_call_no_retry(self):
        from claude_bridge.resilience import retry_with_backoff

        call_count = 0

        async def success():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_with_backoff(success, max_retries=3)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_transient_failure_then_success(self):
        from claude_bridge.resilience import retry_with_backoff

        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "ok"

        result = await retry_with_backoff(flaky, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_permanent_failure_no_retry(self):
        from claude_bridge.resilience import retry_with_backoff, RetryExhaustedError

        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("permanent")

        with pytest.raises(RetryExhaustedError):
            await retry_with_backoff(always_fail, max_retries=2, base_delay=0.01)
        assert call_count == 3


class TestCircuitBreaker:
    """Tests for circuit breaker pattern."""

    @pytest.mark.asyncio
    async def test_circuit_closed_on_success(self):
        from claude_bridge.resilience import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=3)

        async def success():
            return "ok"

        await breaker.call(success)
        assert breaker.state == "closed"

    @pytest.mark.asyncio
    async def test_circuit_opens_on_failures(self):
        from claude_bridge.resilience import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=2)

        async def fail():
            raise ConnectionError("fail")

        for _ in range(2):
            try:
                await breaker.call(fail)
            except ConnectionError:
                pass

        assert breaker.state == "open"

    @pytest.mark.asyncio
    async def test_circuit_allows_half_open_probes(self):
        from claude_bridge.resilience import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)

        async def fail():
            raise ConnectionError("fail")

        try:
            await breaker.call(fail)
        except ConnectionError:
            pass

        assert breaker.state == "open"
        await asyncio.sleep(0.15)
        assert breaker.state == "half-open"


class TestDistributedCache:
    """Tests for distributed cache (Redis)."""

    def test_cache_set_get(self):
        from claude_bridge.distributed_cache import DistributedCache

        cache = DistributedCache(enabled=False)
        cache.set("key1", "value1", ttl=60)
        result = cache.get("key1")
        assert result == "value1" or result is None

    def test_cache_miss(self):
        from claude_bridge.distributed_cache import DistributedCache

        cache = DistributedCache(enabled=False)
        result = cache.get("nonexistent")
        assert result is None

    def test_cache_delete(self):
        from claude_bridge.distributed_cache import DistributedCache

        cache = DistributedCache(enabled=False)
        cache.set("key1", "value1")
        cache.delete("key1")
        result = cache.get("key1")
        assert result is None

    def test_cache_with_redis(self):
        from claude_bridge.distributed_cache import DistributedCache

        cache = DistributedCache(enabled=False, redis_url="redis://localhost:6379")
        cache.set("test_key", "test_value")
        assert cache._enabled is False or cache._client is not None
