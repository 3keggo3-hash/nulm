"""Bridge-internal AI provider routing for advisory workflows."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

_MAX_MODEL_RESPONSE_BYTES = 131072
_DEFAULT_TIMEOUT = 30
_OPENAI_COMPAT_PROVIDERS: dict[str, dict[str, str]] = {
    "openai": {
        "env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        "endpoint": "https://api.openai.com/v1/chat/completions",
    },
    "deepseek": {
        "env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "endpoint": "https://api.deepseek.com/v1/chat/completions",
    },
    "minimax": {
        "env": "MINIMAX_API_KEY",
        "default_model": "MiniMax-M2.5",
        "endpoint": "https://api.minimax.io/v1/chat/completions",
    },
    "google": {
        "env": "GEMINI_API_KEY",
        "default_model": "gemini-2.5-flash",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    },
    "groq": {
        "env": "GROQ_API_KEY",
        "default_model": "llama-3.1-8b-instant",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
    },
    "mistral": {
        "env": "MISTRAL_API_KEY",
        "default_model": "mistral-small-latest",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
    },
    "xai": {
        "env": "XAI_API_KEY",
        "default_model": "grok-4.3",
        "endpoint": "https://api.x.ai/v1/chat/completions",
    },
    "together": {
        "env": "TOGETHER_API_KEY",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "endpoint": "https://api.together.xyz/v1/chat/completions",
    },
    "openrouter": {
        "env": "OPENROUTER_API_KEY",
        "default_model": "openai/gpt-4o-mini",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
    },
    "perplexity": {
        "env": "PERPLEXITY_API_KEY",
        "default_model": "sonar-pro",
        "endpoint": "https://api.perplexity.ai/chat/completions",
    },
    "fireworks": {
        "env": "FIREWORKS_API_KEY",
        "default_model": "accounts/fireworks/models/llama-v3p1-8b-instruct",
        "endpoint": "https://api.fireworks.ai/inference/v1/chat/completions",
    },
}
_ALLOWED_PROVIDERS = {
    "local",
    "anthropic",
    "cohere",
    "ollama",
    *_OPENAI_COMPAT_PROVIDERS,
}
_ALLOWED_QUALITY_TIERS = {"local", "cheap", "balanced", "deep"}
_HIGH_RISK_TERMS = (
    "security",
    "approval",
    "shell",
    "destructive",
    "policy",
    "architecture",
    "risk",
    "secret",
    "secrets",
    "path boundary",
    "path boundaries",
)
_SIMPLE_TASK_TERMS = ("summarize", "summary", "explain", "classify", "describe")
_ROUTE_DECISION_SCHEMA_VERSION = "ai_route_decision.v1"


_route_telemetry_lock = threading.Lock()
_route_telemetry: dict[str, Any] = {
    "total_route_decisions": 0,
    "selected_local_count": 0,
    "selected_remote_count": 0,
    "fallback_count": 0,
    "provider_failure_count": 0,
    "timeout_count": 0,
    "selection_count_by_mode": {},
}


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
    input_cost_per_mtok: float = 0.0
    output_cost_per_mtok: float = 0.0
    quality_tier: str = "local"
    max_output_tokens: int = 0

    def to_redacted_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "tags": list(self.tags),
            "input_cost_per_mtok": self.input_cost_per_mtok,
            "output_cost_per_mtok": self.output_cost_per_mtok,
            "quality_tier": self.quality_tier,
            "max_output_tokens": self.max_output_tokens,
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
    quality_tier: str = "local"
    estimated_input_tokens: int = 0
    effective_max_tokens: int = 0
    estimated_max_cost_usd: float = 0.0
    schema_version: str = _ROUTE_DECISION_SCHEMA_VERSION
    selected_profile: str = ""
    candidate_profiles: tuple[str, ...] = ()
    rejected_profiles: tuple[dict[str, str], ...] = ()
    route_reason: str = ""
    fallback_reason: str = ""
    fallback_from_profile: str = ""
    fallback_status: str = "none"
    timeout_seconds: int = 0
    provider_error: str = ""
    provider_error_class: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile_name,
            "profile_name": self.profile_name,
            "provider": self.provider,
            "model": self.model,
            "mode": self.mode,
            "reason": self.reason,
            "quality_tier": self.quality_tier,
            "estimated_input_tokens": self.estimated_input_tokens,
            "effective_max_tokens": self.effective_max_tokens,
            "estimated_max_cost_usd": round(self.estimated_max_cost_usd, 8),
            "selected_profile": self.selected_profile or self.profile_name,
            "candidate_profiles": list(self.candidate_profiles),
            "rejected_profiles": [dict(item) for item in self.rejected_profiles],
            "route_reason": self.route_reason or self.reason,
            "fallback_reason": self.fallback_reason,
            "fallback_from_profile": self.fallback_from_profile,
            "fallback_status": self.fallback_status,
            "timeout_seconds": self.timeout_seconds,
            "provider_error": self.provider_error,
            "provider_error_class": self.provider_error_class,
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
        input_cost_per_mtok = float(value.get("input_cost_per_mtok", 0.0))
        output_cost_per_mtok = float(value.get("output_cost_per_mtok", 0.0))
        if input_cost_per_mtok < 0:
            raise ValueError(f"ai_model_profiles[{name}].input_cost_per_mtok must be non-negative")
        if output_cost_per_mtok < 0:
            raise ValueError(f"ai_model_profiles[{name}].output_cost_per_mtok must be non-negative")
        quality_tier = str(value.get("quality_tier", "local")).lower()
        if quality_tier not in _ALLOWED_QUALITY_TIERS:
            raise ValueError(f"ai_model_profiles[{name}].quality_tier is unsupported")
        max_output_tokens = int(value.get("max_output_tokens", 0))
        if max_output_tokens < 0:
            raise ValueError(f"ai_model_profiles[{name}].max_output_tokens must be non-negative")
        profiles[name] = AIModelProfile(
            name=name,
            provider=provider,
            model=str(value.get("model", "")),
            api_key_env=str(value.get("api_key_env", "")),
            base_url=str(value.get("base_url", "")),
            timeout=timeout,
            tags=_coerce_str_list(value.get("tags", [])),
            input_cost_per_mtok=input_cost_per_mtok,
            output_cost_per_mtok=output_cost_per_mtok,
            quality_tier=quality_tier,
            max_output_tokens=max_output_tokens,
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
            input_cost_per_mtok=0.15,
            output_cost_per_mtok=0.60,
            quality_tier="cheap",
            max_output_tokens=400,
        ),
        "balanced": AIModelProfile(
            name="balanced",
            provider="openai",
            model="gpt-4o",
            api_key_env="OPENAI_API_KEY",
            tags=("balanced", "quality"),
            input_cost_per_mtok=2.5,
            output_cost_per_mtok=10.0,
            quality_tier="balanced",
            max_output_tokens=800,
        ),
        "deep": AIModelProfile(
            name="deep",
            provider="anthropic",
            model="claude-3-5-sonnet-latest",
            api_key_env="ANTHROPIC_API_KEY",
            tags=("deep", "reasoning"),
            input_cost_per_mtok=3.0,
            output_cost_per_mtok=15.0,
            quality_tier="deep",
            max_output_tokens=1000,
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
        decision = self._select_profile_decision(task, context)
        _record_route_decision(decision)
        return decision

    def _select_profile_decision(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> AIRouteDecision:
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
        return _route_decision(
            profile,
            mode=mode,
            reason=reason,
            prompt=task,
            max_tokens=0,
            candidate_profiles=_candidate_profile_names(self.profiles),
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
        decision = self._select_profile_decision(task or prompt, context)
        if profile_name != "auto" and profile_name in self.profiles:
            profile = self.profiles[profile_name]
            decision = _route_decision(
                profile,
                mode="manual",
                reason="explicit profile",
                prompt=prompt,
                max_tokens=max_tokens,
                candidate_profiles=_candidate_profile_names(self.profiles),
            )
        else:
            profile = self.profiles.get(decision.profile_name, self.profiles["local"])
            decision = _route_decision(
                profile,
                mode=decision.mode,
                reason=decision.reason,
                prompt=prompt,
                max_tokens=max_tokens,
                candidate_profiles=decision.candidate_profiles,
                rejected_profiles=decision.rejected_profiles,
            )
        _record_route_decision(decision)
        effective_max_tokens = _effective_max_tokens(profile, max_tokens)
        try:
            text = self._call_profile(profile, prompt, max_tokens=effective_max_tokens)
            return AIModelResponse(
                ok=True,
                text=text,
                decision=decision,
                duration_ms=(time.perf_counter() - started_at) * 1000,
            )
        except Exception as exc:
            fallback = self.profiles["local"]
            provider_error = _provider_error_reason(exc)
            fallback_decision = _route_decision(
                fallback,
                mode="fallback",
                reason=f"{profile.name} failed: {provider_error}",
                prompt=prompt,
                max_tokens=max_tokens,
                candidate_profiles=_candidate_profile_names(self.profiles),
                fallback_status="used",
                fallback_reason=provider_error,
                fallback_from_profile=profile.name,
                provider_error=provider_error,
                provider_error_class=type(exc).__name__,
            )
            _record_route_decision(fallback_decision)
            return AIModelResponse(
                ok=False,
                text=_local_response(prompt),
                decision=fallback_decision,
                duration_ms=(time.perf_counter() - started_at) * 1000,
                error=provider_error,
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
        task_type = str(context.get("task_type", "")).lower()
        haystack = " ".join([task.lower(), role, task_type])
        if _is_high_risk(haystack):
            return (
                self._cheapest_ready_profile(("deep",))
                or self._cheapest_ready_profile(("balanced",))
                or "local"
            )
        if task_type == "council_consensus" or role == "chair":
            return self._cheapest_ready_profile(("balanced", "deep")) or "local"
        if complexity > 120:
            return self._cheapest_ready_profile(("balanced", "deep")) or "local"
        if role in {"maintainer", "test_strategist"}:
            return self._cheapest_ready_profile(("balanced", "deep")) or "local"
        if _is_simple_task(haystack) or role in {
            "performance_reviewer",
            "docs_reviewer",
            "product_reviewer",
            "implementer",
        }:
            return self._cheapest_ready_profile(("cheap", "balanced")) or "local"
        if self._profile_ready("fast"):
            return "fast"
        cheap_profile = self._cheapest_ready_profile(("cheap", "balanced"))
        if cheap_profile is not None:
            return cheap_profile
        return self.default_profile if self._profile_ready(self.default_profile) else "local"

    def _cheapest_ready_profile(self, quality_tiers: tuple[str, ...]) -> str | None:
        candidates = [
            profile
            for profile in self.profiles.values()
            if profile.quality_tier in quality_tiers and self._profile_ready(profile.name)
        ]
        if not candidates:
            return None
        return min(candidates, key=_profile_cost_sort_key).name

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
        if profile.provider == "anthropic":
            return _call_anthropic(profile, prompt, max_tokens=max_tokens)
        if profile.provider == "cohere":
            return _call_cohere(profile, prompt, max_tokens=max_tokens)
        if profile.provider in _OPENAI_COMPAT_PROVIDERS:
            provider = _OPENAI_COMPAT_PROVIDERS[profile.provider]
            return _call_chat_completions(
                profile,
                prompt,
                endpoint=_chat_completions_endpoint(profile.base_url, provider["endpoint"]),
                default_env=provider["env"],
                default_model=provider["default_model"],
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


def _estimate_token_count(text: str) -> int:
    try:
        from claude_bridge.smart import estimate_token_count

        return estimate_token_count(text)
    except Exception:
        return max(1, int(len(text.split()) * 1.3))


def _effective_max_tokens(profile: AIModelProfile, requested_max_tokens: int) -> int:
    if requested_max_tokens <= 0:
        return 0
    if profile.max_output_tokens > 0:
        return min(requested_max_tokens, profile.max_output_tokens)
    return requested_max_tokens


def _candidate_profile_names(profiles: dict[str, AIModelProfile]) -> tuple[str, ...]:
    return tuple(sorted(profiles))


def _rejected_profiles(
    selected_profile: str,
    candidate_profiles: tuple[str, ...],
) -> tuple[dict[str, str], ...]:
    return tuple(
        {"profile": name, "reason": "not selected"}
        for name in candidate_profiles
        if name != selected_profile
    )


def _estimated_max_cost_usd(
    profile: AIModelProfile, *, estimated_input_tokens: int, effective_max_tokens: int
) -> float:
    return (
        (estimated_input_tokens * profile.input_cost_per_mtok)
        + (effective_max_tokens * profile.output_cost_per_mtok)
    ) / 1_000_000


def _route_decision(
    profile: AIModelProfile,
    *,
    mode: str,
    reason: str,
    prompt: str,
    max_tokens: int,
    candidate_profiles: tuple[str, ...] = (),
    rejected_profiles: tuple[dict[str, str], ...] = (),
    fallback_status: str = "none",
    fallback_reason: str = "",
    fallback_from_profile: str = "",
    provider_error: str = "",
    provider_error_class: str = "",
) -> AIRouteDecision:
    estimated_input_tokens = _estimate_token_count(prompt) if prompt else 0
    effective_max_tokens = _effective_max_tokens(profile, max_tokens)
    candidates = candidate_profiles or (profile.name,)
    return AIRouteDecision(
        profile_name=profile.name,
        provider=profile.provider,
        model=profile.model,
        mode=mode,
        reason=reason,
        quality_tier=profile.quality_tier,
        estimated_input_tokens=estimated_input_tokens,
        effective_max_tokens=effective_max_tokens,
        estimated_max_cost_usd=_estimated_max_cost_usd(
            profile,
            estimated_input_tokens=estimated_input_tokens,
            effective_max_tokens=effective_max_tokens,
        ),
        selected_profile=profile.name,
        candidate_profiles=candidates,
        rejected_profiles=rejected_profiles or _rejected_profiles(profile.name, candidates),
        route_reason=reason,
        fallback_reason=fallback_reason,
        fallback_from_profile=fallback_from_profile,
        fallback_status=fallback_status,
        timeout_seconds=profile.timeout,
        provider_error=provider_error,
        provider_error_class=provider_error_class,
    )


def _record_route_decision(decision: AIRouteDecision) -> None:
    with _route_telemetry_lock:
        _route_telemetry["total_route_decisions"] += 1
        if decision.provider == "local":
            _route_telemetry["selected_local_count"] += 1
        else:
            _route_telemetry["selected_remote_count"] += 1
        if decision.fallback_status != "none":
            _route_telemetry["fallback_count"] += 1
        if decision.provider_error:
            _route_telemetry["provider_failure_count"] += 1
        if _is_timeout_error(decision.provider_error, decision.provider_error_class):
            _route_telemetry["timeout_count"] += 1
        by_mode = _route_telemetry["selection_count_by_mode"]
        by_mode[decision.mode] = by_mode.get(decision.mode, 0) + 1


def _is_timeout_error(provider_error: str, provider_error_class: str) -> bool:
    haystack = f"{provider_error} {provider_error_class}".lower()
    return "timeout" in haystack or "timed out" in haystack


def route_telemetry_summary() -> dict[str, Any]:
    """Return compact in-memory AI route telemetry counters."""
    with _route_telemetry_lock:
        return {
            "schema_version": "ai_route_telemetry.v1",
            "total_route_decisions": int(_route_telemetry["total_route_decisions"]),
            "selected_local_count": int(_route_telemetry["selected_local_count"]),
            "selected_remote_count": int(_route_telemetry["selected_remote_count"]),
            "fallback_count": int(_route_telemetry["fallback_count"]),
            "provider_failure_count": int(_route_telemetry["provider_failure_count"]),
            "timeout_count": int(_route_telemetry["timeout_count"]),
            "selection_count_by_mode": dict(_route_telemetry["selection_count_by_mode"]),
        }


def reset_route_telemetry() -> None:
    """Reset in-memory AI route telemetry counters for tests and diagnostics."""
    with _route_telemetry_lock:
        _route_telemetry["total_route_decisions"] = 0
        _route_telemetry["selected_local_count"] = 0
        _route_telemetry["selected_remote_count"] = 0
        _route_telemetry["fallback_count"] = 0
        _route_telemetry["provider_failure_count"] = 0
        _route_telemetry["timeout_count"] = 0
        _route_telemetry["selection_count_by_mode"] = {}


def _profile_cost_sort_key(profile: AIModelProfile) -> tuple[float, str]:
    # Output dominates council calls, so weight it slightly higher for routing choices.
    blended_cost = profile.input_cost_per_mtok + (profile.output_cost_per_mtok * 2)
    return (blended_cost, profile.name)


def _is_high_risk(haystack: str) -> bool:
    return any(term in haystack for term in _HIGH_RISK_TERMS)


def _is_simple_task(haystack: str) -> bool:
    return any(term in haystack for term in _SIMPLE_TASK_TERMS)


def _api_key(profile: AIModelProfile, default_env: str) -> str:
    env_name = profile.api_key_env or default_env
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise ValueError(f"{profile.name} requires API key env var {env_name}")
    return key


def _chat_completions_endpoint(base_url: str, default_endpoint: str) -> str:
    if not base_url:
        return default_endpoint
    return base_url.rstrip("/") + "/chat/completions"


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
    default_env: str,
    default_model: str,
    max_tokens: int,
) -> str:
    key = _api_key(profile, default_env)
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


def _call_cohere(profile: AIModelProfile, prompt: str, *, max_tokens: int) -> str:
    key = _api_key(profile, "COHERE_API_KEY")
    endpoint = (
        profile.base_url.rstrip("/") if profile.base_url else "https://api.cohere.com/v2/chat"
    )
    body = json.dumps(
        {
            "model": profile.model or "command-a-03-2025",
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
    raw_content = data.get("message", {}).get("content", "")
    if isinstance(raw_content, list):
        return "".join(
            str(item.get("text", "")) for item in raw_content if isinstance(item, dict)
        ).strip()
    return str(raw_content).strip()


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
        "telemetry": route_telemetry_summary(),
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
