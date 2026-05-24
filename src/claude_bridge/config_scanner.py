"""Config scanner for detecting security issues in Nulm configuration files."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ConfigScanResult:
    project_dir: Path
    approval_issues: list[str] = field(default_factory=list)
    secret_leakage_issues: list[str] = field(default_factory=list)
    mcp_config_issues: list[str] = field(default_factory=list)
    config_files_scanned: list[str] = field(default_factory=list)

    @property
    def total_issues(self) -> int:
        return (
            len(self.approval_issues)
            + len(self.secret_leakage_issues)
            + len(self.mcp_config_issues)
        )

    @property
    def risk_level(self) -> str:
        if self.total_issues == 0:
            return "low"
        if any("auto_approve" in i or "power-user" in i for i in self.approval_issues):
            return "high"
        if self.total_issues >= 3:
            return "high"
        return "medium"


def check_approval_permissiveness(config: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    auto_approve = config.get("auto_approve")
    if auto_approve is True:
        issues.append("auto_approve: true — all operations auto-approved")

    approval_preset = config.get("approval_preset")
    if approval_preset == "power-user":
        issues.append("approval_preset: power-user — minimal restrictions")

    client_managed = config.get("client_managed_approval")
    if auto_approve is True and client_managed is False:
        issues.append("auto_approve with client_managed_approval disabled — no guard rails")

    risk_level = config.get("auto_approve_risk_level", "medium")
    if risk_level == "none":
        issues.append("auto_approve_risk_level: none — no risk-based filtering")

    patterns = config.get("auto_approve_patterns", {})
    if patterns:
        for tool, tool_patterns in patterns.items():
            if tool_patterns and len(tool_patterns) > 0:
                issues.append(f"auto_approve_patterns for {tool} — broad auto-approval")

    return issues


def check_secret_leakage(config: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    api_key_pattern = re.compile(r"sk-[a-zA-Z0-9]{20,}")
    token_pattern = re.compile(r"[a-zA-Z0-9_-]{30,}")
    gcp_pattern = re.compile(r"ya29\.[a-zA-Z0-9_-]+")
    aws_pattern = re.compile(r"AKIA[0-9A-Z]{16}")

    for key, value in config.items():
        if not isinstance(value, str):
            continue
        if key in {"ai_evaluator_api_key", "api_key", "secret", "token"}:
            if value and value not in ("", "[REDACTED]"):
                if len(value) > 10:
                    issues.append(f"potential API key in config field: {key}")
        elif api_key_pattern.search(value):
            issues.append(f"potential OpenAI API key pattern in field: {key}")
        elif gcp_pattern.search(value):
            issues.append(f"potential GCP token pattern in field: {key}")
        elif aws_pattern.search(value):
            issues.append(f"potential AWS access key pattern in field: {key}")
        elif token_pattern.search(value) and len(value) > 40:
            if "password" not in key.lower():
                issues.append(f"potential bearer token in field: {key}")

    return issues


def scan_mcp_config(project_dir: Path) -> list[str]:
    issues: list[str] = []
    mcp_configs = [
        project_dir / "mcp_servers.json",
        project_dir / ".mcp.json",
        project_dir / ".claude-bridge" / "mcp_servers.json",
    ]

    for mcp_path in mcp_configs:
        if not mcp_path.exists():
            continue
        try:
            content = mcp_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                servers = data.get("mcpServers", data.get("servers", {}))
                if isinstance(servers, dict):
                    for server_name, server_config in servers.items():
                        if not isinstance(server_config, dict):
                            continue
                        if server_config.get("dangerouslyDisableLocalhost"):
                            issues.append(
                                f"mcp server '{server_name}' has "
                                "dangerouslyDisableLocalhost: true"
                            )
                        command = server_config.get("command", "")
                        if command in ("", "null", "undefined"):
                            issues.append(f"mcp server '{server_name}' has empty command")
        except (OSError, json.JSONDecodeError):
            issues.append(f"failed to parse MCP config: {mcp_path.name}")

    return issues


def scan_config_files(project_dir: Path) -> ConfigScanResult:
    issues: list[str] = []
    scanned: list[str] = []

    config_paths = [
        project_dir / ".claude-bridge-guard.json",
        project_dir / ".claude-bridge" / "config.json",
        project_dir / ".nulm.json",
        project_dir / "nulm.config.json",
    ]

    for config_path in config_paths:
        if not config_path.exists():
            continue
        scanned.append(str(config_path))
        try:
            content = config_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                issues.extend(check_approval_permissiveness(data))
                issues.extend(check_secret_leakage(data))
        except (OSError, json.JSONDecodeError):
            issues.append(f"failed to parse config file: {config_path.name}")

    mcp_issues = scan_mcp_config(project_dir)

    return ConfigScanResult(
        project_dir=project_dir,
        approval_issues=[i for i in issues if "auto_approve" in i or "approval_preset" in i],
        secret_leakage_issues=[
            i for i in issues if "API key" in i or "token" in i or "secret" in i
        ],
        mcp_config_issues=mcp_issues,
        config_files_scanned=scanned,
    )
