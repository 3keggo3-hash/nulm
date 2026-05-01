"""Condition matching engine and rule evaluation for Claude Bridge.

This module implements Package 2C of the security layer: a condition-based
rule matching engine that evaluates ToolRequestContext instances against
GuardRule instances (from guard_policy.py) and produces PolicyDecision
outcomes with source=RULE.

Supported condition types (via ConditionType enum):
  - tool
  - field_equals
  - field_contains
  - regex
  - glob
  - extension
  - file_exists
  - file_size
  - sensitive_path
  - content_contains
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Sequence

from claude_bridge.guard_policy import (
    ConditionType,
    DecisionAction,
    DecisionSource,
    GuardRule,
    PolicyDecision,
    RiskLevel,
    RuleAction,
    RuleCondition,
    ToolRequestContext,
    make_policy_decision,
)
from claude_bridge.tool_utils import sensitive_path_reason

# ---------------------------------------------------------------------------
# RuleAction → DecisionAction mapping
# ---------------------------------------------------------------------------

_RULE_ACTION_TO_DECISION: dict[RuleAction, DecisionAction] = {
    RuleAction.ALLOW: DecisionAction.ALLOW,
    RuleAction.DENY: DecisionAction.DENY,
    RuleAction.ASK: DecisionAction.ASK,
}


def _decision_action_from_rule(rule_action: RuleAction) -> DecisionAction:
    """Map a RuleAction to the equivalent DecisionAction."""
    return _RULE_ACTION_TO_DECISION.get(rule_action, DecisionAction.DENY)


# ---------------------------------------------------------------------------
# Individual condition matchers
# ---------------------------------------------------------------------------


def _match_tool(ctx: ToolRequestContext, condition: RuleCondition) -> bool:
    """Match the tool name (case-insensitive)."""
    expected = condition.value if isinstance(condition.value, str) else condition.field
    if not isinstance(expected, str) or not expected:
        return False
    return ctx.tool_name.lower() == expected.lower()


def _match_field_equals(ctx: ToolRequestContext, condition: RuleCondition) -> bool:
    """Match when a param field equals the given value."""
    if not condition.field:
        return False
    actual = ctx.params.get(condition.field)
    return bool(actual == condition.value)


def _match_field_contains(ctx: ToolRequestContext, condition: RuleCondition) -> bool:
    """Match when a param field (string) contains the given substring."""
    if not condition.field:
        return False
    actual = ctx.params.get(condition.field)
    if not isinstance(actual, str) or not isinstance(condition.value, str):
        return False
    return condition.value in actual


def _match_regex(ctx: ToolRequestContext, condition: RuleCondition) -> bool:
    """Match a param field against a compiled regex pattern."""
    if not condition.field or not isinstance(condition.value, str):
        return False
    actual = ctx.params.get(condition.field)
    if not isinstance(actual, str):
        return False
    try:
        compiled = re.compile(condition.value)
    except re.error:
        return False
    return bool(compiled.search(actual))


def _match_glob(ctx: ToolRequestContext, condition: RuleCondition) -> bool:
    """Match a param field against a glob pattern."""
    if not condition.field or not isinstance(condition.value, str):
        return False
    actual = ctx.params.get(condition.field)
    if not isinstance(actual, str):
        return False
    return fnmatch.fnmatch(actual, condition.value)


def _match_extension(ctx: ToolRequestContext, condition: RuleCondition) -> bool:
    """Match a file extension on a path param field."""
    if not condition.field or not isinstance(condition.value, str):
        return False
    actual = ctx.params.get(condition.field)
    if not isinstance(actual, str):
        return False
    ext = condition.value
    if not ext.startswith("."):
        ext = "." + ext
    return actual.lower().endswith(ext.lower())


def _match_file_exists(ctx: ToolRequestContext, condition: RuleCondition) -> bool:
    """Match based on whether a filesystem path exists.

    The condition value is interpreted as a boolean: True means the file
    must exist, False means it must not exist.
    """
    if not condition.field:
        return False
    actual = ctx.params.get(condition.field)
    if not isinstance(actual, str):
        return False
    try:
        target = Path(actual)
        if not target.is_absolute() and ctx.project_dir:
            target = Path(ctx.project_dir) / target
        target = target.resolve()
        exists = target.exists()
        expected = bool(condition.value)
        return exists == expected
    except (OSError, ValueError):
        return False


def _match_file_size(ctx: ToolRequestContext, condition: RuleCondition) -> bool:
    """Match based on file size (bytes).

    The condition value should be a dict with optional 'min' and 'max'
    keys, or a plain integer treated as max.
    """
    if not condition.field:
        return False
    actual = ctx.params.get(condition.field)
    if not isinstance(actual, str):
        return False
    try:
        target = Path(actual)
        if not target.is_absolute() and ctx.project_dir:
            target = Path(ctx.project_dir) / target
        target = target.resolve()
        if not target.is_file():
            return False
        file_size = target.stat().st_size
    except (OSError, ValueError):
        return False

    min_size: int | None = None
    max_size: int | None = None
    val = condition.value
    if isinstance(val, dict):
        min_size = val.get("min")
        max_size = val.get("max")
    elif isinstance(val, (int, float)):
        max_size = int(val)
    else:
        return False

    if min_size is not None and file_size < int(min_size):
        return False
    if max_size is not None and file_size > int(max_size):
        return False
    return True


def _match_sensitive_path(ctx: ToolRequestContext, condition: RuleCondition) -> bool:
    """Match when a param field points to a sensitive path.

    Uses the built-in sensitive_path_reason helper. The condition field
    is the param key that holds the path string.
    """
    field = condition.field
    if not field:
        return False
    actual = ctx.params.get(field)
    if not isinstance(actual, str):
        return False
    try:
        target = Path(actual)
        if not target.is_absolute() and ctx.project_dir:
            target = Path(ctx.project_dir) / target
        reason = sensitive_path_reason(target)
        return reason is not None
    except (OSError, ValueError):
        return False


def _match_content_contains(ctx: ToolRequestContext, condition: RuleCondition) -> bool:
    """Match when the 'content' param contains a substring (case-insensitive)."""
    if not condition.field or not isinstance(condition.value, str):
        return False
    actual = ctx.params.get(condition.field)
    if not isinstance(actual, str):
        return False
    return condition.value.lower() in actual.lower()


# Registry mapping ConditionType → matcher function
_CONDITION_MATCHERS: dict[ConditionType, Any] = {
    ConditionType.TOOL: _match_tool,
    ConditionType.FIELD_EQUALS: _match_field_equals,
    ConditionType.FIELD_CONTAINS: _match_field_contains,
    ConditionType.REGEX: _match_regex,
    ConditionType.GLOB: _match_glob,
    ConditionType.EXTENSION: _match_extension,
    ConditionType.FILE_EXISTS: _match_file_exists,
    ConditionType.FILE_SIZE: _match_file_size,
    ConditionType.SENSITIVE_PATH: _match_sensitive_path,
    ConditionType.CONTENT_CONTAINS: _match_content_contains,
}

# ---------------------------------------------------------------------------
# Rule matching engine
# ---------------------------------------------------------------------------


def evaluate_condition(ctx: ToolRequestContext, condition: RuleCondition) -> bool:
    """Evaluate a single RuleCondition against a tool request context.

    Returns False for unknown condition types or missing fields (fail-safe).
    """
    matcher = _CONDITION_MATCHERS.get(condition.type)
    if matcher is None:
        return False
    try:
        return bool(matcher(ctx, condition))
    except Exception:
        return False


def evaluate_rule(ctx: ToolRequestContext, rule: GuardRule) -> bool:
    """Check whether all conditions in a GuardRule match the given context.

    An empty conditions list matches nothing (fail-safe).
    Disabled rules are skipped.
    """
    if not rule.enabled:
        return False
    if not rule.conditions:
        return False
    return all(evaluate_condition(ctx, cond) for cond in rule.conditions)


def match_rules(
    ctx: ToolRequestContext,
    rules: Sequence[GuardRule],
) -> PolicyDecision | None:
    """Find the first matching rule from a priority-sorted sequence.

    Rules are evaluated in priority order (lowest number first).  When
    multiple rules share the same priority, the original list order is
    preserved (stable sort via id() tiebreaker).

    Returns:
        A PolicyDecision with source=RULE if a match is found, or None.
        The decision's metadata includes rule_name, rule_id (from
        rule.metadata), and rule_action.
    """
    sorted_rules = sorted(
        [r for r in rules if r.enabled],
        key=lambda r: (r.priority, id(r)),
    )
    for rule in sorted_rules:
        if evaluate_rule(ctx, rule):
            decision_action = _decision_action_from_rule(rule.action)
            rule_id = rule.metadata.get("id", rule.name) if rule.metadata else rule.name
            raw_risk = rule.metadata.get("risk_level", RiskLevel.MEDIUM.value)
            try:
                risk_level = RiskLevel(str(raw_risk))
            except ValueError:
                risk_level = RiskLevel.MEDIUM
            return make_policy_decision(
                action=decision_action,
                source=DecisionSource.RULE,
                risk_level=risk_level,
                reason=f"Rule matched: {rule.name}",
                risk_reasons=[f"guard rule '{rule.name}' triggered"],
                metadata={
                    "rule_name": rule.name,
                    "rule_id": rule_id,
                    "rule_action": rule.action.value,
                },
            )
    return None


# ---------------------------------------------------------------------------
# Decision merging: built-in hard deny → rules → default
# ---------------------------------------------------------------------------


def evaluate_policy_chain(
    ctx: ToolRequestContext,
    *,
    builtin_deny: PolicyDecision | None = None,
    user_rules: Sequence[GuardRule] | None = None,
    default_decision: PolicyDecision | None = None,
) -> PolicyDecision:
    """Run the full policy chain for a tool request.

    Precedence order (strongest first):
      1. Built-in hard deny — never overridden.
      2. Rule match — DENY or ASK from user rules.
      3. Rule match — ALLOW (only metadata enrichment in MVP; does not
         bypass approval or built-in deny).
      4. Built-in default decision.

    The MVP rule ALLOW strategy is documented here: an ALLOW rule adds
    ``rule_allowed: True`` and the rule's metadata to the default decision,
    but never softens a DENY from the built-in layer nor bypasses approval.

    Args:
        ctx: The tool request context.
        builtin_deny: A pre-computed built-in deny decision, or None.
        user_rules: Optional list of user-defined GuardRule objects.
        default_decision: Fallback decision when nothing else matches.

    Returns:
        The winning PolicyDecision.
    """
    # Layer 1: built-in hard deny is inviolable
    if builtin_deny is not None and builtin_deny.action == DecisionAction.DENY:
        return builtin_deny

    # Layer 2: user rules
    if user_rules:
        rule_match = match_rules(ctx, user_rules)
        if rule_match is not None:
            if rule_match.action in (DecisionAction.DENY, DecisionAction.ASK):
                return rule_match
            # MVP: rule ALLOW only enriches metadata; does not bypass approval
            if rule_match.action == DecisionAction.ALLOW:
                if default_decision is not None:
                    enriched = PolicyDecision(
                        action=default_decision.action,
                        source=default_decision.source,
                        risk_level=default_decision.risk_level,
                        reason=default_decision.reason,
                        risk_reasons=list(default_decision.risk_reasons),
                        metadata={
                            **dict(default_decision.metadata),
                            **dict(rule_match.metadata),
                            "rule_allowed": True,
                        },
                    )
                    return enriched

    # Layer 3: default
    if default_decision is not None:
        return default_decision

    return make_policy_decision(
        DecisionAction.ALLOW,
        DecisionSource.DEFAULT,
        RiskLevel.LOW,
        "No policy matched — allowed by default",
    )
