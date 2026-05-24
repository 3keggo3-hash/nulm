"""Integration tests for command velocity limiting."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import pytest
import threading
import time
from unittest.mock import patch

pytestmark = pytest.mark.integration


class TestRateLimiting:
    """Tests for rate limiting with default settings."""

    def test_rate_limiter_default_config(self):
        from claude_bridge.resilience import RateLimiter

        limiter = RateLimiter()
        assert limiter._config.max_calls == 60
        assert limiter._config.window_seconds == 60.0

    def test_rate_limiter_custom_config(self):
        from claude_bridge.resilience import RateLimiter, RateLimitConfig

        config = RateLimitConfig(max_calls=10, window_seconds=5.0)
        limiter = RateLimiter(config)
        assert limiter._config.max_calls == 10
        assert limiter._config.window_seconds == 5.0

    def test_rate_limiter_allows_within_limit(self):
        from claude_bridge.resilience import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(max_calls=3, window_seconds=60.0))
        assert limiter.is_allowed() is True
        assert limiter.is_allowed() is True
        assert limiter.is_allowed() is True

    def test_rate_limiter_rejects_at_limit(self):
        from claude_bridge.resilience import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(max_calls=2, window_seconds=60.0))
        limiter.is_allowed()
        limiter.is_allowed()
        assert limiter.is_allowed() is False

    def test_rate_limiter_wait_time_at_limit(self):
        from claude_bridge.resilience import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(max_calls=2, window_seconds=60.0))
        limiter.is_allowed()
        limiter.is_allowed()
        wait = limiter.wait_time()
        assert wait > 0.0

    def test_rate_limiter_reset(self):
        from claude_bridge.resilience import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(max_calls=2, window_seconds=60.0))
        limiter.is_allowed()
        limiter.is_allowed()
        limiter.reset()
        assert limiter.is_allowed() is True

    def test_rate_limiter_reset_clears_calls(self):
        from claude_bridge.resilience import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(max_calls=2, window_seconds=60.0))
        limiter.is_allowed()
        limiter.is_allowed()
        limiter.reset()
        assert len(limiter._calls) == 0


class TestPerAgentRateLimiting:
    """Tests for per-agent rate limiting isolation."""

    def test_check_command_velocity_new_agent(self):
        from claude_bridge._shell_safety import (
            check_command_velocity,
            _command_timestamps,
            _command_timestamps_lock,
        )

        with _command_timestamps_lock:
            _command_timestamps.clear()
        result = check_command_velocity("test_command", "agent_new_456")
        assert result is None

    def test_check_command_velocity_same_agent(self):
        from claude_bridge._shell_safety import (
            check_command_velocity,
            _command_timestamps,
            _command_timestamps_lock,
            _COMMAND_RATE_LIMIT,
        )

        with _command_timestamps_lock:
            _command_timestamps.clear()
        max_cmds = _COMMAND_RATE_LIMIT["max_commands"]
        for _ in range(max_cmds - 1):
            result = check_command_velocity("test_command", "agent_test")
            assert result is None

    def test_check_command_velocity_different_agents_independent(self):
        from claude_bridge._shell_safety import (
            check_command_velocity,
            _command_timestamps,
            _command_timestamps_lock,
            _COMMAND_RATE_LIMIT,
        )

        with _command_timestamps_lock:
            _command_timestamps.clear()
        max_cmds = _COMMAND_RATE_LIMIT["max_commands"]
        for _ in range(max_cmds):
            check_command_velocity("test_command", "agent_x")
        result = check_command_velocity("test_command", "agent_y")
        assert result is None

    def test_check_command_velocity_blocks_at_limit(self):
        from claude_bridge._shell_safety import (
            check_command_velocity,
            _command_timestamps,
            _command_timestamps_lock,
            _COMMAND_RATE_LIMIT,
        )

        with _command_timestamps_lock:
            _command_timestamps.clear()
        max_cmds = _COMMAND_RATE_LIMIT["max_commands"]
        for _ in range(max_cmds):
            check_command_velocity("test_command", "agent_blocked")
        result = check_command_velocity("test_command", "agent_blocked")
        assert result is not None
        assert "command_rate_limit_exceeded" in result


class TestRateLimitReset:
    """Tests for rate limit reset after window expires."""

    def test_rate_limiter_expired_calls_removed(self):
        from claude_bridge.resilience import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(max_calls=2, window_seconds=0.5))
        limiter.is_allowed()
        limiter.is_allowed()
        time.sleep(0.6)
        assert limiter.is_allowed() is True
        assert limiter.is_allowed() is True

    def test_rate_limiter_old_timestamps_cleaned(self):
        from claude_bridge.resilience import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(max_calls=2, window_seconds=10.0))
        limiter.is_allowed()
        limiter.is_allowed()
        limiter._calls.insert(0, time.time() - 20.0)
        limiter.is_allowed()
        with limiter._lock:
            assert all(t > time.time() - 10.0 for t in limiter._calls)

    def test_check_command_velocity_window_boundary(self):
        from claude_bridge._shell_safety import (
            check_command_velocity,
            _command_timestamps,
            _command_timestamps_lock,
        )

        with _command_timestamps_lock:
            _command_timestamps.clear()
        result1 = check_command_velocity("test_command", "boundary_test")
        assert result1 is None


class TestEnvVarConfiguration:
    """Tests for env var configuration loading."""

    def test_load_rate_limit_config_defaults(self):
        from claude_bridge._shell_safety import _COMMAND_RATE_LIMIT, _load_rate_limit_config

        original_window = _COMMAND_RATE_LIMIT["window_seconds"]
        original_max = _COMMAND_RATE_LIMIT["max_commands"]
        _load_rate_limit_config()
        assert _COMMAND_RATE_LIMIT["window_seconds"] == original_window
        assert _COMMAND_RATE_LIMIT["max_commands"] == original_max

    def test_load_rate_limit_config_window_override(self):
        from claude_bridge._shell_safety import _COMMAND_RATE_LIMIT, _load_rate_limit_config

        original_window = _COMMAND_RATE_LIMIT["window_seconds"]
        with patch.dict("os.environ", {"CLAUDE_BRIDGE_SHELL_RATE_LIMIT_WINDOW": "30"}):
            _load_rate_limit_config()
            assert _COMMAND_RATE_LIMIT["window_seconds"] == 30
        _COMMAND_RATE_LIMIT["window_seconds"] = original_window

    def test_load_rate_limit_config_max_override(self):
        from claude_bridge._shell_safety import _COMMAND_RATE_LIMIT, _load_rate_limit_config

        original_max = _COMMAND_RATE_LIMIT["max_commands"]
        with patch.dict("os.environ", {"CLAUDE_BRIDGE_SHELL_RATE_LIMIT_MAX": "100"}):
            _load_rate_limit_config()
            assert _COMMAND_RATE_LIMIT["max_commands"] == 100
        _COMMAND_RATE_LIMIT["max_commands"] = original_max

    def test_load_rate_limit_config_invalid_window(self):
        from claude_bridge._shell_safety import _COMMAND_RATE_LIMIT, _load_rate_limit_config

        original_window = _COMMAND_RATE_LIMIT["window_seconds"]
        with patch.dict("os.environ", {"CLAUDE_BRIDGE_SHELL_RATE_LIMIT_WINDOW": "invalid"}):
            _load_rate_limit_config()
            assert _COMMAND_RATE_LIMIT["window_seconds"] == original_window

    def test_load_rate_limit_config_invalid_max(self):
        from claude_bridge._shell_safety import _COMMAND_RATE_LIMIT, _load_rate_limit_config

        original_max = _COMMAND_RATE_LIMIT["max_commands"]
        with patch.dict("os.environ", {"CLAUDE_BRIDGE_SHELL_RATE_LIMIT_MAX": "invalid"}):
            _load_rate_limit_config()
            assert _COMMAND_RATE_LIMIT["max_commands"] == original_max


class TestRateLimitEdgeCases:
    """Test edge cases for rapid commands at window boundary."""

    def test_concurrent_rate_limit_access(self):
        from claude_bridge.resilience import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(max_calls=200, window_seconds=60.0))
        results: list[bool] = []

        def check_many() -> None:
            for _ in range(50):
                results.append(limiter.is_allowed())

        threads = [threading.Thread(target=check_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 200

    def test_rate_limiter_zero_window(self):
        from claude_bridge.resilience import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(max_calls=5, window_seconds=0.0))
        limiter.is_allowed()
        wait = limiter.wait_time()
        assert wait == 0.0

    def test_rate_limiter_zero_max_calls(self):
        from claude_bridge.resilience import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(max_calls=0, window_seconds=60.0))
        assert limiter.is_allowed() is False

    def test_rate_limiter_very_large_window(self):
        from claude_bridge.resilience import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(max_calls=5, window_seconds=86400.0))
        for _ in range(5):
            assert limiter.is_allowed() is True
        assert limiter.is_allowed() is False

    def test_rate_limiter_immediate_reset(self):
        from claude_bridge.resilience import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(max_calls=1, window_seconds=60.0))
        limiter.is_allowed()
        assert limiter.is_allowed() is False
        limiter.reset()
        assert limiter.is_allowed() is True
