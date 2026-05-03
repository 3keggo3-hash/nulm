"""Optional AI Evaluator — typed models, provider interface, and strict JSON response parser."""

from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    PolicyDecision,
    RiskLevel,
    ToolRequestContext,
)


class EvaluationAction(str, Enum):
    """The action recommended by the AI evaluation for a tool request."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class EvaluationRequest:
    """Input to an AI evaluator provider describing a tool invocation."""

    prompt: str
    tool_name: str = ""
    tool_params: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the request to a JSON-compatible dictionary."""
        return {
            "prompt": self.prompt,
            "tool_name": self.tool_name,
            "tool_params": dict(self.tool_params),
            "context": dict(self.context),
        }


@dataclass
class EvaluationResponse:
    """Structured response from an AI evaluator indicating the recommended action."""

    action: EvaluationAction
    reason: str = ""
    risk_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the response to a JSON-compatible dictionary."""
        return {
            "action": self.action.value,
            "reason": self.reason,
            "risk_reasons": list(self.risk_reasons),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationResponse:
        """Deserialize a dictionary back into an EvaluationResponse.

        Invalid or missing actions default to ASK (fail-closed).
        """
        action_str = str(data.get("action", "ask"))
        try:
            action = EvaluationAction(action_str.lower())
        except ValueError:
            action = EvaluationAction.ASK
        return cls(
            action=action,
            reason=str(data.get("reason", "")),
            risk_reasons=[str(r) for r in data.get("risk_reasons", [])],
        )

    @classmethod
    def fail_closed(cls, reason: str = "") -> EvaluationResponse:
        """Create a safe default response when evaluation fails."""
        return cls(action=EvaluationAction.ASK, reason=reason)


@dataclass
class ProviderConfig:
    """Configuration for an AI evaluation provider (model, endpoint, etc.)."""

    model: str = "gpt-4"
    base_url: str = ""
    api_key: str = ""
    timeout: int = 30
    extra: dict[str, Any] = field(default_factory=dict)

    def _masked_key(self) -> str:
        if not self.api_key:
            return ""
        return f"sk-***...{self.api_key[-4:]}" if len(self.api_key) > 4 else "sk-***..."

    def __repr__(self) -> str:
        return (
            f"ProviderConfig(model={self.model!r}, base_url={self.base_url!r}, "
            f"api_key={self._masked_key()!r}, timeout={self.timeout}, extra={self.extra!r})"
        )

    def __str__(self) -> str:
        return (
            f"ProviderConfig(model={self.model}, base_url={self.base_url}, "
            f"api_key={self._masked_key()}, timeout={self.timeout})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary (excluding secrets)."""
        return {
            "model": self.model,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "extra": dict(self.extra),
        }


class Provider(ABC):
    """Abstract interface for an AI evaluation provider.

    Subclasses must implement :meth:`evaluate` without raising exceptions;
    all errors should be caught internally and returned as a fail-closed
    :class:`EvaluationResponse`.
    """

    @abstractmethod
    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        """Evaluate a tool request and return a structured decision.

        :param request: The tool invocation details to evaluate.
        :returns: A structured response with action, reason, and risk reasons.
        """
        ...


# ---------------------------------------------------------------------------
# Strict JSON response parser
# ---------------------------------------------------------------------------

_VALID_ACTIONS: frozenset[str] = frozenset(e.value for e in EvaluationAction)


def parse_evaluation_response(raw: str) -> EvaluationResponse:
    """Parse a raw JSON string into an :class:`EvaluationResponse`.

    Handles malformed JSON, missing or invalid ``action``, and unexpected
    payload shapes.  On any error the result is **fail-closed** (ASK).

    Expected JSON schema::

        {"action": "allow"|"deny"|"ask", "reason": "...", "risk_reasons": [...]}
    """
    try:
        data: Any = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return EvaluationResponse.fail_closed(
            reason="Failed to parse evaluation response: invalid JSON"
        )

    if not isinstance(data, dict):
        return EvaluationResponse.fail_closed(
            reason="Failed to parse evaluation response: expected a JSON object"
        )

    action_raw = data.get("action")
    if action_raw is None:
        return EvaluationResponse.fail_closed(
            reason="Evaluation response missing 'action' field"
        )

    if not isinstance(action_raw, str):
        return EvaluationResponse.fail_closed(
            reason="Evaluation response 'action' must be a string"
        )

    action_lower = action_raw.lower()
    if action_lower not in _VALID_ACTIONS:
        return EvaluationResponse(
            action=EvaluationAction.ASK,
            reason=f"Unknown action '{action_raw}'; defaulting to ask",
            risk_reasons=[f"unrecognized_action: {action_raw}"],
        )

    action = EvaluationAction(action_lower)
    reason_raw = data.get("reason")
    if reason_raw is None:
        reason = ""
    elif isinstance(reason_raw, str):
        reason = reason_raw
    else:
        reason = str(reason_raw)

    risk_reasons_raw = data.get("risk_reasons", [])
    if isinstance(risk_reasons_raw, list):
        risk_reasons = [str(r) for r in risk_reasons_raw if isinstance(r, str)]
    else:
        risk_reasons = []

    return EvaluationResponse(
        action=action,
        reason=reason,
        risk_reasons=risk_reasons,
    )


# ---------------------------------------------------------------------------
# Local / mock provider (no network)
# ---------------------------------------------------------------------------


class LocalEvaluatorProvider(Provider):
    """A deterministic local evaluator that requires no network.

    Matches the request prompt against simple deny/ask keyword lists.
    If no keyword matches the request is allowed.
    """

    def __init__(
        self,
        *,
        deny_patterns: list[str] | None = None,
        ask_patterns: list[str] | None = None,
    ) -> None:
        # FIX: use word boundary regex to avoid false positive substring matches
        self._deny_raw = list(deny_patterns or [])
        self._ask_raw = list(ask_patterns or [])
        self._deny = [
            re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE) for p in self._deny_raw
        ]
        self._ask = [
            re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE) for p in self._ask_raw
        ]

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        for i, pattern in enumerate(self._deny):
            if pattern.search(request.prompt):
                return EvaluationResponse(
                    action=EvaluationAction.DENY,
                    reason=f"Local evaluator matched deny pattern: {self._deny_raw[i]}",
                    risk_reasons=[f"matched_deny_pattern: {self._deny_raw[i]}"],
                )
        for i, pattern in enumerate(self._ask):
            if pattern.search(request.prompt):
                return EvaluationResponse(
                    action=EvaluationAction.ASK,
                    reason=f"Local evaluator matched ask pattern: {self._ask_raw[i]}",
                    risk_reasons=[f"matched_ask_pattern: {self._ask_raw[i]}"],
                )
        return EvaluationResponse(
            action=EvaluationAction.ALLOW,
            reason="Local evaluator found no concerning patterns",
            risk_reasons=[],
        )


# ---------------------------------------------------------------------------
# Convert EvaluationResponse → PolicyDecision
# ---------------------------------------------------------------------------


_EVAL_ACTION_TO_DECISION: dict[EvaluationAction, DecisionAction] = {
    EvaluationAction.ALLOW: DecisionAction.ALLOW,
    EvaluationAction.DENY: DecisionAction.DENY,
    EvaluationAction.ASK: DecisionAction.ASK,
}


_RISK_FROM_EVAL_ACTION: dict[EvaluationAction, RiskLevel] = {
    EvaluationAction.ALLOW: RiskLevel.LOW,
    EvaluationAction.DENY: RiskLevel.HIGH,
    EvaluationAction.ASK: RiskLevel.MEDIUM,
}


def evaluation_response_to_policy_decision(
    response: EvaluationResponse,
    ctx: ToolRequestContext | None = None,
) -> PolicyDecision:
    """Turn an :class:`EvaluationResponse` into a :class:`PolicyDecision` with source=AI."""
    action = _EVAL_ACTION_TO_DECISION.get(response.action, DecisionAction.ASK)
    risk_level = _RISK_FROM_EVAL_ACTION.get(response.action, RiskLevel.MEDIUM)
    metadata: dict[str, Any] = {"ai_reason": response.reason}
    if ctx is not None:
        metadata["tool_name"] = ctx.tool_name
    return PolicyDecision(
        action=action,
        source=DecisionSource.AI,
        risk_level=risk_level,
        reason=response.reason,
        risk_reasons=list(response.risk_reasons),
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Timeout wrapper for synchronous providers
# ---------------------------------------------------------------------------


async def evaluate_with_timeout(
    provider: Provider,
    request: EvaluationRequest,
    timeout: float,
) -> EvaluationResponse:
    """Evaluate a request through *provider* with a strict timeout.

    If the provider does not return within *timeout* seconds a fail-closed
    :class:`EvaluationResponse` is returned.
    """
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = loop.run_in_executor(pool, provider.evaluate, request)
        try:
            result: EvaluationResponse = await asyncio.wait_for(
                future, timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            return EvaluationResponse.fail_closed(
                reason=f"AI evaluator timed out after {timeout} seconds"
            )


async def evaluate_tool_with_ai(
    ctx: ToolRequestContext,
    provider: Provider | None,
    enabled: bool,
    timeout: int,
    fallback_action: str,
) -> PolicyDecision | None:
    """Run the AI evaluator for a tool request and return a :class:`PolicyDecision`.

    Returns ``None`` when the evaluator is disabled or no provider is given.
    On timeout or unexpected failure the *fallback_action* (``allow``,
    ``deny`` or ``ask``) controls the safe default.
    """
    if not enabled or provider is None:
        return None
    request = EvaluationRequest(
        prompt=f"Tool: {ctx.tool_name}\nParams: {json.dumps(ctx.params)}",
        tool_name=ctx.tool_name,
        tool_params=ctx.params,
        context={"project_dir": ctx.project_dir or ""},
    )
    try:
        resp = await evaluate_with_timeout(provider, request, timeout=timeout)
    except Exception:
        resp = EvaluationResponse.fail_closed(
            reason="AI evaluator failed unexpectedly"
        )

    is_fallback_trigger = resp.action == EvaluationAction.ASK and (
        resp.reason.startswith("AI evaluator timed out")
        or resp.reason.startswith("AI evaluator failed")
    )
    if is_fallback_trigger:
        if fallback_action == "allow":
            resp = EvaluationResponse(
                action=EvaluationAction.ALLOW,
                reason=f"AI evaluator fallback ({fallback_action}) after timeout/failure",
            )
        elif fallback_action == "deny":
            resp = EvaluationResponse(
                action=EvaluationAction.DENY,
                reason=f"AI evaluator fallback ({fallback_action}) after timeout/failure",
            )
        # else keep ASK (fail-closed)

    return evaluation_response_to_policy_decision(resp, ctx=ctx)
