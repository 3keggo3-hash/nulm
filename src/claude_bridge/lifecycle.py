"""Lifecycle management for Claude Bridge: graceful shutdown and signal handling."""

from __future__ import annotations

import asyncio
import logging
import signal
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class LifecycleState(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass
class LifecycleHooks:
    on_startup: list[Callable[[], Any]] = field(default_factory=list)
    on_shutdown: list[Callable[[], Any]] = field(default_factory=list)
    on_health_check: list[Callable[[], bool]] = field(default_factory=list)
    on_cleanup: list[Callable[[], Any]] = field(default_factory=list)


@dataclass
class HookResult:
    success: bool
    error: str | None = None
    duration: float = 0.0


class LifecycleManager:
    def __init__(self, hooks: LifecycleHooks | None = None) -> None:
        self._state = LifecycleState.STARTING
        self._hooks = hooks or LifecycleHooks()
        self._shutdown_event = asyncio.Event()
        self._lock = threading.Lock()
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._shutdown_timeout: float = 30.0
        self._startup_timeout: float = 30.0
        self._health_check_timeout: float = 5.0
        self._hook_results: list[HookResult] = []

    @property
    def state(self) -> LifecycleState:
        with self._lock:
            return self._state

    @property
    def uptime(self) -> float | None:
        if self._started_at is None:
            return None
        if self._stopped_at is not None:
            return self._stopped_at - self._started_at
        return time.time() - self._started_at

    @property
    def hook_results(self) -> list[HookResult]:
        return self._hook_results.copy()

    def _execute_hook_with_timeout(
        self,
        hook: Callable[[], Any],
        timeout: float,
    ) -> HookResult:
        start = time.time()
        try:
            result = hook()
            if asyncio.iscoroutine(result):
                result = asyncio.wait_for(asyncio.shield(result), timeout=timeout)
            duration = time.time() - start
            return HookResult(success=True, duration=duration)
        except asyncio.TimeoutError:
            duration = time.time() - start
            return HookResult(success=False, error="Hook timed out", duration=duration)
        except Exception as e:
            duration = time.time() - start
            return HookResult(success=False, error=str(e), duration=duration)

    def _execute_hooks(
        self,
        hooks: list[Callable[[], Any]],
        timeout: float,
    ) -> list[HookResult]:
        results = []
        for hook in hooks:
            result = self._execute_hook_with_timeout(hook, timeout)
            results.append(result)
            if not result.success:
                logger.warning("Hook %s failed: %s", hook, result.error)
        return results

    def start(self, timeout: float | None = None) -> None:
        if timeout is None:
            timeout = self._startup_timeout
        with self._lock:
            if self._state not in (LifecycleState.STARTING, LifecycleState.STOPPED):
                return
            self._state = LifecycleState.STARTING
        self._started_at = time.time()
        self._hook_results = self._execute_hooks(self._hooks.on_startup, timeout)
        failed_startup = [r for r in self._hook_results if not r.success]
        with self._lock:
            if failed_startup:
                self._state = LifecycleState.DEGRADED
                logger.warning(
                    "Lifecycle started in degraded state: %d/%d hooks failed",
                    len(failed_startup),
                    len(self._hook_results),
                )
            else:
                self._state = LifecycleState.RUNNING

    def health_check(self, timeout: float | None = None) -> bool:
        if timeout is None:
            timeout = self._health_check_timeout
        if self._state not in (LifecycleState.RUNNING, LifecycleState.DEGRADED):
            return False
        if not self._hooks.on_health_check:
            return True
        results = self._execute_hooks(self._hooks.on_health_check, timeout)
        return all(r.success for r in results)

    def stop(self, timeout: float | None = None) -> None:
        if timeout is None:
            timeout = self._shutdown_timeout
        with self._lock:
            if self._state == LifecycleState.STOPPED:
                return
            self._state = LifecycleState.STOPPING
        self._hook_results = self._execute_hooks(self._hooks.on_shutdown, timeout)
        self._shutdown_event.set()
        with self._lock:
            self._stopped_at = time.time()
            self._state = LifecycleState.STOPPED

    async def stop_async(self, timeout: float | None = None) -> None:
        if timeout is None:
            timeout = self._shutdown_timeout
        with self._lock:
            if self._state == LifecycleState.STOPPED:
                return
            self._state = LifecycleState.STOPPING
        results: list[HookResult] = []
        for hook in self._hooks.on_shutdown:
            result = self._execute_hook_with_timeout(hook, timeout)
            results.append(result)
            if not result.success:
                logger.warning("Shutdown hook %s failed: %s", hook, result.error)
        self._hook_results = results
        await asyncio.sleep(0)
        self._shutdown_event.set()
        with self._lock:
            self._stopped_at = time.time()
            self._state = LifecycleState.STOPPED

    async def wait_for_shutdown(self) -> None:
        await self._shutdown_event.wait()

    def is_running(self) -> bool:
        with self._lock:
            return self._state == LifecycleState.RUNNING

    def is_stopping(self) -> bool:
        with self._lock:
            return self._state == LifecycleState.STOPPING

    def is_degraded(self) -> bool:
        with self._lock:
            return self._state == LifecycleState.DEGRADED


_SHUTDOWN_HANDLERS: list[Callable[[], None]] = []


def register_shutdown_handler(handler: Callable[[], None]) -> None:
    _SHUTDOWN_HANDLERS.append(handler)


def _default_signal_handler(signum: int, frame: Any) -> None:
    for handler in _SHUTDOWN_HANDLERS:
        try:
            handler()
        except Exception:
            pass


def setup_signal_handlers(lifecycle: LifecycleManager) -> None:
    def handle_signal(signum: int, frame: Any) -> None:
        lifecycle.stop()

    if signal.signal is not None:
        try:
            signal.signal(signal.SIGTERM, handle_signal)
        except (ValueError, OSError):
            pass
        try:
            signal.signal(signal.SIGINT, handle_signal)
        except (ValueError, OSError):
            pass


class GracefulServer:
    def __init__(
        self,
        lifecycle: LifecycleManager | None = None,
        task_timeout: float = 30.0,
    ) -> None:
        self._lifecycle = lifecycle or LifecycleManager()
        self._tasks: list[asyncio.Task[Any]] = []
        self._task_timeout: float = task_timeout

    @property
    def lifecycle(self) -> LifecycleManager:
        return self._lifecycle

    def start(self) -> None:
        self._lifecycle.start()
        setup_signal_handlers(self._lifecycle)

    async def stop(self, timeout: float | None = None) -> None:
        if timeout is None:
            timeout = self._task_timeout
        self._lifecycle.stop()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("Task cleanup timed out after %.1fs", timeout)
        self._tasks.clear()
        for hook in self._lifecycle._hooks.on_cleanup:
            try:
                result = hook()
                if asyncio.iscoroutine(result):
                    asyncio.run(result)
            except Exception:
                pass

    def register_task(self, task: asyncio.Task[Any]) -> None:
        self._tasks.append(task)

    def register_tasks(self, tasks: list[asyncio.Task[Any]]) -> None:
        self._tasks.extend(tasks)

    async def run(self, coro: Any) -> Any:
        self.start()
        try:
            return await coro
        finally:
            await self.stop()


_GLOBAL_LIFECYCLE: LifecycleManager | None = None
_LIFECYCLE_LOCK = threading.Lock()


def get_lifecycle_manager() -> LifecycleManager:
    global _GLOBAL_LIFECYCLE
    with _LIFECYCLE_LOCK:
        if _GLOBAL_LIFECYCLE is None:
            _GLOBAL_LIFECYCLE = LifecycleManager()
        return _GLOBAL_LIFECYCLE


def reset_lifecycle_manager() -> None:
    global _GLOBAL_LIFECYCLE
    with _LIFECYCLE_LOCK:
        if _GLOBAL_LIFECYCLE is not None:
            _GLOBAL_LIFECYCLE.stop()
        _GLOBAL_LIFECYCLE = None
