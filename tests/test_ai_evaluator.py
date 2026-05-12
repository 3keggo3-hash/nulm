"""Tests for the optional AI Evaluator module."""

from __future__ import annotations

import pytest

from claude_bridge.ai_evaluator import (
    AnthropicProvider,
    EvaluationAction,
    EvaluationRequest,
    EvaluationResponse,
    LocalEvaluatorProvider,
    OllamaProvider,
    OpenAIProvider,
    Provider,
    ProviderConfig,
    TokenBudget,
    _validate_provider_url,
    ai_latency_summary,
    create_provider,
    evaluate_tool_with_ai,
    evaluate_with_budget,
    evaluate_with_timeout,
    evaluation_response_to_policy_decision,
    load_budget,
    parse_evaluation_response,
    reset_ai_latency_samples,
    save_budget,
)
from claude_bridge.guard_policy import DecisionAction, DecisionSource, RiskLevel, ToolRequestContext

# ---------------------------------------------------------------------------
# EvaluationAction
# ---------------------------------------------------------------------------


class TestEvaluationAction:
    def test_values(self) -> None:
        assert EvaluationAction.ALLOW.value == "allow"
        assert EvaluationAction.DENY.value == "deny"
        assert EvaluationAction.ASK.value == "ask"

    def test_from_string(self) -> None:
        assert EvaluationAction("allow") == EvaluationAction.ALLOW
        assert EvaluationAction("deny") == EvaluationAction.DENY
        assert EvaluationAction("ask") == EvaluationAction.ASK


# ---------------------------------------------------------------------------
# EvaluationRequest
# ---------------------------------------------------------------------------


class TestEvaluationRequest:
    def test_defaults(self) -> None:
        req = EvaluationRequest(prompt="test prompt")
        assert req.prompt == "test prompt"
        assert req.tool_name == ""
        assert req.tool_params == {}
        assert req.context == {}

    def test_to_dict(self) -> None:
        req = EvaluationRequest(
            prompt="test",
            tool_name="write_file",
            tool_params={"path": "/tmp/x"},
            context={"risk": "high"},
        )
        d = req.to_dict()
        assert d == {
            "prompt": "test",
            "tool_name": "write_file",
            "tool_params": {"path": "/tmp/x"},
            "context": {"risk": "high"},
        }


# ---------------------------------------------------------------------------
# EvaluationResponse
# ---------------------------------------------------------------------------


class TestEvaluationResponse:
    def test_to_dict_allow(self) -> None:
        r = EvaluationResponse(
            action=EvaluationAction.ALLOW,
            reason="looks safe",
            risk_reasons=[],
        )
        assert r.to_dict() == {
            "action": "allow",
            "reason": "looks safe",
            "risk_reasons": [],
        }

    def test_to_dict_deny_with_risk_reasons(self) -> None:
        r = EvaluationResponse(
            action=EvaluationAction.DENY,
            reason="suspicious pattern",
            risk_reasons=["sensitive_path", "high_risk_file"],
        )
        d = r.to_dict()
        assert d["action"] == "deny"
        assert "sensitive_path" in d["risk_reasons"]

    def test_from_dict_valid(self) -> None:
        r = EvaluationResponse.from_dict({"action": "deny", "reason": "bad", "risk_reasons": ["x"]})
        assert r.action == EvaluationAction.DENY
        assert r.reason == "bad"
        assert r.risk_reasons == ["x"]

    def test_from_dict_missing_action_defaults_to_ask(self) -> None:
        r = EvaluationResponse.from_dict({})
        assert r.action == EvaluationAction.ASK

    def test_from_dict_invalid_action_defaults_to_ask(self) -> None:
        r = EvaluationResponse.from_dict({"action": "banana"})
        assert r.action == EvaluationAction.ASK

    def test_from_dict_missing_fields_are_empty(self) -> None:
        r = EvaluationResponse.from_dict({"action": "allow"})
        assert r.reason == ""
        assert r.risk_reasons == []

    def test_fail_closed(self) -> None:
        r = EvaluationResponse.fail_closed(reason="something went wrong")
        assert r.action == EvaluationAction.ASK
        assert r.reason == "something went wrong"
        assert r.risk_reasons == []


# ---------------------------------------------------------------------------
# ProviderConfig
# ---------------------------------------------------------------------------


class TestProviderConfig:
    def test_defaults(self) -> None:
        c = ProviderConfig()
        assert c.model == "gpt-4"
        assert c.timeout == 30
        assert c.api_key == ""

    def test_to_dict_excludes_api_key(self) -> None:
        c = ProviderConfig(model="claude-3", base_url="https://example.com", api_key="secret")
        d = c.to_dict()
        assert d == {
            "model": "claude-3",
            "base_url": "https://example.com",
            "timeout": 30,
            "extra": {},
        }
        assert "api_key" not in d

    def test_to_dict_with_extra(self) -> None:
        c = ProviderConfig(extra={"temperature": 0.5})
        d = c.to_dict()
        assert d["extra"] == {"temperature": 0.5}


class _DummyHttpResponse:
    def __init__(self, payload: str) -> None:
        self._payload = payload.encode("utf-8")

    def __enter__(self) -> "_DummyHttpResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, *_args: object) -> bytes:
        return self._payload


class TestNetworkProviders:
    def test_create_provider_trims_api_key_and_preserves_timeout(self) -> None:
        provider = create_provider(
            "openai",
            api_key="  sk-test  ",
            model="gpt-test",
            timeout=7,
        )

        assert isinstance(provider, OpenAIProvider)
        assert provider.api_key == "sk-test"
        assert provider.timeout == 7

    def test_anthropic_provider_uses_configured_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, object] = {}

        def fake_urlopen(req: object, *, timeout: int) -> _DummyHttpResponse:
            seen["timeout"] = timeout
            seen["request"] = req
            return _DummyHttpResponse(
                '{"content": [{"text": "{\\"action\\": \\"allow\\", \\"reason\\": \\"ok\\"}"}]}'
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        provider = AnthropicProvider(api_key="sk-test", timeout=9)

        response = provider.evaluate(EvaluationRequest(prompt="run git status"))

        assert response.action == EvaluationAction.ALLOW
        assert seen["timeout"] == 9

    def test_openai_provider_uses_configured_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}

        def fake_urlopen(req: object, *, timeout: int) -> _DummyHttpResponse:
            seen["timeout"] = timeout
            seen["request"] = req
            return _DummyHttpResponse(
                '{"choices": [{"message": {"content": "{\\"action\\": \\"deny\\"}"}}]}'
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        provider = OpenAIProvider(api_key="sk-test", timeout=11)

        response = provider.evaluate(EvaluationRequest(prompt="run rm"))

        assert response.action == EvaluationAction.DENY
        assert seen["timeout"] == 11

    def test_ollama_provider_uses_configured_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}

        def fake_urlopen(req: object, *, timeout: int) -> _DummyHttpResponse:
            seen["timeout"] = timeout
            seen["request"] = req
            return _DummyHttpResponse('{"response": "{\\"action\\": \\"ask\\"}"}')

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        monkeypatch.setattr("claude_bridge.ai_evaluator._validate_provider_url", lambda url: None)
        provider = OllamaProvider(timeout=13)

        response = provider.evaluate(EvaluationRequest(prompt="run curl"))

        assert response.action == EvaluationAction.ASK
        assert seen["timeout"] == 13

    def test_ollama_provider_rejects_private_base_url(self) -> None:
        with pytest.raises(ValueError, match="private/internal"):
            _validate_provider_url("http://169.254.169.254/latest/meta-data/")

    def test_provider_rejects_fenced_json_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(req: object, *, timeout: int) -> _DummyHttpResponse:
            return _DummyHttpResponse(
                '{"choices": [{"message": {"content": "```json\\n'
                '{\\"action\\": \\"allow\\"}\\n```"}}]}'
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        provider = OpenAIProvider(api_key="sk-test")

        response = provider.evaluate(EvaluationRequest(prompt="run git status"))

        assert response.action == EvaluationAction.ASK
        assert "invalid json" in response.reason.lower()


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class TestProviderInterface:
    def test_cannot_instantiate_abstract_class(self) -> None:
        """Provider is abstract and cannot be instantiated directly."""
        try:
            Provider()  # type: ignore[abstract]
            assert False, "Expected TypeError"
        except TypeError:
            pass

    def test_concrete_subclass_must_implement_evaluate(self) -> None:
        """A subclass without evaluate should also be uninstantiable."""
        try:
            type("Incomplete", (Provider,), {})()  # type: ignore[abstract]
            assert False, "Expected TypeError"
        except TypeError:
            pass

    def test_concrete_provider_works(self) -> None:
        class FakeProvider(Provider):
            def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
                return EvaluationResponse(
                    action=EvaluationAction.ALLOW,
                    reason="always allow",
                )

        p = FakeProvider()
        req = EvaluationRequest(prompt="test")
        resp = p.evaluate(req)
        assert resp.action == EvaluationAction.ALLOW
        assert resp.reason == "always allow"


# ---------------------------------------------------------------------------
# parse_evaluation_response
# ---------------------------------------------------------------------------


class TestParseEvaluationResponse:
    def test_valid_allow(self) -> None:
        resp = parse_evaluation_response(
            '{"action": "allow", "reason": "safe", "risk_reasons": []}'
        )
        assert resp.action == EvaluationAction.ALLOW
        assert resp.reason == "safe"

    def test_valid_deny(self) -> None:
        resp = parse_evaluation_response(
            '{"action": "deny", "reason": "high risk", "risk_reasons": ["sensitive"]}'
        )
        assert resp.action == EvaluationAction.DENY
        assert resp.risk_reasons == ["sensitive"]

    def test_valid_ask(self) -> None:
        resp = parse_evaluation_response('{"action": "ask", "reason": "uncertain"}')
        assert resp.action == EvaluationAction.ASK

    def test_action_case_insensitive(self) -> None:
        for variant in ("ALLOW", "Allow", "aLlOw"):
            resp = parse_evaluation_response(f'{{"action": "{variant}"}}')
            assert resp.action == EvaluationAction.ALLOW, f"failed for {variant}"

    def test_missing_action_fail_closed(self) -> None:
        resp = parse_evaluation_response('{"reason": "no action"}')
        assert resp.action == EvaluationAction.ASK
        assert "missing" in resp.reason.lower()

    def test_invalid_action_fail_closed(self) -> None:
        resp = parse_evaluation_response('{"action": "banana"}')
        assert resp.action == EvaluationAction.ASK
        assert "banana" in resp.reason

    def test_null_action_fail_closed(self) -> None:
        resp = parse_evaluation_response('{"action": null}')
        assert resp.action == EvaluationAction.ASK

    def test_non_string_action_fail_closed(self) -> None:
        resp = parse_evaluation_response('{"action": 42}')
        assert resp.action == EvaluationAction.ASK

    def test_malformed_json_fail_closed(self) -> None:
        resp = parse_evaluation_response("{not valid json}")
        assert resp.action == EvaluationAction.ASK
        assert "invalid json" in resp.reason.lower()

    def test_non_dict_json_fail_closed(self) -> None:
        resp = parse_evaluation_response('"just a string"')
        assert resp.action == EvaluationAction.ASK
        assert "object" in resp.reason.lower()

    def test_empty_string_fail_closed(self) -> None:
        resp = parse_evaluation_response("")
        assert resp.action == EvaluationAction.ASK

    def test_risk_reasons_non_list_ignored(self) -> None:
        resp = parse_evaluation_response('{"action": "deny", "risk_reasons": "not_a_list"}')
        assert resp.risk_reasons == []

    def test_risk_reasons_mixed_types(self) -> None:
        resp = parse_evaluation_response(
            '{"action": "deny", "risk_reasons": ["valid", 42, null, "also_valid"]}'
        )
        assert resp.risk_reasons == ["valid", "also_valid"]

    def test_reason_non_string_coerced(self) -> None:
        resp = parse_evaluation_response('{"action": "allow", "reason": 123}')
        assert resp.reason == "123"

    def test_reason_null_becomes_empty(self) -> None:
        resp = parse_evaluation_response('{"action": "allow", "reason": null}')
        assert resp.reason == ""

    def test_reason_missing_becomes_empty(self) -> None:
        resp = parse_evaluation_response('{"action": "allow"}')
        assert resp.reason == ""

    def test_extra_fields_ignored(self) -> None:
        resp = parse_evaluation_response(
            '{"action": "allow", "extra_field": "ignored", "nested": {"x": 1}}'
        )
        assert resp.action == EvaluationAction.ALLOW


# ---------------------------------------------------------------------------
# LocalEvaluatorProvider
# ---------------------------------------------------------------------------


class TestLocalEvaluatorProvider:
    def test_deny_pattern_matches(self) -> None:
        p = LocalEvaluatorProvider(deny_patterns=["rm -rf"])
        req = EvaluationRequest(prompt="user wants to run rm -rf /")
        resp = p.evaluate(req)
        assert resp.action == EvaluationAction.DENY
        assert "rm -rf" in resp.reason

    def test_ask_pattern_matches(self) -> None:
        p = LocalEvaluatorProvider(ask_patterns=["curl"])
        req = EvaluationRequest(prompt="user wants to curl example.com")
        resp = p.evaluate(req)
        assert resp.action == EvaluationAction.ASK
        assert "curl" in resp.reason

    def test_deny_takes_precedence_over_ask(self) -> None:
        p = LocalEvaluatorProvider(deny_patterns=["rm"], ask_patterns=["rm"])
        req = EvaluationRequest(prompt="run rm command")
        resp = p.evaluate(req)
        assert resp.action == EvaluationAction.DENY

    def test_allow_when_no_match(self) -> None:
        p = LocalEvaluatorProvider(deny_patterns=["rm"], ask_patterns=["curl"])
        req = EvaluationRequest(prompt="run git status")
        resp = p.evaluate(req)
        assert resp.action == EvaluationAction.ALLOW

    def test_case_insensitive(self) -> None:
        p = LocalEvaluatorProvider(deny_patterns=["SUDO"])
        req = EvaluationRequest(prompt="user wants SUDO access")
        resp = p.evaluate(req)
        assert resp.action == EvaluationAction.DENY


# ---------------------------------------------------------------------------
# evaluation_response_to_policy_decision
# ---------------------------------------------------------------------------


class TestEvaluationResponseToPolicyDecision:
    def test_allow_becomes_ai_allow(self) -> None:
        resp = EvaluationResponse(action=EvaluationAction.ALLOW, reason="safe")
        dec = evaluation_response_to_policy_decision(resp)
        assert dec.action == DecisionAction.ALLOW
        assert dec.source == DecisionSource.AI
        assert dec.risk_level == RiskLevel.LOW

    def test_deny_becomes_ai_deny(self) -> None:
        resp = EvaluationResponse(action=EvaluationAction.DENY, reason="dangerous")
        dec = evaluation_response_to_policy_decision(resp)
        assert dec.action == DecisionAction.DENY
        assert dec.source == DecisionSource.AI
        assert dec.risk_level == RiskLevel.HIGH

    def test_ask_becomes_ai_ask(self) -> None:
        resp = EvaluationResponse(action=EvaluationAction.ASK, reason="uncertain")
        dec = evaluation_response_to_policy_decision(resp)
        assert dec.action == DecisionAction.ASK
        assert dec.source == DecisionSource.AI
        assert dec.risk_level == RiskLevel.MEDIUM

    def test_includes_tool_context(self) -> None:
        resp = EvaluationResponse(action=EvaluationAction.ALLOW, reason="ok")
        ctx = ToolRequestContext(tool_name="write_file", params={"path": "x"})
        dec = evaluation_response_to_policy_decision(resp, ctx=ctx)
        assert dec.metadata.get("tool_name") == "write_file"


# ---------------------------------------------------------------------------
# evaluate_with_timeout
# ---------------------------------------------------------------------------


class TestEvaluateWithTimeout:
    @pytest.mark.asyncio
    async def test_returns_result_when_fast(self) -> None:
        reset_ai_latency_samples()

        class FastProvider(Provider):
            def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
                return EvaluationResponse(action=EvaluationAction.ALLOW)

        resp = await evaluate_with_timeout(FastProvider(), EvaluationRequest(prompt="x"), timeout=5)
        assert resp.action == EvaluationAction.ALLOW
        summary = ai_latency_summary()
        assert summary["sample_count"] == 1
        assert summary["last_ms"] is not None

    @pytest.mark.asyncio
    async def test_timeout_returns_fail_closed(self) -> None:
        reset_ai_latency_samples()

        class SlowProvider(Provider):
            def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
                import time

                time.sleep(10)
                return EvaluationResponse(action=EvaluationAction.ALLOW)

        resp = await evaluate_with_timeout(
            SlowProvider(), EvaluationRequest(prompt="x"), timeout=0.1
        )
        assert resp.action == EvaluationAction.ASK
        assert "timed out" in resp.reason.lower()
        assert ai_latency_summary()["sample_count"] == 1


# ---------------------------------------------------------------------------
# evaluate_tool_with_ai
# ---------------------------------------------------------------------------


class TestEvaluateToolWithAi:
    @pytest.mark.asyncio
    async def test_disabled_returns_none(self) -> None:
        result = await evaluate_tool_with_ai(
            ToolRequestContext(tool_name="run_shell", params={}),
            provider=LocalEvaluatorProvider(),
            enabled=False,
            timeout=5,
            fallback_action="ask",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_allow(self) -> None:
        reset_ai_latency_samples()

        result = await evaluate_tool_with_ai(
            ToolRequestContext(tool_name="run_shell", params={"command": "ls"}),
            provider=LocalEvaluatorProvider(),
            enabled=True,
            timeout=5,
            fallback_action="ask",
        )
        assert result is not None
        assert result.action == DecisionAction.ALLOW
        assert result.source == DecisionSource.AI
        assert result.metadata["ai_evaluator_latency_ms"] is not None

    @pytest.mark.asyncio
    async def test_deny(self) -> None:
        result = await evaluate_tool_with_ai(
            ToolRequestContext(tool_name="run_shell", params={"command": "rm -rf /"}),
            provider=LocalEvaluatorProvider(deny_patterns=["rm -rf"]),
            enabled=True,
            timeout=5,
            fallback_action="ask",
        )
        assert result is not None
        assert result.action == DecisionAction.DENY
        assert result.source == DecisionSource.AI

    @pytest.mark.asyncio
    async def test_ask(self) -> None:
        result = await evaluate_tool_with_ai(
            ToolRequestContext(tool_name="run_shell", params={"command": "curl x"}),
            provider=LocalEvaluatorProvider(ask_patterns=["curl"]),
            enabled=True,
            timeout=5,
            fallback_action="ask",
        )
        assert result is not None
        assert result.action == DecisionAction.ASK
        assert result.source == DecisionSource.AI

    @pytest.mark.asyncio
    async def test_timeout_fallback_allow_is_treated_as_ask(self) -> None:
        class SlowProvider(Provider):
            def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
                import time

                time.sleep(10)
                return EvaluationResponse(action=EvaluationAction.ALLOW)

        result = await evaluate_tool_with_ai(
            ToolRequestContext(tool_name="run_shell", params={}),
            provider=SlowProvider(),
            enabled=True,
            timeout=0.1,
            fallback_action="allow",
        )
        assert result is not None
        assert result.action == DecisionAction.ASK
        assert "fallback" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_timeout_fallback_deny(self) -> None:
        class SlowProvider(Provider):
            def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
                import time

                time.sleep(10)
                return EvaluationResponse(action=EvaluationAction.ALLOW)

        result = await evaluate_tool_with_ai(
            ToolRequestContext(tool_name="run_shell", params={}),
            provider=SlowProvider(),
            enabled=True,
            timeout=0.1,
            fallback_action="deny",
        )
        assert result is not None
        assert result.action == DecisionAction.DENY

    @pytest.mark.asyncio
    async def test_malformed_provider_exception(self) -> None:
        class BrokenProvider(Provider):
            def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
                raise RuntimeError("boom")

        result = await evaluate_tool_with_ai(
            ToolRequestContext(tool_name="run_shell", params={}),
            provider=BrokenProvider(),
            enabled=True,
            timeout=5,
            fallback_action="ask",
        )
        assert result is not None
        assert result.action == DecisionAction.ASK
        assert "failure" in result.reason.lower()


# ---------------------------------------------------------------------------
# Token Budget Manager — automatic model routing
# ---------------------------------------------------------------------------


class TestMeasureComplexity:
    def test_empty_task_low_complexity(self) -> None:
        from claude_bridge.ai_evaluator import measure_complexity

        score = measure_complexity("", {})
        assert score == 0.0

    def test_token_count_contributes(self) -> None:
        from claude_bridge.ai_evaluator import measure_complexity

        # 50 tokens * 0.01 = 0.5
        score = measure_complexity(" ".join(["word"] * 50), {})
        assert score == 0.5

    def test_file_count_contributes(self) -> None:
        from claude_bridge.ai_evaluator import measure_complexity

        # "task" = 1 token * 0.01 = 0.01, 5 files * 0.05 = 0.25, total = 0.26
        score = measure_complexity("task", {"file_count": 5})
        assert abs(score - 0.26) < 0.001

    def test_depth_contributes(self) -> None:
        from claude_bridge.ai_evaluator import measure_complexity

        # "task" = 1 token * 0.01 = 0.01, 3 depth * 0.1 = 0.3, total = 0.31
        score = measure_complexity("task", {"nested_depth": 3})
        assert abs(score - 0.31) < 0.001

    def test_combined_scores(self) -> None:
        from claude_bridge.ai_evaluator import measure_complexity

        # 10 tokens * 0.01 = 0.1, 5 files * 0.05 = 0.25, 2 depth * 0.1 = 0.2
        score = measure_complexity(" ".join(["word"] * 10), {"file_count": 5, "nested_depth": 2})
        assert abs(score - 0.55) < 0.001

    def test_capped_at_one(self) -> None:
        from claude_bridge.ai_evaluator import measure_complexity

        score = measure_complexity(" ".join(["word"] * 200), {"file_count": 100, "nested_depth": 100})
        assert score == 1.0


class TestSelectModel:
    def test_low_complexity_selects_haiku(self) -> None:
        from claude_bridge.ai_evaluator import select_model

        model = select_model("simple task", {})
        assert model == "claude-haiku"

    def test_medium_complexity_selects_sonnet(self) -> None:
        from claude_bridge.ai_evaluator import select_model

        # 50 tokens * 0.01 = 0.5, 5 files * 0.05 = 0.25, total = 0.75 (capped at 1.0)
        # but with 30 tokens to get 0.75... wait, 50 tokens = 0.5 + 5*0.05=0.25 = 0.75 > 0.7
        # so 30 tokens = 0.3 + 5*0.05=0.25 = 0.55 which is < 0.7 but >= 0.3
        model = select_model(" ".join(["task"] * 30), {"file_count": 5})
        assert model == "claude-sonnet"

    def test_high_complexity_selects_opus(self) -> None:
        from claude_bridge.ai_evaluator import select_model

        model = select_model(" ".join(["task"] * 100), {"file_count": 50, "nested_depth": 10})
        assert model == "claude-opus"

    def test_boundary_low_medium(self) -> None:
        from claude_bridge.ai_evaluator import select_model

        # complexity 0.3 is NOT < 0.3, so it becomes sonnet (not haiku)
        model = select_model(" ".join(["task"] * 30), {})
        assert model == "claude-sonnet"

    def test_boundary_medium_high(self) -> None:
        from claude_bridge.ai_evaluator import select_model

        # complexity 0.7 is NOT < 0.7, so it becomes opus (not sonnet)
        model = select_model(" ".join(["task"] * 70), {})
        assert model == "claude-opus"


# ---------------------------------------------------------------------------
# TokenBudget
# ---------------------------------------------------------------------------


class TestTokenBudget:
    def test_usage_percent_initially_zero(self) -> None:
        budget = TokenBudget()
        assert budget.usage_percent == 0.0

    def test_usage_percent_after_usage(self) -> None:
        budget = TokenBudget(monthly_limit=100000, used=50000)
        assert budget.usage_percent == 0.5

    def test_is_warning_below_threshold(self) -> None:
        budget = TokenBudget(monthly_limit=100000, used=50000)
        assert not budget.is_warning

    def test_is_warning_at_threshold(self) -> None:
        budget = TokenBudget(monthly_limit=100000, used=80000)
        assert budget.is_warning

    def test_is_exhausted_below_hard_limit(self) -> None:
        budget = TokenBudget(monthly_limit=100000, used=99000)
        assert not budget.is_exhausted

    def test_is_exhausted_at_hard_limit(self) -> None:
        budget = TokenBudget(monthly_limit=100000, used=100000)
        assert budget.is_exhausted

    def test_track_usage_increments_used(self) -> None:
        budget = TokenBudget(monthly_limit=100000, used=10000)
        budget.track_usage(5000)
        assert budget.used == 15000

    def test_auto_rollback_returns_essential(self) -> None:
        budget = TokenBudget()
        assert budget.auto_rollback_to_essential() == "essential"

    def test_reset_clears_usage_and_warning(self) -> None:
        budget = TokenBudget(monthly_limit=100000, used=90000)
        budget._warned_user = True
        budget.reset()
        assert budget.used == 0
        assert budget._warned_user is False


class TestBudgetStorage:
    def test_save_and_load_budget(self, tmp_path: pytest.TempPathFactory) -> None:
        budget = TokenBudget(monthly_limit=50000, used=25000)
        path = tmp_path / "budget.json"

        save_budget(budget, str(path))
        loaded = load_budget(str(path))

        assert loaded.monthly_limit == 50000
        assert loaded.used == 25000

    def test_load_budget_missing_file_returns_default(self, tmp_path: pytest.TempPathFactory) -> None:
        path = tmp_path / "nonexistent.json"
        loaded = load_budget(str(path))

        assert loaded.monthly_limit == 100000
        assert loaded.used == 0


class TestEvaluateWithBudget:
    @pytest.mark.asyncio
    async def test_exhausted_budget_returns_ask(self) -> None:
        budget = TokenBudget(monthly_limit=100000, used=100000)
        provider = LocalEvaluatorProvider()

        resp = await evaluate_with_budget(
            EvaluationRequest(prompt="test"),
            provider,
            budget,
        )
        assert resp.action == EvaluationAction.ASK
        assert "optimized automatically" in resp.reason.lower()

    @pytest.mark.asyncio
    async def test_normal_evaluation_works(self) -> None:
        budget = TokenBudget(monthly_limit=100000, used=1000)
        provider = LocalEvaluatorProvider()

        resp = await evaluate_with_budget(
            EvaluationRequest(prompt="run git status"),
            provider,
            budget,
        )
        assert resp.action == EvaluationAction.ALLOW
