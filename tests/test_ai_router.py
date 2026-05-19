"""Tests for Bridge-internal AI routing."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from claude_bridge import ai_router
from claude_bridge.ai_router import AIModelProfile, AIModelRouter, parse_model_profiles


def test_parse_model_profiles_rejects_raw_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        parse_model_profiles({"bad": {"provider": "unknown"}})


def test_parse_model_profiles_accepts_cost_metadata() -> None:
    profiles = parse_model_profiles(
        {
            "balanced": {
                "provider": "openai",
                "model": "gpt-test",
                "api_key_env": "OPENAI_API_KEY",
                "input_cost_per_mtok": 1.25,
                "output_cost_per_mtok": 5.0,
                "quality_tier": "balanced",
                "max_output_tokens": 600,
            }
        }
    )

    profile = profiles["balanced"]

    assert profile.input_cost_per_mtok == 1.25
    assert profile.output_cost_per_mtok == 5.0
    assert profile.quality_tier == "balanced"
    assert profile.max_output_tokens == 600


@pytest.mark.parametrize(
    "provider",
    [
        "minimax",
        "google",
        "groq",
        "mistral",
        "cohere",
        "xai",
        "together",
        "openrouter",
        "perplexity",
        "fireworks",
    ],
)
def test_parse_model_profiles_accepts_popular_providers(provider: str) -> None:
    profiles = parse_model_profiles(
        {"remote": {"provider": provider, "model": "model-test", "api_key_env": "API_KEY"}}
    )

    assert profiles["remote"].provider == provider


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("input_cost_per_mtok", -0.1, "input_cost_per_mtok"),
        ("output_cost_per_mtok", -0.1, "output_cost_per_mtok"),
        ("quality_tier", "premium", "quality_tier"),
        ("max_output_tokens", -1, "max_output_tokens"),
    ],
)
def test_parse_model_profiles_rejects_invalid_cost_metadata(
    field: str, value: object, message: str
) -> None:
    raw = {"fast": {"provider": "openai", "api_key_env": "OPENAI_API_KEY", field: value}}

    with pytest.raises(ValueError, match=message):
        parse_model_profiles(raw)


def test_router_uses_local_when_disabled() -> None:
    router = AIModelRouter(enabled=False, default_profile="fast")

    decision = router.select_profile("security review this feature")

    assert decision.profile_name == "local"
    assert decision.reason == "AI routing disabled"


def test_auto_router_uses_ready_fast_profile(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    router = AIModelRouter(enabled=True, mode="auto", default_profile="local")

    decision = router.select_profile("summarize this small task")

    assert decision.profile_name == "fast"
    assert decision.provider == "openai"
    assert decision.quality_tier == "cheap"


def test_auto_router_preserves_quality_for_consensus(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    router = AIModelRouter(enabled=True, mode="auto", default_profile="local")

    decision = router.select_profile(
        "synthesize the council plan",
        context={"task_type": "council_consensus", "role": "chair"},
    )

    assert decision.profile_name == "balanced"
    assert decision.quality_tier == "balanced"


def test_auto_router_uses_deep_for_high_risk_when_ready(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    router = AIModelRouter(enabled=True, mode="auto", default_profile="local")

    decision = router.select_profile("security review shell approval policy")

    assert decision.profile_name == "deep"
    assert decision.quality_tier == "deep"


def test_auto_router_uses_balanced_for_high_risk_without_deep(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    router = AIModelRouter(enabled=True, mode="auto", default_profile="local")

    decision = router.select_profile("security review shell approval policy")

    assert decision.profile_name == "balanced"
    assert decision.quality_tier == "balanced"


def test_rules_router_matches_keyword(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    router = AIModelRouter.from_config(
        {
            "ai_routing_enabled": True,
            "ai_routing_mode": "rules",
            "ai_default_model_profile": "local",
            "ai_model_profiles": {
                "reviewer": {
                    "provider": "anthropic",
                    "model": "claude-test",
                    "api_key_env": "ANTHROPIC_API_KEY",
                }
            },
            "ai_routing_rules": [
                {"name": "reviews", "profile": "reviewer", "keywords": ["review"]}
            ],
        }
    )

    decision = router.select_profile("please review this")

    assert decision.profile_name == "reviewer"
    assert decision.reason == "matched rule: reviews"


def test_generate_text_falls_back_without_api_key() -> None:
    router = AIModelRouter(
        enabled=True,
        mode="manual",
        default_profile="missing",
        profiles={
            "local": AIModelProfile(name="local", provider="local"),
            "missing": AIModelProfile(
                name="missing",
                provider="openai",
                model="gpt-test",
                api_key_env="MISSING_API_KEY",
            ),
        },
    )

    response = router.generate_text("Council task: test", profile_name="missing")

    assert response.ok is False
    assert response.decision.profile_name == "local"
    assert "MISSING_API_KEY" in response.error


def test_generate_text_caps_output_and_reports_cost(monkeypatch) -> None:
    monkeypatch.setattr(ai_router, "_estimate_token_count", lambda text: 100)
    router = AIModelRouter(
        enabled=True,
        mode="manual",
        default_profile="local",
        profiles={
            "local": AIModelProfile(name="local", provider="local"),
            "cheap": AIModelProfile(
                name="cheap",
                provider="local",
                quality_tier="cheap",
                input_cost_per_mtok=1.0,
                output_cost_per_mtok=2.0,
                max_output_tokens=250,
            ),
        },
    )

    response = router.generate_text("Council task: test", profile_name="cheap", max_tokens=700)
    route = response.decision.to_dict()

    assert response.ok is True
    assert route["effective_max_tokens"] == 250
    assert route["estimated_input_tokens"] == 100
    assert route["estimated_max_cost_usd"] == 0.0006
