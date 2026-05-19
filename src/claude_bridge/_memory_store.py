"""Memory persistence store with namespace isolation and JSONL backend."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any


class MemoryStore:
    def __init__(self, base_path: str | None = None) -> None:
        self._base_path = Path(base_path or os.path.expanduser("~/.claude-bridge/memory"))
        self._locks: dict[str, threading.RLock] = {}
        self._global_lock = threading.RLock()

    def _get_namespace_path(self, namespace: str) -> Path:
        ns_path = self._base_path / namespace
        ns_path.mkdir(parents=True, exist_ok=True)
        return ns_path

    def _get_lock(self, namespace: str) -> threading.RLock:
        with self._global_lock:
            if namespace not in self._locks:
                self._locks[namespace] = threading.RLock()
            return self._locks[namespace]

    def _get_file_path(self, key: str, namespace: str) -> Path:
        safe_key = re.sub(r'[^\w\-\.]', '_', key)
        return self._get_namespace_path(namespace) / f"{safe_key}.jsonl"

    def get(self, key: str, namespace: str = "default") -> Any | None:
        file_path = self._get_file_path(key, namespace)
        lock = self._get_lock(namespace)

        with lock:
            if not file_path.exists():
                return None

            try:
                with open(file_path, "r") as f:
                    lines = f.readlines()
                if not lines:
                    return None
                last_line = lines[-1].strip()
                if last_line:
                    record = json.loads(last_line)
                    return record.get("value")
                return None
            except (json.JSONDecodeError, OSError):
                return None

    def set(self, key: str, value: Any, namespace: str = "default", ttl: int | None = None) -> None:
        import time

        file_path = self._get_file_path(key, namespace)
        lock = self._get_lock(namespace)

        record: dict[str, Any] = {
            "key": key,
            "value": value,
            "timestamp": time.time(),
        }
        if ttl is not None:
            record["expires_at"] = time.time() + ttl

        with lock:
            try:
                with open(file_path, "a") as f:
                    f.write(json.dumps(record) + "\n")
            except OSError:
                pass

    def delete(self, key: str, namespace: str = "default") -> bool:
        file_path = self._get_file_path(key, namespace)
        lock = self._get_lock(namespace)

        with lock:
            if file_path.exists():
                try:
                    file_path.unlink()
                    return True
                except OSError:
                    return False
        return False

    def query(self, pattern: str, namespace: str = "default") -> list[Any]:
        ns_path = self._get_namespace_path(namespace)
        lock = self._get_lock(namespace)
        results: list[Any] = []

        try:
            regex = re.compile(pattern)
        except re.error:
            return results

        with lock:
            if not ns_path.exists():
                return results

            for file_path in ns_path.glob("*.jsonl"):
                try:
                    with open(file_path, "r") as f:
                        lines = f.readlines()
                    if lines:
                        last_line = lines[-1].strip()
                        if last_line:
                            record = json.loads(last_line)
                            key_name = record.get("key", file_path.stem)
                            if regex.search(key_name):
                                results.append(record.get("value"))
                except (json.JSONDecodeError, OSError):
                    continue

        return results

    def clear_namespace(self, namespace: str) -> None:
        ns_path = self._get_namespace_path(namespace)
        lock = self._get_lock(namespace)

        with lock:
            if ns_path.exists():
                for file_path in ns_path.glob("*.jsonl"):
                    try:
                        file_path.unlink()
                    except OSError:
                        pass