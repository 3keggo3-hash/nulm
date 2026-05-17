"""Tests for Redis-backed distributed cache edge cases."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import pytest

from claude_bridge import distributed_cache as cache_module
from claude_bridge.distributed_cache import DistributedCache


class FailingRedisClient:
    def ping(self) -> bool:
        raise RuntimeError("redis unavailable")


class InvalidJsonRedisClient:
    def ping(self) -> bool:
        return True

    def get(self, _key: str) -> str:
        return "{not-json"

    def hget(self, _name: str, _key: str) -> str:
        return "1"


class RecordingRedisClient:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def ping(self) -> bool:
        return True

    def scan_iter(self, match: str):
        assert match == "safe:*"
        yield "safe:a"
        yield "safe:b"

    def delete(self, key: str) -> None:
        self.deleted.append(key)


class FakeRedisModule:
    def __init__(self, client) -> None:
        self.client = client

    def from_url(self, _url: str, *, decode_responses: bool = False):
        assert decode_responses is True
        return self.client


def test_redis_unavailable_disables_remote_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache_module, "redis", FakeRedisModule(FailingRedisClient()))

    cache = DistributedCache(enabled=True, redis_url="redis://example.invalid")

    assert cache.is_available is False
    assert cache.set("local", {"value": 1}) is True
    assert cache.get("local") == {"value": 1}


def test_invalid_remote_json_is_treated_as_cache_miss() -> None:
    cache = DistributedCache(enabled=False)
    cache._client = InvalidJsonRedisClient()
    cache._enabled = True

    assert cache.get("bad") is None
    assert cache.stats["misses"] == 1


def test_remote_errors_do_not_raise_to_callers() -> None:
    cache = DistributedCache(enabled=False)
    cache._client = FailingRedisClient()
    cache._enabled = True

    assert cache.is_available is False
    assert cache.get("missing") is None
    assert cache.delete("missing") is False


def test_clear_deletes_only_prefixed_remote_keys() -> None:
    client = RecordingRedisClient()
    cache = DistributedCache(enabled=False, prefix="safe:")
    cache._client = client
    cache._enabled = True

    assert cache.clear() is True
    assert client.deleted == ["safe:a", "safe:b"]
