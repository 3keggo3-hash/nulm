"""Bridge-internal AI provider routing for advisory workflows."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

_MAX_MODEL_RESPONSE_BYTES = 131072
_DEFAULT_TIMEOUT = 30
_ALLOWED_PROVIDERS = {"local", "openai", "anthropic", "deepseek", "ollama"}


@dataclass(frozen=True)
class AIModelProfile:
    """Named model/provider profile without storing secret values."""

    name: str
    provider: str = "local"
    model: str = ""
    api_key_env: str = ""
    base_url: str = ""
    timeout: int = _DEFAULT_TIMEOUT
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_redacted_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "tags": list(self.tags),
            "has_api_key": bool(self.api_key_env and os.environ.get(self.api_key_env, "")),
        }


@dataclass(frozen=True)
class AIRoutingRule:
    """Keyword-based profile routing rule."""

    name: str
    profile: str
    keywords: tuple[str, ...] = field(default_factory=tuple)
    task_types: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AIRouteDecision:
    """Selected AI profile plus routing metadata."""

    profile_name: str
    provider: str
    model: str
    mode: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile_name,
            "provider": self.provider,
            "model": self.model,
            "mode": self.mode,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AIModelResponse:
    """Text response from a routed provider call."""

    ok: bool
    text: str
    decision: AIRouteDecision
    duration_ms: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "text": self.text,
            "route": self.decision.to_dict(),
            "duration_ms": round(self.duration_ms, 3),
            "error": self.error,
        }


def _coerce_str_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def parse_model_profiles(raw: Any) -> dict[str, AIModelProfile]:
    """Parse model profile config into named profiles."""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("ai_model_profiles must be valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("ai_model_profiles must be a dict")
    profiles: dict[str, AIModelProfile] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError("ai_model_profiles keys must be non-empty strings")
        if not isinstance(value, dict):
            raise ValueError(f"ai_model_profiles[{name}] must be a dict")
        provider = str(value.get("provider", "local")).lower()
        if provider not in _ALLOWED_PROVIDERS:
            raise ValueError(f"ai_model_profiles[{name}].provider is unsupported")
        timeout = int(value.get("timeout", _DEFAULT_TIMEOUT))
        if timeout <= 0:
            raise ValueError(f"ai_model_profiles[{name}].timeout must be positive")
        profiles[name] = AIModelProfile(
            name=name,
            provider=provider,
            model=str(value.get("model", "")),
            api_key_env=str(value.get("api_key_env", "")),
            base_url=str(value.get("base_url", "")),
            timeout=timeout,
            tags=_coerce_str_list(value.get("tags", [])),
        )
    return profiles


def parse_routing_rules(raw: Any) -> list[AIRoutingRule]:
    """Parse routing rules from JSON-compatible config."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("ai_routing_rules must be valid JSON") from exc
    if not isinstance(raw, list):
        raise ValueError("ai_routing_rules must be a list")
    rules: list[AIRoutingRule] = []
    for index, value in enumerate(raw):
        if not isinstance(value, dict):
            raise ValueError(f"ai_routing_rules[{index}] must be a dict")
        profile = str(value.get("profile", "")).strip()
        if not profile:
            raise ValueError(f"ai_routing_rules[{index}].profile is required")
        rules.append(
            AIRoutingRule(
                name=str(value.get("name", f"rule_{index}")),
                profile=profile,
                keywords=_coerce_str_list(value.get("keywords", [])),
                task_types=_coerce_str_list(value.get("task_types", [])),
            )
        )
    return rules


def _default_profiles() -> dict[str, AIModelProfile]:
    return {
        "local": AIModelProfile(name="local", provider="local", tags=("fallback",)),
        "fast": AIModelProfile(
            name="fast",
            provider="openai",
            model="gpt-4o-mini",
            api_key_env="OPENAI_API_KEY",
            tags=("fast", "low-cost"),
        ),
        "deep": AIModelProfile(
            name="deep",
            provider="anthropic",
            model="claude-3-5-sonnet-latest",
            api_key_env="ANTHROPIC_API_KEY",
            tags=("deep", "reasoning"),
        ),
    }


class AIModelRouter:
    """Select and call Bridge-internal AI model profiles."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        mode: str = "auto",
        default_profile: str = "local",
        profiles: dict[str, AIModelProfile] | None = None,
        rules: list[AIRoutingRule] | None = None,
    ) -> None:
        self.enabled = enabled
        self.mode = mode
        self.default_profile = default_profile
        self.profiles = profiles or _default_profiles()
        self.rules = rules or []

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> AIModelRouter:
        profiles = _default_profiles()
        profiles.update(parse_model_profiles(config.get("ai_model_profiles", {})))
        rules = parse_routing_rules(config.get("ai_routing_rules", []))
        return cls(
            enabled=bool(config.get("ai_routing_enabled", False)),
            mode=str(config.get("ai_routing_mode", "auto")),
            default_profile=str(config.get("ai_default_model_profile", "local")),
            profiles=profiles,
            rules=rules,
        )

    def select_profile(self, task: str, context: dict[str, Any] | None = None) -> AIRouteDecision:
        context = dict(context or {})
        mode = "off" if not self.enabled else self.mode
        profile_name = self.default_profile if self.default_profile in self.profiles else "local"
        reason = "default profile"

        if mode == "off":
            profile_name = "local"
            reason = "AI routing disabled"
        elif mode == "rules":
            matched = self._match_rule(task, context)
            if matched is not None:
                profile_name = matched.profile
                reason = f"matched rule: {matched.name}"
        elif mode == "auto":
            matched = self._match_rule(task, context)
            if matched is not None:
                profile_name = matched.profile
                reason = f"matched rule: {matched.name}"
            else:
                profile_name = self._auto_profile(task, context)
                reason = "auto complexity routing"
        elif mode != "manual":
            profile_name = "local"
            reason = f"unsupported routing mode {mode!r}; using local"

        profile = self.profiles.get(profile_name, self.profiles["local"])
        return AIRouteDecision(
            profile_name=profile.name,
            provider=profile.provider,
            model=profile.model,
            mode=mode,
            reason=reason,
        )

    def generate_text(
        self,
        prompt: str,
        *,
        task: str = "",
        context: dict[str, Any] | None = None,
        profile_name: str = "auto",
        max_tokens: int = 700,
    ) -> AIModelResponse:
        started_at = time.perf_counter()
        decision = self.select_profile(task or prompt, context)
        if profile_name != "auto" and profile_name in self.profiles:
            profile = self.profiles[profile_name]
            decision = AIRouteDecision(
                profile_name=profile.name,
                provider=profile.provider,
                model=profile.model,
                mode="manual",
                reason="explicit profile",
            )
        else:
            profile = self.profiles.get(decision.profile_name, self.profiles["local"])
        try:
            text = self._call_profile(profile, prompt, max_tokens=max_tokens)
            return AIModelResponse(
                ok=True,
                text=text,
                decision=decision,
                duration_ms=(time.perf_counter() - started_at) * 1000,
            )
        except Exception as exc:
            fallback = self.profiles["local"]
            fallback_decision = AIRouteDecision(
                profile_name=fallback.name,
                provider=fallback.provider,
                model=fallback.model,
                mode="fallback",
                reason=f"{profile.name} failed: {_provider_error_reason(exc)}",
            )
            return AIModelResponse(
                ok=False,
                text=_local_response(prompt),
                decision=fallback_decision,
                duration_ms=(time.perf_counter() - started_at) * 1000,
                error=_provider_error_reason(exc),
            )

    def _match_rule(self, task: str, context: dict[str, Any]) -> AIRoutingRule | None:
        haystack = " ".join([task, str(context.get("task_type", "")), str(context.get("role", ""))])
        haystack = haystack.lower()
        for rule in self.rules:
            if rule.profile not in self.profiles:
                continue
            if any(keyword.lower() in haystack for keyword in rule.keywords):
                return rule
            if str(context.get("task_type", "")).lower() in {t.lower() for t in rule.task_types}:
                return rule
        return None

    def _auto_profile(self, task: str, context: dict[str, Any]) -> str:
        complexity = len(task.split()) + int(context.get("file_count", 0)) * 5
        role = str(context.get("role", "")).lower()
        if any(
            word in task.lower() or word in role for word in ("security", "architecture", "risk")
        ):
            return "deep" if self._profile_ready("deep") else "local"
        if complexity > 120 and self._profile_ready("deep"):
            return "deep"
        if self._profile_ready("fast"):
            return "fast"
        return self.default_profile if self._profile_ready(self.default_profile) else "local"

    def _profile_ready(self, name: str) -> bool:
        profile = self.profiles.get(name)
        if profile is None:
            return False
        if profile.provider in {"local", "ollama"}:
            return True
        return bool(profile.api_key_env and os.environ.get(profile.api_key_env, ""))

    def _call_profile(self, profile: AIModelProfile, prompt: str, *, max_tokens: int) -> str:
        if profile.provider == "local":
            return _local_response(prompt)
        if profile.provider == "openai":
            return _call_openai(profile, prompt, max_tokens=max_tokens)
        if profile.provider == "anthropic":
            return _call_anthropic(profile, prompt, max_tokens=max_tokens)
        if profile.provider == "deepseek":
            return _call_chat_completions(
                profile,
                prompt,
                endpoint="https://api.deepseek.com/v1/chat/completions",
                default_model="deepseek-chat",
                max_tokens=max_tokens,
            )
        if profile.provider == "ollama":
            return _call_ollama(profile, prompt, max_tokens=max_tokens)
        raise ValueError(f"Unsupported provider: {profile.provider}")


def _provider_error_reason(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"connection error: {exc.reason}"
    return str(exc)


def _api_key(profile: AIModelProfile, default_env: str) -> str:
    env_name = profile.api_key_env or default_env
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise ValueError(f"{profile.name} requires API key env var {env_name}")
    return key


def _read_json_response(req: urllib.request.Request, timeout: int) -> dict[str, Any]:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(_MAX_MODEL_RESPONSE_BYTES)
        if len(raw) >= _MAX_MODEL_RESPONSE_BYTES:
            raise ValueError("model response exceeded maximum size")
        data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("model response was not a JSON object")
    return data


def _call_chat_completions(
    profile: AIModelProfile,
    prompt: str,
    *,
    endpoint: str,
    default_model: str,
    max_tokens: int,
) -> str:
    key = _api_key(profile, "OPENAI_API_KEY")
    body = json.dumps(
        {
            "model": profile.model or default_model,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a concise engineering council member. Return plain text.",
                },
                {"role": "user", "content": prompt},
            ],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    data = _read_json_response(req, profile.timeout)
    return str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()


def _call_openai(profile: AIModelProfile, prompt: str, *, max_tokens: int) -> str:
    endpoint = (
        (profile.base_url.rstrip("/") + "/chat/completions")
        if profile.base_url
        else ("https://api.openai.com/v1/chat/completions")
    )
    return _call_chat_completions(
        profile,
        prompt,
        endpoint=endpoint,
        default_model="gpt-4o-mini",
        max_tokens=max_tokens,
    )


def _call_anthropic(profile: AIModelProfile, prompt: str, *, max_tokens: int) -> str:
    key = _api_key(profile, "ANTHROPIC_API_KEY")
    endpoint = (
        profile.base_url.rstrip("/")
        if profile.base_url
        else "https://api.anthropic.com/v1/messages"
    )
    body = json.dumps(
        {
            "model": profile.model or "claude-3-5-sonnet-latest",
            "max_tokens": max_tokens,
            "system": "You are a concise engineering council member. Return plain text.",
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    data = _read_json_response(req, profile.timeout)
    content = data.get("content", [{}])
    if isinstance(content, list) and content:
        return str(content[0].get("text", "")).strip()
    return ""


def _call_ollama(profile: AIModelProfile, prompt: str, *, max_tokens: int) -> str:
    endpoint = (profile.base_url or "http://localhost:11434").rstrip("/") + "/api/generate"
    body = json.dumps(
        {
            "model": profile.model or "llama3",
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    data = _read_json_response(req, profile.timeout)
    return str(data.get("response", "")).strip()


def _local_response(prompt: str) -> str:
    first_line = next((line.strip() for line in prompt.splitlines() if line.strip()), "")
    return (
        "Local deterministic council fallback. "
        f"Focus on: {first_line[:180]}. "
        "Prefer a small plan, explicit risks, and existing approval-gated tools."
    )


def router_status(router: AIModelRouter) -> dict[str, Any]:
    return {
        "enabled": router.enabled,
        "mode": router.mode,
        "default_profile": router.default_profile,
        "profiles": {
            name: profile.to_redacted_dict() for name, profile in sorted(router.profiles.items())
        },
        "rules": [
            {
                "name": rule.name,
                "profile": rule.profile,
                "keywords": list(rule.keywords),
                "task_types": list(rule.task_types),
            }
            for rule in router.rules
        ],
    }
