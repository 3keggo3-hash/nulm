"""Tests for Bridge-internal AI routing."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from claude_bridge.ai_router import AIModelProfile, AIModelRouter, parse_model_profiles


def test_parse_model_profiles_rejects_raw_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        parse_model_profiles({"bad": {"provider": "unknown"}})


def test_parse_model_profiles_rejects_cloud_private_base_url() -> None:
    with pytest.raises(ValueError, match="private/internal"):
        parse_model_profiles({"bad": {"provider": "openai", "base_url": "https://localhost/v1"}})


def test_parse_model_profiles_allows_ollama_loopback_base_url() -> None:
    profiles = parse_model_profiles(
        {"local_ollama": {"provider": "ollama", "base_url": "http://127.0.0.1:11434"}}
    )

    assert profiles["local_ollama"].provider == "ollama"


def test_parse_model_profiles_rejects_remote_ollama_base_url() -> None:
    with pytest.raises(ValueError, match="loopback"):
        parse_model_profiles({"bad": {"provider": "ollama", "base_url": "https://example.com"}})


def test_router_uses_local_when_disabled() -> None:
    router = AIModelRouter(enabled=False, default_profile="fast")

    decision = router.select_profile("security review this feature")

    assert decision.profile_name == "local"
    assert decision.reason == "AI routing disabled"


def test_auto_router_uses_ready_fast_profile(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    router = AIModelRouter(enabled=True, mode="auto", default_profile="local")

    decision = router.select_profile("summarize this small task")

    assert decision.profile_name == "fast"
    assert decision.provider == "openai"


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
