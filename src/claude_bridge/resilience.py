"""Resilience patterns for Claude Bridge: retry, circuit breaker, and error handling."""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class RetryExhaustedError(Exception):
    pass


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    retryable_exceptions: tuple[type[Exception], ...] = (ConnectionError, TimeoutError, OSError)


def _compute_delay(config: RetryConfig, attempt: int) -> float:
    delay = config.base_delay * (config.exponential_base ** (attempt - 1))
    return min(delay, config.max_delay)


async def retry_with_backoff(
    func: Callable[..., Any],
    *args: Any,
    config: RetryConfig | None = None,
    max_retries: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    exponential_base: float | None = None,
    retryable_exceptions: tuple[type[Exception], ...] | None = None,
    **kwargs: Any,
) -> Any:
    if config is None:
        config = RetryConfig()
    overrides: dict[str, Any] = {}
    if max_retries is not None:
        overrides["max_retries"] = max_retries
    if base_delay is not None:
        overrides["base_delay"] = base_delay
    if max_delay is not None:
        overrides["max_delay"] = max_delay
    if exponential_base is not None:
        overrides["exponential_base"] = exponential_base
    if retryable_exceptions is not None:
        overrides["retryable_exceptions"] = retryable_exceptions
    if overrides:
        config = replace(config, **overrides)
    last_exception: Exception | None = None
    for attempt in range(1, config.max_retries + 2):
        try:
            if inspect.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            return result
        except config.retryable_exceptions as e:
            last_exception = e
            if attempt <= config.max_retries:
                delay = _compute_delay(config, attempt)
                await asyncio.sleep(delay)
    if last_exception is not None:
        raise RetryExhaustedError(
            f"Retry exhausted after {config.max_retries} attempts"
        ) from last_exception
    raise RetryExhaustedError("Retry exhausted with no exception")


class CircuitState(str):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    success_threshold: int = 2
    recovery_timeout: float = 60.0
    half_open_max_calls: int = 3


class CircuitBreaker:
    def __init__(
        self,
        config: CircuitBreakerConfig | None = None,
        *,
        failure_threshold: int | None = None,
        success_threshold: int | None = None,
        recovery_timeout: float | None = None,
        half_open_max_calls: int | None = None,
    ) -> None:
        if config is None:
            config = CircuitBreakerConfig()
        overrides: dict[str, Any] = {}
        if failure_threshold is not None:
            overrides["failure_threshold"] = failure_threshold
        if success_threshold is not None:
            overrides["success_threshold"] = success_threshold
        if recovery_timeout is not None:
            overrides["recovery_timeout"] = recovery_timeout
        if half_open_max_calls is not None:
            overrides["half_open_max_calls"] = half_open_max_calls
        if overrides:
            config = replace(config, **overrides)
        self._config = config
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._evaluate_state()

    def _evaluate_state(self) -> str:
        if self._state == CircuitState.OPEN:
            if self._last_failure_time is not None:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self._config.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    self._success_count = 0
        return self._state

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            current_state = self._evaluate_state()
            if current_state == CircuitState.OPEN:
                raise RuntimeError("Circuit breaker is OPEN")
            if current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._config.half_open_max_calls:
                    raise RuntimeError("Circuit breaker is HALF-OPEN, max calls reached")
                self._half_open_calls += 1
        try:
            if inspect.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e

    def _on_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitState.CLOSED:
                self._failure_count = max(0, self._failure_count - 1)

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._half_open_calls = 0
            elif self._failure_count >= self._config.failure_threshold:
                self._state = CircuitState.OPEN

    def reset(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            self._half_open_calls = 0

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._evaluate_state(),
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "last_failure_time": self._last_failure_time,
            }


@dataclass
class RateLimitConfig:
    max_calls: int = 60
    window_seconds: float = 60.0


class RateLimiter:
    def __init__(self, config: RateLimitConfig | None = None) -> None:
        if config is None:
            config = RateLimitConfig()
        self._config = config
        self._calls: list[float] = []
        self._lock = threading.Lock()

    def is_allowed(self) -> bool:
        with self._lock:
            now = time.time()
            cutoff = now - self._config.window_seconds
            self._calls = [t for t in self._calls if t > cutoff]
            if len(self._calls) < self._config.max_calls:
                self._calls.append(now)
                return True
            return False

    def wait_time(self) -> float:
        with self._lock:
            if not self._calls:
                return 0.0
            now = time.time()
            cutoff = now - self._config.window_seconds
            recent = [t for t in self._calls if t > cutoff]
            if len(recent) < self._config.max_calls:
                return 0.0
            oldest = min(recent)
            return max(0.0, (oldest + self._config.window_seconds) - now)

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()
