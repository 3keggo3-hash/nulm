"""AI-assisted shell command analysis."""

from dataclasses import dataclass


@dataclass
class CommandAnalysis:
    """Result of command analysis."""
    command: str
    risk_score: float
    risk_level: str
    reasons: list[str]
    warnings: list[str]
    suggested_safer_alternatives: list[str]
    is_blocked: bool


class CommandAnalyzer:
    """
    Analyzes shell commands for potential risks.

    Uses deterministic heuristics as the primary layer,
    with optional AI-based analysis for complex cases.
    """

    BLOCKED_COMMANDS = {
        "rm -rf /": "Completely destructive",
        "rm -rf /*": "Completely destructive",
        "> /dev/sda": "Disk wipe",
        "dd if=/dev/zero of=/dev/sda": "Disk wipe",
    }

    RISKY_PATTERNS = [
        (r"chmod\s+777", "Overly permissive file permissions", 4.0),
        (r"chmod\s+000", "Removes all permissions", 3.0),
        (r"sudo\s+su", "Privilege escalation", 3.0),
        (r"\|\s*sh", "Pipe to shell interpreter", 3.0),
        (r"curl.*\|.*bash", "Remote code execution risk", 4.0),
        (r"wget.*\|.*bash", "Remote code execution risk", 4.0),
        (r"rm\s+-rf\s+\.", "Recursive delete in current dir", 4.0),
        (r"git\s+reset\s+--hard", "Destroys uncommitted work", 3.0),
        (r"git\s+clean\s+-f", "Removes untracked files", 3.0),
    ]

    def analyze(self, command: str) -> CommandAnalysis:
        """Analyze a command and return risk assessment."""
        import re

        for blocked, reason in self.BLOCKED_COMMANDS.items():
            if blocked in command:
                return CommandAnalysis(
                    command=command,
                    risk_score=10.0,
                    risk_level="high",
                    reasons=[reason],
                    warnings=["DO NOT EXECUTE"],
                    suggested_safer_alternatives=[],
                    is_blocked=True,
                )

        reasons: list[str] = []
        warnings: list[str] = []
        risk_score = 0.0

        for pattern, description, score in self.RISKY_PATTERNS:
            if re.search(pattern, command):
                reasons.append(description)
                risk_score += score

        if re.search(r"[;&|`$]\s*\(", command):
            reasons.append("Command substitution detected")
            risk_score += 3.0

        if re.search(r"\x00", command):
            reasons.append("Null bytes detected (possible obfuscation)")
            risk_score += 4.0

        alternatives = self._generate_alternatives(command, reasons)

        if risk_score >= 7:
            risk_level = "high"
        elif risk_score >= 4:
            risk_level = "medium"
        else:
            risk_level = "low"

        return CommandAnalysis(
            command=command,
            risk_score=min(risk_score, 10.0),
            risk_level=risk_level,
            reasons=reasons,
            warnings=warnings,
            suggested_safer_alternatives=alternatives,
            is_blocked=risk_score >= 8,
        )

    def _generate_alternatives(self, command: str, risks: list[str]) -> list[str]:
        """Suggest safer alternatives based on detected risks."""
        alternatives = []

        if any("777" in r for r in risks):
            alternatives.append("chmod 644 (owner read/write, others read)")
            alternatives.append("chmod 755 (owner full, others read/execute)")

        if any("rm -rf" in r for r in risks):
            alternatives.append("rm -i (interactive mode)")
            alternatives.append("rm --interactive=always")

        if any("curl" in r or "wget" in r or "remote code execution" in r.lower() for r in risks):
            alternatives.append("Download to file first, then inspect")
            alternatives.append("Use --remote-name and inspect before execution")

        if any("git reset" in r for r in risks):
            alternatives.append("git stash instead (preserves work)")
            alternatives.append("git reset --soft (keeps staging)")

        return alternatives


def analyze_command(command: str) -> CommandAnalysis:
    """Convenience function."""
    return CommandAnalyzer().analyze(command)