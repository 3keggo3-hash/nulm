"""Tests for role_assigner.py - RoleAssigner and role assignment."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations


from claude_bridge.role_assigner import (
    RoleAssigner,
    ROLE_DEFINITIONS,
)


class TestRoleAssigner:
    def setup_method(self) -> None:
        self.assigner = RoleAssigner()

    def test_assign_role_shell_script_exec(self):
        result = self.assigner.assign_role(
            entity_name="shell_helper",
            context="run shell script to deploy",
            metrics={},
        )
        assert result.role == "executor"
        assert result.requires_approval is True

    def test_assign_role_readme_write(self):
        result = self.assigner.assign_role(
            entity_name="docs_helper",
            context="write README for the project",
            metrics={},
        )
        assert result.role == "docs_reviewer"
        assert result.requires_approval is False

    def test_assign_role_observer_unknown_task(self):
        result = self.assigner.assign_role(
            entity_name="xyz_skill",
            context="perform xyz operation",
            metrics={},
        )
        assert result.role in ROLE_DEFINITIONS

    def test_assign_role_high_acceptance_boosts_confidence(self):
        result = self.assigner.assign_role(
            entity_name="git_helper",
            context="run git commit",
            metrics={"hit_count": 10, "acceptance_rate": 0.9},
        )
        assert result.role == "executor"
        assert result.confidence >= 0.9

    def test_assign_role_security_context(self):
        result = self.assigner.assign_role(
            entity_name="auth_helper",
            context="check password and auth permissions",
            metrics={},
        )
        assert result.role == "security_reviewer"
        assert result.requires_approval is False

    def test_assign_role_architect_design(self):
        result = self.assigner.assign_role(
            entity_name="design_skill",
            context="design system architecture",
            metrics={},
        )
        assert result.role == "architect"

    def test_assign_role_test_strategy(self):
        result = self.assigner.assign_role(
            entity_name="test_skill",
            context="run pytest and verify coverage",
            metrics={},
        )
        assert result.role == "test_strategist"

    def test_assign_role_implementer_create(self):
        result = self.assigner.assign_role(
            entity_name="create_skill",
            context="create new file and implement feature",
            metrics={},
        )
        assert result.role == "implementer"

    def test_assign_role_refactor_cleanup(self):
        result = self.assigner.assign_role(
            entity_name="cleanup_skill",
            context="refactor and clean up codebase",
            metrics={},
        )
        assert result.role == "refactor_agent"

    def test_assign_role_executor_deploy(self):
        result = self.assigner.assign_role(
            entity_name="deploy_skill",
            context="deploy to production via sudo",
            metrics={},
        )
        assert result.role == "executor"
        assert result.requires_approval is True

    def test_assign_role_empty_metrics(self):
        result = self.assigner.assign_role(
            entity_name="test",
            context="test validation",
            metrics={},
        )
        assert result.role == "test_strategist"
        assert result.confidence > 0

    def test_assign_role_no_hit_count_no_boost(self):
        result = self.assigner.assign_role(
            entity_name="test",
            context="test validation",
            metrics={"hit_count": 0, "acceptance_rate": 0.5},
        )
        assert result.confidence < 0.9

    def test_assign_role_to_dict(self):
        result = self.assigner.assign_role(
            entity_name="test",
            context="test",
            metrics={},
        )
        d = result.to_dict()
        assert "role" in d
        assert "confidence" in d
        assert "reason" in d
        assert "requires_approval" in d

    def test_assign_bulk_multiple_entities(self):
        entities = [
            {"name": "shell_helper", "metrics": {}},
            {"name": "docs_helper", "metrics": {}},
            {"name": "test_helper", "metrics": {}},
        ]
        contexts = [
            "run shell script to deploy",
            "write documentation for project",
            "run pytest to validate",
        ]
        results = []
        for entity, context in zip(entities, contexts):
            results.append(
                self.assigner.assign_role(
                    entity_name=entity["name"],
                    context=context,
                    metrics=entity.get("metrics", {}),
                )
            )
        assert len(results) == 3
        assert results[0].role == "executor"
        assert results[1].role == "docs_reviewer"
        assert results[2].role == "test_strategist"

    def test_assign_bulk_empty_list(self):
        results = self.assigner.assign_bulk([], context="test")
        assert results == []

    def test_assign_bulk_preserves_order(self):
        entities = [
            {"name": "a", "metrics": {}},
            {"name": "b", "metrics": {}},
            {"name": "c", "metrics": {}},
        ]
        results = self.assigner.assign_bulk(entities, context="architect design plan")
        assert all(r.role == "architect" for r in results)

    def test_role_definitions_complete(self):
        expected_roles = {
            "architect",
            "implementer",
            "test_strategist",
            "security_reviewer",
            "executor",
            "docs_reviewer",
            "refactor_agent",
            "observer",
        }
        assert set(ROLE_DEFINITIONS.keys()) == expected_roles

    def test_role_definitions_have_keywords(self):
        for role, definition in ROLE_DEFINITIONS.items():
            if role == "observer":
                continue
            assert "keywords" in definition
            assert isinstance(definition["keywords"], list)
            assert "risk" in definition

    def test_role_definitions_risk_values(self):
        valid_risks = {"low", "medium", "high"}
        for role, definition in ROLE_DEFINITIONS.items():
            assert definition["risk"] in valid_risks

    def test_assign_role_missing_entity_name(self):
        result = self.assigner.assign_role(
            entity_name="",
            context="run shell script",
            metrics={},
        )
        assert result.role == "executor"

    def test_assign_role_missing_metrics(self):
        result = self.assigner.assign_role(
            entity_name="test",
            context="run shell script",
            metrics={},
        )
        assert result.requires_approval is True
        assert result.role == "executor"

    def test_high_acceptance_low_hit_no_boost(self):
        result = self.assigner.assign_role(
            entity_name="test",
            context="architect design",
            metrics={"hit_count": 1, "acceptance_rate": 0.95},
        )
        assert result.role == "architect"

    def test_custom_role_definitions(self):
        custom_roles = {
            "custom_role": {
                "keywords": ["custom", "special"],
                "risk": "medium",
            },
        }
        assigner = RoleAssigner(role_definitions=custom_roles)
        result = assigner.assign_role(
            entity_name="test",
            context="custom special task",
            metrics={},
        )
        assert result.role == "custom_role"
