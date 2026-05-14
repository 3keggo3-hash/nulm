"""Distributed cache module for Claude Bridge with Redis opt-in support."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, cast

try:
    import redis  # type: ignore[import-not-found]
except ImportError:
    redis = None


class DistributedCache:
    _hits: int = 0
    _misses: int = 0
    _evictions: int = 0

    def __init__(
        self,
        enabled: bool = False,
        redis_url: str | None = None,
        prefix: str = "claude-bridge:",
        default_ttl: int = 3600,
    ) -> None:
        self._enabled = enabled and redis is not None
        self._prefix = prefix
        self._default_ttl = default_ttl
        self._client: Any | None = None
        self._local_cache: dict[str, tuple[Any, float]] = {}
        self._local_lock = threading.Lock()
        if self._enabled:
            url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
            try:
                self._client = redis.from_url(url, decode_responses=True)
                self._client.ping()
            except Exception:
                self._client = None
                self._enabled = False

    @property
    def is_available(self) -> bool:
        if not self._enabled:
            return False
        if self._client is None:
            return False
        try:
            self._client.ping()
            return True
        except Exception:
            return False

    @property
    def stats(self) -> dict[str, int]:
        return {
            "hits": DistributedCache._hits,
            "misses": DistributedCache._misses,
            "evictions": DistributedCache._evictions,
        }

    @classmethod
    def reset_stats(cls) -> None:
        cls._hits = 0
        cls._misses = 0
        cls._evictions = 0

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        if ttl is None:
            ttl = self._default_ttl
        full_key = f"{self._prefix}{key}"
        serialized = json.dumps(value)
        with self._local_lock:
            self._local_cache[key] = (value, time.time() + ttl)
        if self._client is not None:
            try:
                self._client.setex(full_key, ttl, serialized)
                return True
            except Exception:
                return False
        return True

    def get(self, key: str) -> Any | None:
        with self._local_lock:
            if key in self._local_cache:
                value, expiry = self._local_cache[key]
                if time.time() < expiry:
                    DistributedCache._hits += 1
                    return value
                del self._local_cache[key]
                DistributedCache._evictions += 1
        if self._client is not None:
            try:
                full_key = f"{self._prefix}{key}"
                data = self._client.get(full_key)
                if data is None:
                    DistributedCache._misses += 1
                    return None
                DistributedCache._hits += 1
                return json.loads(data)
            except Exception:
                DistributedCache._misses += 1
                return None
        DistributedCache._misses += 1
        return None

    def delete(self, key: str) -> bool:
        with self._local_lock:
            self._local_cache.pop(key, None)
        if self._client is not None:
            try:
                full_key = f"{self._prefix}{key}"
                self._client.delete(full_key)
                return True
            except Exception:
                return False
        return True

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def clear(self) -> bool:
        with self._local_lock:
            self._local_cache.clear()
        if self._client is not None:
            try:
                pattern = f"{self._prefix}*"
                for key in self._client.scan_iter(match=pattern):
                    self._client.delete(key)
                return True
            except Exception:
                return False
        return True

    def increment(self, key: str, amount: int = 1) -> int | None:
        with self._local_lock:
            if key in self._local_cache:
                value, expiry = self._local_cache[key]
                if isinstance(value, int) and time.time() < expiry:
                    new_value = value + amount
                    self._local_cache[key] = (new_value, expiry)
                    if self._client is not None:
                        try:
                            full_key = f"{self._prefix}{key}"
                            return cast(int, self._client.incrby(full_key, amount))  # type: ignore[no-any-return]
                        except Exception:
                            pass
                    return new_value
        if self._client is not None:
            try:
                full_key = f"{self._prefix}{key}"
                result = self._client.incrby(full_key, amount)
                return cast(int, result)  # type: ignore[no-any-return]
            except Exception:
                pass
        return None

    def get_ttl(self, key: str) -> int | None:
        if self._client is not None:
            try:
                full_key = f"{self._prefix}{key}"
                ttl = self._client.ttl(full_key)
                return int(ttl) if ttl > 0 else None
            except Exception:
                pass
        with self._local_lock:
            if key in self._local_cache:
                _, expiry = self._local_cache[key]
                remaining = int(expiry - time.time())
                return remaining if remaining > 0 else None
        return None

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in keys:
            value = self.get(key)
            if value is not None:
                result[key] = value
        return result

    def set_many(self, mapping: dict[str, Any], ttl: int | None = None) -> bool:
        for key, value in mapping.items():
            self.set(key, value, ttl)
        return True

    def delete_many(self, keys: list[str]) -> bool:
        with self._local_lock:
            for key in keys:
                self._local_cache.pop(key, None)
        if self._client is not None:
            try:
                full_keys = [f"{self._prefix}{key}" for key in keys]
                self._client.delete(*full_keys)
                return True
            except Exception:
                return False
        return True

    def get_many_bulk(self, keys: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        local_hits: dict[str, Any] = {}
        keys_to_fetch: list[str] = []
        with self._local_lock:
            for key in keys:
                if key in self._local_cache:
                    value, expiry = self._local_cache[key]
                    if time.time() < expiry:
                        local_hits[key] = value
                    else:
                        del self._local_cache[key]
                        keys_to_fetch.append(key)
                else:
                    keys_to_fetch.append(key)
        result.update(local_hits)
        if keys_to_fetch and self._client is not None:
            try:
                full_keys = [f"{self._prefix}{key}" for key in keys_to_fetch]
                redis_result = self._client.mget(full_keys)
                for key, data in zip(keys_to_fetch, redis_result):
                    if data is not None:
                        try:
                            value = json.loads(data)
                            result[key] = value
                            with self._local_lock:
                                ttl = self._default_ttl
                                self._local_cache[key] = (value, time.time() + ttl)
                        except (json.JSONDecodeError, TypeError):
                            pass
            except Exception:
                pass
        return result

    def set_many_pipeline(self, mapping: dict[str, Any], ttl: int | None = None) -> bool:
        if ttl is None:
            ttl = self._default_ttl
        local_entries = {}
        for key, value in mapping.items():
            local_entries[key] = (value, time.time() + ttl)
        with self._local_lock:
            self._local_cache.update(local_entries)
        if self._client is not None:
            try:
                pipe = self._client.pipeline()
                for key, value in mapping.items():
                    full_key = f"{self._prefix}{key}"
                    serialized = json.dumps(value)
                    pipe.setex(full_key, ttl, serialized)
                pipe.execute()
                return True
            except Exception:
                return False
        return True

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


_GLOBAL_CACHE: DistributedCache | None = None
_CACHE_LOCK = threading.Lock()


def get_distributed_cache() -> DistributedCache:
    global _GLOBAL_CACHE
    with _CACHE_LOCK:
        if _GLOBAL_CACHE is None:
            redis_url = os.environ.get("REDIS_URL")
            enabled = redis_url is not None
            _GLOBAL_CACHE = DistributedCache(
                enabled=enabled,
                redis_url=redis_url,
            )
        return _GLOBAL_CACHE


def clear_global_cache() -> None:
    global _GLOBAL_CACHE
    with _CACHE_LOCK:
        if _GLOBAL_CACHE is not None:
            _GLOBAL_CACHE.clear()
            _GLOBAL_CACHE.close()
        _GLOBAL_CACHE = None
