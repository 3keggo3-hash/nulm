"""Golden-dataset checks for relevance ranking quality."""

from __future__ import annotations

import json
from pathlib import Path

from claude_bridge import server as mcp_server

from tests.helpers import parse_payload


def _load_cases() -> list[dict]:
    fixture_path = Path(__file__).parent / "fixtures" / "relevance_golden_cases.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


class TestRelevanceGoldenDataset:
    async def test_relevance_cases_match_expected_rank_prefix(self, temp_project):
        cases = _load_cases()

        for case in cases:
            for relative_path, content in case["files"].items():
                target = temp_project / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            payload = parse_payload(
                await mcp_server.find_relevant_files(
                    query=case["query"],
                    path=case["path"],
                    limit=case["limit"],
                )
            )

            assert payload["ok"] is True, case["name"]
            ranked_paths = [item["path"] for item in payload["details"]["results"]]
            expected_prefix = case["expected_top_paths"]
            for expected_path in expected_prefix:
                assert (
                    expected_path in ranked_paths
                ), f"{case['name']}: {expected_path} not in results"
            assert payload["details"]["total_results"] >= len(expected_prefix), case["name"]
