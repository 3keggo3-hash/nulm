"""Team role and policy bundle models for Claude Bridge.

This module implements role-based access control with inheritance:
  - RolePolicy: a single role with permissions, restrictions, and optional extends.
  - PolicyBundle: a named collection of roles that can be validated together.
  - Built-in role definitions: junior, senior, ci, contractor.
  - Inheritance validation: circular chains, missing bases, self-references.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    PolicyDecision,
    RiskLevel,
    ToolRequestContext,
    ValidationError,
    make_policy_decision,
)


class PermissionAction(str, Enum):
    """Action a role permission can specify."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class RolePermission:
    """A single permission entry within a role.

    Each permission grants or denies a tool/area, optionally scoped by
    field-level conditions.
    """

    tool: str
    action: PermissionAction = PermissionAction.ALLOW
    scope: dict[str, Any] = dc_field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "tool": self.tool,
            "action": self.action.value,
        }
        if self.scope:
            result["scope"] = dict(self.scope)
        if self.description:
            result["description"] = self.description
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RolePermission:
        if not isinstance(data, dict):
            return cls(tool="")
        action_raw = data.get("action", "allow")
        try:
            action = PermissionAction(action_raw)
        except ValueError:
            action = PermissionAction.ALLOW
        return cls(
            tool=str(data.get("tool", "")),
            action=action,
            scope=dict(data.get("scope", {})),
            description=str(data.get("description", "")),
        )


@dataclass
class RolePolicy:
    """A named role defining permissions and restrictions.

    Roles may inherit from a base role via ``extends``. Resolved
    permissions merge parent permissions first, then overlay the
    child's own entries.
    """

    name: str
    description: str = ""
    extends: str | None = None
    permissions: list[RolePermission] = dc_field(default_factory=list)
    restrictions: list[str] = dc_field(default_factory=list)
    metadata: dict[str, Any] = dc_field(default_factory=dict)
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "permissions": [p.to_dict() for p in self.permissions],
            "restrictions": list(self.restrictions),
            "enabled": self.enabled,
        }
        if self.extends is not None:
            result["extends"] = self.extends
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RolePolicy:
        if not isinstance(data, dict):
            return cls(name="")
        perms_raw = data.get("permissions", [])
        if not isinstance(perms_raw, list):
            perms_raw = []
        permissions = [RolePermission.from_dict(p) for p in perms_raw if isinstance(p, dict)]
        restrictions_raw = data.get("restrictions", [])
        if not isinstance(restrictions_raw, list):
            restrictions_raw = []
        restrictions = [str(r) for r in restrictions_raw]
        extends_val = data.get("extends")
        if extends_val is not None:
            extends_val = str(extends_val)
        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            extends=extends_val,
            permissions=permissions,
            restrictions=restrictions,
            metadata=dict(data.get("metadata", {})),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class PolicyBundle:
    """A named collection of role policies.

    Bundles are the top-level grouping that can be validated, serialized,
    and resolved with full inheritance expansion.
    """

    name: str
    roles: dict[str, RolePolicy] = dc_field(default_factory=dict)
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "roles": {k: v.to_dict() for k, v in self.roles.items()},
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyBundle:
        if not isinstance(data, dict):
            return cls(name="")
        roles_raw = data.get("roles", {})
        if not isinstance(roles_raw, dict):
            roles_raw = {}
        roles: dict[str, RolePolicy] = {}
        for key, val in roles_raw.items():
            if isinstance(val, dict):
                role = RolePolicy.from_dict(val)
                role_name = role.name or key
                roles[role_name] = role
        return cls(
            name=str(data.get("name", "")),
            roles=roles,
            metadata=dict(data.get("metadata", {})),
        )

    def add_role(self, role: RolePolicy) -> None:
        self.roles[role.name] = role

    def get_role(self, name: str) -> RolePolicy | None:
        return self.roles.get(name)


def resolve_role_permissions(
    role: RolePolicy,
    bundle: PolicyBundle,
    visited: set[str] | None = None,
) -> list[RolePermission]:
    """Resolve a role's full permission chain following extends inheritance.

    Parent permissions come first; child permissions overlay them.
    Circular chains are truncated to prevent infinite loops.
    """
    if visited is None:
        visited = set()
    if role.name in visited:
        return []
    visited = visited | {role.name}
    inherited: list[RolePermission] = []
    if role.extends is not None:
        parent = bundle.get_role(role.extends)
        if parent is not None:
            inherited = resolve_role_permissions(parent, bundle, visited)
    return inherited + list(role.permissions)


def _has_circular_inheritance(role_name: str, bundle: PolicyBundle) -> bool:
    """Detect whether *role_name* is part of a circular extends chain.

    Walks the inheritance graph starting from *role_name* and returns
    True if any node is visited more than once.
    """
    visited: set[str] = set()
    current = role_name
    while current not in visited:
        visited.add(current)
        role = bundle.get_role(current)
        if role is None or role.extends is None:
            return False
        current = role.extends
    return True


def validate_role_inheritance(bundle: PolicyBundle) -> list[ValidationError]:
    """Validate role extends / base inheritance chains within *bundle*.

    Checks:
      - Self-referencing extends.
      - Extends pointing to roles that don't exist in the bundle.
      - Circular inheritance chains.
    """
    errors: list[ValidationError] = []

    for role_name, role in bundle.roles.items():
        if role.extends is None:
            continue

        if role.extends == role_name:
            errors.append(
                ValidationError(
                    path=f"roles.{role_name}.extends",
                    message=f"Role '{role_name}' cannot extend itself",
                    code="circular_inheritance",
                )
            )
            continue

        parent = bundle.get_role(role.extends)
        if parent is None:
            errors.append(
                ValidationError(
                    path=f"roles.{role_name}.extends",
                    message=(
                        f"Role '{role_name}' extends '{role.extends}' "
                        f"which does not exist in the bundle"
                    ),
                    code="missing_base_role",
                )
            )
            continue

        if _has_circular_inheritance(role_name, bundle):
            errors.append(
                ValidationError(
                    path=f"roles.{role_name}.extends",
                    message=(
                        f"Circular inheritance detected: role '{role_name}' is in its own ancestry"
                    ),
                    code="circular_inheritance",
                )
            )

    return errors


def validate_role_policy(role: RolePolicy, path_prefix: str = "") -> list[ValidationError]:
    """Validate a single RolePolicy and return any errors found."""
    errors: list[ValidationError] = []
    prefix = f"roles.{role.name}" if not path_prefix else path_prefix

    if not role.name or not role.name.strip():
        errors.append(
            ValidationError(
                path=f"{prefix}.name",
                message="Role name must not be empty",
                code="empty_role_name",
            )
        )

    if role.extends is not None:
        stripped = role.extends.strip()
        if not stripped:
            errors.append(
                ValidationError(
                    path=f"{prefix}.extends",
                    message="Extends must be a non-empty string or null",
                    code="empty_extends",
                )
            )

    for pi, perm in enumerate(role.permissions):
        perm_path = f"{prefix}.permissions[{pi}]"
        if not perm.tool or not perm.tool.strip():
            errors.append(
                ValidationError(
                    path=f"{perm_path}.tool",
                    message="Permission tool must not be empty",
                    code="empty_permission_tool",
                )
            )
        try:
            PermissionAction(perm.action.value)
        except ValueError:
            errors.append(
                ValidationError(
                    path=f"{perm_path}.action",
                    message=f"Invalid permission action: {perm.action}",
                    code="invalid_permission_action",
                )
            )

    for ri, restriction in enumerate(role.restrictions):
        if not restriction or not restriction.strip():
            errors.append(
                ValidationError(
                    path=f"{prefix}.restrictions[{ri}]",
                    message="Restriction must be a non-empty string",
                    code="empty_restriction",
                )
            )

    return errors


def validate_policy_bundle(bundle: PolicyBundle) -> list[ValidationError]:
    """Validate an entire PolicyBundle including inheritance and per-role checks."""
    errors: list[ValidationError] = []

    if not bundle.name or not bundle.name.strip():
        errors.append(
            ValidationError(
                path="name",
                message="Policy bundle name must not be empty",
                code="empty_bundle_name",
            )
        )

    if not bundle.roles:
        errors.append(
            ValidationError(
                path="roles",
                message="Policy bundle must contain at least one role",
                code="empty_roles",
            )
        )

    for role_name, role in bundle.roles.items():
        if role_name != role.name:
            errors.append(
                ValidationError(
                    path=f"roles.{role_name}",
                    message=(f"Role key '{role_name}' does not match role name '{role.name}'"),
                    code="role_key_mismatch",
                )
            )
        errors.extend(validate_role_policy(role))

    errors.extend(validate_role_inheritance(bundle))

    return errors


# ---------------------------------------------------------------------------
# Built-in role definitions
# ---------------------------------------------------------------------------

BUILTIN_ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "base": {
        "name": "base",
        "description": "Base role with minimal read-only permissions",
        "extends": None,
        "permissions": [
            {"tool": "read_file", "action": "allow"},
            {"tool": "list_directory", "action": "allow"},
            {"tool": "search_files", "action": "allow"},
        ],
        "restrictions": ["destructive_shell", "sensitive_paths", "unapproved_write"],
        "metadata": {"risk_level": "low"},
        "enabled": True,
    },
    "junior": {
        "name": "junior",
        "description": "Junior developer with read access and limited write access",
        "extends": "base",
        "permissions": [
            {"tool": "write_file", "action": "ask"},
            {"tool": "run_shell", "action": "ask", "scope": {"safe_commands_only": True}},
        ],
        "restrictions": [
            "destructive_shell",
            "sensitive_paths",
            "unapproved_write",
            "production_env",
        ],
        "metadata": {"risk_level": "medium"},
        "enabled": True,
    },
    "senior": {
        "name": "senior",
        "description": "Senior developer with broader access permissions",
        "extends": "base",
        "permissions": [
            {"tool": "write_file", "action": "allow"},
            {"tool": "run_shell", "action": "allow", "scope": {"safe_commands_only": True}},
            {"tool": "git_operations", "action": "allow"},
        ],
        "restrictions": ["destructive_shell", "sensitive_paths"],
        "metadata": {"risk_level": "low"},
        "enabled": True,
    },
    "ci": {
        "name": "ci",
        "description": "CI/automation role with targeted permissions",
        "extends": "base",
        "permissions": [
            {"tool": "run_shell", "action": "allow", "scope": {"ci_commands_only": True}},
            {"tool": "write_file", "action": "allow", "scope": {"ci_output_paths": True}},
        ],
        "restrictions": ["interactive_shell", "sensitive_paths", "manual_approval_required"],
        "metadata": {"risk_level": "low"},
        "enabled": True,
    },
    "contractor": {
        "name": "contractor",
        "description": "Contractor role with restricted, supervised access",
        "extends": "base",
        "permissions": [
            {"tool": "write_file", "action": "ask", "scope": {"non_production_only": True}},
        ],
        "restrictions": [
            "destructive_shell",
            "sensitive_paths",
            "unapproved_write",
            "production_env",
            "infrastructure_changes",
        ],
        "metadata": {"risk_level": "high"},
        "enabled": True,
    },
}


def parse_builtin_roles() -> PolicyBundle:
    """Parse and return a PolicyBundle with all built-in role definitions."""
    roles: dict[str, RolePolicy] = {}
    for key, definition in BUILTIN_ROLE_DEFINITIONS.items():
        role = RolePolicy.from_dict(definition)
        roles[role.name] = role
    return PolicyBundle(
        name="builtin",
        roles=roles,
        metadata={"source": "builtin", "version": 1},
    )


# ---------------------------------------------------------------------------
# Role restriction evaluation
# ---------------------------------------------------------------------------

_RESOLVED_BUNDLE: PolicyBundle | None = None
_BUNDLE_LOCK = threading.RLock()


def _get_builtin_bundle() -> PolicyBundle:
    """Return the singleton built-in policy bundle with thread safety."""
    global _RESOLVED_BUNDLE
    with _BUNDLE_LOCK:
        if _RESOLVED_BUNDLE is None:
            _RESOLVED_BUNDLE = parse_builtin_roles()
        return _RESOLVED_BUNDLE


def resolve_role(
    role_name: str | None,
    bundle: PolicyBundle | None = None,
) -> RolePolicy | None:
    """Resolve a role name to its RolePolicy definition.

    Uses the built-in bundle by default; a custom bundle may be passed.
    Returns None if the role name is None or not found.
    """
    if role_name is None:
        return None
    resolved = bundle or _get_builtin_bundle()
    return resolved.get_role(role_name)


# ---------------------------------------------------------------------------
# Pre-rule restrictions (evaluated before user rules engine)
# ---------------------------------------------------------------------------

# Set of restriction names that are evaluated before user rules.
_PRE_RULE_RESTRICTIONS: frozenset[str] = frozenset(
    {
        "production_env",
        "infrastructure_changes",
    }
)

# Set of restriction names that are evaluated after user rules.
_POST_RULE_RESTRICTIONS: frozenset[str] = frozenset(
    {
        "unapproved_write",
        "manual_approval_required",
    }
)

# Set of restriction names unique to contractor role.
_CONTRACTOR_RESTRICTIONS: frozenset[str] = frozenset(
    {
        "contractor_workspace",
        "contractor_time",
    }
)


def _is_production_path(ctx: ToolRequestContext) -> bool:
    """Check if the operation targets a production path."""
    for field in ("path", "file"):
        path_val = ctx.params.get(field)
        if not isinstance(path_val, str) or not path_val:
            continue
        path_lower = path_val.lower()
        production_indicators = [
            "/prod/",
            "/production/",
            "/live/",
            "/deploy/",
            "/release/",
            "/staging/",
        ]
        if any(indicator in path_lower for indicator in production_indicators):
            return True
    return False


def _is_infrastructure_change(ctx: ToolRequestContext) -> bool:
    """Check if the operation involves infrastructure changes."""
    if ctx.tool_name in ("run_shell", "start_process"):
        command = ctx.params.get("command", "")
        if not isinstance(command, str):
            return False
        cmd_lower = command.strip().lower()
        infra_keywords = [
            "kubectl",
            "helm",
            "terraform",
            "ansible",
            "pulumi",
            "docker compose",
            "docker stack",
            "docker swarm",
        ]
        return any(kw in cmd_lower for kw in infra_keywords)
    if ctx.tool_name == "write_file":
        path_val = ctx.params.get("path", "")
        if not isinstance(path_val, str):
            return False
        infra_files = [
            "docker-compose",
            "docker-compose",
            "kubernetes",
            "k8s",
            "terraform",
            ".tf",
            "helmfile",
        ]
        return any(kw in path_val.lower() for kw in infra_files)
    return False


def _is_contractor_workspace_violation(ctx: ToolRequestContext) -> bool:
    """Check if the operation is outside the contractor workspace boundary.

    Contractor workspace is restricted to paths under a ``contractor/``
    subdirectory within the project.
    """
    path_val = ctx.params.get("path")
    file_val = ctx.params.get("file")
    has_path = isinstance(path_val, str) and path_val
    has_file = isinstance(file_val, str) and file_val
    if not has_path and not has_file:
        return False
    violations = 0
    if has_path:
        target = Path(str(path_val))
        if target.is_absolute():
            if ctx.project_dir:
                try:
                    target = target.relative_to(Path(ctx.project_dir))
                except (ValueError, OSError):
                    return True
            else:
                return True
        parts = Path(str(target)).parts
        if len(parts) == 0 or parts[0] != "contractor":
            violations += 1
    if has_file:
        target = Path(str(file_val))
        if target.is_absolute():
            if ctx.project_dir:
                try:
                    target = target.relative_to(Path(ctx.project_dir))
                except (ValueError, OSError):
                    return True
            else:
                return True
        parts = Path(str(target)).parts
        if len(parts) == 0 or parts[0] != "contractor":
            violations += 1
    return violations > 0


def _is_outside_contractor_hours() -> bool:
    """Check if the current time is outside contractor allowed hours.

    MVP: contractor operations are allowed Mon-Fri 06:00-20:00 UTC.
    """
    now = datetime.now(timezone.utc)  # FIX: timezone-aware datetime
    if now.weekday() >= 5:
        return True
    if now.hour < 6 or now.hour >= 20:
        return True
    return False


def evaluate_role_pre_restrictions(
    role_name: str | None,
    ctx: ToolRequestContext,
    bundle: PolicyBundle | None = None,
) -> PolicyDecision | None:
    """Evaluate pre-rule role restrictions that produce DENY outcomes.

    These restrictions are checked *before* the user rules engine runs.
    If a violation is found, a DENY decision is returned immediately.

    Args:
        role_name: The role name to evaluate restrictions for.
        ctx: The tool request context.
        bundle: Optional custom policy bundle; defaults to built-in.

    Returns:
        A DENY PolicyDecision if a restriction is violated, or None.
    """
    if role_name is None:
        return None
    role = resolve_role(role_name, bundle)
    if role is None or not role.enabled:
        return None

    # First check standard pre-rule restrictions (more specific)
    for restriction in role.restrictions:
        if restriction not in _PRE_RULE_RESTRICTIONS:
            continue
        if restriction == "production_env" and _is_production_path(ctx):
            return make_policy_decision(
                DecisionAction.DENY,
                DecisionSource.BUILTIN_GUARD,
                RiskLevel.CRITICAL,
                f"Role restriction ({role_name}): production environment changes are not allowed",
                [f"role restriction: {restriction}"],
                {"role": role_name, "restriction": restriction},
            )
        if restriction == "infrastructure_changes" and _is_infrastructure_change(ctx):
            return make_policy_decision(
                DecisionAction.DENY,
                DecisionSource.BUILTIN_GUARD,
                RiskLevel.CRITICAL,
                f"Role restriction ({role_name}): infrastructure changes are not allowed",
                [f"role restriction: {restriction}"],
                {"role": role_name, "restriction": restriction},
            )

    # Then check contractor-specific restrictions (less specific)
    if role_name == "contractor":
        if _is_contractor_workspace_violation(ctx):
            return make_policy_decision(
                DecisionAction.DENY,
                DecisionSource.BUILTIN_GUARD,
                RiskLevel.HIGH,
                "Contractor workspace restriction: path is outside the contractor/ subdirectory",
                ["role restriction: contractor_workspace"],
                {"role": role_name, "restriction": "contractor_workspace"},
            )
        if _is_outside_contractor_hours():
            return make_policy_decision(
                DecisionAction.DENY,
                DecisionSource.BUILTIN_GUARD,
                RiskLevel.HIGH,
                "Contractor time restriction: operations are only allowed Mon-Fri 06:00-20:00 UTC",
                ["role restriction: contractor_time"],
                {"role": role_name, "restriction": "contractor_time"},
            )

    return None


def evaluate_role_post_restrictions(
    role_name: str | None,
    ctx: ToolRequestContext,
    current_decision: PolicyDecision,
    bundle: PolicyBundle | None = None,
) -> PolicyDecision | None:
    """Evaluate post-rule role restrictions that may modify the decision.

    These restrictions are checked *after* the user rules engine runs
    and can upgrade an ALLOW to ASK or enrich metadata.

    Args:
        role_name: The role name to evaluate restrictions for.
        ctx: The tool request context.
        current_decision: The current decision from the rules engine.
        bundle: Optional custom policy bundle; defaults to built-in.

    Returns:
        A modified PolicyDecision if a restriction applies, or None.
    """
    if role_name is None:
        return None
    role = resolve_role(role_name, bundle)
    if role is None or not role.enabled:
        return None

    for restriction in role.restrictions:
        if restriction not in _POST_RULE_RESTRICTIONS:
            continue
        if restriction == "unapproved_write":
            write_tools = {"write_file", "patch_file", "move_file", "copy_path"}
            if ctx.tool_name in write_tools and current_decision.action == DecisionAction.ALLOW:
                return make_policy_decision(
                    DecisionAction.ASK,
                    DecisionSource.APPROVAL,
                    RiskLevel.MEDIUM,
                    f"Role restriction ({role_name}): write operations require approval",
                    [f"role restriction: {restriction}"],
                    {"role": role_name, "restriction": restriction},
                )
        if restriction == "manual_approval_required":
            if current_decision.action == DecisionAction.ALLOW:
                return make_policy_decision(
                    DecisionAction.ASK,
                    DecisionSource.APPROVAL,
                    RiskLevel.MEDIUM,
                    f"Role restriction ({role_name}): manual approval is "
                    "required for this operation",
                    [f"role restriction: {restriction}"],
                    {
                        "role": role_name,
                        "restriction": restriction,
                        "manual_approval_required": True,
                    },
                )

    return None


def is_ci_auto_approve_allowed(
    ctx: ToolRequestContext,
    role_name: str | None = "ci",
) -> bool:
    """Check if auto-approve is allowed for a CI role on this operation.

    CI role auto-approve boundaries:
      - run_shell: auto-approve only for commands matching CI patterns
        (build, test, lint, format, coverage).
      - write_file: auto-approve only for paths under ``ci-output/``
        or files matching CI output patterns.
      - All other tools: auto-approve is NOT allowed.

    Args:
        ctx: The tool request context.
        role_name: The role name to check (defaults to "ci").

    Returns:
        True if auto-approve is allowed for this operation under CI role.
    """
    if role_name != "ci":
        return True

    if ctx.tool_name == "run_shell":
        command = ctx.params.get("command", "")
        if not isinstance(command, str):
            return False
        if any(c in command for c in ";|&"):  # FIX: reject shell metacharacters
            return False
        ci_command_prefixes = (
            "npm run",
            "npm test",
            "npm build",
            "npm ci",
            "pytest",
            "ruff",
            "black",
            "mypy",
            "make build",
            "make test",
            "make lint",
            "python -m pytest",
            "python3 -m pytest",
            "coverage",
            "flake8",
            "eslint",
            "prettier",
            "go test",
            "go build",
            "cargo test",
            "cargo build",
        )
        cmd_stripped = command.strip().lower()
        return any(cmd_stripped.startswith(prefix) for prefix in ci_command_prefixes)

    if ctx.tool_name == "write_file":
        path_val = ctx.params.get("path", "")
        if not isinstance(path_val, str):
            return False
        ci_output_prefixes = ("ci-output/", "ci_report/", "build/", "dist/", ".ci/")
        return any(path_val.lower().startswith(prefix) for prefix in ci_output_prefixes)

    return True
