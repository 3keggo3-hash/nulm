"""Lifecycle management for Claude Bridge: graceful shutdown and signal handling."""

from __future__ import annotations

import asyncio
import signal
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class LifecycleState(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass
class LifecycleHooks:
    on_startup: list[Callable[[], Any]] = field(default_factory=list)
    on_shutdown: list[Callable[[], Any]] = field(default_factory=list)
    on_health_check: list[Callable[[], bool]] = field(default_factory=list)


class LifecycleManager:
    def __init__(self, hooks: LifecycleHooks | None = None) -> None:
        self._state = LifecycleState.STARTING
        self._hooks = hooks or LifecycleHooks()
        self._shutdown_event = asyncio.Event()
        self._lock = threading.Lock()
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._shutdown_timeout: float = 30.0

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

    def start(self) -> None:
        with self._lock:
            if self._state != LifecycleState.STARTING:
                return
            self._started_at = time.time()
            self._state = LifecycleState.RUNNING
        for hook in self._hooks.on_startup:
            try:
                hook()
            except Exception:
                pass

    def stop(self, timeout: float | None = None) -> None:
        if timeout is None:
            timeout = self._shutdown_timeout
        with self._lock:
            if self._state == LifecycleState.STOPPED:
                return
            self._state = LifecycleState.STOPPING
        for hook in self._hooks.on_shutdown:
            try:
                result = hook()
                if asyncio.iscoroutine(result):
                    asyncio.run(result)
            except Exception:
                pass
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
    def __init__(self, lifecycle: LifecycleManager | None = None) -> None:
        self._lifecycle = lifecycle or LifecycleManager()
        self._tasks: list[asyncio.Task[Any]] = []
        self._shutdown_timeout: float = 30.0

    @property
    def lifecycle(self) -> LifecycleManager:
        return self._lifecycle

    def start(self) -> None:
        self._lifecycle.start()
        setup_signal_handlers(self._lifecycle)

    async def stop(self) -> None:
        self._lifecycle.stop()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def register_task(self, task: asyncio.Task[Any]) -> None:
        self._tasks.append(task)

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
