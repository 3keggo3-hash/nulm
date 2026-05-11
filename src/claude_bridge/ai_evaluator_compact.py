"""Optional AI Evaluator — typed models, provider interface, and strict JSON response parser."""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    PolicyDecision,
    RiskLevel,
    ToolRequestContext,
)
from claude_bridge.tool_utils import _mask_secrets

_AI_PROVIDER_MAX_RESPONSE_BYTES = 65536
_AI_LATENCY_SAMPLES_MS: deque[float] = deque(maxlen=100)
_A = "action"
_R = "reason"
_RR = "risk_reasons"
_OK = "ok"
_M = "model"
_U = "url"
_K = "key"
_V = "value"
_S = "schema_version"
_P = "prompt"
_TN = "tool_name"
_TP = "tool_params"
_CTX = "context"

_EVAL_SYS = "You are a security evaluator for a CLI tool bridge. Determine if the tool call is safe. Respond with JSON only: {\"action\": \"allow\"|\"deny\"|\"ask\", \"reason\": \"string\"}"


class _ResponseTruncatedError(Exception):
    pass


_RATE_LIMIT_CALLS = 60
_RATE_LIMIT_WINDOW_SEC = 60.0
_RATE_LIMIT_TOKENS: deque[float] = deque(maxlen=_RATE_LIMIT_CALLS)


class EvaluationAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class EvaluationRequest:
    prompt: str
    tool_name: str = ""
    tool_params: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {_P: self.prompt, _TN: self.tool_name, _TP: dict(self.tool_params), _CTX: dict(self.context)}

    def to_compact_dict(self) -> dict[str, Any]:
        return {_P: self.prompt[:200] if len(self.prompt) > 200 else self.prompt, _TN: self.tool_name, _TP: dict(self.tool_params), _CTX: dict(self.context)}


@dataclass
class EvaluationResponse:
    action: EvaluationAction
    reason: str = ""
    risk_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {_A: self.action.value, _R: self.reason, _RR: list(self.risk_reasons)}

    def to_compact_dict(self) -> dict[str, Any]:
        return {_A: self.action.value[0], _R: self.reason[:100] if len(self.reason) > 100 else self.reason, _RR: self.risk_reasons[:3]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationResponse:
        action_str = str(data.get(_A, "ask"))
        try:
            action = EvaluationAction(action_str.lower())
        except ValueError:
            action = EvaluationAction.ASK
        return cls(action=action, reason=str(data.get(_R, "")), risk_reasons=[str(r) for r in data.get(_RR, [])])

    @classmethod
    def fail_closed(cls, reason: str = "") -> EvaluationResponse:
        return cls(action=EvaluationAction.ASK, reason=reason)


@dataclass
class ProviderConfig:
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
        return f"ProviderConfig(model={self.model!r}, base_url={self.base_url!r}, api_key={self._masked_key()!r}, timeout={self.timeout}, extra={self.extra!r})"

    def __str__(self) -> str:
        return f"ProviderConfig(model={self.model}, base_url={self.base_url}, api_key={self._masked_key()}, timeout={self.timeout})"

    def to_dict(self) -> dict[str, Any]:
        return {_M: self.model, _U: self.base_url, "timeout": self.timeout, "extra": dict(self.extra)}


class Provider(ABC):
    @abstractmethod
    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        ...


_VALID_ACTIONS: frozenset[str] = frozenset(e.value for e in EvaluationAction)


def _record_ai_latency(duration_ms: float) -> None:
    _AI_LATENCY_SAMPLES_MS.append(duration_ms)


def reset_ai_latency_samples() -> None:
    _AI_LATENCY_SAMPLES_MS.clear()


def _check_rate_limit() -> bool:
    now = time.monotonic()
    while _RATE_LIMIT_TOKENS and now - _RATE_LIMIT_TOKENS[0] >= _RATE_LIMIT_WINDOW_SEC:
        _RATE_LIMIT_TOKENS.popleft()
    if len(_RATE_LIMIT_TOKENS) < _RATE_LIMIT_CALLS:
        _RATE_LIMIT_TOKENS.append(now)
        return True
    return False


def ai_latency_summary() -> dict[str, Any]:
    samples = list(_AI_LATENCY_SAMPLES_MS)
    if not samples:
        return {"sample_count": 0, "last_ms": None, "avg_ms": None, "p95_ms": None}
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))
    return {"sample_count": len(samples), "last_ms": round(samples[-1], 3), "avg_ms": round(sum(samples) / len(samples), 3), "p95_ms": round(ordered[p95_index], 3)}


def parse_evaluation_response(raw: str) -> EvaluationResponse:
    try:
        data: Any = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return EvaluationResponse.fail_closed(reason="Failed to parse evaluation response: invalid JSON")

    if not isinstance(data, dict):
        return EvaluationResponse.fail_closed(reason="Failed to parse evaluation response: expected a JSON object")

    action_raw = data.get(_A)
    if action_raw is None:
        return EvaluationResponse.fail_closed(reason="Evaluation response missing 'action' field")

    if not isinstance(action_raw, str):
        return EvaluationResponse.fail_closed(reason="Evaluation response 'action' must be a string")

    action_lower = action_raw.lower()
    if action_lower not in _VALID_ACTIONS:
        return EvaluationResponse(action=EvaluationAction.ASK, reason=f"Unknown action '{action_raw}'; defaulting to ask", risk_reasons=[f"unrecognized_action: {action_raw}"])

    action = EvaluationAction(action_lower)
    reason_raw = data.get(_R)
    reason = "" if reason_raw is None else (reason_raw if isinstance(reason_raw, str) else str(reason_raw))

    risk_reasons_raw = data.get(_RR, [])
    risk_reasons = [str(r) for r in risk_reasons_raw if isinstance(r, str)] if isinstance(risk_reasons_raw, list) else []

    return EvaluationResponse(action=action, reason=reason, risk_reasons=risk_reasons)


_MASKED_CONTENT_FIELDS = {"content", "search", "replace", "command", "url", "path"}


def _mask_evaluation_params(params: dict[str, Any]) -> dict[str, Any]:
    masked: dict[str, Any] = {}
    for k, v in params.items():
        masked_v = _mask_secrets(v)
        if isinstance(masked_v, str) and len(masked_v) > 150:
            masked_v = masked_v[:150] + "..."
        if k in _MASKED_CONTENT_FIELDS and isinstance(masked_v, str) and len(masked_v) > 60:
            masked_v = masked_v[:60] + "...[masked]"
        masked[k] = masked_v
    return masked


def create_provider(
    provider_name: str,
    *,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    timeout: int = 30,
) -> Provider:
    if provider_name == "local":
        return LocalEvaluatorProvider()
    if provider_name == "anthropic":
        key = (api_key or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
        if not key:
            raise ValueError("Anthropic provider requires an API key (set ANTHROPIC_API_KEY or ai_evaluator_api_key)")
        return AnthropicProvider(api_key=key, model=model or "claude-3-haiku-20240307", timeout=timeout)
    if provider_name == "openai":
        key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
        if not key:
            raise ValueError("OpenAI provider requires an API key (set OPENAI_API_KEY or ai_evaluator_api_key)")
        return OpenAIProvider(api_key=key, model=model or "gpt-4o-mini", timeout=timeout)
    if provider_name == "ollama":
        return OllamaProvider(base_url=(base_url or "http://localhost:11434").strip(), model=model or "llama3", timeout=timeout)
    if provider_name == "deepseek":
        key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
        if not key:
            raise ValueError("DeepSeek provider requires an API key (set DEEPSEEK_API_KEY or ai_evaluator_api_key)")
        return DeepSeekProvider(api_key=key, model=model or "deepseek-chat", timeout=timeout)
    raise ValueError(f"Unknown provider: {provider_name!r}")


class LocalEvaluatorProvider(Provider):
    def __init__(
        self,
        *,
        deny_patterns: list[str] | None = None,
        ask_patterns: list[str] | None = None,
    ) -> None:
        self._deny_raw = list(deny_patterns or [])
        self._ask_raw = list(ask_patterns or [])
        self._deny = [re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE) for p in self._deny_raw]
        self._ask = [re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE) for p in self._ask_raw]

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        for i, pattern in enumerate(self._deny):
            if pattern.search(request.prompt):
                return EvaluationResponse(action=EvaluationAction.DENY, reason=f"Local evaluator matched deny pattern: {self._deny_raw[i]}", risk_reasons=[f"matched_deny_pattern: {self._deny_raw[i]}"])
        for i, pattern in enumerate(self._ask):
            if pattern.search(request.prompt):
                return EvaluationResponse(action=EvaluationAction.ASK, reason=f"Local evaluator matched ask pattern: {self._ask_raw[i]}", risk_reasons=[f"matched_ask_pattern: {self._ask_raw[i]}"])
        return EvaluationResponse(action=EvaluationAction.ALLOW, reason="Local evaluator found no concerning patterns", risk_reasons=[])


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


def _build_eval_body(model: str, prompt: str, max_tokens: int = 256) -> dict[str, Any]:
    return {"model": model, "max_tokens": max_tokens, "system": _EVAL_SYS, "messages": [{"role": "user", "content": prompt}]}


def _build_chat_body(model: str, prompt: str, max_tokens: int = 256) -> dict[str, Any]:
    return {"model": model, "max_tokens": max_tokens, "messages": [{"role": "system", "content": _EVAL_SYS}, {"role": "user", "content": prompt}]}


class AnthropicProvider(Provider):
    def __init__(self, api_key: str, model: str = "claude-3-haiku-20240307", timeout: int = 30):
        self.api_key = api_key.strip()
        self.model = model
        self.timeout = timeout
        self._endpoint = "https://api.anthropic.com/v1/messages"

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        body = json.dumps(_build_eval_body(self.model, request.prompt)).encode("utf-8")
        try:
            return self._call_api(body)
        except _ResponseTruncatedError:
            return EvaluationResponse.fail_closed(reason="AI evaluator response truncated (exceeded 65536 bytes)")
        except Exception as exc:
            return EvaluationResponse.fail_closed(reason=_provider_error_reason("Anthropic", exc))

    def _call_api(self, body: bytes) -> EvaluationResponse:
        req = urllib.request.Request(self._endpoint, data=body, headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw_read = resp.read(_AI_PROVIDER_MAX_RESPONSE_BYTES)
            if len(raw_read) >= _AI_PROVIDER_MAX_RESPONSE_BYTES:
                raise _ResponseTruncatedError(f"Response exceeded {_AI_PROVIDER_MAX_RESPONSE_BYTES} bytes")
            data = json.loads(raw_read.decode("utf-8"))
        content = data.get("content", [{}])[0].get("text", "{}")
        return _parse_json_response(content)


class OpenAIProvider(Provider):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", timeout: int = 30):
        self.api_key = api_key.strip()
        self.model = model
        self.timeout = timeout
        self._endpoint = "https://api.openai.com/v1/chat/completions"

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        body = json.dumps(_build_chat_body(self.model, request.prompt)).encode("utf-8")
        try:
            return self._call_api(body)
        except _ResponseTruncatedError:
            return EvaluationResponse.fail_closed(reason="AI evaluator response truncated (exceeded 65536 bytes)")
        except Exception as exc:
            return EvaluationResponse.fail_closed(reason=_provider_error_reason("OpenAI", exc))

    def _call_api(self, body: bytes) -> EvaluationResponse:
        req = urllib.request.Request(self._endpoint, data=body, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw_read = resp.read(_AI_PROVIDER_MAX_RESPONSE_BYTES)
            if len(raw_read) >= _AI_PROVIDER_MAX_RESPONSE_BYTES:
                raise _ResponseTruncatedError(f"Response exceeded {_AI_PROVIDER_MAX_RESPONSE_BYTES} bytes")
            data = json.loads(raw_read.decode("utf-8"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return _parse_json_response(content)


def _validate_provider_url(url: str) -> None:
    from urllib.parse import urlparse as _urlparse

    parsed = _urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Invalid provider URL: {url!r}")
    from claude_bridge.url_tools import _is_private_host, _resolve_and_check_host

    if _is_private_host(hostname):
        raise ValueError(f"Provider URL hostname is blocked (private/internal): {hostname}")
    private_ip = _resolve_and_check_host(hostname)
    if private_ip is not None:
        raise ValueError(f"Provider URL hostname resolves to internal IP: {private_ip}")


class OllamaProvider(Provider):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3", timeout: int = 30):
        _validate_provider_url(base_url)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._endpoint = f"{self.base_url}/api/generate"

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        body = json.dumps({"model": self.model, "prompt": _EVAL_SYS + "\n\nTool request: " + request.prompt, "stream": False}).encode("utf-8")
        try:
            return self._call_api(body)
        except _ResponseTruncatedError:
            return EvaluationResponse.fail_closed(reason="AI evaluator response truncated (exceeded 65536 bytes)")
        except Exception as exc:
            return EvaluationResponse.fail_closed(reason=_provider_error_reason("Ollama", exc))

    def _call_api(self, body: bytes) -> EvaluationResponse:
        req = urllib.request.Request(self._endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw_read = resp.read(_AI_PROVIDER_MAX_RESPONSE_BYTES)
            if len(raw_read) >= _AI_PROVIDER_MAX_RESPONSE_BYTES:
                raise _ResponseTruncatedError(f"Response exceeded {_AI_PROVIDER_MAX_RESPONSE_BYTES} bytes")
            data = json.loads(raw_read.decode("utf-8"))
        content = data.get("response", "{}")
        return _parse_json_response(content)


class DeepSeekProvider(Provider):
    def __init__(self, api_key: str, model: str = "deepseek-chat", timeout: int = 30):
        self.api_key = api_key.strip()
        self.model = model
        self.timeout = timeout
        self._endpoint = "https://api.deepseek.com/v1/chat/completions"

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        body = json.dumps(_build_chat_body(self.model, request.prompt)).encode("utf-8")
        try:
            return self._call_api(body)
        except _ResponseTruncatedError:
            return EvaluationResponse.fail_closed(reason="AI evaluator response truncated (exceeded 65536 bytes)")
        except Exception as exc:
            return EvaluationResponse.fail_closed(reason=_provider_error_reason("DeepSeek", exc))

    def _call_api(self, body: bytes) -> EvaluationResponse:
        req = urllib.request.Request(self._endpoint, data=body, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw_read = resp.read(_AI_PROVIDER_MAX_RESPONSE_BYTES)
            if len(raw_read) >= _AI_PROVIDER_MAX_RESPONSE_BYTES:
                raise _ResponseTruncatedError(f"Response exceeded {_AI_PROVIDER_MAX_RESPONSE_BYTES} bytes")
            data = json.loads(raw_read.decode("utf-8"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return _parse_json_response(content)


def _parse_json_response(text: str) -> EvaluationResponse:
    return parse_evaluation_response(text.strip())


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


def evaluation_response_to_policy_decision(response: EvaluationResponse, ctx: ToolRequestContext | None = None) -> PolicyDecision:
    action = _EVAL_ACTION_TO_DECISION.get(response.action, DecisionAction.ASK)
    risk_level = _RISK_FROM_EVAL_ACTION.get(response.action, RiskLevel.MEDIUM)
    metadata: dict[str, Any] = {"ai_reason": response.reason}
    if ctx is not None:
        metadata["tool_name"] = ctx.tool_name
    return PolicyDecision(action=action, source=DecisionSource.AI, risk_level=risk_level, reason=response.reason, risk_reasons=list(response.risk_reasons), metadata=metadata)


async def evaluate_with_timeout(provider: Provider, request: EvaluationRequest, timeout: float) -> EvaluationResponse:
    loop = asyncio.get_running_loop()
    started_at = time.perf_counter()
    if not _check_rate_limit():
        return EvaluationResponse.fail_closed(reason="AI evaluator rate limit exceeded (60 calls/min)")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = loop.run_in_executor(pool, provider.evaluate, request)
        try:
            result: EvaluationResponse = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return EvaluationResponse.fail_closed(reason=f"AI evaluator timed out after {timeout} seconds")
        finally:
            _record_ai_latency((time.perf_counter() - started_at) * 1000)


async def evaluate_tool_with_ai(
    ctx: ToolRequestContext,
    provider: Provider | None,
    enabled: bool,
    timeout: int,
    fallback_action: str,
) -> PolicyDecision | None:
    if not enabled or provider is None:
        return None
    masked_params = _mask_evaluation_params(dict(ctx.params))
    safe_params = json.dumps(masked_params)[:400]
    request = EvaluationRequest(prompt=f"Tool: {ctx.tool_name}\nParams: {safe_params}", tool_name=ctx.tool_name, tool_params=masked_params, context={"project_dir": ctx.project_dir or ""})
    try:
        resp = await evaluate_with_timeout(provider, request, timeout=timeout)
    except Exception:
        resp = EvaluationResponse.fail_closed(reason="AI evaluator failed unexpectedly")

    is_fallback_trigger = resp.action == EvaluationAction.ASK and (resp.reason.startswith("AI evaluator timed out") or resp.reason.startswith("AI evaluator failed"))
    if is_fallback_trigger:
        if fallback_action == "deny":
            resp = EvaluationResponse(action=EvaluationAction.DENY, reason=f"AI evaluator fallback ({fallback_action}) after timeout/failure")
        else:
            resp = EvaluationResponse(action=EvaluationAction.ASK, reason="AI evaluator fallback after timeout/failure; requires approval")

    decision = evaluation_response_to_policy_decision(resp, ctx=ctx)
    latency = ai_latency_summary().get("last_ms")
    if latency is not None:
        decision.metadata["ai_evaluator_latency_ms"] = latency
    return decision


def evaluation_response_to_policy_decision_compact(response: EvaluationResponse, ctx: ToolRequestContext | None = None) -> PolicyDecision:
    action = _EVAL_ACTION_TO_DECISION.get(response.action, DecisionAction.ASK)
    risk_level = _RISK_FROM_EVAL_ACTION.get(response.action, RiskLevel.MEDIUM)
    metadata: dict[str, Any] = {"ai_r": response.reason[:80]}
    if ctx is not None:
        metadata["tn"] = ctx.tool_name
    return PolicyDecision(action=action, source=DecisionSource.AI, risk_level=risk_level, reason=response.reason, risk_reasons=list(response.risk_reasons), metadata=metadata)


async def evaluate_tool_with_ai_compact(
    ctx: ToolRequestContext,
    provider: Provider | None,
    enabled: bool,
    timeout: int,
    fallback_action: str,
) -> PolicyDecision | None:
    if not enabled or provider is None:
        return None
    masked_params = _mask_evaluation_params(dict(ctx.params))
    request = EvaluationRequest(prompt=f"T:{ctx.tool_name} P:{json.dumps(masked_params)[:300]}", tool_name=ctx.tool_name, tool_params=masked_params, context={"pd": ctx.project_dir or ""})
    try:
        resp = await evaluate_with_timeout(provider, request, timeout=timeout)
    except Exception:
        resp = EvaluationResponse.fail_closed(reason="AI evaluator failed unexpectedly")

    is_fallback_trigger = resp.action == EvaluationAction.ASK and (resp.reason.startswith("AI evaluator timed out") or resp.reason.startswith("AI evaluator failed"))
    if is_fallback_trigger:
        if fallback_action == "deny":
            resp = EvaluationResponse(action=EvaluationAction.DENY, reason=f"AI evaluator fallback ({fallback_action}) after timeout/failure")
        else:
            resp = EvaluationResponse(action=EvaluationAction.ASK, reason="AI evaluator fallback after timeout/failure; requires approval")

    decision = evaluation_response_to_policy_decision_compact(resp, ctx=ctx)
    latency = ai_latency_summary().get("last_ms")
    if latency is not None:
        decision.metadata["lat_ms"] = latency
    return decision