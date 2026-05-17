"""Distributed cache module for Nulm with Redis opt-in support."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, cast

try:
    import redis  # type: ignore[import-not-found]
except ImportError:
    redis = None


class DistributedCache:
    def __init__(
        self,
        enabled: bool = False,
        redis_url: str | None = None,
        prefix: str = "nulm:",
        default_ttl: int = 3600,
        consistency_mode: str = "eventual",
        cluster_nodes: list[str] | None = None,
    ) -> None:
        self._enabled = enabled and redis is not None
        self._prefix = prefix
        self._default_ttl = default_ttl
        self._client: Any | None = None
        self._local_cache: dict[str, tuple[Any, float, dict[str, Any]]] = {}
        self._local_lock = threading.Lock()
        self._consistency_mode = consistency_mode
        self._instance_id = str(uuid.uuid4())[:8]
        self._version_vector: dict[str, int] = {}
        self._vv_lock = threading.Lock()
        self._last_sync: float = 0
        self._sync_lock = threading.Lock()
        self._cluster_nodes = cluster_nodes or []
        self._partition_detected: bool = False
        self._partition_lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
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
            self._clear_partition_flag()
            return True
        except Exception:
            self._set_partition_flag()
            return False

    def _set_partition_flag(self) -> None:
        with self._partition_lock:
            self._partition_detected = True

    def _clear_partition_flag(self) -> None:
        with self._partition_lock:
            self._partition_detected = False

    def _is_partitioned(self) -> bool:
        with self._partition_lock:
            return self._partition_detected

    @property
    def stats(self) -> dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
        }

    def reset_stats(self) -> None:
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def _increment_version(self, key: str) -> int:
        with self._vv_lock:
            current = self._version_vector.get(key, 0)
            new_version = current + 1
            self._version_vector[key] = new_version
            return new_version

    def _get_version(self, key: str) -> int:
        with self._vv_lock:
            return self._version_vector.get(key, 0)

    def _invalidate_local(self, key: str) -> None:
        with self._local_lock:
            if key in self._local_cache:
                value, expiry, metadata = self._local_cache[key]
                metadata = metadata.copy()
                metadata["invalidated"] = True
                metadata["invalidated_at"] = time.time()
                self._local_cache[key] = (value, expiry, metadata)
                self._evictions += 1

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        if ttl is None:
            ttl = self._default_ttl
        full_key = f"{self._prefix}{key}"
        version = self._increment_version(key)
        serialized = json.dumps(value)
        metadata = {
            "version": version,
            "instance_id": self._instance_id,
            "created_at": time.time(),
            "invalidated": False,
        }
        with self._local_lock:
            self._local_cache[key] = (value, time.time() + ttl, metadata)
        if self._client is not None:
            try:
                pipe = self._client.pipeline()
                pipe.setex(full_key, ttl, serialized)
                pipe.hset(f"{self._prefix}__versions__", key, str(version))
                pipe.execute()
                return True
            except Exception:
                return False
        return True

    def get(self, key: str, force_local: bool = False) -> Any | None:
        with self._local_lock:
            if key in self._local_cache:
                value, expiry, metadata = self._local_cache[key]
                if time.time() < expiry:
                    if metadata.get("invalidated"):
                        self._hits += 1
                        return None
                    self._hits += 1
                    if (
                        self._consistency_mode == "local-first"
                        and not force_local
                        and not self._is_partitioned()
                    ):
                        return value
                    if self._consistency_mode == "strict":
                        pass
                    return value
                del self._local_cache[key]
                self._evictions += 1
        if force_local or self._is_partitioned():
            self._misses += 1
            return None
        if self._client is not None:
            try:
                full_key = f"{self._prefix}{key}"
                data = self._client.get(full_key)
                if data is None:
                    self._misses += 1
                    return None
                server_version_str = self._client.hget(f"{self._prefix}__versions__", key)
                server_version = int(server_version_str) if server_version_str else 0
                local_version = self._get_version(key)
                if server_version > 0 and server_version > local_version:
                    self._increment_version(key)
                try:
                    result_value = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    self._misses += 1
                    return None
                self._hits += 1
                with self._local_lock:
                    ttl = self._default_ttl
                    metadata = {
                        "version": server_version or local_version,
                        "instance_id": "remote",
                        "created_at": time.time(),
                        "invalidated": False,
                    }
                    self._local_cache[key] = (result_value, time.time() + ttl, metadata)
                return result_value
            except Exception:
                self._misses += 1
                return None
        self._misses += 1
        return None

    def delete(self, key: str) -> bool:
        with self._local_lock:
            self._local_cache.pop(key, None)
        self._increment_version(key)
        if self._client is not None:
            try:
                full_key = f"{self._prefix}{key}"
                pipe = self._client.pipeline()
                pipe.delete(full_key)
                pipe.hdel(f"{self._prefix}__versions__", key)
                pipe.execute()
                return True
            except Exception:
                return False
        return True

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def clear(self) -> bool:
        with self._local_lock:
            self._local_cache.clear()
        with self._vv_lock:
            self._version_vector.clear()
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
                value, expiry, metadata = self._local_cache[key]
                if isinstance(value, int) and time.time() < expiry:
                    if metadata.get("invalidated"):
                        pass
                    else:
                        new_value = value + amount
                        self._local_cache[key] = (new_value, expiry, metadata)
                        if self._client is not None:
                            try:
                                full_key = f"{self._prefix}{key}"
                                return cast(int, self._client.incrby(full_key, amount))
                            except Exception:
                                pass
                        return new_value
        if self._client is not None:
            try:
                full_key = f"{self._prefix}{key}"
                result = self._client.incrby(full_key, amount)
                self._increment_version(key)
                return cast(int, result)
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
                _, expiry, _ = self._local_cache[key]
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
        for key in keys:
            self._increment_version(key)
        if self._client is not None:
            try:
                full_keys = [f"{self._prefix}{key}" for key in keys]
                pipe = self._client.pipeline()
                pipe.delete(*full_keys)
                for key in keys:
                    pipe.hdel(f"{self._prefix}__versions__", key)
                pipe.execute()
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
                    value, expiry, metadata = self._local_cache[key]
                    if time.time() < expiry:
                        if not metadata.get("invalidated"):
                            local_hits[key] = value
                        else:
                            keys_to_fetch.append(key)
                    else:
                        del self._local_cache[key]
                        keys_to_fetch.append(key)
                else:
                    keys_to_fetch.append(key)
        result.update(local_hits)
        if keys_to_fetch and self._client is not None and not self._is_partitioned():
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
                                metadata = {
                                    "version": 0,
                                    "instance_id": "remote",
                                    "created_at": time.time(),
                                    "invalidated": False,
                                }
                                self._local_cache[key] = (
                                    value,
                                    time.time() + ttl,
                                    metadata,
                                )
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
            version = self._increment_version(key)
            local_entries[key] = (
                value,
                time.time() + ttl,
                {
                    "version": version,
                    "instance_id": self._instance_id,
                    "created_at": time.time(),
                    "invalidated": False,
                },
            )
        with self._local_lock:
            self._local_cache.update(local_entries)
        if self._client is not None:
            try:
                pipe = self._client.pipeline()
                for key, value in mapping.items():
                    full_key = f"{self._prefix}{key}"
                    serialized = json.dumps(value)
                    pipe.setex(full_key, ttl, serialized)
                    pipe.hset(f"{self._prefix}__versions__", key, str(self._get_version(key)))
                pipe.execute()
                return True
            except Exception:
                return False
        return True

    def cache_sync(self, source_node: str | None = None) -> bool:
        if self._client is None:
            return False
        with self._sync_lock:
            try:
                if source_node:
                    source_client = redis.from_url(source_node, decode_responses=True)
                    source_client.ping()
                else:
                    source_client = self._client
                pattern = f"{self._prefix}*"
                if source_node:
                    for key in source_client.scan_iter(match=pattern):
                        if key.endswith("__versions__"):
                            continue
                        data = source_client.get(key)
                        if data is not None:
                            self._client.set(key, data)
                else:
                    local_keys = list(self._local_cache.keys())
                    for key in local_keys:
                        value, _, metadata = self._local_cache[key]
                        full_key = f"{self._prefix}{key}"
                        serialized = json.dumps(value)
                        ttl = self.get_ttl(key) or self._default_ttl
                        self._client.setex(full_key, ttl, serialized)
                        version = metadata.get("version", 0)
                        self._client.hset(f"{self._prefix}__versions__", key, str(version))
                self._last_sync = time.time()
                self._clear_partition_flag()
                return True
            except Exception:
                self._set_partition_flag()
                return False

    def get_cluster_nodes(self) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        if self._client is None:
            return nodes
        try:
            if hasattr(self._client, "cluster_nodes"):
                cluster_info = self._client.cluster_nodes()
                for node_line in cluster_info.splitlines():
                    if node_line.strip():
                        parts = node_line.split()
                        if len(parts) >= 3:
                            nodes.append(
                                {
                                    "id": parts[0],
                                    "host": parts[1].split(":")[0] if ":" in parts[1] else parts[1],
                                    "port": parts[1].split(":")[1] if ":" in parts[1] else "6379",
                                    "flags": parts[2].split(","),
                                    "role": parts[3] if len(parts) > 3 else "unknown",
                                }
                            )
            else:
                self._client.info("server")
                nodes.append(
                    {
                        "id": "single",
                        "host": self._client.connection_pool.connection_kwargs.get(
                            "host", "localhost"
                        ),
                        "port": self._client.connection_pool.connection_kwargs.get("port", "6379"),
                        "flags": ["myself"],
                        "role": "master",
                    }
                )
        except Exception:
            pass
        return nodes

    def get_version_vector(self) -> dict[str, int]:
        with self._vv_lock:
            return self._version_vector.copy()

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
