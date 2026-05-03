"""Unit tests for team role and policy bundle models."""

from __future__ import annotations

import json

import pytest

from claude_bridge.team_policy import (
    BUILTIN_ROLE_DEFINITIONS,
    PermissionAction,
    PolicyBundle,
    RolePermission,
    RolePolicy,
    evaluate_role_post_restrictions,
    evaluate_role_pre_restrictions,
    is_ci_auto_approve_allowed,
    parse_builtin_roles,
    resolve_role_permissions,
    validate_policy_bundle,
    validate_role_inheritance,
    validate_role_policy,
)
from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    PolicyDecision,
    RiskLevel,
    ToolRequestContext,
)


# ---------------------------------------------------------------------------
# PermissionAction
# ---------------------------------------------------------------------------


class TestPermissionAction:
    def test_members(self) -> None:
        assert PermissionAction.ALLOW.value == "allow"
        assert PermissionAction.DENY.value == "deny"
        assert PermissionAction.ASK.value == "ask"

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            PermissionAction("bogus")

    def test_three_members(self) -> None:
        assert len(list(PermissionAction)) == 3


# ---------------------------------------------------------------------------
# RolePermission
# ---------------------------------------------------------------------------


class TestRolePermission:
    def test_construction_minimal(self) -> None:
        p = RolePermission(tool="read_file")
        assert p.tool == "read_file"
        assert p.action is PermissionAction.ALLOW
        assert p.scope == {}
        assert p.description == ""

    def test_construction_full(self) -> None:
        p = RolePermission(
            tool="run_shell",
            action=PermissionAction.ASK,
            scope={"safe_commands_only": True},
            description="Shell with restrictions",
        )
        assert p.tool == "run_shell"
        assert p.action is PermissionAction.ASK
        assert p.scope == {"safe_commands_only": True}
        assert p.description == "Shell with restrictions"

    def test_to_dict_minimal(self) -> None:
        p = RolePermission(tool="write_file", action=PermissionAction.DENY)
        result = p.to_dict()
        assert result == {"tool": "write_file", "action": "deny"}

    def test_to_dict_full(self) -> None:
        p = RolePermission(
            tool="run_shell",
            action=PermissionAction.ASK,
            scope={"ci": True},
            description="desc",
        )
        result = p.to_dict()
        assert result["tool"] == "run_shell"
        assert result["action"] == "ask"
        assert result["scope"] == {"ci": True}
        assert result["description"] == "desc"

    def test_from_dict_roundtrip(self) -> None:
        p = RolePermission(
            tool="write_file",
            action=PermissionAction.ALLOW,
            scope={"path": "/tmp"},
            description="Temporary writes",
        )
        restored = RolePermission.from_dict(p.to_dict())
        assert restored.tool == p.tool
        assert restored.action == p.action
        assert restored.scope == p.scope
        assert restored.description == p.description

    def test_from_dict_invalid_action_defaults(self) -> None:
        restored = RolePermission.from_dict(
            {"tool": "read_file", "action": "bogus"}
        )
        assert restored.action is PermissionAction.ALLOW

    def test_from_dict_empty(self) -> None:
        restored = RolePermission.from_dict({})
        assert restored.tool == ""
        assert restored.action is PermissionAction.ALLOW

    def test_from_dict_non_dict(self) -> None:
        restored = RolePermission.from_dict("not a dict")  # type: ignore[arg-type]
        assert restored.tool == ""

    def test_to_dict_json_serializable(self) -> None:
        p = RolePermission(tool="read_file", action=PermissionAction.ALLOW)
        raw = json.dumps(p.to_dict())
        parsed = json.loads(raw)
        assert parsed["tool"] == "read_file"


# ---------------------------------------------------------------------------
# RolePolicy
# ---------------------------------------------------------------------------


class TestRolePolicy:
    def test_construction_minimal(self) -> None:
        r = RolePolicy(name="dev")
        assert r.name == "dev"
        assert r.description == ""
        assert r.extends is None
        assert r.permissions == []
        assert r.restrictions == []
        assert r.metadata == {}
        assert r.enabled is True

    def test_construction_full(self) -> None:
        r = RolePolicy(
            name="senior",
            description="Senior developer",
            extends="base",
            permissions=[RolePermission(tool="write_file", action=PermissionAction.ALLOW)],
            restrictions=["destructive_shell"],
            metadata={"risk_level": "low"},
            enabled=False,
        )
        assert r.name == "senior"
        assert r.extends == "base"
        assert len(r.permissions) == 1
        assert r.restrictions == ["destructive_shell"]
        assert r.metadata == {"risk_level": "low"}
        assert r.enabled is False

    def test_to_dict_no_extends(self) -> None:
        r = RolePolicy(name="base")
        result = r.to_dict()
        assert "extends" not in result

    def test_to_dict_with_extends(self) -> None:
        r = RolePolicy(name="junior", extends="base")
        result = r.to_dict()
        assert result["extends"] == "base"

    def test_to_dict_with_metadata(self) -> None:
        r = RolePolicy(name="x", metadata={"level": 1})
        result = r.to_dict()
        assert result["metadata"] == {"level": 1}

    def test_to_dict_no_metadata_omitted(self) -> None:
        r = RolePolicy(name="x")
        result = r.to_dict()
        assert "metadata" not in result

    def test_from_dict_roundtrip(self) -> None:
        r = RolePolicy(
            name="contractor",
            description="Restricted",
            extends="base",
            permissions=[RolePermission(tool="read_file")],
            restrictions=["prod"],
            metadata={"risk": "high"},
        )
        restored = RolePolicy.from_dict(r.to_dict())
        assert restored.name == r.name
        assert restored.description == r.description
        assert restored.extends == r.extends
        assert len(restored.permissions) == 1
        assert restored.restrictions == r.restrictions
        assert restored.metadata == r.metadata

    def test_from_dict_empty(self) -> None:
        r = RolePolicy.from_dict({})
        assert r.name == ""
        assert r.extends is None

    def test_from_dict_non_dict(self) -> None:
        r = RolePolicy.from_dict("bad")  # type: ignore[arg-type]
        assert r.name == ""

    def test_from_dict_permissions_list(self) -> None:
        r = RolePolicy.from_dict(
            {"name": "dev", "permissions": [{"tool": "read", "action": "allow"}]}
        )
        assert len(r.permissions) == 1
        assert r.permissions[0].tool == "read"

    def test_from_dict_restrictions(self) -> None:
        r = RolePolicy.from_dict(
            {"name": "dev", "restrictions": ["a", "b"]}
        )
        assert r.restrictions == ["a", "b"]

    def test_from_dict_extends_none(self) -> None:
        r = RolePolicy.from_dict({"name": "root", "extends": None})
        assert r.extends is None

    def test_from_dict_extends_string(self) -> None:
        r = RolePolicy.from_dict({"name": "child", "extends": "parent"})
        assert r.extends == "parent"


# ---------------------------------------------------------------------------
# PolicyBundle
# ---------------------------------------------------------------------------


class TestPolicyBundle:
    def test_construction_minimal(self) -> None:
        b = PolicyBundle(name="test")
        assert b.name == "test"
        assert b.roles == {}
        assert b.metadata == {}

    def test_construction_with_roles(self) -> None:
        base = RolePolicy(name="base")
        junior = RolePolicy(name="junior", extends="base")
        b = PolicyBundle(name="team", roles={"base": base, "junior": junior})
        assert len(b.roles) == 2

    def test_add_role(self) -> None:
        b = PolicyBundle(name="test")
        r = RolePolicy(name="dev")
        b.add_role(r)
        assert "dev" in b.roles

    def test_get_role(self) -> None:
        b = PolicyBundle(name="test", roles={"base": RolePolicy(name="base")})
        assert b.get_role("base") is not None
        assert b.get_role("missing") is None

    def test_to_dict_roundtrip(self) -> None:
        base = RolePolicy(name="base")
        junior = RolePolicy(name="junior", extends="base")
        b = PolicyBundle(name="team", roles={"base": base, "junior": junior})
        result = b.to_dict()
        assert result["name"] == "team"
        assert "base" in result["roles"]
        assert "junior" in result["roles"]

    def test_from_dict_roundtrip(self) -> None:
        base = RolePolicy(name="base")
        junior = RolePolicy(name="junior", extends="base")
        b = PolicyBundle(name="team", roles={"base": base, "junior": junior})
        restored = PolicyBundle.from_dict(b.to_dict())
        assert restored.name == "team"
        assert "base" in restored.roles
        assert "junior" in restored.roles
        assert restored.roles["junior"].extends == "base"

    def test_from_dict_empty(self) -> None:
        b = PolicyBundle.from_dict({})
        assert b.name == ""
        assert b.roles == {}

    def test_from_dict_non_dict(self) -> None:
        b = PolicyBundle.from_dict("bad")  # type: ignore[arg-type]
        assert b.name == ""

    def test_to_dict_json_serializable(self) -> None:
        b = parse_builtin_roles()
        raw = json.dumps(b.to_dict())
        parsed = json.loads(raw)
        assert parsed["name"] == "builtin"


# ---------------------------------------------------------------------------
# parse_builtin_roles
# ---------------------------------------------------------------------------


class TestParseBuiltinRoles:
    def test_returns_bundle(self) -> None:
        bundle = parse_builtin_roles()
        assert isinstance(bundle, PolicyBundle)
        assert bundle.name == "builtin"

    def test_contains_all_builtin_roles(self) -> None:
        bundle = parse_builtin_roles()
        for role_name in ("base", "junior", "senior", "ci", "contractor"):
            assert role_name in bundle.roles, f"Missing role: {role_name}"

    def test_base_has_no_extends(self) -> None:
        bundle = parse_builtin_roles()
        assert bundle.roles["base"].extends is None

    def test_junior_extends_base(self) -> None:
        bundle = parse_builtin_roles()
        assert bundle.roles["junior"].extends == "base"

    def test_senior_extends_base(self) -> None:
        bundle = parse_builtin_roles()
        assert bundle.roles["senior"].extends == "base"

    def test_ci_extends_base(self) -> None:
        bundle = parse_builtin_roles()
        assert bundle.roles["ci"].extends == "base"

    def test_contractor_extends_base(self) -> None:
        bundle = parse_builtin_roles()
        assert bundle.roles["contractor"].extends == "base"

    def test_builtin_roles_are_enabled(self) -> None:
        bundle = parse_builtin_roles()
        for role in bundle.roles.values():
            assert role.enabled is True

    def test_junior_has_ask_permissions(self) -> None:
        bundle = parse_builtin_roles()
        junior = bundle.roles["junior"]
        ask_perms = [p for p in junior.permissions if p.action == PermissionAction.ASK]
        assert len(ask_perms) > 0

    def test_contractor_has_many_restrictions(self) -> None:
        bundle = parse_builtin_roles()
        contractor = bundle.roles["contractor"]
        assert len(contractor.restrictions) >= 4

    def test_builtin_roles_validate_clean(self) -> None:
        bundle = parse_builtin_roles()
        errors = validate_policy_bundle(bundle)
        assert errors == []


# ---------------------------------------------------------------------------
# resolve_role_permissions
# ---------------------------------------------------------------------------


class TestResolveRolePermissions:
    def test_base_role_permissions_only(self) -> None:
        bundle = parse_builtin_roles()
        perms = resolve_role_permissions(bundle.roles["base"], bundle)
        assert len(perms) == 3
        assert all(isinstance(p, RolePermission) for p in perms)

    def test_junior_inherits_base(self) -> None:
        bundle = parse_builtin_roles()
        junior_perms = resolve_role_permissions(bundle.roles["junior"], bundle)
        base_perms = resolve_role_permissions(bundle.roles["base"], bundle)
        assert len(junior_perms) > len(base_perms)
        assert junior_perms[0].tool == "read_file"

    def test_senior_inherits_base_plus_own(self) -> None:
        bundle = parse_builtin_roles()
        perms = resolve_role_permissions(bundle.roles["senior"], bundle)
        tool_names = [p.tool for p in perms]
        assert "read_file" in tool_names
        assert "git_operations" in tool_names

    def test_role_without_extends(self) -> None:
        role = RolePolicy(
            name="standalone",
            permissions=[RolePermission(tool="read_file")],
        )
        bundle = PolicyBundle(name="test", roles={"standalone": role})
        perms = resolve_role_permissions(role, bundle)
        assert len(perms) == 1
        assert perms[0].tool == "read_file"

    def test_missing_parent_returns_own_perms(self) -> None:
        role = RolePolicy(
            name="orphan",
            extends="nonexistent",
            permissions=[RolePermission(tool="write_file")],
        )
        bundle = PolicyBundle(name="test", roles={"orphan": role})
        perms = resolve_role_permissions(role, bundle)
        assert len(perms) == 1

    def test_circular_chain_truncated(self) -> None:
        a = RolePolicy(name="a", extends="b", permissions=[RolePermission(tool="read_file")])
        b = RolePolicy(name="b", extends="a", permissions=[RolePermission(tool="write_file")])
        bundle = PolicyBundle(name="test", roles={"a": a, "b": b})
        perms_a = resolve_role_permissions(a, bundle)
        assert len(perms_a) >= 1


# ---------------------------------------------------------------------------
# validate_role_inheritance
# ---------------------------------------------------------------------------


class TestValidateRoleInheritance:
    def test_valid_bundle_no_errors(self) -> None:
        bundle = parse_builtin_roles()
        errors = validate_role_inheritance(bundle)
        assert errors == []

    def test_self_reference(self) -> None:
        role = RolePolicy(name="selfish", extends="selfish")
        bundle = PolicyBundle(name="test", roles={"selfish": role})
        errors = validate_role_inheritance(bundle)
        assert len(errors) == 1
        assert errors[0].code == "circular_inheritance"
        assert "selfish" in errors[0].message

    def test_missing_base(self) -> None:
        role = RolePolicy(name="orphan", extends="nonexistent")
        bundle = PolicyBundle(name="test", roles={"orphan": role})
        errors = validate_role_inheritance(bundle)
        assert len(errors) == 1
        assert errors[0].code == "missing_base_role"

    def test_circular_chain_a_b_a(self) -> None:
        a = RolePolicy(name="a", extends="b")
        b = RolePolicy(name="b", extends="a")
        bundle = PolicyBundle(name="test", roles={"a": a, "b": b})
        errors = validate_role_inheritance(bundle)
        assert any(e.code == "circular_inheritance" for e in errors)

    def test_circular_chain_three_nodes(self) -> None:
        a = RolePolicy(name="a", extends="b")
        b = RolePolicy(name="b", extends="c")
        c = RolePolicy(name="c", extends="a")
        bundle = PolicyBundle(name="test", roles={"a": a, "b": b, "c": c})
        errors = validate_role_inheritance(bundle)
        assert any(e.code == "circular_inheritance" for e in errors)

    def test_no_extends_no_errors(self) -> None:
        role = RolePolicy(name="root")
        bundle = PolicyBundle(name="test", roles={"root": role})
        errors = validate_role_inheritance(bundle)
        assert errors == []


# ---------------------------------------------------------------------------
# validate_role_policy
# ---------------------------------------------------------------------------


class TestValidateRolePolicy:
    def test_valid_role_no_errors(self) -> None:
        role = RolePolicy(name="dev", permissions=[RolePermission(tool="read_file")])
        errors = validate_role_policy(role)
        assert errors == []

    def test_empty_name(self) -> None:
        role = RolePolicy(name="")
        errors = validate_role_policy(role)
        assert any(e.code == "empty_role_name" for e in errors)

    def test_whitespace_name(self) -> None:
        role = RolePolicy(name="  ")
        errors = validate_role_policy(role)
        assert any(e.code == "empty_role_name" for e in errors)

    def test_empty_extends(self) -> None:
        role = RolePolicy(name="dev", extends="  ")
        errors = validate_role_policy(role)
        assert any(e.code == "empty_extends" for e in errors)

    def test_empty_permission_tool(self) -> None:
        role = RolePolicy(
            name="dev",
            permissions=[RolePermission(tool="")],
        )
        errors = validate_role_policy(role)
        assert any(e.code == "empty_permission_tool" for e in errors)

    def test_empty_restriction(self) -> None:
        role = RolePolicy(name="dev", restrictions=[""])
        errors = validate_role_policy(role)
        assert any(e.code == "empty_restriction" for e in errors)

    def test_custom_path_prefix(self) -> None:
        role = RolePolicy(name="")
        errors = validate_role_policy(role, path_prefix="custom.path")
        assert errors[0].path.startswith("custom.path")


# ---------------------------------------------------------------------------
# validate_policy_bundle
# ---------------------------------------------------------------------------


class TestValidatePolicyBundle:
    def test_valid_bundle_no_errors(self) -> None:
        bundle = parse_builtin_roles()
        errors = validate_policy_bundle(bundle)
        assert errors == []

    def test_empty_name(self) -> None:
        bundle = PolicyBundle(name="")
        errors = validate_policy_bundle(bundle)
        assert any(e.code == "empty_bundle_name" for e in errors)

    def test_empty_roles(self) -> None:
        bundle = PolicyBundle(name="test")
        errors = validate_policy_bundle(bundle)
        assert any(e.code == "empty_roles" for e in errors)

    def test_key_mismatch(self) -> None:
        role = RolePolicy(name="alpha")
        bundle = PolicyBundle(name="test", roles={"beta": role})
        errors = validate_policy_bundle(bundle)
        assert any(e.code == "role_key_mismatch" for e in errors)

    def test_collects_inheritance_errors(self) -> None:
        role = RolePolicy(name="orphan", extends="missing")
        bundle = PolicyBundle(name="test", roles={"orphan": role})
        errors = validate_policy_bundle(bundle)
        assert any(e.code == "missing_base_role" for e in errors)

    def test_collects_role_policy_errors(self) -> None:
        role = RolePolicy(
            name="",
            permissions=[RolePermission(tool="")],
            restrictions=[""],
        )
        bundle = PolicyBundle(name="test", roles={"bad": role})
        errors = validate_policy_bundle(bundle)
        assert any(e.code == "empty_role_name" for e in errors)
        assert any(e.code == "empty_permission_tool" for e in errors)
        assert any(e.code == "empty_restriction" for e in errors)

    def test_multiple_errors_combined(self) -> None:
        a = RolePolicy(name="", extends="missing")
        b = RolePolicy(name="b", permissions=[RolePermission(tool="")])
        bundle = PolicyBundle(name="test", roles={"x": a, "b": b})
        errors = validate_policy_bundle(bundle)
        assert len(errors) >= 3

    def test_builtin_bundle_roundtrip_validates(self) -> None:
        bundle = parse_builtin_roles()
        data = bundle.to_dict()
        restored = PolicyBundle.from_dict(data)
        errors = validate_policy_bundle(restored)
        assert errors == []


# ---------------------------------------------------------------------------
# BUILTIN_ROLE_DEFINITIONS consistency
# ---------------------------------------------------------------------------


class TestBuiltinRoleDefinitions:
    def test_all_definitions_parse(self) -> None:
        for key, definition in BUILTIN_ROLE_DEFINITIONS.items():
            role = RolePolicy.from_dict(definition)
            assert role.name == key

    def test_inheritance_chain_is_valid(self) -> None:
        bundle = parse_builtin_roles()
        errors = validate_role_inheritance(bundle)
        assert errors == []

    def test_base_has_no_parent(self) -> None:
        assert BUILTIN_ROLE_DEFINITIONS["base"]["extends"] is None

    def test_children_extend_base(self) -> None:
        for role_name in ("junior", "senior", "ci", "contractor"):
            assert BUILTIN_ROLE_DEFINITIONS[role_name]["extends"] == "base"


# ---------------------------------------------------------------------------
# evaluate_role_pre_restrictions
# ---------------------------------------------------------------------------


class TestEvaluateRolePreRestrictions:
    def test_none_role_returns_none(self) -> None:
        ctx = ToolRequestContext(tool_name="write_file")
        result = evaluate_role_pre_restrictions(None, ctx)
        assert result is None

    def test_unknown_role_returns_none(self) -> None:
        ctx = ToolRequestContext(tool_name="write_file")
        result = evaluate_role_pre_restrictions("nonexistent", ctx)
        assert result is None

    def test_junior_production_path_blocked(self) -> None:
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={"path": "/prod/config.yaml"},
            role="junior",
        )
        result = evaluate_role_pre_restrictions("junior", ctx)
        assert result is not None
        assert result.action == DecisionAction.DENY
        assert "production" in result.reason.lower()

    def test_junior_safe_path_not_blocked(self) -> None:
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={"path": "src/main.py"},
            role="junior",
        )
        result = evaluate_role_pre_restrictions("junior", ctx)
        assert result is None

    def test_contractor_outside_workspace_blocked(self) -> None:
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={"path": "src/main.py"},
            role="contractor",
        )
        result = evaluate_role_pre_restrictions("contractor", ctx)
        assert result is not None
        assert result.action == DecisionAction.DENY
        assert "contractor" in result.reason.lower()

    def test_contractor_inside_workspace_allowed(self) -> None:
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={"path": "contractor/report.md"},
            role="contractor",
        )
        result = evaluate_role_pre_restrictions("contractor", ctx)
        # contractor_time may fire depending on current hour; we just check
        # workspace restriction did not fire
        if result is not None:
            assert "workspace" not in result.reason.lower()

    def test_infrastructure_change_blocked_for_contractor(self) -> None:
        ctx = ToolRequestContext(
            tool_name="run_shell",
            params={"command": "kubectl apply -f deploy.yaml"},
            role="contractor",
        )
        result = evaluate_role_pre_restrictions("contractor", ctx)
        assert result is not None
        assert result.action == DecisionAction.DENY
        assert "infrastructure" in result.reason.lower()

    def test_contractor_shell_not_blocked_by_pre(self) -> None:
        ctx = ToolRequestContext(
            tool_name="run_shell",
            params={"command": "echo hello"},
            role="contractor",
        )
        result = evaluate_role_pre_restrictions("contractor", ctx)
        # May still be blocked by contractor_time, but not by workspace or infra
        if result is not None:
            assert result.metadata.get("restriction") != "contractor_workspace"


# ---------------------------------------------------------------------------
# evaluate_role_post_restrictions
# ---------------------------------------------------------------------------


class TestEvaluateRolePostRestrictions:
    def test_none_role_returns_none(self) -> None:
        ctx = ToolRequestContext(tool_name="write_file")
        decision = PolicyDecision(
            DecisionAction.ALLOW, DecisionSource.DEFAULT, RiskLevel.LOW, "ok",
        )
        result = evaluate_role_post_restrictions(None, ctx, decision)
        assert result is None

    def test_junior_write_needs_approval(self) -> None:
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={"path": "notes.txt"},
            role="junior",
        )
        decision = PolicyDecision(
            DecisionAction.ALLOW, DecisionSource.DEFAULT, RiskLevel.LOW, "ok",
        )
        result = evaluate_role_post_restrictions("junior", ctx, decision)
        assert result is not None
        assert result.action == DecisionAction.ASK
        assert result.source == DecisionSource.APPROVAL

    def test_senior_write_no_post_restriction(self) -> None:
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={"path": "notes.txt"},
            role="senior",
        )
        decision = PolicyDecision(
            DecisionAction.ALLOW, DecisionSource.DEFAULT, RiskLevel.LOW, "ok",
        )
        result = evaluate_role_post_restrictions("senior", ctx, decision)
        assert result is None

    def test_ci_manual_approval_required(self) -> None:
        ctx = ToolRequestContext(
            tool_name="run_shell",
            params={"command": "echo hello"},
            role="ci",
        )
        decision = PolicyDecision(
            DecisionAction.ALLOW, DecisionSource.DEFAULT, RiskLevel.LOW, "ok",
        )
        result = evaluate_role_post_restrictions("ci", ctx, decision)
        assert result is not None
        assert result.action == DecisionAction.ASK
        assert result.metadata.get("manual_approval_required") is True

    def test_read_only_not_affected_by_unapproved_write(self) -> None:
        ctx = ToolRequestContext(
            tool_name="read_file",
            params={"path": "notes.txt"},
            role="junior",
        )
        decision = PolicyDecision(
            DecisionAction.ALLOW, DecisionSource.DEFAULT, RiskLevel.LOW, "ok",
        )
        result = evaluate_role_post_restrictions("junior", ctx, decision)
        assert result is None


# ---------------------------------------------------------------------------
# is_ci_auto_approve_allowed
# ---------------------------------------------------------------------------


class TestIsCiAutoApproveAllowed:
    def test_ci_shell_build_command_allowed(self) -> None:
        ctx = ToolRequestContext(
            tool_name="run_shell",
            params={"command": "npm run build"},
            role="ci",
        )
        assert is_ci_auto_approve_allowed(ctx, "ci") is True

    def test_ci_shell_test_command_allowed(self) -> None:
        ctx = ToolRequestContext(
            tool_name="run_shell",
            params={"command": "pytest tests/"},
            role="ci",
        )
        assert is_ci_auto_approve_allowed(ctx, "ci") is True

    def test_ci_shell_arbitrary_command_blocked(self) -> None:
        ctx = ToolRequestContext(
            tool_name="run_shell",
            params={"command": "curl example.com"},
            role="ci",
        )
        assert is_ci_auto_approve_allowed(ctx, "ci") is False

    def test_ci_write_output_path_allowed(self) -> None:
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={"path": "ci-output/report.json"},
            role="ci",
        )
        assert is_ci_auto_approve_allowed(ctx, "ci") is True

    def test_ci_write_source_path_blocked(self) -> None:
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={"path": "src/main.py"},
            role="ci",
        )
        assert is_ci_auto_approve_allowed(ctx, "ci") is False

    def test_non_ci_role_always_allowed(self) -> None:
        ctx = ToolRequestContext(
            tool_name="run_shell",
            params={"command": "curl example.com"},
            role="senior",
        )
        assert is_ci_auto_approve_allowed(ctx, "senior") is True