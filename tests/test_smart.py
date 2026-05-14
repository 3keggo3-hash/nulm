"""Tests for smart helper fallbacks."""

from __future__ import annotations

from typing import Any

from claude_bridge import smart


def test_detect_file_encoding_falls_back_to_utf8_without_charset_normalizer(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(smart, "_CHARSET_NORMALIZER_AVAILABLE", False)
    monkeypatch.setattr(smart, "_detect_encoding_bytes", None)

    assert smart.detect_file_encoding(b"\xef\xbb\xbfhello") == "utf-8-sig"
    assert smart.detect_file_encoding(b"hello") == "utf-8"


def test_detect_file_encoding_uses_charset_normalizer_when_available(
    monkeypatch: Any,
) -> None:
    class FakeMatch:
        encoding = "cp1254"

    class FakeResults:
        def best(self) -> FakeMatch:
            return FakeMatch()

    def fake_detect(raw: bytes) -> FakeResults:
        assert raw == b"hello"
        return FakeResults()

    monkeypatch.setattr(smart, "_CHARSET_NORMALIZER_AVAILABLE", True)
    monkeypatch.setattr(smart, "_detect_encoding_bytes", fake_detect)

    assert smart.detect_file_encoding(b"hello") == "cp1254"


def test_compact_intent_recommends_existing_clarification_tools_for_vague_input() -> None:
    result = smart.compact_intent("do something")

    assert result["is_vague"] is False
    assert "undecided_mode_analyze" not in result["recommended_usage"]
    assert "advise_next_step" not in result["recommended_usage"]
