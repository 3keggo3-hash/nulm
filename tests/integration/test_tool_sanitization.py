"""Integration tests for tool sanitization."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import pytest

pytestmark = pytest.mark.integration


class TestBidiUnicodeDetection:
    """Tests for Bidi unicode detection."""

    def test_rle_in_name(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "test\u202etool",
            "description": "A test tool",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        assert result.valid is False
        assert len(result.prompt_injection) > 0

    def test_lro_in_description(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "test_tool",
            "description": "Read\u202dfiles",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        assert result.valid is False

    def test_combined_bidi_chars(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "\u202eadmin\u202dtool",
            "description": "\u200bhidden\u200cdescription",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        assert result.valid is False

    def test_clean_tool_name(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "read_file",
            "description": "Read files from the filesystem",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        assert result.valid is True

    def test_zwsp_in_param_name(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "tool",
            "description": "A tool",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path\u200bname": {"type": "string"},
                },
            },
        }
        result = validator.validate(tool_schema)
        assert result.valid is True

    def test_multiple_unicode_control_chars(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "test\u202e\u202d\u200b",
            "description": "A tool",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        assert result.valid is False


class TestHomoglyphDetection:
    """Tests for homoglyph detection."""

    def test_cyrillic_a_in_name(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "rеad_file",
            "description": "Read files",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        assert result.valid is False

    def test_cyrillic_o_in_description(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "read_file",
            "description": "Rеad files from filesystem",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        assert result.valid is False

    def test_multiple_homoglyphs(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "rеаd_filе",
            "description": "Rеad files from systеm",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        assert result.valid is False

    def test_latin_chars_only(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "read_file",
            "description": "Read files from filesystem",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        assert result.valid is True

    def test_mixed_cyrillic_latin(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "rea\u043ed_file",
            "description": "Read files",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        assert result.valid is False

    def test_homoglyph_in_param_name(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "read_file",
            "description": "A tool",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "fil\u0435path": {"type": "string"},
                },
            },
        }
        result = validator.validate(tool_schema)
        assert result.valid is True


class TestValidationResultUnicodeIssues:
    """Tests for ValidationResult.unicode_issues attribute."""

    def test_validation_result_unicode_issues_tuple(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "test\u202etool",
            "description": "A tool",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        assert result.valid is False
        assert isinstance(result.unicode_issues, tuple)
        assert len(result.unicode_issues) > 0

    def test_validation_result_to_dict(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "test\u202etool",
            "description": "A tool",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        d = result.to_dict()
        assert "unicode_issues" in d
        assert isinstance(d["unicode_issues"], list)

    def test_validation_result_str_with_unicode(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "test\u202etool",
            "description": "A tool",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        s = str(result)
        assert "unicode_issues" in s or "unicode" in s.lower()

    def test_validation_result_empty_unicode_issues(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "read_file",
            "description": "Read files",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        assert result.valid is True
        assert len(result.unicode_issues) == 0


class TestSanitizeToolMetadata:
    """Tests for sanitize_tool_metadata method."""

    def test_sanitize_removes_zwsp(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        name, desc = validator.sanitize_tool_metadata("tool\u200bname", "desc\u200bcription")
        assert "\u200b" not in name
        assert "\u200b" not in desc

    def test_sanitize_removes_rle(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        name, desc = validator.sanitize_tool_metadata("tool\u202ename", "desc\u202eription")
        assert "\u202e" not in name
        assert "\u202e" not in desc

    def test_sanitize_removes_bom(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        name, desc = validator.sanitize_tool_metadata("\ufefftool", "description")
        assert "\ufeff" not in name

    def test_sanitize_preserves_normal_text(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        name, desc = validator.sanitize_tool_metadata("read_file_v2", "Read file version 2.0")
        assert name == "read_file_v2"
        assert desc == "Read file version 2.0"

    def test_sanitize_homoglyph_normalization(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        name, desc = validator.sanitize_tool_metadata("rеad_file", "Read files")
        assert "а" not in name or "е" not in name


class TestUnicodeConstants:
    """Tests for module-level unicode constants."""

    def test_unicode_control_chars_list(self):
        from claude_bridge.tool_validator import UNICODE_CONTROL_CHARS

        assert isinstance(UNICODE_CONTROL_CHARS, (list, tuple, frozenset))
        assert len(UNICODE_CONTROL_CHARS) > 0
        assert "\u202e" in UNICODE_CONTROL_CHARS or "\u202e" in str(UNICODE_CONTROL_CHARS)

    def test_homoglyphs_dict(self):
        from claude_bridge.tool_validator import HOMOGLYPHS

        assert isinstance(HOMOGLYPHS, dict)
        assert len(HOMOGLYPHS) > 0
        assert "a" in HOMOGLYPHS
        assert HOMOGLYPHS["a"] == "\u0430"

    def test_latin_homoglyphs_reverse(self):
        from claude_bridge.tool_validator import LATIN_HOMOGLYPHS

        assert isinstance(LATIN_HOMOGLYPHS, dict)
        assert len(LATIN_HOMOGLYPHS) > 0


class TestEdgeCases:
    """Edge case tests."""

    def test_only_unicode_chars(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        tool_schema = {
            "name": "\u202e\u202d\u200b",
            "description": "\ufeff",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = validator.validate(tool_schema)
        assert result.valid is False
        assert len(result.prompt_injection) > 0

    def test_sanitize_preserves_ascii_alphanumeric(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator()
        name, desc = validator.sanitize_tool_metadata("read_file_v2", "Read file version 2.0")
        assert name == "read_file_v2"
        assert desc == "Read file version 2.0"
