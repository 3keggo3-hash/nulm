"""Agent messaging system with in-memory pub/sub message bus."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import time


@dataclass
class AgentMessage:
    sender: str
    recipient: str | None
    content: Any
    message_type: str
    correlation_id: str
    topic: str | None = None
    ttl: float = 5.0
    timestamp: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl


class AgentMessageBus:
    """In-memory pub/sub message bus for agent communication."""

    def __init__(self) -> None:
        self._subscriptions: dict[str, set[str]] = defaultdict(set)
        self._inbox: dict[str, list[AgentMessage]] = defaultdict(list)
        self._lock = threading.RLock()

    def subscribe(self, agent_id: str, topics: set[str]) -> None:
        with self._lock:
            for topic in topics:
                self._subscriptions[topic].add(agent_id)
                if agent_id not in self._inbox:
                    self._inbox[agent_id] = []

    def unsubscribe(self, agent_id: str, topics: set[str] | None = None) -> None:
        with self._lock:
            if topics is None:
                for topic_subs in self._subscriptions.values():
                    topic_subs.discard(agent_id)
            else:
                for topic in topics:
                    self._subscriptions[topic].discard(agent_id)

    def send(self, message: AgentMessage, timeout: float = 5.0) -> bool:
        with self._lock:
            self._cleanup_expired()
            delivered = True

            if message.recipient is None:
                if message.topic:
                    subscribers = self._subscriptions.get(message.topic, set()).copy()
                    for agent_id in subscribers:
                        self._inbox[agent_id].append(message)
                else:
                    for agent_id in self._inbox:
                        self._inbox[agent_id].append(message)
            else:
                self._inbox[message.recipient].append(message)

            return delivered

    def receive(self, agent_id: str, timeout: float = 0.1) -> list[AgentMessage]:
        messages = []
        end_time = time.time() + timeout

        while time.time() < end_time:
            with self._lock:
                self._cleanup_expired()
                if self._inbox[agent_id]:
                    messages = self._inbox[agent_id]
                    self._inbox[agent_id] = []
                    break

        return messages

    def get_inbox_size(self, agent_id: str) -> int:
        with self._lock:
            self._cleanup_expired()
            return len(self._inbox.get(agent_id, []))

    def _cleanup_expired(self) -> None:
        for agent_id in list(self._inbox.keys()):
            self._inbox[agent_id] = [
                msg for msg in self._inbox[agent_id] if not msg.is_expired()
            ]


_message_bus: AgentMessageBus | None = None
_message_bus_lock = threading.Lock()


def get_message_bus() -> AgentMessageBus:
    """Get singleton message bus instance."""
    global _message_bus
    if _message_bus is None:
        with _message_bus_lock:
            if _message_bus is None:
                _message_bus = AgentMessageBus()
    return _message_bus


def agent_send(
    sender: str,
    recipient: str | None,
    content: Any,
    message_type: str = "notification",
    topic: str | None = None,
    correlation_id: str | None = None,
) -> bool:
    """Convenience function to send a message."""
    message = AgentMessage(
        sender=sender,
        recipient=recipient,
        content=content,
        message_type=message_type,
        topic=topic,
        correlation_id=correlation_id or str(uuid.uuid4()),
    )
    return get_message_bus().send(message)


def agent_receive(agent_id: str, timeout: float = 0.1) -> list[AgentMessage]:
    """Convenience function to receive messages."""
    return get_message_bus().receive(agent_id, timeout)