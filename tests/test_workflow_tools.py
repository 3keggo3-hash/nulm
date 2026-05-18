"""Tests for workflow tools."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import json
import time
from pathlib import Path  # noqa: F401

import pytest  # noqa: F401

from claude_bridge import server as mcp_server
from claude_bridge import workflow_agent_loop as wf_agent_loop
from claude_bridge import workflow_cache
from claude_bridge import workflow_tools as wf
from claude_bridge.workflow_runner import run_workflow as run_workflow_impl


def parse_payload(result: str) -> dict:
    return json.loads(result)


class TestDetectProjectType:
    def test_python_project(self, temp_project):
        (temp_project / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        assert wf.detect_project_type(temp_project, temp_project) == "python"

    def test_node_project(self, temp_project):
        (temp_project / "package.json").write_text('{"name": "test"}')
        assert wf.detect_project_type(temp_project, temp_project) == "node"

    def test_rust_project(self, temp_project):
        (temp_project / "Cargo.toml").write_text("[package]\nname = 'test'")
        assert wf.detect_project_type(temp_project, temp_project) == "rust"

    def test_go_project(self, temp_project):
        (temp_project / "go.mod").write_text("module example.com/test")
        assert wf.detect_project_type(temp_project, temp_project) == "go"

    def test_unknown_project(self, temp_project):
        assert wf.detect_project_type(temp_project, temp_project) == "unknown"


class TestBuildContextPack:
    async def test_build_context_pack_for_file(self, temp_project):
        src = temp_project / "src"
        src.mkdir()
        (src / "main.py").write_text("print('hello')")
        payload = parse_payload(
            await mcp_server.build_context_pack(target="src/main.py", goal="understand main")
        )
        assert payload["ok"] is True
        assert any("main.py" in f for f in payload["details"]["selected_files"])

    async def test_build_context_pack_with_tests(self, temp_project):
        (temp_project / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        tests = temp_project / "tests"
        tests.mkdir()
        (tests / "test_main.py").write_text("def test_main(): pass")
        (temp_project / "main.py").write_text("print('hello')")
        payload = parse_payload(
            await mcp_server.build_context_pack(
                target=".", goal="understand tests", include_tests=True
            )
        )
        assert payload["ok"] is True
        assert any("test_main.py" in f for f in payload["details"]["test_files"])

    def test_workflow_disk_cache_limits_total_size(self, temp_project, monkeypatch):
        cache_dir = temp_project / ".cache" / "workflow"
        cache_dir.mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_BRIDGE_CACHE_DIR", str(temp_project / ".cache"))
        monkeypatch.setattr(workflow_cache, "_MAX_WORKFLOW_DISK_CACHE_FILES", 10)
        monkeypatch.setattr(workflow_cache, "_MAX_WORKFLOW_DISK_CACHE_BYTES", 10)

        for index in range(3):
            path = cache_dir / f"context-v1-{index}.json"
            path.write_text("12345", encoding="utf-8")
            time.sleep(0.01)

        workflow_cache._prune_workflow_disk_cache()
        remaining = sorted(path.name for path in cache_dir.glob("*.json"))

        assert remaining == ["context-v1-1.json", "context-v1-2.json"]


class TestSuggestValidationCommands:
    def test_python_validation(self, temp_project):
        (temp_project / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        commands = wf.suggest_validation_commands(temp_project, temp_project)
        assert "python3 -m pytest" in commands
        assert "git diff" in commands

    def test_rust_validation(self, temp_project):
        (temp_project / "Cargo.toml").write_text("[package]\nname = 'test'")
        commands = wf.suggest_validation_commands(temp_project, temp_project)
        assert "cargo test" in commands
        assert "git diff" in commands


class TestRunAgentLoopStep:
    def test_validation_allowlist_includes_format_and_typecheck_commands(self):
        allowed = [
            "ruff format --check .",
            "npm run typecheck",
            "pnpm lint",
            "cargo fmt --check",
            "go vet ./...",
            "deno check main.ts",
        ]

        for command in allowed:
            assert wf_agent_loop._validation_command_error(command) is None

    async def test_agent_loop_step_patch_and_validate(self, temp_project, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_UNSAFE_AUTO_APPROVE_CONFIRMED", "1")
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)
        test_file = temp_project / "module.py"
        test_file.write_text("def old_name():\n    return 1\n")
        monkeypatch.setattr(wf_agent_loop, "_validation_command_error", lambda cmd: None)
        payload = parse_payload(
            await mcp_server.run_agent_loop_step(
                file="module.py",
                search="old_name",
                replace="new_name",
                validation_command="echo ok",
                iteration=1,
                max_iterations=3,
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["patch_result"]["ok"] is True
        assert payload["details"]["decision"] == "stop_success"
        assert "new_name" in test_file.read_text()

    async def test_agent_loop_step_invalid_iteration(self, temp_project):
        payload = parse_payload(
            await mcp_server.run_agent_loop_step(
                file="module.py",
                search="x",
                replace="y",
                validation_command="git diff",
                iteration=0,
                max_iterations=3,
            )
        )
        assert payload["ok"] is False
        assert payload["code"] == "invalid_iteration"

    async def test_agent_loop_step_validation_fails_no_continue_budget(
        self, temp_project, monkeypatch
    ):
        monkeypatch.setenv("CLAUDE_BRIDGE_UNSAFE_AUTO_APPROVE_CONFIRMED", "1")
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)
        test_file = temp_project / "module.py"
        test_file.write_text("def old_name():\n    return 1\n")
        monkeypatch.setattr(wf_agent_loop, "_validation_command_error", lambda cmd: None)
        payload = parse_payload(
            await mcp_server.run_agent_loop_step(
                file="module.py",
                search="old_name",
                replace="new_name",
                validation_command="false",
                iteration=3,
                max_iterations=3,
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["patch_result"]["ok"] is True
        assert payload["details"]["decision"] == "stop_failure"


class TestRunAgentLoopSession:
    async def test_agent_loop_session_two_steps_success(self, temp_project, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_UNSAFE_AUTO_APPROVE_CONFIRMED", "1")
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)
        test_file = temp_project / "module.py"
        test_file.write_text("def fn_a():\n    return 'a'\n\ndef fn_b():\n    return 'b'\n")
        monkeypatch.setattr(wf_agent_loop, "_validation_command_error", lambda cmd: None)
        steps = [
            {
                "file": "module.py",
                "search": "fn_a",
                "replace": "patched_a",
                "validation_command": "false",
            },
            {
                "file": "module.py",
                "search": "fn_b",
                "replace": "patched_b",
                "validation_command": "echo ok",
            },
        ]
        payload = parse_payload(
            await mcp_server.run_agent_loop_session(steps=steps, max_iterations=5)
        )
        assert payload["ok"] is True
        assert payload["details"]["final_decision"] == "stop_success"
        assert payload["details"]["executed_steps"] == 2

    async def test_agent_loop_session_includes_boundary_quality_advice(
        self, temp_project, monkeypatch
    ):
        test_file = temp_project / "module.py"
        test_file.write_text("def fn_a():\n    return 'a'\n")
        monkeypatch.setattr(wf_agent_loop, "_validation_command_error", lambda cmd: None)
        steps = [
            {
                "file": "module.py",
                "search": "fn_a",
                "replace": "patched_a",
                "validation_command": "echo ok",
            }
        ]

        payload = parse_payload(await mcp_server.run_agent_loop_session(steps=steps))

        assert payload["ok"] is True
        advisory = payload["details"]["agent_quality"]
        assert advisory["schema_version"] == "agent_loop_session_quality.v1"


class TestRunCouncilSession:
    async def test_run_council_session_is_read_only_plan(self, temp_project):
        payload = parse_payload(
            await mcp_server.run_council_session(
                task="add AI routing",
                target="src/",
                agent_count=3,
                rounds=1,
            )
        )

        assert payload["ok"] is True
        details = payload["details"]
        assert details["schema_version"] == "ai_council_session.v1"
        assert details["execution_boundary"].startswith("This council is read-only")
        assert details["cost_estimate"]["estimated_model_calls"] == 4
        assert "steps_json" in details

    async def test_agent_loop_session_does_not_add_advice_to_each_step(
        self, temp_project, monkeypatch
    ):
        test_file = temp_project / "module.py"
        test_file.write_text("def fn_a():\n    return 'a'\n")
        monkeypatch.setattr(wf_agent_loop, "_validation_command_error", lambda cmd: None)
        steps = [
            {
                "file": "module.py",
                "search": "fn_a",
                "replace": "patched_a",
                "validation_command": "echo ok",
            }
        ]

        payload = parse_payload(await mcp_server.run_agent_loop_session(steps=steps))

        assert payload["ok"] is True
        assert "agent_quality" in payload["details"]
        for result in payload["details"]["results"]:
            assert "agent_quality" not in result


class TestRunWorkflowAgentQuality:
    async def test_workflow_output_includes_agent_quality_advisory(self, temp_project):
        (temp_project / "module.py").write_text("def fn():\n    return 1\n")

        payload = parse_payload(
            await mcp_server.run_workflow(mode="review", target=".", detail_level="full")
        )

        assert payload["ok"] is True
        advisory = payload["details"]["agent_quality"]
        assert advisory["schema_version"] == "workflow_agent_quality.v1"
        assert advisory["improved_request"]["schema_version"] == "improved_request.v1"
        assert advisory["plan_quality"]["schema_version"] == "plan_quality_review.v1"
        assert advisory["context_strategy"]
        assert advisory["token_strategy"]
        assert advisory["read_only"] is True

    async def test_quality_mode_surfaces_quality_boundaries(self, temp_project):
        (temp_project / "module.py").write_text("def fn():\n    return 1\n")

        payload = parse_payload(
            await mcp_server.run_workflow(
                mode="quality",
                target=".",
                option="correctness and regression safety",
                detail_level="full",
            )
        )

        assert payload["ok"] is True
        advisory = payload["details"]["agent_quality"]
        assert advisory["especially_visible"] is True
        quality_first = advisory["quality_first"]
        assert quality_first["enabled"] is True
        assert quality_first["clarified_goal"]
        assert quality_first["improved_request"]["schema_version"] == "improved_request.v1"
        assert quality_first["plan_quality_review"]["schema_version"] == "plan_quality_review.v1"
        assert advisory["plan_quality"]["summary"]
        assert advisory["context_strategy"]
        assert advisory["token_strategy"]
        assert quality_first["context_strategy"]
        assert quality_first["token_strategy"]
        assert quality_first["suggested_next_prompt"]
        result_template = advisory["quality_gate_plan"]["result_review_template"]
        assert result_template["schema_version"] == "result_quality_review.v1"
        assert result_template["next_small_fixes"]
        assert advisory["quality_gate_plan"]["checklist"]
        assert quality_first["result_quality_gate_checklist"]

    async def test_quality_mode_suggests_next_prompt(self, temp_project):
        (temp_project / "module.py").write_text("def fn():\n    return 1\n")

        payload = parse_payload(
            await mcp_server.run_workflow(mode="quality", target=".", detail_level="full")
        )

        assert payload["ok"] is True
        advisory = payload["details"]["agent_quality"]
        assert "smallest safe implementation slice" in advisory["suggested_next_prompt"]
        assert (
            advisory["quality_first"]["suggested_next_prompt"] == advisory["suggested_next_prompt"]
        )

    async def test_run_workflow_default_execute_false_does_not_mutate(self, temp_project):
        target = temp_project / "module.py"
        original = "def fn():\n    return 1\n"
        target.write_text(original)

        payload = parse_payload(await mcp_server.run_workflow(mode="quality", target="."))

        assert payload["ok"] is True
        assert payload["details"]["execute"] is False
        assert "execution" not in payload["details"]
        assert target.read_text() == original

    async def test_existing_workflow_mode_still_returns_original_fields(self, temp_project):
        (temp_project / "module.py").write_text("def fn():\n    return 1\n")

        payload = parse_payload(await mcp_server.run_workflow(mode="review", target="."))

        assert payload["ok"] is True
        details = payload["details"]
        assert details["mode"] == "review"
        assert details["steps"]
        assert details["recommended_tools"] == ["list_directory", "read_file"]
        assert details["detail_level"] == "compact"
        assert "examples" not in details
        assert "examples" in details["omitted_detail_keys"]
        assert details["agent_quality"]["quality_first"]["enabled"] is False

    async def test_executed_workflow_success_adds_summary_based_next_prompt(self, temp_project):
        target = temp_project / "module.py"
        target.write_text("def fn():\n    return 1\n")

        payload = parse_payload(
            await mcp_server.run_workflow(
                mode="quality",
                target="module.py",
                execute=True,
                detail_level="full",
            )
        )

        assert payload["ok"] is True
        advisory = payload["details"]["agent_quality"]
        assert advisory["schema_version"] == "workflow_agent_quality.v1"
        assert advisory["execution_summary"]["status"] == "succeeded"
        assert "read_file" in advisory["execution_summary"]["performed_actions"]
        assert "executed workflow summary" in advisory["suggested_next_prompt"]
        assert advisory["executed_result_quality"]["schema_version"] == "result_quality_review.v1"

    async def test_executed_workflow_failure_next_prompt_inspects_failure(self, temp_project):
        def json_response(
            ok: bool,
            message: str,
            *,
            code: str | None = None,
            details: dict | None = None,
        ) -> str:
            payload = {"ok": ok, "message": message, "details": details or {}}
            if code is not None:
                payload["code"] = code
            return json.dumps(payload)

        async def read_file(path: str) -> str:
            return json_response(True, "read", details={"path": path})

        async def list_directory(path: str) -> str:
            return json_response(True, "listed", details={"path": path})

        async def find_relevant_files(**kwargs: object) -> str:
            return json_response(
                False,
                "validation discovery failed",
                code="validation_failed",
                details={"output": "pytest failed"},
            )

        payload = parse_payload(
            await run_workflow_impl(
                mode="quality",
                target=".",
                option="regression safety",
                language="English",
                execute=True,
                max_iterations=3,
                resolve_path=lambda target: temp_project,
                read_file=read_file,
                list_directory=list_directory,
                find_relevant_files=find_relevant_files,
                path_from_active_root=lambda path: str(path),
                project_dir=lambda: temp_project,
                infer_project_root=lambda path: temp_project,
                json_response=json_response,
                detail_level="full",
            )
        )

        assert payload["ok"] is False
        advisory = payload["details"]["agent_quality"]
        assert advisory["execution_summary"]["status"] == "failed"
        assert advisory["execution_summary"]["error_code"] == "validation_failed"
        assert "Inspect this workflow failure" in advisory["suggested_next_prompt"]
        assert advisory["executed_result_quality"]["schema_version"] == "result_quality_review.v1"

    async def test_execute_false_keeps_agent_quality_schema(self, temp_project):
        (temp_project / "module.py").write_text("def fn():\n    return 1\n")

        payload = parse_payload(await mcp_server.run_workflow(mode="quality", target="."))

        assert payload["ok"] is True
        advisory = payload["details"]["agent_quality"]
        assert advisory["schema_version"] == "workflow_agent_quality.v1"
        assert "quality_first" in advisory
        assert "execution_summary" not in advisory
        assert payload["details"]["execute"] is False

    async def test_compact_mode_preserves_critical_step_info(self, temp_project):
        (temp_project / "module.py").write_text("def old():\n    return 1\n")

        compact_payload = parse_payload(
            await mcp_server.run_workflow(mode="review", target=".", detail_level="compact")
        )
        assert compact_payload["ok"] is True
        compact_details = compact_payload["details"]
        assert compact_details["detail_level"] == "compact"
        assert "omitted_detail_keys" in compact_details
        assert "steps" in compact_details
        assert len(compact_details["steps"]) > 0

    async def test_full_mode_vs_compact_mode_content_comparison(self, temp_project):
        (temp_project / "module.py").write_text("def old():\n    return 1\n")

        compact_payload = parse_payload(
            await mcp_server.run_workflow(mode="review", target=".", detail_level="compact")
        )
        full_payload = parse_payload(
            await mcp_server.run_workflow(mode="review", target=".", detail_level="full")
        )

        assert compact_payload["ok"] is True
        assert full_payload["ok"] is True

        compact_details = compact_payload["details"]
        full_details = full_payload["details"]

        assert compact_details["detail_level"] == "compact"
        assert "detail_level" not in full_details
        assert compact_details["mode"] == full_details["mode"]
        assert compact_details["target"] == full_details["target"]
        assert compact_details["steps"] == full_details["steps"]
        assert "examples" in full_details
        assert "examples" in compact_details["omitted_detail_keys"]
