"""AI response streaming support for Claude Bridge."""

from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, TypeVar

T = TypeVar("T")


class StreamChunk:
    def __init__(
        self,
        content: str = "",
        is_final: bool = False,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.content = content
        self.is_final = is_final
        self.error = error
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "is_final": self.is_final,
            "error": self.error,
            "metadata": self.metadata,
        }


class StreamHandler(ABC):
    @abstractmethod
    def on_chunk(self, chunk: StreamChunk) -> None:
        pass

    @abstractmethod
    def on_error(self, error: Exception) -> None:
        pass

    @abstractmethod
    def on_complete(self) -> None:
        pass


class SyncStreamHandler(StreamHandler):
    def __init__(self, callback: Callable[[StreamChunk], None] | None = None) -> None:
        self.callback = callback
        self.chunks: list[StreamChunk] = []
        self._lock = threading.Lock()

    def on_chunk(self, chunk: StreamChunk) -> None:
        with self._lock:
            self.chunks.append(chunk)
        if self.callback:
            self.callback(chunk)

    def on_error(self, error: Exception) -> None:
        pass

    def on_complete(self) -> None:
        pass

    def get_full_content(self) -> str:
        with self._lock:
            return "".join(c.content for c in self.chunks if not c.error)


class AsyncStreamHandler:
    def __init__(self, callback: Callable[[StreamChunk], Any] | None = None) -> None:
        self.callback = callback
        self.chunks: list[StreamChunk] = []
        self._lock = asyncio.Lock()
        self._complete = asyncio.Event()
        self._cancelled = False

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    async def on_chunk(self, chunk: StreamChunk) -> None:
        async with self._lock:
            self.chunks.append(chunk)
        if self.callback:
            result = self.callback(chunk)
            if asyncio.iscoroutine(result):
                await result

    async def on_error(self, error: Exception) -> None:
        async with self._lock:
            self.chunks.append(StreamChunk(error=str(error), is_final=True))
        self._complete.set()

    async def on_complete(self) -> None:
        async with self._lock:
            self.chunks.append(StreamChunk(is_final=True))
        self._complete.set()

    async def get_full_content(self) -> str:
        async with self._lock:
            return "".join(c.content for c in self.chunks if not c.error)

    async def wait_for_complete(self) -> None:
        await self._complete.wait()


@dataclass
class StreamingConfig:
    enabled: bool = True
    chunk_size: int = 64
    rate_limit_ms: int = 0
    buffer_size: int = 100


class StreamingResponse:
    def __init__(
        self,
        handler: StreamHandler,
        config: StreamingConfig | None = None,
    ) -> None:
        self.handler = handler
        self.config = config or StreamingConfig()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled


async def stream_async_generator(
    generator: AsyncGenerator[str, None],
    handler: AsyncStreamHandler,
    config: StreamingConfig | None = None,
) -> str:
    config = config or StreamingConfig()
    full_content = ""
    try:
        async for chunk in generator:
            if asyncio.get_event_loop().is_closed():
                break
            if handler.is_cancelled:
                break
            if config.rate_limit_ms > 0:
                await asyncio.sleep(config.rate_limit_ms / 1000.0)
            stream_chunk = StreamChunk(content=chunk)
            await handler.on_chunk(stream_chunk)
            full_content += chunk
        await handler.on_complete()
    except Exception as e:
        await handler.on_error(e)
    return full_content


def stream_sync_generator(
    generator: AsyncGenerator[str, None],
    handler: SyncStreamHandler,
    config: StreamingConfig | None = None,
) -> str:
    config = config or StreamingConfig()
    full_content = ""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def run() -> str:
                return await _stream_async_with_sync_handler(generator, handler, config)

            full_content = loop.run_until_complete(run())
        finally:
            loop.close()
    except Exception as e:
        handler.on_error(e)
    return full_content


async def _stream_async_with_sync_handler(
    generator: AsyncGenerator[str, None],
    handler: SyncStreamHandler,
    config: StreamingConfig | None,
) -> str:
    config = config or StreamingConfig()
    full_content = ""
    try:
        async for chunk in generator:
            if asyncio.get_event_loop().is_closed():
                break
            stream_chunk = StreamChunk(content=chunk)
            handler.on_chunk(stream_chunk)
            full_content += chunk
        handler.on_complete()
    except Exception as e:
        handler.on_error(e)
    return full_content


class AIStreamingProvider(ABC):
    @abstractmethod
    async def stream_complete(
        self,
        prompt: str,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        pass


@dataclass
class ChunkedStreamWriter:
    buffer: list[str] = field(default_factory=list)
    config: StreamingConfig | None = None

    def write(self, chunk: str) -> str:
        if not chunk:
            return ""
        self.buffer.append(chunk)
        if self.config and len(chunk) >= self.config.chunk_size:
            return self._flush_buffer()
        return ""

    def _flush_buffer(self) -> str:
        if not self.buffer:
            return ""
        result = "".join(self.buffer)
        self.buffer.clear()
        return result

    def finalize(self) -> str:
        return "".join(self.buffer)


async def wrap_streaming_provider(
    provider: AIStreamingProvider,
    prompt: str,
    handler: AsyncStreamHandler,
    config: StreamingConfig | None = None,
) -> dict[str, Any]:
    config = config or StreamingConfig()
    writer = ChunkedStreamWriter(config=config)
    full_content = ""
    try:
        async for chunk in await provider.stream_complete(prompt):
            if asyncio.get_event_loop().is_closed():
                break
            if handler.is_cancelled:
                break
            processed = writer.write(chunk)
            if processed:
                stream_chunk = StreamChunk(content=processed)
                await handler.on_chunk(stream_chunk)
            full_content += chunk
        remaining = writer.finalize()
        if remaining:
            stream_chunk = StreamChunk(content=remaining)
            await handler.on_chunk(stream_chunk)
        await handler.on_complete()
    except Exception as e:
        await handler.on_error(e)
        return {"ok": False, "error": str(e), "content": full_content}
    return {"ok": True, "content": full_content}
