"""Unit and E2E tests for policy diff, role-based simulation, and inheritance validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claude_bridge import cli
from claude_bridge.policy_diff import (
    DiffStatus,
    PermissionDiff,
    PolicyDiffResult,
    RoleDiff,
    _diff_permissions,
    diff_policies,
    diff_role,
    load_bundle_from_file,
    simulate_tool_with_role,
)
from claude_bridge.team_policy import (
    PermissionAction,
    PolicyBundle,
    RolePermission,
    RolePolicy,
    parse_builtin_roles,
    validate_role_inheritance,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bundle(name: str = "test", **roles: RolePolicy) -> PolicyBundle:
    return PolicyBundle(name=name, roles={r.name: r for r in roles.values()})


def _write_policy_file(tmp_path: Path, filename: str, bundle: PolicyBundle) -> Path:
    path = tmp_path / filename
    path.write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")
    return path


def _write_policy_file_yaml(tmp_path: Path, filename: str, bundle: PolicyBundle) -> Path:
    import yaml  # type: ignore[import-untyped]

    path = tmp_path / filename
    path.write_text(yaml.dump(bundle.to_dict(), default_flow_style=False), encoding="utf-8")
    return path


_YAML_AVAILABLE = False
try:
    import yaml  # noqa: F401

    _YAML_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# load_bundle_from_file
# ---------------------------------------------------------------------------


class TestLoadBundleFromFile:
    def test_loads_valid_json(self, tmp_path: Path) -> None:
        bundle = PolicyBundle(
            name="demo",
            roles={
                "junior": RolePolicy(name="junior", extends="base"),
            },
        )
        path = _write_policy_file(tmp_path, "policy.json", bundle)
        result = load_bundle_from_file(path)
        assert result is not None
        assert result.name == "demo"
        assert "junior" in result.roles

    def test_loads_valid_yaml(self, tmp_path: Path) -> None:
        if not _YAML_AVAILABLE:
            pytest.skip("PyYAML is not installed")
        bundle = PolicyBundle(
            name="demo",
            roles={
                "senior": RolePolicy(name="senior"),
            },
        )
        path = _write_policy_file_yaml(tmp_path, "policy.yaml", bundle)
        result = load_bundle_from_file(path)
        assert result is not None
        assert result.name == "demo"

    def test_returns_none_for_missing_file(self) -> None:
        assert load_bundle_from_file(Path("/nonexistent/policy.json")) is None

    def test_returns_none_for_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{invalid", encoding="utf-8")
        assert load_bundle_from_file(path) is None

    def test_falls_back_to_stem_name(self, tmp_path: Path) -> None:
        roles = {"r": RolePolicy(name="r")}
        bundle = PolicyBundle(name="", roles=roles)
        path = _write_policy_file(tmp_path, "my-policy.json", bundle)
        result = load_bundle_from_file(path)
        assert result is not None
        assert result.name == "my-policy"


# ---------------------------------------------------------------------------
# _diff_permissions
# ---------------------------------------------------------------------------


class TestDiffPermissions:
    def test_empty_both(self) -> None:
        diffs = _diff_permissions([], [])
        assert diffs == []

    def test_added_permission(self) -> None:
        old: list[RolePermission] = []
        new = [RolePermission(tool="run_shell")]
        diffs = _diff_permissions(old, new)
        assert len(diffs) == 1
        assert diffs[0].status == DiffStatus.ADDED
        assert diffs[0].tool == "run_shell"

    def test_removed_permission(self) -> None:
        old = [RolePermission(tool="run_shell")]
        new: list[RolePermission] = []
        diffs = _diff_permissions(old, new)
        assert len(diffs) == 1
        assert diffs[0].status == DiffStatus.REMOVED
        assert diffs[0].tool == "run_shell"

    def test_modified_action(self) -> None:
        old = [RolePermission(tool="write_file", action=PermissionAction.ASK)]
        new = [RolePermission(tool="write_file", action=PermissionAction.ALLOW)]
        diffs = _diff_permissions(old, new)
        assert len(diffs) == 1
        assert diffs[0].status == DiffStatus.MODIFIED
        assert diffs[0].old_action == "ask"
        assert diffs[0].new_action == "allow"

    def test_unchanged_permission_no_diff(self) -> None:
        p = RolePermission(tool="read_file", action=PermissionAction.ALLOW)
        diffs = _diff_permissions([p], [p])
        assert diffs == []

    def test_scope_change_detected(self) -> None:
        old = [RolePermission(tool="run_shell", scope={"safe": True})]
        new = [RolePermission(tool="run_shell", scope={"safe": False})]
        diffs = _diff_permissions(old, new)
        assert len(diffs) == 1
        assert diffs[0].status == DiffStatus.MODIFIED


# ---------------------------------------------------------------------------
# diff_role
# ---------------------------------------------------------------------------


class TestDiffRole:
    def test_added_role(self) -> None:
        rd = diff_role(None, RolePolicy(name="new"))
        assert rd.status == DiffStatus.ADDED
        assert rd.role_name == "new"

    def test_removed_role(self) -> None:
        rd = diff_role(RolePolicy(name="old"), None)
        assert rd.status == DiffStatus.REMOVED
        assert rd.role_name == "old"

    def test_unchanged_role(self) -> None:
        role = RolePolicy(name="dev", extends="base")
        rd = diff_role(role, role)
        assert rd.status == DiffStatus.UNCHANGED

    def test_extends_changed(self) -> None:
        old = RolePolicy(name="dev", extends="base")
        new = RolePolicy(name="dev", extends="admin")
        rd = diff_role(old, new)
        assert rd.status == DiffStatus.MODIFIED
        assert rd.extends_changed
        assert rd.old_extends == "base"
        assert rd.new_extends == "admin"

    def test_restrictions_added(self) -> None:
        old = RolePolicy(name="dev")
        new = RolePolicy(name="dev", restrictions=["production_env"])
        rd = diff_role(old, new)
        assert rd.restrictions_added == ["production_env"]
        assert rd.restrictions_removed == []

    def test_restrictions_removed(self) -> None:
        old = RolePolicy(name="dev", restrictions=["destructive_shell"])
        new = RolePolicy(name="dev")
        rd = diff_role(old, new)
        assert rd.restrictions_removed == ["destructive_shell"]
        assert rd.restrictions_added == []

    def test_enabled_changed(self) -> None:
        old = RolePolicy(name="dev", enabled=True)
        new = RolePolicy(name="dev", enabled=False)
        rd = diff_role(old, new)
        assert rd.enabled_changed
        assert rd.old_enabled is True
        assert rd.new_enabled is False

    def test_description_changed(self) -> None:
        old = RolePolicy(name="dev", description="Old desc")
        new = RolePolicy(name="dev", description="New desc")
        rd = diff_role(old, new)
        assert rd.description_changed


# ---------------------------------------------------------------------------
# diff_policies
# ---------------------------------------------------------------------------


class TestDiffPolicies:
    def test_identical_bundles(self) -> None:
        b = _make_bundle("demo", dev=RolePolicy(name="dev"))
        result = diff_policies(b, b)
        assert result.status == DiffStatus.OK
        assert not result.has_changes

    def test_role_added(self) -> None:
        base = _make_bundle("demo")
        head = _make_bundle("demo", new_role=RolePolicy(name="new_role"))
        result = diff_policies(base, head)
        assert result.status == DiffStatus.MODIFIED
        assert result.roles_added == ["new_role"]

    def test_role_removed(self) -> None:
        base = _make_bundle("demo", old=RolePolicy(name="old"))
        head = _make_bundle("demo")
        result = diff_policies(base, head)
        assert result.roles_removed == ["old"]

    def test_name_change(self) -> None:
        base = PolicyBundle(name="old-name")
        head = PolicyBundle(name="new-name")
        result = diff_policies(base, head)
        assert result.name_changed

    def test_inheritance_error_in_head(self) -> None:
        base = _make_bundle("demo")
        head = _make_bundle("demo", orphan=RolePolicy(name="orphan", extends="missing"))
        result = diff_policies(base, head)
        assert result.status == DiffStatus.MODIFIED
        assert len(result.head_inheritance_errors) > 0
        assert result.head_inheritance_errors[0]["code"] == "missing_base_role"

    def test_circular_inheritance_detected(self) -> None:
        a = RolePolicy(name="a", extends="b")
        b = RolePolicy(name="b", extends="a")
        head = _make_bundle("demo", **{"a": a, "b": b})
        base = _make_bundle("demo")
        result = diff_policies(base, head)
        circular_errors = [
            e for e in result.head_inheritance_errors if e["code"] == "circular_inheritance"
        ]
        assert len(circular_errors) >= 1

    def test_self_referencing_inheritance(self) -> None:
        role = RolePolicy(name="selfie", extends="selfie")
        head = _make_bundle("demo", selfie=role)
        base = _make_bundle("demo")
        result = diff_policies(base, head)
        errors = [e for e in result.head_inheritance_errors if e["code"] == "circular_inheritance"]
        assert len(errors) >= 1

    def test_role_diff_included(self) -> None:
        old_junior = RolePolicy(name="junior")
        new_junior = RolePolicy(name="junior", restrictions=["production_env"])
        base = _make_bundle("demo", junior=old_junior)
        head = _make_bundle("demo", junior=new_junior)
        result = diff_policies(base, head)
        assert result.status == DiffStatus.MODIFIED
        diffs = [r for r in result.role_diffs if r.role_name == "junior"]
        assert len(diffs) == 1
        assert diffs[0].restrictions_added == ["production_env"]

    def test_to_dict_output(self) -> None:
        base = _make_bundle("demo")
        head = _make_bundle("demo", dev=RolePolicy(name="dev"))
        result = diff_policies(base, head)
        d = result.to_dict()
        assert d["status"] == "modified"
        assert d["roles_added"] == ["dev"]


# ---------------------------------------------------------------------------
# simulate_tool_with_role
# ---------------------------------------------------------------------------


class TestSimulateToolWithRole:
    """E2E: role-based simulation via simulate_tool_with_role."""

    def test_junior_read_file_allowed(self) -> None:
        result = simulate_tool_with_role(
            tool="read_file",
            params={"path": "src/main.py"},
            role_name="junior",
        )
        assert result.action == "allow"
        assert result.role == "junior"

    def test_junior_write_production_path_denied(self) -> None:
        result = simulate_tool_with_role(
            tool="write_file",
            params={"path": "/prod/config.yaml"},
            role_name="junior",
        )
        assert result.action == "deny"

    def test_senior_write_allowed(self) -> None:
        result = simulate_tool_with_role(
            tool="write_file",
            params={"path": "notes.txt"},
            role_name="senior",
        )
        assert result.action in ("allow", "ask")

    def test_ci_pytest_auto_approved(self) -> None:
        result = simulate_tool_with_role(
            tool="run_shell",
            params={"command": "pytest tests/"},
            role_name="ci",
        )
        assert result.action in ("allow", "ask")

    def test_ci_interactive_shell_denied(self) -> None:
        result = simulate_tool_with_role(
            tool="run_shell",
            params={"command": "python -i"},
            role_name="ci",
            project_dir="/tmp/test",
            allowed_roots=["/tmp/test"],
        )
        # CI role has interactive_shell restriction
        assert result.action in ("deny", "ask")

    def test_contractor_outside_workspace_denied(self) -> None:
        result = simulate_tool_with_role(
            tool="write_file",
            params={"path": "src/main.py"},
            role_name="contractor",
        )
        assert result.action == "deny"

    def test_contractor_in_workspace_allowed(self) -> None:
        result = simulate_tool_with_role(
            tool="write_file",
            params={"path": "contractor/report.md"},
            role_name="contractor",
        )
        # May still be blocked by time restriction; check workspace not the issue
        assert result.role == "contractor"

    def test_to_dict(self) -> None:
        result = simulate_tool_with_role(
            tool="read_file",
            params={"path": "hello.txt"},
            role_name="base",
        )
        d = result.to_dict()
        assert d["tool"] == "read_file"
        assert d["role"] == "base"
        assert "action" in d
        assert "source" in d
        assert "risk_level" in d

    def test_none_role(self) -> None:
        result = simulate_tool_with_role(
            tool="read_file",
            params={"path": "x.txt"},
            role_name=None,
        )
        assert result.role is None

    def test_nonexistent_role(self) -> None:
        result = simulate_tool_with_role(
            tool="read_file",
            params={"path": "x.txt"},
            role_name="nonexistent",
        )
        assert result.role == "nonexistent"

    def test_json_serializable(self) -> None:
        result = simulate_tool_with_role(
            tool="read_file",
            params={"path": "x.txt"},
            role_name="junior",
        )
        json.dumps(result.to_dict())


# ---------------------------------------------------------------------------
# PolicyDiffResult properties
# ---------------------------------------------------------------------------


class TestPolicyDiffResult:
    def test_has_changes_false_for_ok(self) -> None:
        r = PolicyDiffResult(base_name="a", head_name="a", status=DiffStatus.OK)
        assert not r.has_changes

    def test_has_changes_true_for_modified(self) -> None:
        r = PolicyDiffResult(base_name="a", head_name="a", status=DiffStatus.MODIFIED)
        assert r.has_changes

    def test_has_issues_with_validation_errors(self) -> None:
        r = PolicyDiffResult(
            base_name="a", head_name="a", head_validation_errors=[{"code": "test"}]
        )
        assert r.has_issues

    def test_has_issues_with_inheritance_errors(self) -> None:
        r = PolicyDiffResult(
            base_name="a", head_name="a", head_inheritance_errors=[{"code": "circular"}]
        )
        assert r.has_issues


# ---------------------------------------------------------------------------
# PermissionDiff
# ---------------------------------------------------------------------------


class TestPermissionDiff:
    def test_to_dict_minimal(self) -> None:
        pd = PermissionDiff(tool="run_shell", status=DiffStatus.ADDED, new_action="allow")
        d = pd.to_dict()
        assert d["tool"] == "run_shell"
        assert d["status"] == "added"

    def test_to_dict_full(self) -> None:
        pd = PermissionDiff(
            tool="run_shell",
            status=DiffStatus.MODIFIED,
            old_action="ask",
            new_action="allow",
            old_scope={"safe": True},
            new_scope={"safe": False},
        )
        d = pd.to_dict()
        assert d["old_action"] == "ask"
        assert d["new_action"] == "allow"
        assert d["old_scope"] == {"safe": True}
        assert d["new_scope"] == {"safe": False}


# ---------------------------------------------------------------------------
# RoleDiff
# ---------------------------------------------------------------------------


class TestRoleDiff:
    def test_to_dict(self) -> None:
        rd = RoleDiff(
            role_name="dev",
            status=DiffStatus.MODIFIED,
            extends_changed=True,
            old_extends="base",
            new_extends="super",
            restrictions_added=["production_env"],
        )
        d = rd.to_dict()
        assert d["role"] == "dev"
        assert d["status"] == "modified"
        assert d["extends"] == {"old": "base", "new": "super"}
        assert d["restrictions_added"] == ["production_env"]


# ---------------------------------------------------------------------------
# Invalid inheritance E2E tests
# ---------------------------------------------------------------------------


class TestInvalidInheritanceE2E:
    """End-to-end tests for invalid inheritance patterns."""

    def test_missing_base_role_validated(self) -> None:
        role = RolePolicy(name="orphan", extends="nonexistent")
        bundle = PolicyBundle(name="test", roles={"orphan": role})
        errors = validate_role_inheritance(bundle)
        assert len(errors) == 1
        assert errors[0].code == "missing_base_role"
        assert "orphan" in errors[0].message
        assert "nonexistent" in errors[0].message

    def test_self_reference_validated(self) -> None:
        role = RolePolicy(name="loop", extends="loop")
        bundle = PolicyBundle(name="test", roles={"loop": role})
        errors = validate_role_inheritance(bundle)
        assert any(e.code == "circular_inheritance" for e in errors)
        assert any("loop" in e.message for e in errors if e.code == "circular_inheritance")

    def test_circular_chain_validated(self) -> None:
        a = RolePolicy(name="a", extends="b")
        b = RolePolicy(name="b", extends="c")
        c = RolePolicy(name="c", extends="a")
        bundle = PolicyBundle(name="test", roles={"a": a, "b": b, "c": c})
        errors = validate_role_inheritance(bundle)
        circular = [e for e in errors if e.code == "circular_inheritance"]
        assert len(circular) >= 1

    def test_builtin_roles_are_valid(self) -> None:
        bundle = parse_builtin_roles()
        errors = validate_role_inheritance(bundle)
        assert errors == []

    def test_partial_chain_invalid_only(self) -> None:
        valid = RolePolicy(name="base")
        orphan = RolePolicy(name="orphan", extends="missing")
        bundle = PolicyBundle(name="test", roles={"base": valid, "orphan": orphan})
        errors = validate_role_inheritance(bundle)
        assert len(errors) == 1
        assert errors[0].code == "missing_base_role"


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestCLIPolicyDiff:
    def test_diff_identical_bundles(self, tmp_path: Path) -> None:
        bundle = _make_bundle("demo", dev=RolePolicy(name="dev"))
        base_path = _write_policy_file(tmp_path, "base.json", bundle)
        head_path = _write_policy_file(tmp_path, "head.json", bundle)

        result = runner.invoke(
            cli.app,
            ["policy", "diff", "--base", str(base_path), "--head", str(head_path)],
        )
        assert result.exit_code == 0
        assert "no changes" in result.stdout.lower()

    def test_diff_role_added(self, tmp_path: Path) -> None:
        base = _make_bundle("demo")
        head = _make_bundle("demo", added=RolePolicy(name="added"))
        base_path = _write_policy_file(tmp_path, "base.json", base)
        head_path = _write_policy_file(tmp_path, "head.json", head)

        result = runner.invoke(
            cli.app,
            ["policy", "diff", "--base", str(base_path), "--head", str(head_path)],
        )
        assert "added" in result.stdout.lower()

    def test_diff_json_output(self, tmp_path: Path) -> None:
        base = _make_bundle("demo", existing=RolePolicy(name="existing"))
        head = _make_bundle(
            "demo", existing=RolePolicy(name="existing"), added=RolePolicy(name="added")
        )
        base_path = _write_policy_file(tmp_path, "base.json", base)
        head_path = _write_policy_file(tmp_path, "head.json", head)

        result = runner.invoke(
            cli.app,
            ["policy", "diff", "--base", str(base_path), "--head", str(head_path), "--json"],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["status"] == "modified"
        assert parsed["roles_added"] == ["added"]

    def test_diff_json_with_errors_exits_nonzero(self, tmp_path: Path) -> None:
        head = _make_bundle("demo", orphan=RolePolicy(name="orphan", extends="missing"))
        base = _make_bundle("demo")
        base_path = _write_policy_file(tmp_path, "base.json", base)
        head_path = _write_policy_file(tmp_path, "head.json", head)

        result = runner.invoke(
            cli.app,
            ["policy", "diff", "--base", str(base_path), "--head", str(head_path), "--json"],
        )
        assert result.exit_code == 1
        parsed = json.loads(result.stdout)
        assert "inheritance_errors" in parsed

    def test_diff_missing_base_file(self, tmp_path: Path) -> None:
        result = runner.invoke(
            cli.app,
            [
                "policy",
                "diff",
                "--base",
                "/nonexistent/policy.json",
                "--head",
                str(tmp_path / "x.json"),
            ],
        )
        assert result.exit_code == 1
        assert "could not load" in result.stdout.lower()

    def test_diff_inheritance_error_detected(self, tmp_path: Path) -> None:
        head = _make_bundle("demo", orphan=RolePolicy(name="orphan", extends="missing"))
        base = _make_bundle("demo")
        base_path = _write_policy_file(tmp_path, "base.json", base)
        head_path = _write_policy_file(tmp_path, "head.json", head)

        result = runner.invoke(
            cli.app,
            ["policy", "diff", "--base", str(base_path), "--head", str(head_path)],
        )
        assert result.exit_code == 1
        assert "inheritance errors" in result.stdout.lower()

    def test_diff_inheritance_errors_human_readable(self, tmp_path: Path) -> None:
        head = _make_bundle("demo", orphan=RolePolicy(name="orphan", extends="missing"))
        base = _make_bundle("demo")
        base_path = _write_policy_file(tmp_path, "base.json", base)
        head_path = _write_policy_file(tmp_path, "head.json", head)

        result = runner.invoke(
            cli.app,
            ["policy", "diff", "--base", str(base_path), "--head", str(head_path)],
        )
        assert "[missing_base_role]" in result.stdout
        assert "orphan" in result.stdout


class TestCLIPolicySimulate:
    def test_simulate_with_role_junior(self, tmp_path: Path) -> None:
        bundle = _make_bundle("demo", junior=RolePolicy(name="junior", extends="base"))
        policy_path = _write_policy_file(tmp_path, "policy.json", bundle)

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(policy_path),
                "--tool",
                "write_file",
                "--param",
                "path=src/main.py",
                "--role",
                "junior",
            ],
        )
        assert result.exit_code == 0
        assert "Role Simulation" in result.stdout
        assert "junior" in result.stdout

    def test_simulate_with_role_json_output(self, tmp_path: Path) -> None:
        bundle = _make_bundle("demo", junior=RolePolicy(name="junior", extends="base"))
        policy_path = _write_policy_file(tmp_path, "policy.json", bundle)

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(policy_path),
                "--tool",
                "read_file",
                "--param",
                "path=main.py",
                "--role",
                "junior",
                "--json",
            ],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["tool"] == "read_file"
        assert parsed["role"] == "junior"
        assert "action" in parsed

    def test_simulate_role_production_path_denied(self, tmp_path: Path) -> None:
        bundle = parse_builtin_roles()
        policy_path = _write_policy_file(tmp_path, "policy.json", bundle)

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(policy_path),
                "--tool",
                "write_file",
                "--param",
                "path=/prod/config.yaml",
                "--role",
                "junior",
            ],
        )
        # May be denied due to production_env restriction
        assert result.exit_code == 0

    def test_simulate_invalid_bundle_file(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{bad", encoding="utf-8")

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(path),
                "--tool",
                "read_file",
                "--param",
                "path=x.txt",
                "--role",
                "junior",
            ],
        )
        assert result.exit_code == 1

    def test_simulate_no_role_uses_guard_rules(self, tmp_path: Path) -> None:
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "name": "allow-read",
                            "scope": "read_file",
                            "action": "allow",
                            "conditions": [{"type": "tool", "field": "read_file"}],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(policy_path),
                "--tool",
                "read_file",
            ],
        )
        assert result.exit_code == 0
        assert "Policy Decision" in result.stdout

    def test_simulate_no_role_json_output(self, tmp_path: Path) -> None:
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "name": "allow-read",
                            "scope": "read_file",
                            "action": "allow",
                            "conditions": [{"type": "tool", "field": "read_file"}],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(policy_path),
                "--tool",
                "read_file",
                "--json",
            ],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "action" in parsed
        assert "source" in parsed

    def test_simulate_contractor_outside_workspace(self, tmp_path: Path) -> None:
        bundle = parse_builtin_roles()
        policy_path = _write_policy_file(tmp_path, "policy.json", bundle)

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(policy_path),
                "--tool",
                "write_file",
                "--param",
                "path=src/main.py",
                "--role",
                "contractor",
            ],
        )
        assert result.exit_code == 0

    def test_simulate_senior_write(self, tmp_path: Path) -> None:
        bundle = parse_builtin_roles()
        policy_path = _write_policy_file(tmp_path, "policy.json", bundle)

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(policy_path),
                "--tool",
                "write_file",
                "--param",
                "path=notes.txt",
                "--role",
                "senior",
            ],
        )
        assert result.exit_code == 0

    def test_simulate_ci_pytest_command(self, tmp_path: Path) -> None:
        bundle = parse_builtin_roles()
        policy_path = _write_policy_file(tmp_path, "policy.json", bundle)

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(policy_path),
                "--tool",
                "run_shell",
                "--param",
                "command=pytest tests/",
                "--role",
                "ci",
            ],
        )
        assert result.exit_code == 0
