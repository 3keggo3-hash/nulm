"""Tests for tool_validator.py - ToolSchemaValidator and security validation."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations


from claude_bridge.tool_validator import (
    ToolSchemaValidator,
    ValidationResult,
    MAX_PARAM_COUNT,
)


class TestToolSchemaValidator:
    def setup_method(self) -> None:
        self.validator = ToolSchemaValidator()

    def test_valid_schema_passes(self):
        schema = {
            "name": "read_file",
            "description": "Read contents of a file",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is True
        assert result.risk_level in ("low", "medium", "high")

    def test_valid_schema_with_multiple_params(self):
        schema = {
            "name": "search_files",
            "description": "Search for files matching pattern",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "pattern": {"type": "string"},
                    "recursive": {"type": "boolean"},
                },
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is True

    def test_eval_in_description_blocked(self):
        schema = {
            "name": "dynamic_eval",
            "description": "Execute eval() on input string",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                },
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "blocked pattern" in result.reason.lower()
        assert result.risk_level == "high"

    def test_exec_in_name_blocked(self):
        schema = {
            "name": "run_exec",
            "description": "Execute via exec()",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string"},
                },
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "blocked pattern" in result.reason.lower()
        assert result.risk_level == "high"

    def test_import_os_in_description_blocked(self):
        schema = {
            "name": "system_info",
            "description": "Import os and get system information",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "blocked pattern" in result.reason.lower()

    def test_subprocess_in_description_blocked(self):
        schema = {
            "name": "run_subprocess",
            "description": "Run subprocess commands",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "blocked pattern" in result.reason.lower()

    def test_rm_dangerous_in_description_blocked(self):
        schema = {
            "name": "delete_files",
            "description": "Remove files with rm -rf command",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "blocked pattern" in result.reason.lower()

    def test_drop_table_sql_blocked(self):
        schema = {
            "name": "sql_query",
            "description": "Execute DROP TABLE query",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "blocked pattern" in result.reason.lower()

    def test_missing_name_field_fails(self):
        schema = {
            "description": "Some tool",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "name" in result.reason

    def test_missing_description_field_fails(self):
        schema = {
            "name": "some_tool",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "description" in result.reason

    def test_missing_input_schema_fails(self):
        schema = {
            "name": "some_tool",
            "description": "Some tool",
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "inputSchema" in result.reason

    def test_exceeds_max_param_count_fails(self):
        properties = {f"param_{i}": {"type": "string"} for i in range(MAX_PARAM_COUNT + 1)}
        schema = {
            "name": "many_params",
            "description": "Tool with many parameters",
            "inputSchema": {
                "type": "object",
                "properties": properties,
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "parameter count" in result.reason

    def test_exactly_max_params_passes(self):
        properties = {f"param_{i}": {"type": "string"} for i in range(MAX_PARAM_COUNT)}
        schema = {
            "name": "max_params",
            "description": "Tool with exactly max parameters",
            "inputSchema": {
                "type": "object",
                "properties": properties,
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is True

    def test_exceeds_max_description_length_fails(self):
        schema = {
            "name": "long_desc",
            "description": "x" * (ToolSchemaValidator.max_description_length + 1),
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "description exceeds" in result.reason

    def test_filesystem_tool_high_risk(self):
        schema = {
            "name": "delete_file_exec",
            "description": "Execute file deletion command",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is True
        assert result.risk_level == "high"

    def test_shell_tool_high_risk(self):
        schema = {
            "name": "run_shell",
            "description": "Execute shell command",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is True
        assert result.risk_level == "high"

    def test_readonly_tool_low_risk(self):
        schema = {
            "name": "list_directory",
            "description": "List files in directory",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is True
        assert result.risk_level in ("low", "medium")

    def test_invalid_param_type_fails(self):
        schema = {
            "name": "bad_param_type",
            "description": "Tool with invalid param type",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "data": {"type": "buffer"},
                },
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "invalid parameter type" in result.reason

    def test_blocked_pattern_in_param_name(self):
        schema = {
            "name": "some_tool",
            "description": "Tool with blocked param name",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "subprocess_cmd": {"type": "string"},
                },
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "parameter name" in result.reason.lower()

    def test_validation_result_to_dict(self):
        result = ValidationResult(
            valid=False,
            reason="test blocked",
            risk_level="high",
            blocked_patterns=("eval(", "exec("),
        )
        d = result.to_dict()
        assert d["valid"] is False
        assert d["reason"] == "test blocked"
        assert d["risk_level"] == "high"
        assert "eval(" in d["blocked_patterns"]
        assert "exec(" in d["blocked_patterns"]

    def test_validate_many(self):
        schemas = [
            {
                "name": "tool_a",
                "description": "Valid tool A",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "eval_tool",
                "description": "Contains eval() pattern",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]
        results = self.validator.validate_many(schemas)
        assert len(results) == 2
        assert results[0].valid is True
        assert results[1].valid is False

    def test_parameters_instead_of_input_schema(self):
        schema = {
            "name": "alt_schema",
            "description": "Uses parameters instead of inputSchema",
            "parameters": {
                "type": "object",
                "properties": {
                    "arg": {"type": "string"},
                },
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is True

    def test_case_insensitive_blocked_patterns(self):
        schema = {
            "name": "EVAL_TOOL",
            "description": "Contains EVAL() pattern uppercase",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is False
        assert "blocked pattern" in result.reason.lower()

    def test_safe_tool_with_acceptable_description(self):
        schema = {
            "name": "get_time",
            "description": "Returns current UTC time",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        }
        result = self.validator.validate(schema)
        assert result.valid is True
        assert result.risk_level == "low"
