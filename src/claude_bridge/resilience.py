"""Resilience patterns for Nulm: retry, circuit breaker, and error handling."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import asyncio
import inspect
import random
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class RetryExhaustedError(Exception):
    pass


class CircuitOpenError(RuntimeError):
    pass


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: float = 0.1
    retryable_exceptions: tuple[type[Exception], ...] = (ConnectionError, TimeoutError, OSError)
    total_timeout: float | None = None
    on_retry: Callable[[Exception, int], None] | None = None


def _compute_delay(config: RetryConfig, attempt: int) -> float:
    delay = config.base_delay * (config.exponential_base ** (attempt - 1))
    delay = min(delay, config.max_delay)
    if config.jitter > 0:
        jitter_range = delay * config.jitter
        delay += random.uniform(-jitter_range, jitter_range)
    return max(0.0, delay)


async def retry_with_backoff(
    func: Callable[..., Any],
    *args: Any,
    config: RetryConfig | None = None,
    max_retries: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    exponential_base: float | None = None,
    retryable_exceptions: tuple[type[Exception], ...] | None = None,
    jitter: float | None = None,
    total_timeout: float | None = None,
    on_retry: Callable[[Exception, int], None] | None = None,
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
    if jitter is not None:
        overrides["jitter"] = jitter
    if total_timeout is not None:
        overrides["total_timeout"] = total_timeout
    if on_retry is not None:
        overrides["on_retry"] = on_retry
    if overrides:
        config = replace(config, **overrides)
    last_exception: Exception | None = None
    start_time = time.monotonic()
    for attempt in range(1, config.max_retries + 2):
        if config.total_timeout is not None:
            elapsed = time.monotonic() - start_time
            if elapsed >= config.total_timeout:
                raise RetryExhaustedError(
                    f"Retry timeout exceeded after {elapsed:.2f}s. "
                    f"Consider increasing total_timeout."
                )
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
                if config.on_retry is not None:
                    config.on_retry(e, attempt)
                await asyncio.sleep(delay)
    if last_exception is not None:
        hint = (
            " Consider increasing max_retries, using a higher base_delay, "
            "or checking if the service is reachable."
        )
        raise RetryExhaustedError(
            f"Retry exhausted after {config.max_retries} attempts. Last error: {last_exception}"
            f"{hint}"
        ) from last_exception
    raise RetryExhaustedError(
        "Retry exhausted with no exception. "
        "Ensure your async function is properly awaited or check retry configuration."
    )


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
    reset_timeout: float | None = None
    excluded_exceptions: tuple[type[Exception], ...] = ()
    on_state_change: Callable[[str, str], None] | None = None


class CircuitBreaker:
    def __init__(
        self,
        config: CircuitBreakerConfig | None = None,
        *,
        failure_threshold: int | None = None,
        success_threshold: int | None = None,
        recovery_timeout: float | None = None,
        half_open_max_calls: int | None = None,
        reset_timeout: float | None = None,
        excluded_exceptions: tuple[type[Exception], ...] | None = None,
        on_state_change: Callable[[str, str], None] | None = None,
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
        if reset_timeout is not None:
            overrides["reset_timeout"] = reset_timeout
        if excluded_exceptions is not None:
            overrides["excluded_exceptions"] = excluded_exceptions
        if on_state_change is not None:
            overrides["on_state_change"] = on_state_change
        if overrides:
            config = replace(config, **overrides)
        self._config = config
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._total_calls = 0
        self._total_failures = 0
        self._last_success_time: float | None = None
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

    def _transition_to(self, new_state: str) -> None:
        old_state = self._state
        self._state = new_state
        if self._config.on_state_change is not None and old_state != new_state:
            self._config.on_state_change(old_state, new_state)

    async def call(
        self,
        func: Callable[..., Any],
        *args: Any,
        fallback_func: Callable[..., Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        with self._lock:
            current_state = self._evaluate_state()
            if current_state == CircuitState.OPEN:
                recovery = self._config.recovery_timeout
                if fallback_func is not None:
                    pass
                else:
                    raise CircuitOpenError(
                        f"Circuit breaker is OPEN. Service is temporarily unavailable. "
                        f"Retry after {recovery:.0f}s or reset the circuit breaker."
                    )
            if current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._config.half_open_max_calls:
                    raise CircuitOpenError(
                        f"Circuit breaker is HALF-OPEN (testing recovery). "
                        f"Max probe calls ({self._config.half_open_max_calls}) reached. "
                        f"Wait {self._config.recovery_timeout:.0f}s for full recovery."
                    )
                self._half_open_calls += 1
        self._total_calls += 1
        try:
            if inspect.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            if isinstance(e, self._config.excluded_exceptions):
                return None
            self._on_failure()
            if fallback_func is not None:
                if inspect.iscoroutinefunction(fallback_func):
                    return await fallback_func(*args, **kwargs)
                return fallback_func(*args, **kwargs)
            raise e

    def _on_success(self) -> None:
        with self._lock:
            self._last_success_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitState.CLOSED:
                self._failure_count = max(0, self._failure_count - 1)

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._total_failures += 1
            self._last_failure_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.OPEN)
                self._half_open_calls = 0
            elif self._failure_count >= self._config.failure_threshold:
                self._transition_to(CircuitState.OPEN)

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
                "last_success_time": self._last_success_time,
                "total_calls": self._total_calls,
                "total_failures": self._total_failures,
                "failure_rate": (
                    self._total_failures / self._total_calls if self._total_calls > 0 else 0.0
                ),
            }

    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        return self.state == CircuitState.HALF_OPEN


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
