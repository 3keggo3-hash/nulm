"""Tests for url_tools SSRF protections."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from claude_bridge.url_tools import _is_private_host


class TestIsPrivateHost:
    def test_localhost_blocked(self):
        assert _is_private_host("localhost") is True

    def test_public_ip_allowed(self):
        assert _is_private_host("8.8.8.8") is False

    def test_loopback_blocked(self):
        assert _is_private_host("127.0.0.1") is True

    def test_private_range_blocked(self):
        assert _is_private_host("192.168.1.1") is True

    def test_ambiguous_ip_like_blocked(self):
        # Octal-like and hex-like forms that ipaddress cannot parse
        # should be rejected to prevent SSRF bypasses.
        assert _is_private_host("0177.0.0.1") is True
        assert _is_private_host("0x7f.0.0.1") is True
        assert _is_private_host("010.0.0.1") is True

    def test_non_ip_allowed(self):
        assert _is_private_host("example.com") is False

    def test_empty_host_blocked(self):
        assert _is_private_host("") is True
