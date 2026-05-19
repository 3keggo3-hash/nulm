"""Unified scanner for tool schemas, skill packages, MCP peers, and config."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_bridge._detective_classifiers import get_prompt_injection_classifier
from claude_bridge.config_scanner import (
    check_approval_permissiveness,
    check_secret_leakage,
    scan_mcp_config,
)
from claude_bridge.skill_marketplace import PackageRiskProfile, score_package_risk
from claude_bridge.tool_validator import ToolSchemaValidator, ValidationResult


@dataclass
class ScanResult:
    tool_schemas: list[dict[str, Any]] = field(default_factory=list)
    skill_packages: list[dict[str, Any]] = field(default_factory=list)
    mcp_peers: list[dict[str, Any]] = field(default_factory=list)
    config_issues: list[str] = field(default_factory=list)
    prompt_injection_findings: list[dict[str, Any]] = field(default_factory=list)
    overall_risk: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_schemas": self.tool_schemas,
            "skill_packages": self.skill_packages,
            "mcp_peers": self.mcp_peers,
            "config_issues": self.config_issues,
            "prompt_injection_findings": self.prompt_injection_findings,
            "overall_risk": self.overall_risk,
        }


def scan_tool_schema(schema: dict[str, Any]) -> ValidationResult:
    validator = ToolSchemaValidator()
    return validator.validate(schema)


def scan_skill_package(path: Path) -> PackageRiskProfile:
    if not path.exists() or not path.name.endswith(".tar.gz"):
        return PackageRiskProfile(
            overall_score=10.0,
            code_markers_found=["invalid_package_path"],
            dependency_risk="unknown",
            typosquat_score=0.0,
            supply_chain_indicators=[],
            permission_requests=[],
        )

    try:
        with tarfile.open(path, "r:gz") as tar:
            manifest_file = tar.extractfile("skill.json")
            code_file = tar.extractfile("skill.py")
            if manifest_file is None or code_file is None:
                return PackageRiskProfile(
                    overall_score=10.0,
                    code_markers_found=["missing_required_files"],
                    dependency_risk="unknown",
                    typosquat_score=0.0,
                    supply_chain_indicators=[],
                    permission_requests=[],
                )

            manifest = json.loads(manifest_file.read().decode("utf-8"))
            code = code_file.read().decode("utf-8")

        profile_or_dict = score_package_risk(manifest, code)
        profile: PackageRiskProfile
        if isinstance(profile_or_dict, PackageRiskProfile):
            profile = profile_or_dict
        else:
            profile = PackageRiskProfile(
                overall_score=float(profile_or_dict.get("risk_score", 0)),
                code_markers_found=[],
                dependency_risk="unknown",
                typosquat_score=0.0,
                supply_chain_indicators=[],
                permission_requests=[],
            )
        return profile
    except Exception:
        return PackageRiskProfile(
            overall_score=10.0,
            code_markers_found=["scan_failed"],
            dependency_risk="unknown",
            typosquat_score=0.0,
            supply_chain_indicators=[],
            permission_requests=[],
        )


def scan_all(project_dir: Path) -> ScanResult:
    result = ScanResult()
    classifier = get_prompt_injection_classifier()

    guard_path = project_dir / ".claude-bridge-guard.json"
    if guard_path.exists():
        try:
            config = json.loads(guard_path.read_text(encoding="utf-8"))
            if isinstance(config, dict):
                result.config_issues.extend(check_approval_permissiveness(config))
                result.config_issues.extend(check_secret_leakage(config))
        except (OSError, json.JSONDecodeError):
            pass

    mcp_issues = scan_mcp_config(project_dir)
    result.config_issues.extend(mcp_issues)

    skills_dir = project_dir / ".claude-bridge" / "skills"
    if skills_dir.exists():
        for skill_file in skills_dir.glob("*.json"):
            if skill_file.stem.startswith("."):
                continue
            try:
                data = json.loads(skill_file.read_text(encoding="utf-8"))
                code_path = skill_file.with_suffix(".py")
                code = ""
                if code_path.exists():
                    code = code_path.read_text(encoding="utf-8")

                for field_name, text in [
                    ("name", data.get("name", "")),
                    ("description", data.get("description", "")),
                    ("trigger_phrases", " ".join(data.get("trigger_phrases", []))),
                ]:
                    is_suspicious, reason, score = classifier.classify(str(text))
                    if is_suspicious:
                        result.prompt_injection_findings.append({
                            "source": f"skill:{skill_file.stem}",
                            "field": field_name,
                            "score": score,
                            "reason": reason,
                        })

                if code:
                    is_suspicious, reason, score = classifier.classify(code)
                    if is_suspicious:
                        result.prompt_injection_findings.append({
                            "source": f"skill:{skill_file.stem}",
                            "field": "code",
                            "score": score,
                            "reason": reason,
                        })

                pkg_info: dict[str, Any] = {
                    "name": data.get("name", "unknown"),
                    "version": data.get("version", "unknown"),
                    "path": str(skill_file),
                }
                if code:
                    profile_or_dict = score_package_risk(data, code)
                    if isinstance(profile_or_dict, PackageRiskProfile):
                        pkg_info["risk_level"] = profile_or_dict.risk_level
                        pkg_info["risk_score"] = profile_or_dict.overall_score
                    else:
                        pkg_info["risk_level"] = profile_or_dict.get("risk_level", "unknown")
                        pkg_info["risk_score"] = profile_or_dict.get("risk_score", 0)
                result.skill_packages.append(pkg_info)
            except (OSError, json.JSONDecodeError):
                continue

    mcp_servers_path = project_dir / "mcp_servers.json"
    if mcp_servers_path.exists():
        try:
            data = json.loads(mcp_servers_path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", {}) or data.get("servers", {})
            if isinstance(servers, dict):
                for name, config in servers.items():
                    if not isinstance(config, dict):
                        continue
                    endpoint = config.get("url", config.get("endpoint", ""))
                    if endpoint:
                        is_suspicious, reason, score = classifier.classify(endpoint)
                        if is_suspicious:
                            result.prompt_injection_findings.append({
                                "source": f"mcp_peer:{name}",
                                "field": "endpoint",
                                "score": score,
                                "reason": reason,
                            })
                    result.mcp_peers.append({
                        "name": name,
                        "enabled": config.get("enabled", True),
                        "has_endpoint": bool(endpoint),
                    })
        except (OSError, json.JSONDecodeError):
            pass

    max_risk = 0
    for finding in result.prompt_injection_findings:
        score = finding.get("score", 0)
        if score >= 8:
            max_risk = max(max_risk, 3)
        elif score >= 5:
            max_risk = max(max_risk, 2)
        else:
            max_risk = max(max_risk, 1)

    if any("auto_approve: true" in i for i in result.config_issues):
        max_risk = max(max_risk, 3)

    risk_labels = {0: "low", 1: "low", 2: "medium", 3: "high"}
    result.overall_risk = risk_labels.get(max_risk, "low")

    return result


def generate_scan_report(result: ScanResult, format: str = "text") -> str:
    if format == "json":
        return json.dumps(result.to_dict(), indent=2, ensure_ascii=False)

    if format == "yaml":
        import yaml  # type: ignore[import-untyped]
        return yaml.dump(result.to_dict(), default_flow_style=False, sort_keys=False)  # type: ignore[no-any-return]

    lines: list[str] = []
    lines.append("=== Nulm Security Scan Report ===")
    lines.append(f"Overall Risk: {result.overall_risk.upper()}")

    if result.config_issues:
        lines.append(f"\nConfig Issues ({len(result.config_issues)}):")
        for issue in result.config_issues:
            lines.append(f"  - {issue}")
    else:
        lines.append("\nConfig: OK")

    if result.prompt_injection_findings:
        lines.append(f"\nPrompt Injection Findings ({len(result.prompt_injection_findings)}):")
        for finding in result.prompt_injection_findings:
            lines.append(
                f"  - [{finding['source']}] field={finding['field']} "
                f"score={finding['score']} reason={finding['reason']}"
            )
    else:
        lines.append("\nPrompt Injection: No suspicious patterns detected")

    if result.skill_packages:
        lines.append(f"\nSkill Packages ({len(result.skill_packages)}):")
        for pkg in result.skill_packages:
            risk = pkg.get("risk_level", "unknown")
            lines.append(f"  - {pkg['name']} v{pkg.get('version','?')} [{risk}]")
    else:
        lines.append("\nSkill Packages: None found")

    if result.mcp_peers:
        lines.append(f"\nMCP Peers ({len(result.mcp_peers)}):")
        for peer in result.mcp_peers:
            status = "enabled" if peer.get("enabled") else "disabled"
            lines.append(f"  - {peer['name']} [{status}]")
    else:
        lines.append("\nMCP Peers: None found")

    return "\n".join(lines)