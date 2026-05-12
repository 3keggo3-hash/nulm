"""Tests for shared memory space."""

import threading

from claude_bridge.agents.shared_memory import SharedMemorySpace


def test_shared_memory_write_read():
    memory = SharedMemorySpace()
    memory.write("key1", "value1")
    assert memory.read("key1") == "value1"


def test_shared_memory_read_nonexistent():
    memory = SharedMemorySpace()
    assert memory.read("nonexistent") is None


def test_shared_memory_get_all_keys():
    memory = SharedMemorySpace()
    memory.write("key1", "value1")
    memory.write("key2", "value2")
    keys = memory.get_all_keys()
    assert "key1" in keys
    assert "key2" in keys


def test_shared_memory_thread_safe():
    memory = SharedMemorySpace()
    results: list[int] = []

    def writer(n: int) -> None:
        for i in range(100):
            memory.write(f"key_{n}_{i}", i)
        results.append(n)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 5


def test_shared_memory_clear():
    memory = SharedMemorySpace()
    memory.write("key1", "value1")
    memory.clear()
    assert memory.read("key1") is None
    assert memory.get_all_keys() == []


def test_shared_memory_get_agent_view():
    memory = SharedMemorySpace()
    memory.write("key1", "value1")
    view = memory.get_agent_view("test_agent")
    assert view["key1"] == "value1"


def test_shared_memory_update_agent_view():
    memory = SharedMemorySpace()
    memory.write("custom_key", "custom_value")
    view = memory.get_agent_view("test_agent")
    assert view["custom_key"] == "custom_value"