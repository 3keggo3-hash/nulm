
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT

"""Semantic diff engine for team policy bundles.

Computes and reports structural differences between two PolicyBundle
instances (typical use: base branch vs. PR head) in a machine-readable
format suitable for CI pipelines.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from enum import Enum
from pathlib import Path
from typing import Any

from claude_bridge.team_policy import (
    PolicyBundle,
    RolePermission,
    RolePolicy,
    validate_policy_bundle,
    validate_role_inheritance,
)


class DiffStatus(str, Enum):
    """Categorisation of a diff entry."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    OK = "ok"
    ERROR = "error"
    WARNING = "warning"


@dataclass
class PermissionDiff:
    """Describes a single permission-level change."""

    tool: str
    status: DiffStatus
    old_action: str | None = None
    new_action: str | None = None
    old_scope: dict[str, Any] | None = None
    new_scope: dict[str, Any] | None = None
    old_description: str | None = None
    new_description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "tool": self.tool,
            "status": self.status.value,
        }
        if self.old_action is not None or self.new_action is not None:
            result["old_action"] = self.old_action
            result["new_action"] = self.new_action
        if self.old_scope is not None or self.new_scope is not None:
            result["old_scope"] = self.old_scope
            result["new_scope"] = self.new_scope
        return result


@dataclass
class RoleDiff:
    """Describes all changes within a single role."""

    role_name: str
    status: DiffStatus
    extends_changed: bool = False
    old_extends: str | None = None
    new_extends: str | None = None
    description_changed: bool = False
    enabled_changed: bool = False
    old_enabled: bool | None = None
    new_enabled: bool | None = None
    restrictions_added: list[str] = dc_field(default_factory=list)
    restrictions_removed: list[str] = dc_field(default_factory=list)
    permission_diffs: list[PermissionDiff] = dc_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "role": self.role_name,
            "status": self.status.value,
        }
        if self.extends_changed:
            result["extends"] = {
                "old": self.old_extends,
                "new": self.new_extends,
            }
        if self.description_changed:
            result["description_changed"] = True
        if self.enabled_changed:
            result["enabled"] = {
                "old": self.old_enabled,
                "new": self.new_enabled,
            }
        if self.restrictions_added:
            result["restrictions_added"] = self.restrictions_added
        if self.restrictions_removed:
            result["restrictions_removed"] = self.restrictions_removed
        if self.permission_diffs:
            result["permission_diffs"] = [pd.to_dict() for pd in self.permission_diffs]
        return result


@dataclass
class PolicyDiffResult:
    """Top-level diff result between two PolicyBundles."""

    base_name: str
    head_name: str
    status: DiffStatus = DiffStatus.OK
    name_changed: bool = False
    old_name: str = ""
    new_name: str = ""
    roles_added: list[str] = dc_field(default_factory=list)
    roles_removed: list[str] = dc_field(default_factory=list)
    role_diffs: list[RoleDiff] = dc_field(default_factory=list)
    base_validation_errors: list[dict[str, str]] = dc_field(default_factory=list)
    head_validation_errors: list[dict[str, str]] = dc_field(default_factory=list)
    base_inheritance_errors: list[dict[str, str]] = dc_field(default_factory=list)
    head_inheritance_errors: list[dict[str, str]] = dc_field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return self.status != DiffStatus.OK

    @property
    def has_issues(self) -> bool:
        return bool(
            self.head_validation_errors
            or self.head_inheritance_errors
            or self.base_validation_errors
            or self.base_inheritance_errors
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status.value,
            "base": self.base_name,
            "head": self.head_name,
        }
        if self.name_changed:
            result["name_changed"] = True
            result["old_name"] = self.old_name
            result["new_name"] = self.new_name
        if self.roles_added:
            result["roles_added"] = self.roles_added
        if self.roles_removed:
            result["roles_removed"] = self.roles_removed
        if self.role_diffs:
            result["role_diffs"] = [rd.to_dict() for rd in self.role_diffs]
        if self.base_validation_errors or self.head_validation_errors:
            result["validation_errors"] = {
                "base": self.base_validation_errors,
                "head": self.head_validation_errors,
            }
        if self.base_inheritance_errors or self.head_inheritance_errors:
            result["inheritance_errors"] = {
                "base": self.base_inheritance_errors,
                "head": self.head_inheritance_errors,
            }
        return result


def _parse_file(path: Path) -> dict[str, Any] | None:
    """Parse a policy file (JSON or YAML) into a dictionary.

    Returns None on any read/parse error.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import-untyped]

            result = yaml.safe_load(raw)
        except Exception:
            return None
    else:
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            return None

    if not isinstance(result, dict):
        return None
    return result


def load_bundle_from_file(path: Path) -> PolicyBundle | None:
    """Load a PolicyBundle from a JSON or YAML file.

    The file is expected to have a top-level ``roles`` mapping
    (same shape as PolicyBundle.to_dict() output). Returns None
    when the file cannot be parsed or lacks a ``roles`` key.
    """
    data = _parse_file(path)
    if data is None:
        return None
    roles_raw = data.get("roles")
    if not isinstance(roles_raw, dict):
        if "roles" not in data and isinstance(data, dict):
            roles_raw = {}
        else:
            return None
    bundle = PolicyBundle.from_dict(data)
    if bundle.name == "":
        bundle = PolicyBundle(
            name=path.stem,
            roles=bundle.roles,
            metadata=bundle.metadata,
        )
    return bundle


def _diff_permissions(
    old_perms: list[RolePermission], new_perms: list[RolePermission]
) -> list[PermissionDiff]:
    """Compute permission-level diffs between two ordered lists."""
    diffs: list[PermissionDiff] = []
    old_by_tool: dict[str, RolePermission] = {p.tool: p for p in old_perms}
    new_by_tool: dict[str, RolePermission] = {p.tool: p for p in new_perms}

    all_tools = sorted(set(old_by_tool.keys()) | set(new_by_tool.keys()))
    for tool in all_tools:
        old_perm = old_by_tool.get(tool)
        new_perm = new_by_tool.get(tool)
        if old_perm is None and new_perm is not None:
            diffs.append(
                PermissionDiff(
                    tool=tool,
                    status=DiffStatus.ADDED,
                    new_action=new_perm.action.value,
                    new_scope=dict(new_perm.scope),
                    new_description=new_perm.description,
                )
            )
        elif new_perm is None and old_perm is not None:
            diffs.append(
                PermissionDiff(
                    tool=tool,
                    status=DiffStatus.REMOVED,
                    old_action=old_perm.action.value,
                    old_scope=dict(old_perm.scope),
                    old_description=old_perm.description,
                )
            )
        else:
            assert old_perm is not None and new_perm is not None
            unchanged = (
                old_perm.action == new_perm.action
                and old_perm.scope == new_perm.scope
                and old_perm.description == new_perm.description
            )
            if unchanged:
                continue
            diffs.append(
                PermissionDiff(
                    tool=tool,
                    status=DiffStatus.MODIFIED,
                    old_action=old_perm.action.value,
                    new_action=new_perm.action.value,
                    old_scope=dict(old_perm.scope),
                    new_scope=dict(new_perm.scope),
                    old_description=old_perm.description,
                    new_description=new_perm.description,
                )
            )
    return diffs


def diff_role(old: RolePolicy | None, new: RolePolicy | None) -> RoleDiff:
    """Compute the semantic diff between two RolePolicy instances."""
    if old is None and new is not None:
        return RoleDiff(
            role_name=new.name,
            status=DiffStatus.ADDED,
        )
    if new is None and old is not None:
        return RoleDiff(
            role_name=old.name,
            status=DiffStatus.REMOVED,
        )
    assert old is not None and new is not None

    extends_changed = old.extends != new.extends
    desc_changed = old.description != new.description
    enabled_changed = old.enabled != new.enabled

    old_restrictions = set(old.restrictions)
    new_restrictions = set(new.restrictions)
    restrictions_added = sorted(new_restrictions - old_restrictions)
    restrictions_removed = sorted(old_restrictions - new_restrictions)

    perm_diffs = _diff_permissions(old.permissions, new.permissions)

    has_any_change = (
        extends_changed
        or desc_changed
        or enabled_changed
        or restrictions_added
        or restrictions_removed
        or len(perm_diffs) > 0
    )
    status = DiffStatus.MODIFIED if has_any_change else DiffStatus.UNCHANGED

    return RoleDiff(
        role_name=new.name,
        status=status,
        extends_changed=extends_changed,
        old_extends=old.extends,
        new_extends=new.extends,
        description_changed=desc_changed,
        enabled_changed=enabled_changed,
        old_enabled=old.enabled,
        new_enabled=new.enabled,
        restrictions_added=restrictions_added,
        restrictions_removed=restrictions_removed,
        permission_diffs=perm_diffs,
    )


def diff_policies(base: PolicyBundle, head: PolicyBundle) -> PolicyDiffResult:
    """Compute the full semantic diff between two PolicyBundles.

    Compares bundle metadata, role membership, and per-role details.
    Also runs inheritance validation on both bundles to catch issues
    introduced (or resolved) by the change.
    """
    result = PolicyDiffResult(
        base_name=base.name or "(unnamed)",
        head_name=head.name or "(unnamed)",
    )

    if base.name != head.name:
        result.name_changed = True
        result.old_name = base.name or ""
        result.new_name = head.name or ""

    base_role_names = set(base.roles.keys())
    head_role_names = set(head.roles.keys())

    result.roles_added = sorted(head_role_names - base_role_names)
    result.roles_removed = sorted(base_role_names - head_role_names)

    all_roles = sorted(base_role_names | head_role_names)
    role_diffs: list[RoleDiff] = []
    for role_name in all_roles:
        old_role = base.roles.get(role_name)
        new_role = head.roles.get(role_name)
        rd = diff_role(old_role, new_role)
        role_diffs.append(rd)

    # Sort: changes first, then alphabetical
    status_order = {
        DiffStatus.ADDED: 0,
        DiffStatus.REMOVED: 1,
        DiffStatus.MODIFIED: 2,
        DiffStatus.UNCHANGED: 3,
    }
    role_diffs.sort(key=lambda rd: (status_order.get(rd.status, 9), rd.role_name))
    result.role_diffs = role_diffs

    if (
        result.roles_added
        or result.roles_removed
        or result.name_changed
        or any(rd.status != DiffStatus.UNCHANGED for rd in role_diffs)
    ):
        result.status = DiffStatus.MODIFIED

    base_inheritance = validate_role_inheritance(base)
    head_inheritance = validate_role_inheritance(head)
    base_validation = validate_policy_bundle(base)
    head_validation = validate_policy_bundle(head)

    result.base_validation_errors = [e.to_dict() for e in base_validation]
    result.head_validation_errors = [e.to_dict() for e in head_validation]
    result.base_inheritance_errors = [e.to_dict() for e in base_inheritance]
    result.head_inheritance_errors = [e.to_dict() for e in head_inheritance]

    return result


# --------------------------------------------------------------------------
# Role-based simulation helpers
# --------------------------------------------------------------------------


@dataclass
class SimulationResult:
    """Result of a policy simulation for a single tool request."""

    tool: str
    role: str | None
    action: str
    source: str
    risk_level: str
    reason: str
    risk_reasons: list[str] = dc_field(default_factory=list)
    metadata: dict[str, Any] = dc_field(default_factory=dict)
    warnings: list[str] = dc_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "role": self.role,
            "action": self.action,
            "source": self.source,
            "risk_level": self.risk_level,
            "reason": self.reason,
            "risk_reasons": list(self.risk_reasons),
            "metadata": dict(self.metadata),
            "warnings": list(self.warnings),
        }


def simulate_tool_with_role(
    *,
    tool: str,
    params: dict[str, Any],
    role_name: str | None,
    project_dir: str = "",
    allowed_roots: list[str] | None = None,
    bundle: PolicyBundle | None = None,
) -> SimulationResult:
    """Simulate a tool request under a specific role within a policy bundle.

    This runs the full policy chain evaluation (pre-rule role restrictions,
    rules, post-rule restrictions) and returns a structured result.

    Args:
        tool: Tool name (e.g., ``run_shell``, ``write_file``).
        params: Tool parameters as a dict.
        role_name: The role to simulate as (e.g., ``junior``, ``senior``).
        project_dir: Optional project directory for path checks.
        allowed_roots: Optional allowed roots for path checks.
        bundle: Optional custom PolicyBundle; defaults to built-in roles.

    Returns:
        A SimulationResult with the full policy decision breakdown.
    """
    from claude_bridge.guard_policy import (
        ToolRequestContext,
        PolicyDecision,
    )
    from claude_bridge.rules_engine import evaluate_policy_chain

    ctx = ToolRequestContext(
        tool_name=tool,
        params=params,
        project_dir=project_dir,
        allowed_roots=allowed_roots or [],
        role=role_name,
    )

    decision: PolicyDecision = evaluate_policy_chain(ctx)

    metadata = dict(decision.metadata)
    if role_name is not None:
        metadata["role"] = role_name
        from claude_bridge.team_policy import (
            validate_role_inheritance as _vi,
            validate_policy_bundle as _vb,
        )

        resolved_bundle = bundle or _get_any_bundle()
        if resolved_bundle is not None:
            inh_errors = _vi(resolved_bundle)
            val_errors = _vb(resolved_bundle)
            warns: list[str] = []
            for e in inh_errors:
                warns.append(f"[{e.code}] {e.path}: {e.message}")
            for e in val_errors:
                warns.append(f"[{e.code}] {e.path}: {e.message}")
            metadata["validation_warnings"] = warns

    return SimulationResult(
        tool=tool,
        role=role_name,
        action=decision.action.value,
        source=decision.source.value,
        risk_level=decision.risk_level.value,
        reason=decision.reason or "No policy rule matched — default allow",
        risk_reasons=list(decision.risk_reasons),
        metadata=metadata,
    )


def _get_any_bundle() -> PolicyBundle | None:
    """Return the built-in bundle if available, otherwise None."""
    try:
        from claude_bridge.team_policy import _get_builtin_bundle

        return _get_builtin_bundle()
    except Exception:
        return None
