"""Tests for approach_explorer module."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import time

from claude_bridge import approach_explorer as ae


class TestExploreApproaches:
    def test_generates_sort_approaches(self, temp_project):
        result = ae.explore_approaches("I need to sort a large list of numbers", count=3)
        assert result["ok"] is True
        assert len(result["approaches"]) == 3
        assert result["keywords_matched"] == ["sort"]
        names = [a["name"] for a in result["approaches"]]
        assert "Quicksort" in names

    def test_generates_search_approaches(self, temp_project):
        result = ae.explore_approaches("implement a search algorithm for finding text", count=2)
        assert result["ok"] is True
        assert len(result["approaches"]) == 2
        assert result["keywords_matched"] == ["search"]

    def test_generates_multiple_keyword_approaches(self, temp_project):
        result = ae.explore_approaches("sort and search a database with cache", count=5)
        assert result["ok"] is True
        assert len(result["approaches"]) == 5
        assert "sort" in result["keywords_matched"]
        assert "search" in result["keywords_matched"]
        assert "database" in result["keywords_matched"]

    def test_no_keywords_returns_empty(self, temp_project):
        result = ae.explore_approaches("xyzzy flurb gronk", count=3)
        assert result["ok"] is False
        assert result["approaches"] == []

    def test_each_approach_has_required_fields(self, temp_project):
        result = ae.explore_approaches("optimize a slow function", count=2)
        assert result["ok"] is True
        for approach in result["approaches"]:
            assert "id" in approach
            assert "name" in approach
            assert "description" in approach
            assert "pros" in approach
            assert "cons" in approach
            assert "complexity" in approach
            assert approach["complexity"] in {"low", "medium", "high"}

    def test_approach_files_persisted_to_disk(self, temp_project):
        result = ae.explore_approaches("deploy the application", count=1)
        assert result["ok"] is True
        approach_id = result["approaches"][0]["id"]
        store_dir = temp_project / ".claude-bridge" / "approaches"
        file_path = store_dir / f"{approach_id}.json"
        assert file_path.exists()
        saved = json.loads(file_path.read_text())
        assert saved["name"] == result["approaches"][0]["name"]

    def test_count_limits_output(self, temp_project):
        result = ae.explore_approaches("build and test and deploy", count=2)
        assert result["ok"] is True
        assert len(result["approaches"]) == 2

    def test_handles_security_keyword(self, temp_project):
        result = ae.explore_approaches("improve security of our auth system", count=3)
        assert result["ok"] is True
        assert "security" in result["keywords_matched"]
        assert "auth" in result["keywords_matched"]

    def test_handles_refactor_keyword(self, temp_project):
        result = ae.explore_approaches("refactor the legacy auth module", count=1)
        assert result["ok"] is True
        assert "refactor" in result["keywords_matched"]


class TestExecuteApproach:
    def test_execute_valid_approach(self, temp_project):
        result = ae.explore_approaches("sort an array", count=1)
        approach_id = result["approaches"][0]["id"]
        exec_result = ae.execute_approach(approach_id)
        assert exec_result["ok"] is True
        assert exec_result["approach"]["executed"] is True
        assert "executed_at" in exec_result["approach"]

    def test_execute_nonexistent_approach(self, temp_project):
        result = ae.execute_approach("nonexistent-id")
        assert result["ok"] is False

    def test_execute_rejects_invalid_approach_id(self, temp_project):
        result = ae.execute_approach("../outside")
        assert result["ok"] is False
        assert result["message"] == "Invalid approach_id."

    def test_execute_stamps_timestamp(self, temp_project):
        result = ae.explore_approaches("sort an array", count=1)
        approach_id = result["approaches"][0]["id"]
        before = time.time()
        exec_result = ae.execute_approach(approach_id)
        after = time.time()
        assert exec_result["ok"] is True
        ts = exec_result["approach"]["executed_at"]
        assert before - 1 <= ts <= after + 1


class TestCompareApproaches:
    def test_compare_returns_best_by_complexity(self, temp_project):
        r1 = ae.explore_approaches("sort an array", count=3)
        ids = [a["id"] for a in r1["approaches"]]
        comp = ae.compare_approaches(ids)
        assert comp["ok"] is True
        assert comp["comparison"]["best_recommendation"]["complexity"] == "medium"
        assert "compared_approaches" in comp["comparison"]
        assert "complexity_levels" in comp["comparison"]
        assert len(comp["comparison"]["compared_approaches"]) == 3

    def test_compare_low_beats_high(self, temp_project):
        store_dir = ae._approach_store_dir()
        aid_high = "a" * 32
        aid_low = "b" * 32
        (store_dir / f"{aid_high}.json").write_text(
            json.dumps(
                {
                    "id": aid_high,
                    "name": "High Approach",
                    "description": "high",
                    "pros": [],
                    "cons": [],
                    "complexity": "high",
                }
            )
        )
        (store_dir / f"{aid_low}.json").write_text(
            json.dumps(
                {
                    "id": aid_low,
                    "name": "Low Approach",
                    "description": "low",
                    "pros": [],
                    "cons": [],
                    "complexity": "low",
                }
            )
        )
        comp = ae.compare_approaches([aid_high, aid_low])
        assert comp["ok"] is True
        assert comp["comparison"]["best_recommendation"]["name"] == "Low Approach"

    def test_compare_missing_ids_reported(self, temp_project):
        r1 = ae.explore_approaches("sort an array", count=1)
        ids = [r1["approaches"][0]["id"], "nonexistent"]
        comp = ae.compare_approaches(ids)
        assert comp["ok"] is True
        assert "missing" in comp["comparison"]
        assert "nonexistent" in comp["comparison"]["missing"]

    def test_compare_all_missing(self, temp_project):
        comp = ae.compare_approaches(["a", "b"])
        assert comp["ok"] is False
        assert comp["missing"] == ["a", "b"]

    def test_compare_single_approach(self, temp_project):
        r1 = ae.explore_approaches("sort an array", count=1)
        comp = ae.compare_approaches([r1["approaches"][0]["id"]])
        assert comp["ok"] is True
        assert comp["comparison"]["best_recommendation"]["name"] == "Quicksort"


class TestDetectKeywords:
    def test_empty_problem(self):
        assert ae._detect_keywords("") == []

    def test_no_match(self):
        assert ae._detect_keywords("nothing relevant here") == []

    def test_single_match(self):
        assert ae._detect_keywords("how to sort data") == ["sort"]

    def test_multiple_matches(self):
        kw = ae._detect_keywords("sort and search with cache")
        assert "sort" in kw
        assert "search" in kw
        assert "cache" in kw

    def test_case_insensitive(self):
        assert ae._detect_keywords("SORT the ARRAY") == ["sort"]


class TestSynonymDetection:
    def test_sorting_synonyms(self):
        assert "sort" in ae._detect_keywords("need help with sorting numbers")

    def test_find_synonym(self):
        assert "search" in ae._detect_keywords("find the element in the array")

    def test_performance_synonym(self):
        assert "optimize" in ae._detect_keywords("improve performance of this code")

    def test_container_synonym(self):
        assert "deploy" in ae._detect_keywords("docker container deployment")


class TestIntentPatternDetection:
    def test_optimize_intent(self):
        kw = ae._detect_keywords("make this faster")
        assert "optimize" in kw

    def test_slow_intent(self):
        kw = ae._detect_keywords("this is slow")
        assert "optimize" in kw

    def test_legacy_intent(self):
        kw = ae._detect_keywords("migrate legacy system")
        assert "refactor" in kw

    def test_parallel_intent(self):
        kw = ae._detect_keywords("use multithreading")
        assert "async" in kw


class TestEdgeCases:
    def test_count_zero(self):
        result = ae.explore_approaches("sort an array", count=0)
        assert result["ok"] is False
        assert "positive" in result["message"]

    def test_count_negative(self):
        result = ae.explore_approaches("sort an array", count=-1)
        assert result["ok"] is False

    def test_count_exceeds_limit(self):
        result = ae.explore_approaches("sort an array", count=100)
        assert result["ok"] is False
        assert "exceed" in result["message"]

    def test_explore_with_relevance_flag(self):
        result = ae.explore_approaches(
            "sort and search and cache database", count=10, include_low_relevance=True
        )
        assert result["ok"] is True
        assert len(result["approaches"]) <= 10

    def test_explore_contains_relevance_scores(self):
        result = ae.explore_approaches("optimize slow code", count=3)
        assert result["ok"] is True
        for approach in result["approaches"]:
            assert "relevance_score" in approach
            assert 0.0 <= approach["relevance_score"] <= 1.0
