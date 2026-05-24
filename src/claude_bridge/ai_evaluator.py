"""Optional AI Evaluator — typed models, provider interface, and strict JSON response parser."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from claude_bridge._event_bus import EventType
from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    PolicyDecision,
    RiskLevel,
    ToolRequestContext,
)
from claude_bridge.hooks import get_hook_registry
from claude_bridge.tool_utils import _mask_secrets

_AI_PROVIDER_MAX_RESPONSE_BYTES = 65536
_AI_LATENCY_SAMPLES_MS: deque[float] = deque(maxlen=100)
_OPENAI_COMPAT_PROVIDER_CONFIG: dict[str, dict[str, str]] = {
    "openai": {
        "label": "OpenAI",
        "env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        "endpoint": "https://api.openai.com/v1/chat/completions",
    },
    "deepseek": {
        "label": "DeepSeek",
        "env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "endpoint": "https://api.deepseek.com/v1/chat/completions",
    },
    "minimax": {
        "label": "MiniMax",
        "env": "MINIMAX_API_KEY",
        "default_model": "MiniMax-M2.5",
        "endpoint": "https://api.minimax.io/v1/chat/completions",
    },
    "google": {
        "label": "Google Gemini",
        "env": "GEMINI_API_KEY",
        "default_model": "gemini-2.5-flash",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    },
    "groq": {
        "label": "Groq",
        "env": "GROQ_API_KEY",
        "default_model": "llama-3.1-8b-instant",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
    },
    "mistral": {
        "label": "Mistral",
        "env": "MISTRAL_API_KEY",
        "default_model": "mistral-small-latest",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
    },
    "xai": {
        "label": "xAI",
        "env": "XAI_API_KEY",
        "default_model": "grok-4.3",
        "endpoint": "https://api.x.ai/v1/chat/completions",
    },
    "together": {
        "label": "Together AI",
        "env": "TOGETHER_API_KEY",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "endpoint": "https://api.together.xyz/v1/chat/completions",
    },
    "openrouter": {
        "label": "OpenRouter",
        "env": "OPENROUTER_API_KEY",
        "default_model": "openai/gpt-4o-mini",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
    },
    "perplexity": {
        "label": "Perplexity",
        "env": "PERPLEXITY_API_KEY",
        "default_model": "sonar-pro",
        "endpoint": "https://api.perplexity.ai/chat/completions",
    },
    "fireworks": {
        "label": "Fireworks",
        "env": "FIREWORKS_API_KEY",
        "default_model": "accounts/fireworks/models/llama-v3p1-8b-instruct",
        "endpoint": "https://api.fireworks.ai/inference/v1/chat/completions",
    },
}
AI_EVALUATOR_PROVIDERS: frozenset[str] = frozenset(
    {"local", "anthropic", "ollama", "cohere", *_OPENAI_COMPAT_PROVIDER_CONFIG}
)


class _ResponseTruncatedError(Exception):
    """Raised when an AI provider response exceeds the max response bytes limit."""

    pass


_RATE_LIMIT_CALLS = 60
_RATE_LIMIT_WINDOW_SEC = 60.0
_RATE_LIMIT_TOKENS: deque[float] = deque(maxlen=_RATE_LIMIT_CALLS)
_RATE_LIMIT_LOCK = threading.Lock()


class EvaluationAction(str, Enum):
    """The action recommended by the AI evaluation for a tool request."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class EvaluationRequest:
    """Input to an AI evaluator provider describing a tool invocation."""

    prompt: str
    tool_name: str = ""
    tool_params: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the request to a JSON-compatible dictionary."""
        return {
            "prompt": self.prompt,
            "tool_name": self.tool_name,
            "tool_params": dict(self.tool_params),
            "context": dict(self.context),
        }


@dataclass
class EvaluationResponse:
    """Structured response from an AI evaluator indicating the recommended action."""

    action: EvaluationAction
    reason: str = ""
    risk_reasons: list[str] = field(default_factory=list)
    tokens_used: float = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the response to a JSON-compatible dictionary."""
        return {
            "action": self.action.value,
            "reason": self.reason,
            "risk_reasons": list(self.risk_reasons),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationResponse:
        """Deserialize a dictionary back into an EvaluationResponse.

        Invalid or missing actions default to ASK (fail-closed).
        """
        action_str = str(data.get("action", "ask"))
        try:
            action = EvaluationAction(action_str.lower())
        except ValueError:
            action = EvaluationAction.ASK
        return cls(
            action=action,
            reason=str(data.get("reason", "")),
            risk_reasons=[str(r) for r in data.get("risk_reasons", [])],
        )

    @classmethod
    def fail_closed(cls, reason: str = "") -> EvaluationResponse:
        """Create a safe default response when evaluation fails."""
        return cls(action=EvaluationAction.ASK, reason=reason)


@dataclass
class ProviderConfig:
    """Configuration for an AI evaluation provider (model, endpoint, etc.)."""

    model: str = "gpt-4"
    base_url: str = ""
    api_key: str = ""
    timeout: int = 30
    extra: dict[str, Any] = field(default_factory=dict)

    def _masked_key(self) -> str:
        if not self.api_key:
            return ""
        return f"sk-***...{self.api_key[-4:]}" if len(self.api_key) > 4 else "sk-***..."

    def __repr__(self) -> str:
        return (
            f"ProviderConfig(model={self.model!r}, base_url={self.base_url!r}, "
            f"api_key={self._masked_key()!r}, timeout={self.timeout}, extra={self.extra!r})"
        )

    def __str__(self) -> str:
        return (
            f"ProviderConfig(model={self.model}, base_url={self.base_url}, "
            f"api_key={self._masked_key()}, timeout={self.timeout})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary (excluding secrets)."""
        return {
            "model": self.model,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "extra": dict(self.extra),
        }


class Provider(ABC):
    """Abstract interface for an AI evaluation provider.

    Subclasses must implement :meth:`evaluate` without raising exceptions;
    all errors should be caught internally and returned as a fail-closed
    :class:`EvaluationResponse`.
    """

    @abstractmethod
    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        """Evaluate a tool request and return a structured decision.

        :param request: The tool invocation details to evaluate.
        :returns: A structured response with action, reason, and risk reasons.
        """
        ...


class UnavailableEvaluatorProvider(Provider):
    """Fail-closed provider used when configured AI evaluator setup is invalid."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        return EvaluationResponse.fail_closed(self.reason)


# ---------------------------------------------------------------------------
# Strict JSON response parser
# ---------------------------------------------------------------------------

_VALID_ACTIONS: frozenset[str] = frozenset(e.value for e in EvaluationAction)


def _record_ai_latency(duration_ms: float) -> None:
    _AI_LATENCY_SAMPLES_MS.append(duration_ms)


def reset_ai_latency_samples() -> None:
    """Clear in-memory AI evaluator latency samples."""
    _AI_LATENCY_SAMPLES_MS.clear()


def reset_ai_evaluator_state() -> None:
    """Clear in-memory AI evaluator telemetry and rate-limit state."""
    reset_ai_latency_samples()
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_TOKENS.clear()


def _check_rate_limit() -> bool:
    """Return True if under rate limit, False if limit exceeded."""
    now = time.monotonic()
    with _RATE_LIMIT_LOCK:
        while _RATE_LIMIT_TOKENS and now - _RATE_LIMIT_TOKENS[0] >= _RATE_LIMIT_WINDOW_SEC:
            _RATE_LIMIT_TOKENS.popleft()
        if len(_RATE_LIMIT_TOKENS) < _RATE_LIMIT_CALLS:
            _RATE_LIMIT_TOKENS.append(now)
            return True
    return False


def ai_latency_summary() -> dict[str, Any]:
    """Return a compact summary of recent AI evaluator latency samples."""
    samples = list(_AI_LATENCY_SAMPLES_MS)
    if not samples:
        return {
            "sample_count": 0,
            "last_ms": None,
            "avg_ms": None,
            "p95_ms": None,
        }
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))
    return {
        "sample_count": len(samples),
        "last_ms": round(samples[-1], 3),
        "avg_ms": round(sum(samples) / len(samples), 3),
        "p95_ms": round(ordered[p95_index], 3),
    }


def parse_evaluation_response(raw: str) -> EvaluationResponse:
    """Parse a raw JSON string into an :class:`EvaluationResponse`.

    Handles malformed JSON, missing or invalid ``action``, and unexpected
    payload shapes.  On any error the result is **fail-closed** (ASK).

    Expected JSON schema::

        {"action": "allow"|"deny"|"ask", "reason": "...", "risk_reasons": [...]}
    """
    try:
        data: Any = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return EvaluationResponse.fail_closed(
            reason="Failed to parse evaluation response: invalid JSON"
        )

    if not isinstance(data, dict):
        return EvaluationResponse.fail_closed(
            reason="Failed to parse evaluation response: expected a JSON object"
        )

    action_raw = data.get("action")
    if action_raw is None:
        return EvaluationResponse.fail_closed(reason="Evaluation response missing 'action' field")

    if not isinstance(action_raw, str):
        return EvaluationResponse.fail_closed(
            reason="Evaluation response 'action' must be a string"
        )

    action_lower = action_raw.lower()
    if action_lower not in _VALID_ACTIONS:
        return EvaluationResponse(
            action=EvaluationAction.ASK,
            reason=f"Unknown action '{action_raw}'; defaulting to ask",
            risk_reasons=[f"unrecognized_action: {action_raw}"],
        )

    action = EvaluationAction(action_lower)
    reason_raw = data.get("reason")
    if reason_raw is None:
        reason = ""
    elif isinstance(reason_raw, str):
        reason = reason_raw
    else:
        reason = str(reason_raw)

    risk_reasons_raw = data.get("risk_reasons", [])
    if isinstance(risk_reasons_raw, list):
        risk_reasons = [str(r) for r in risk_reasons_raw if isinstance(r, str)]
    else:
        risk_reasons = []

    return EvaluationResponse(
        action=action,
        reason=reason,
        risk_reasons=risk_reasons,
    )


# ---------------------------------------------------------------------------
# Local / mock provider (no network)
# ---------------------------------------------------------------------------


_MASKED_CONTENT_FIELDS = {"content", "search", "replace", "command", "url", "path"}


def _mask_evaluation_params(params: dict[str, Any]) -> dict[str, Any]:
    masked: dict[str, Any] = {}
    for k, v in params.items():
        masked_v = _mask_secrets(v)
        if isinstance(masked_v, str) and len(masked_v) > 200:
            masked_v = masked_v[:200] + "..."
        if k in _MASKED_CONTENT_FIELDS and isinstance(masked_v, str) and len(masked_v) > 80:
            masked_v = masked_v[:80] + "...[masked]"
        masked[k] = masked_v
    return masked


def _strip_content_for_remote(params: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for k, v in params.items():
        if k in _MASKED_CONTENT_FIELDS and isinstance(v, str):
            safe[k] = (
                f"[content-hash:{hashlib.sha256(v.encode()).hexdigest()[:16]}" f" len:{len(v)}]"
            )
        else:
            safe[k] = v
    return safe


def create_provider(
    provider_name: str,
    *,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    timeout: int = 30,
) -> Provider:
    provider_name = provider_name.lower()
    if provider_name == "local":
        return LocalEvaluatorProvider()
    if provider_name == "anthropic":
        key = (api_key or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
        if not key:
            raise ValueError(
                "Anthropic provider requires an API key "
                "(set ANTHROPIC_API_KEY or ai_evaluator_api_key)"
            )
        return AnthropicProvider(
            api_key=key,
            model=model or "claude-3-haiku-20240307",
            timeout=timeout,
        )
    if provider_name == "ollama":
        return OllamaProvider(
            base_url=(base_url or "http://localhost:11434").strip(),
            model=model or "llama3",
            timeout=timeout,
        )
    if provider_name == "cohere":
        key = (api_key or os.environ.get("COHERE_API_KEY", "")).strip()
        if not key:
            raise ValueError(
                "Cohere provider requires an API key "
                "(set COHERE_API_KEY or ai_evaluator_api_key)"
            )
        return CohereProvider(api_key=key, model=model or "command-a-03-2025", timeout=timeout)
    if provider_name in _OPENAI_COMPAT_PROVIDER_CONFIG:
        info = _OPENAI_COMPAT_PROVIDER_CONFIG[provider_name]
        key = (api_key or os.environ.get(info["env"], "")).strip()
        if not key:
            raise ValueError(
                f"{info['label']} provider requires an API key "
                f"(set {info['env']} or ai_evaluator_api_key)"
            )
        endpoint = _chat_completions_endpoint(base_url, info["endpoint"])
        if provider_name == "openai":
            return OpenAIProvider(
                api_key=key,
                model=model or info["default_model"],
                timeout=timeout,
                endpoint=endpoint,
            )
        if provider_name == "deepseek":
            return DeepSeekProvider(
                api_key=key,
                model=model or info["default_model"],
                timeout=timeout,
                endpoint=endpoint,
            )
        return OpenAICompatibleProvider(
            provider_label=info["label"],
            api_key=key,
            model=model or info["default_model"],
            endpoint=endpoint,
            timeout=timeout,
        )
    raise ValueError(f"Unknown provider: {provider_name!r}")


class LocalEvaluatorProvider(Provider):
    """A deterministic local evaluator that requires no network.

    Matches the request prompt against simple deny/ask keyword lists.
    If no keyword matches the request is allowed.
    """

    def __init__(
        self,
        *,
        deny_patterns: list[str] | None = None,
        ask_patterns: list[str] | None = None,
    ) -> None:
        # FIX: use word boundary regex to avoid false positive substring matches
        self._deny_raw = list(deny_patterns or [])
        self._ask_raw = list(ask_patterns or [])
        self._deny = [re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE) for p in self._deny_raw]
        self._ask = [re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE) for p in self._ask_raw]

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        for i, pattern in enumerate(self._deny):
            if pattern.search(request.prompt):
                return EvaluationResponse(
                    action=EvaluationAction.DENY,
                    reason=f"Local evaluator matched deny pattern: {self._deny_raw[i]}",
                    risk_reasons=[f"matched_deny_pattern: {self._deny_raw[i]}"],
                )
        for i, pattern in enumerate(self._ask):
            if pattern.search(request.prompt):
                return EvaluationResponse(
                    action=EvaluationAction.ASK,
                    reason=f"Local evaluator matched ask pattern: {self._ask_raw[i]}",
                    risk_reasons=[f"matched_ask_pattern: {self._ask_raw[i]}"],
                )
        return EvaluationResponse(
            action=EvaluationAction.ALLOW,
            reason="Local evaluator found no concerning patterns",
            risk_reasons=[],
        )


def _provider_error_reason(provider_name: str, exc: Exception) -> str:
    if isinstance(exc, socket.timeout):
        return f"{provider_name} timeout"
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 429:
            return f"{provider_name} rate limited (HTTP 429)"
        return f"{provider_name} HTTP error {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"{provider_name} connection error: {exc.reason}"
    return f"{provider_name} error: {exc}"


class AnthropicProvider(Provider):
    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-haiku-20240307",
        timeout: int = 30,
    ):
        self.api_key = api_key.strip()
        self.model = model
        self.timeout = timeout
        self._endpoint = "https://api.anthropic.com/v1/messages"

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": 256,
                "system": (
                    "You are a security evaluator for a CLI tool bridge. "
                    "Determine if the tool call is safe. "
                    'Respond with JSON only: {"action": "allow"|"deny"|"ask", '
                    '"reason": "string"}'
                ),
                "messages": [{"role": "user", "content": request.prompt}],
            }
        ).encode("utf-8")
        try:
            return self._call_api(body)
        except _ResponseTruncatedError:
            return EvaluationResponse.fail_closed(
                reason="AI evaluator response truncated (exceeded 65536 bytes)"
            )
        except Exception as exc:
            return EvaluationResponse.fail_closed(reason=_provider_error_reason("Anthropic", exc))

    def _call_api(self, body: bytes) -> EvaluationResponse:
        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw_read = resp.read(_AI_PROVIDER_MAX_RESPONSE_BYTES)
            if len(raw_read) >= _AI_PROVIDER_MAX_RESPONSE_BYTES:
                raise _ResponseTruncatedError(
                    f"Response exceeded {_AI_PROVIDER_MAX_RESPONSE_BYTES} bytes"
                )
            data = json.loads(raw_read.decode("utf-8"))
        content = data.get("content", [{}])[0].get("text", "{}")
        return _parse_json_response(content)


def _chat_completions_endpoint(base_url: str, default_endpoint: str) -> str:
    if not base_url:
        return default_endpoint
    return base_url.rstrip("/") + "/chat/completions"


class OpenAICompatibleProvider(Provider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: int = 30,
        endpoint: str = "https://api.openai.com/v1/chat/completions",
        provider_label: str = "OpenAI",
    ):
        self.api_key = api_key.strip()
        self.model = model
        self.timeout = timeout
        self.provider_label = provider_label
        self._endpoint = endpoint

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": 256,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a security evaluator for a CLI tool bridge. "
                            "Determine if the tool call is safe. "
                            'Respond with JSON only: {"action": "allow"|"deny"|"ask", '
                            '"reason": "string"}'
                        ),
                    },
                    {"role": "user", "content": request.prompt},
                ],
            }
        ).encode("utf-8")
        try:
            return self._call_api(body)
        except _ResponseTruncatedError:
            return EvaluationResponse.fail_closed(
                reason="AI evaluator response truncated (exceeded 65536 bytes)"
            )
        except Exception as exc:
            return EvaluationResponse.fail_closed(
                reason=_provider_error_reason(self.provider_label, exc)
            )

    def _call_api(self, body: bytes) -> EvaluationResponse:
        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw_read = resp.read(_AI_PROVIDER_MAX_RESPONSE_BYTES)
            if len(raw_read) >= _AI_PROVIDER_MAX_RESPONSE_BYTES:
                raise _ResponseTruncatedError(
                    f"Response exceeded {_AI_PROVIDER_MAX_RESPONSE_BYTES} bytes"
                )
            data = json.loads(raw_read.decode("utf-8"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return _parse_json_response(content)


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: int = 30,
        endpoint: str = "https://api.openai.com/v1/chat/completions",
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            timeout=timeout,
            endpoint=endpoint,
            provider_label="OpenAI",
        )


def _validate_provider_url(url: str) -> None:
    """Raise ValueError if *url* points to a private/internal host."""
    from urllib.parse import urlparse as _urlparse

    parsed = _urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Invalid provider URL: {url!r}")
    from claude_bridge.url_tools import _is_private_host, _resolve_and_check_host

    if _is_private_host(hostname):
        raise ValueError(
            f"Provider URL hostname is blocked (private/internal): {hostname}. "
            f"Use a public hostname or IP address for the AI evaluator provider."
        )
    private_ip = _resolve_and_check_host(hostname)
    if private_ip is not None:
        raise ValueError(
            f"Provider URL hostname resolves to internal IP: {private_ip}. "
            f"AI evaluator cannot connect to private/internal networks for security."
        )


class OllamaProvider(Provider):
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3",
        timeout: int = 30,
    ):
        _validate_provider_url(base_url)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._endpoint = f"{self.base_url}/api/generate"

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        body = json.dumps(
            {
                "model": self.model,
                "prompt": (
                    "You are a security evaluator for a CLI tool bridge. "
                    "Determine if the tool call is safe. "
                    'Respond with JSON only: {"action": "allow"|"deny"|"ask", '
                    '"reason": "string"}\n\n'
                    f"Tool request: {request.prompt}"
                ),
                "stream": False,
            }
        ).encode("utf-8")
        try:
            return self._call_api(body)
        except _ResponseTruncatedError:
            return EvaluationResponse.fail_closed(
                reason="AI evaluator response truncated (exceeded 65536 bytes)"
            )
        except Exception as exc:
            return EvaluationResponse.fail_closed(reason=_provider_error_reason("Ollama", exc))

    def _call_api(self, body: bytes) -> EvaluationResponse:
        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw_read = resp.read(_AI_PROVIDER_MAX_RESPONSE_BYTES)
            if len(raw_read) >= _AI_PROVIDER_MAX_RESPONSE_BYTES:
                raise _ResponseTruncatedError(
                    f"Response exceeded {_AI_PROVIDER_MAX_RESPONSE_BYTES} bytes"
                )
            data = json.loads(raw_read.decode("utf-8"))
        content = data.get("response", "{}")
        return _parse_json_response(content)


class DeepSeekProvider(Provider):
    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        timeout: int = 30,
        endpoint: str = "https://api.deepseek.com/v1/chat/completions",
    ):
        self._provider = OpenAICompatibleProvider(
            provider_label="DeepSeek",
            api_key=api_key,
            model=model,
            timeout=timeout,
            endpoint=endpoint,
        )
        self.api_key = self._provider.api_key
        self.model = self._provider.model
        self.timeout = self._provider.timeout
        self._endpoint = self._provider._endpoint

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        return self._provider.evaluate(request)


class CohereProvider(Provider):
    def __init__(
        self,
        api_key: str,
        model: str = "command-a-03-2025",
        timeout: int = 30,
    ):
        self.api_key = api_key.strip()
        self.model = model
        self.timeout = timeout
        self._endpoint = "https://api.cohere.com/v2/chat"

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a security evaluator for a CLI tool bridge. "
                            "Determine if the tool call is safe. "
                            'Respond with JSON only: {"action": "allow"|"deny"|"ask", '
                            '"reason": "string"}'
                        ),
                    },
                    {"role": "user", "content": request.prompt},
                ],
            }
        ).encode("utf-8")
        try:
            return self._call_api(body)
        except _ResponseTruncatedError:
            return EvaluationResponse.fail_closed(
                reason="AI evaluator response truncated (exceeded 65536 bytes)"
            )
        except Exception as exc:
            return EvaluationResponse.fail_closed(reason=_provider_error_reason("Cohere", exc))

    def _call_api(self, body: bytes) -> EvaluationResponse:
        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw_read = resp.read(_AI_PROVIDER_MAX_RESPONSE_BYTES)
            if len(raw_read) >= _AI_PROVIDER_MAX_RESPONSE_BYTES:
                raise _ResponseTruncatedError(
                    f"Response exceeded {_AI_PROVIDER_MAX_RESPONSE_BYTES} bytes"
                )
            data = json.loads(raw_read.decode("utf-8"))
        message = data.get("message", {})
        raw_content = message.get("content", "")
        if isinstance(raw_content, list):
            content = "".join(
                str(item.get("text", "")) for item in raw_content if isinstance(item, dict)
            )
        else:
            content = str(raw_content)
        return _parse_json_response(content)


def _parse_json_response(text: str) -> EvaluationResponse:
    return parse_evaluation_response(text.strip())


# ---------------------------------------------------------------------------
# Convert EvaluationResponse → PolicyDecision
# ---------------------------------------------------------------------------


_EVAL_ACTION_TO_DECISION: dict[EvaluationAction, DecisionAction] = {
    EvaluationAction.ALLOW: DecisionAction.ALLOW,
    EvaluationAction.DENY: DecisionAction.DENY,
    EvaluationAction.ASK: DecisionAction.ASK,
}


_RISK_FROM_EVAL_ACTION: dict[EvaluationAction, RiskLevel] = {
    EvaluationAction.ALLOW: RiskLevel.LOW,
    EvaluationAction.DENY: RiskLevel.HIGH,
    EvaluationAction.ASK: RiskLevel.MEDIUM,
}


def evaluation_response_to_policy_decision(
    response: EvaluationResponse,
    ctx: ToolRequestContext | None = None,
) -> PolicyDecision:
    """Turn an :class:`EvaluationResponse` into a :class:`PolicyDecision` with source=AI."""
    action = _EVAL_ACTION_TO_DECISION.get(response.action, DecisionAction.ASK)
    risk_level = _RISK_FROM_EVAL_ACTION.get(response.action, RiskLevel.MEDIUM)
    metadata: dict[str, Any] = {"ai_reason": response.reason}
    if ctx is not None:
        metadata["tool_name"] = ctx.tool_name
    return PolicyDecision(
        action=action,
        source=DecisionSource.AI,
        risk_level=risk_level,
        reason=response.reason,
        risk_reasons=list(response.risk_reasons),
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Timeout wrapper for synchronous providers
# ---------------------------------------------------------------------------


async def evaluate_with_timeout(
    provider: Provider,
    request: EvaluationRequest,
    timeout: float,
) -> EvaluationResponse:
    """Evaluate a request through *provider* with a strict timeout.

    If the provider does not return within *timeout* seconds a fail-closed
    :class:`EvaluationResponse` is returned.
    """
    loop = asyncio.get_running_loop()
    started_at = time.perf_counter()
    if not _check_rate_limit():
        return EvaluationResponse.fail_closed(
            reason="AI evaluator rate limit exceeded (60 calls/min)"
        )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = loop.run_in_executor(pool, provider.evaluate, request)
        try:
            result: EvaluationResponse = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return EvaluationResponse.fail_closed(
                reason=f"AI evaluator timed out after {timeout} seconds"
            )
        finally:
            _record_ai_latency((time.perf_counter() - started_at) * 1000)


async def evaluate_tool_with_ai(
    ctx: ToolRequestContext,
    provider: Provider | None,
    enabled: bool,
    timeout: int,
    fallback_action: str,
) -> PolicyDecision | None:
    """Run the AI evaluator for a tool request and return a :class:`PolicyDecision`.

    Returns ``None`` when the evaluator is disabled or no provider is given.
    On timeout or unexpected failure the *fallback_action* (``allow``,
    ``deny`` or ``ask``) controls the safe default.
    """
    if not enabled or provider is None:
        return None
    masked_params = _mask_evaluation_params(dict(ctx.params))
    safe_params = json.dumps(masked_params)[:500]
    is_local = isinstance(provider, LocalEvaluatorProvider)
    remote_params = masked_params if is_local else _strip_content_for_remote(masked_params)
    request = EvaluationRequest(
        prompt=f"Tool: {ctx.tool_name}\nParams: {safe_params}",
        tool_name=ctx.tool_name,
        tool_params=remote_params,
        context={"project_dir": ctx.project_dir or ""},
    )
    budget: TokenBudget | None = None
    budget_path = _budget_path_for_context(ctx)
    if not is_local:
        budget = load_budget(str(budget_path))
        if budget.is_exhausted:
            resp = EvaluationResponse(
                action=EvaluationAction.ASK,
                reason="AI evaluator token budget exhausted; requires approval",
            )
            decision = evaluation_response_to_policy_decision(resp, ctx=ctx)
            decision.metadata["ai_budget_exhausted"] = True
            decision.metadata["ai_budget_used"] = budget.used
            decision.metadata["ai_budget_monthly_limit"] = budget.monthly_limit
            return decision
    try:
        registry = get_hook_registry()
        prompt_context = {
            "prompt": request.prompt,
            "tool_name": request.tool_name,
            "params": request.tool_params,
        }
        prompt_result = registry.invoke_hooks(EventType.PROMPT_SEND, prompt_context)
        if not prompt_result.allow:
            return evaluation_response_to_policy_decision(
                EvaluationResponse(
                    action=EvaluationAction.DENY,
                    reason=prompt_result.message or "Prompt hooks denied",
                ),
                ctx=ctx,
            )
        if prompt_result.modified_params and "prompt" in prompt_result.modified_params:
            request.prompt = prompt_result.modified_params["prompt"]

        resp = await evaluate_with_timeout(provider, request, timeout=timeout)
        result_context = {"response": resp.to_dict(), "tool_name": request.tool_name}
        registry.invoke_hooks(EventType.RESULT_RECEIVE, result_context)
    except Exception:
        resp = EvaluationResponse.fail_closed(reason="AI evaluator failed unexpectedly")
    if budget is not None:
        tokens_used = resp.tokens_used or _estimate_evaluation_tokens(request, resp)
        budget.track_usage(tokens_used)
        try:
            save_budget(budget, str(budget_path))
        except OSError:
            pass

    is_fallback_trigger = resp.action == EvaluationAction.ASK and (
        resp.reason.startswith("AI evaluator timed out")
        or resp.reason.startswith("AI evaluator failed")
    )
    if is_fallback_trigger:
        if fallback_action == "deny":
            resp = EvaluationResponse(
                action=EvaluationAction.DENY,
                reason=f"AI evaluator fallback ({fallback_action}) after timeout/failure",
            )
        else:
            resp = EvaluationResponse(
                action=EvaluationAction.ASK,
                reason="AI evaluator fallback after timeout/failure; requires approval",
            )

    decision = evaluation_response_to_policy_decision(resp, ctx=ctx)
    latency = ai_latency_summary().get("last_ms")
    if latency is not None:
        decision.metadata["ai_evaluator_latency_ms"] = latency
    if budget is not None:
        decision.metadata["ai_budget_used"] = budget.used
        decision.metadata["ai_budget_monthly_limit"] = budget.monthly_limit
    return decision


def _budget_path_for_context(ctx: ToolRequestContext) -> Path:
    root = Path(ctx.project_dir).resolve() if ctx.project_dir else Path.cwd()
    return root / BUDGET_STORAGE_PATH


def _estimate_evaluation_tokens(request: EvaluationRequest, response: EvaluationResponse) -> float:
    payload = json.dumps(request.to_dict(), ensure_ascii=False, sort_keys=True)
    response_text = json.dumps(response.to_dict(), ensure_ascii=False, sort_keys=True)
    return float(max(1, (len(payload) + len(response_text) + 3) // 4))


# ---------------------------------------------------------------------------
# Token Budget Manager — automatic model routing based on task complexity
# ---------------------------------------------------------------------------


def measure_complexity(task: str, context: dict[str, Any]) -> float:
    """Measure task complexity score based on token count, file count, and recursion depth.

    The score is normalized to [0.0, 1.0].
    """
    token_count = len(task.split()) * 0.01
    file_count_score = float(context.get("file_count", 0)) * 0.05
    depth_score = float(context.get("nested_depth", 0)) * 0.1
    score = token_count + file_count_score + depth_score
    return min(score, 1.0)


def select_model(task: str, context: dict[str, Any]) -> str:
    """ "Select an AI model based on task complexity.

    User NEVER sees or selects models — routing is automatic only.

    :param task: The task description string.
    :param context: Additional context dict with keys like file_count, nested_depth.
    :returns: Model name string — one of claude-haiku, claude-sonnet, claude-opus.
    """
    complexity = measure_complexity(task, context)
    if complexity < 0.3:
        return "claude-haiku"
    elif complexity < 0.7:
        return "claude-sonnet"
    else:
        return "claude-opus"


# ---------------------------------------------------------------------------
# Token Budget — tracking and automatic rollback
# ---------------------------------------------------------------------------

BUDGET_WARNING = 80
BUDGET_LIMIT = 100
BUDGET_STORAGE_PATH = ".claude-bridge/budget.json"


@dataclass
class TokenBudget:
    """Token budget with warning thresholds and automatic essential model rollback."""

    monthly_limit: float = 100000
    used: float = 0
    warning_threshold: float = 0.80
    hard_limit: float = 1.0
    _warned_user: bool = field(default=False, repr=False)

    @property
    def usage_percent(self) -> float:
        return self.used / self.monthly_limit

    @property
    def is_warning(self) -> bool:
        return self.usage_percent >= self.warning_threshold

    @property
    def is_exhausted(self) -> bool:
        return self.usage_percent >= self.hard_limit

    def track_usage(self, tokens: float) -> None:
        self.used += tokens

    def auto_rollback_to_essential(self) -> str:
        """Called when budget exhausted - force essential model."""
        return "essential"

    def reset(self) -> None:
        self.used = 0
        self._warned_user = False


def _log_warning(message: str) -> None:
    import logging

    logging.warning(message)


def load_budget(path: str = BUDGET_STORAGE_PATH) -> TokenBudget:
    """Load budget from JSON file, returning a fresh budget if missing or invalid."""
    try:
        with open(path) as f:
            data = json.load(f)
        return TokenBudget(
            monthly_limit=data.get("monthly_limit", 100000),
            used=data.get("used", 0),
            warning_threshold=data.get("warning_threshold", 0.80),
            hard_limit=data.get("hard_limit", 1.0),
        )
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return TokenBudget()


def save_budget(budget: TokenBudget, path: str = BUDGET_STORAGE_PATH) -> None:
    """Persist budget state to JSON file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "monthly_limit": budget.monthly_limit,
        "used": budget.used,
        "warning_threshold": budget.warning_threshold,
        "hard_limit": budget.hard_limit,
    }
    with open(path, "w") as f:
        json.dump(data, f)


class _BudgetAwareEvaluator:
    """Wrapper that adds budget management to any provider."""

    def __init__(self, provider: Provider, budget: TokenBudget) -> None:
        self._provider = provider
        self._budget = budget

    async def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        """Evaluate with automatic budget management."""
        if self._budget.is_exhausted:
            return EvaluationResponse(
                action=EvaluationAction.ASK,
                reason="Token usage optimized automatically",
            )

        result = self._provider.evaluate(request)

        if hasattr(result, "tokens_used"):
            self._budget.track_usage(result.tokens_used)

        if self._budget.is_warning and not self._budget._warned_user:
            _log_warning(f"Token budget at {self._budget.usage_percent:.0%}")
            self._budget._warned_user = True

        return result


async def evaluate_with_budget(
    request: EvaluationRequest,
    provider: Provider,
    budget: TokenBudget,
) -> EvaluationResponse:
    """Evaluate a request with automatic budget tracking and essential model fallback."""
    wrapped = _BudgetAwareEvaluator(provider, budget)
    return await wrapped.evaluate(request)
