"""Tests for intent_engine module."""

from __future__ import annotations

from claude_bridge.intent_engine import (
    IntentType,
    detect_undecided,
    parse_intent,
    has_clear_success_criteria,
    has_specific_files,
)


class TestIntentType:
    def test_intent_type_values(self):
        assert IntentType.ERROR_COMPLAINT.value == "ERROR_COMPLAINT"
        assert IntentType.PERFORMANCE_CONCERN.value == "PERFORMANCE_CONCERN"
        assert IntentType.SECURITY_CONCERN.value == "SECURITY_CONCERN"
        assert IntentType.MISSING_FEATURE.value == "MISSING_FEATURE"
        assert IntentType.VAGUE.value == "VAGUE"
        assert IntentType.REFACTORING_CONCERN.value == "REFACTORING_CONCERN"
        assert IntentType.TEST_CREATION.value == "TEST_CREATION"
        assert IntentType.DOCUMENTATION_REQUEST.value == "DOCUMENTATION_REQUEST"


class TestDetectUndecided:
    def test_detect_vague_input_biraz_karisik(self):
        is_vague, intent = detect_undecided("biraz karışık bir proje yapmak istiyorum")
        assert is_vague is True
        assert intent.confidence >= 0.7
        assert intent.intent_type == IntentType.VAGUE

    def test_detect_vague_input_nasil_yapacagimi_biliyorum(self):
        is_vague, intent = detect_undecided(
            "nasıl yapacağımı bilmiyorum ama web sitemi hızlandırmak istiyorum"
        )
        assert is_vague is True
        assert intent.intent_type == IntentType.PERFORMANCE_CONCERN

    def test_detect_error_complaint(self):
        is_vague, intent = detect_undecided("uygulama çalışmıyor hata veriyor")
        assert intent.intent_type == IntentType.ERROR_COMPLAINT
        assert intent.confidence >= 0.7
        assert "Run diagnostics" in intent.suggested_actions

    def test_detect_performance_concern(self):
        is_vague, intent = detect_undecided("sistem çok yavaş çalışıyor")
        assert intent.intent_type == IntentType.PERFORMANCE_CONCERN
        assert intent.confidence >= 0.7

    def test_detect_security_concern(self):
        is_vague, intent = detect_undecided("bu kod güvenli mi?")
        assert intent.intent_type == IntentType.SECURITY_CONCERN
        assert intent.confidence >= 0.7

    def test_detect_missing_feature(self):
        is_vague, intent = detect_undecided("bir özellik eksik gibi")
        assert intent.intent_type == IntentType.MISSING_FEATURE
        assert intent.confidence >= 0.7

    def test_detect_refactoring_concern(self):
        is_vague, intent = detect_undecided("bu kodu refactor etmem gerekiyor")
        assert intent.intent_type == IntentType.REFACTORING_CONCERN
        assert intent.confidence >= 0.7

    def test_detect_test_creation(self):
        is_vague, intent = detect_undecided("bu fonksiyon için pytest testi yaz")
        assert intent.intent_type == IntentType.TEST_CREATION
        assert intent.confidence >= 0.7

    def test_detect_documentation_request(self):
        is_vague, intent = detect_undecided("bu kodun dokümantasyonunu yap")
        assert intent.intent_type == IntentType.DOCUMENTATION_REQUEST
        assert intent.confidence >= 0.7

    def test_graceful_degradation_unknown_intent(self):
        is_vague, intent = detect_undecided("simple query")
        if not is_vague:
            assert intent.confidence < 0.7 or intent.suggested_actions == []

    def test_clear_input_not_vague(self):
        is_vague, intent = detect_undecided(
            "src/main.py dosyasındaki calculate_total fonksiyonunu optimize et"
        )
        assert is_vague is False or intent.confidence < 0.7

    def test_matched_patterns_populated(self):
        is_vague, intent = detect_undecided("uygulama çalışmıyor")
        assert len(intent.matched_patterns) > 0
        assert "çalışmıyor" in intent.matched_patterns

    def test_suggested_actions_for_error(self):
        _, intent = detect_undecided("program crash oldu")
        assert len(intent.suggested_actions) > 0
        assert any("diagnostic" in action.lower() for action in intent.suggested_actions)


class TestParseIntent:
    def test_parse_intent_returns_dict(self):
        result = parse_intent("biraz karışık")
        assert isinstance(result, dict)
        assert "is_vague" in result
        assert "intent_type" in result
        assert "confidence" in result
        assert "suggested_actions" in result

    def test_parse_intent_vague_content(self):
        result = parse_intent("nasıl yapacağımı bilmiyorum")
        assert result["is_vague"] is True
        assert result["intent_type"] in [e.value for e in IntentType]

    def test_parse_intent_error_complaint(self):
        result = parse_intent("sistem çalışmıyor hata veriyor")
        assert result["intent_type"] == IntentType.ERROR_COMPLAINT.value


class TestHasClearSuccessCriteria:
    def test_has_criteria_with_file_path(self):
        assert has_clear_success_criteria("src/app.py dosyasını düzelt") is True

    def test_has_criteria_with_error(self):
        assert has_clear_success_criteria("error is at line 42") is True

    def test_no_criteria_vague(self):
        assert has_clear_success_criteria("biraz karışık") is False
        assert has_clear_success_criteria("nasıl yapacağımı bilmiyorum") is False


class TestHasSpecificFiles:
    def test_has_specific_file(self):
        assert has_specific_files("src/main.py") is True
        assert has_specific_files("tests/test_app.py") is True

    def test_no_specific_file(self):
        assert has_specific_files("biraz karışık") is False
        assert has_specific_files("nasıl yapacağımı bilmiyorum") is False
