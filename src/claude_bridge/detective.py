"""Bridge Detective - Error investigation workflow for Claude Bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from claude_bridge._detective_classifiers import classify_error, extract_error_location
from claude_bridge._detective_investigator import check_dependencies, run_diagnostics
from claude_bridge._detective_learner import find_similar_lesson
from claude_bridge._detective_locator import find_related_files, get_recent_changes
from claude_bridge._detective_report import format_detective_report
from claude_bridge.checkpoint import create_checkpoint
from claude_bridge.config import project_dir
from claude_bridge.memory import get_memory_store


class DetectiveState(Enum):
    """Workflow states for error investigation."""

    IDLE = "IDLE"
    CLASSIFY = "CLASSIFY"
    LOCATE = "LOCATE"
    INVESTIGATE = "INVESTIGATE"
    SOLVE = "SOLVE"
    LEARN = "LEARN"
    DONE = "DONE"


class ErrorType(Enum):
    """Supported error types for classification."""

    SYNTAX_ERROR = "SYNTAX_ERROR"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    SECURITY_ERROR = "SECURITY_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass
class ErrorContext:
    """Context information about an error."""

    error_message: str
    error_output: str
    command: str = ""
    file_path: str = ""
    line_number: str = ""
    error_type: str = "UNKNOWN"


@dataclass
class DetectiveReport:
    """Final report from the investigation workflow."""

    state: DetectiveState
    error_message: str
    error_type: str
    file_path: str
    line_number: str
    related_files: list[str] = field(default_factory=list)
    recent_changes: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    similar_lesson: dict[str, Any] | None = None
    suggested_fix: str = ""
    likelihood: str = "unknown"
    checkpoint_created: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "related_files": self.related_files,
            "recent_changes": self.recent_changes,
            "diagnostics": self.diagnostics,
            "similar_lesson": self.similar_lesson,
            "suggested_fix": self.suggested_fix,
            "likelihood": self.likelihood,
            "checkpoint_created": self.checkpoint_created,
        }


class BridgeDetective:
    """Automatic error investigation workflow.

    Flow: CLASSIFY -> LOCATE -> INVESTIGATE -> SOLVE -> LEARN
    """

    def __init__(self, error_output: str, command: str = "") -> None:
        self.error_output = error_output
        self.command = command
        self.state = DetectiveState.IDLE
        self._context: ErrorContext | None = None

    async def investigate(self) -> DetectiveReport:
        """Run the full investigation workflow."""
        self.state = DetectiveState.CLASSIFY
        self._context = self._classify()

        self.state = DetectiveState.LOCATE
        self._locate()

        self.state = DetectiveState.INVESTIGATE
        await self._investigate()

        self.state = DetectiveState.SOLVE
        self._solve()

        self.state = DetectiveState.LEARN
        self._learn()

        self.state = DetectiveState.DONE
        return self._build_report()

    def _classify(self) -> ErrorContext:
        error_type = classify_error(self.error_output)
        location = extract_error_location(self.error_output)
        return ErrorContext(
            error_message=self.error_output.split("\n")[-1] if self.error_output else "Unknown",
            error_output=self.error_output,
            command=self.command,
            file_path=location.get("file", ""),
            line_number=location.get("line", ""),
            error_type=error_type,
        )

    def _locate(self) -> None:
        if self._context is None:
            return
        pd = project_dir()
        ctx = self._context

        ctx.file_path = str((pd / ctx.file_path).resolve()) if ctx.file_path else ""

        if ctx.file_path:
            related = find_related_files(ctx.file_path, pd)
            if hasattr(self, "_related_files"):
                self._related_files = related
            if hasattr(self, "_recent_changes"):
                self._recent_changes = get_recent_changes(ctx.file_path, pd)

        if hasattr(self, "_related_files"):
            self._related_files = []
        if hasattr(self, "_recent_changes"):
            self._recent_changes = []

    async def _investigate(self) -> None:
        if self._context is None:
            return
        ctx = self._context
        pd = project_dir()

        if hasattr(self, "_diagnostics"):
            self._diagnostics = []
        if ctx.file_path:
            diag_result = await run_diagnostics(ctx.file_path, ctx.error_type, pd)
            if hasattr(self, "_diagnostics"):
                self._diagnostics = diag_result.get("diagnostics", [])

            deps_result = check_dependencies(ctx.file_path, pd)
            if hasattr(self, "_dep_check"):
                self._dep_check = deps_result

    def _solve(self) -> None:
        if self._context is None:
            return
        ctx = self._context

        if hasattr(self, "_suggested_fix"):
            self._suggested_fix = ""

        if ctx.error_type == "SYNTAX_ERROR":
            if "parenthesis" in ctx.error_output.lower():
                self._suggested_fix = "Check matching parentheses and brackets"
            elif "indent" in ctx.error_output.lower():
                self._suggested_fix = "Fix indentation (use spaces, not tabs)"
            else:
                self._suggested_fix = "Review syntax near the reported line"

        elif ctx.error_type == "RUNTIME_ERROR":
            if "ModuleNotFoundError" in ctx.error_output or "No module named" in ctx.error_output:
                import re
                m = re.search(r"No module named '([^']+)'", ctx.error_output)
                if m:
                    self._suggested_fix = f"pip install {m.group(1)}"
                else:
                    self._suggested_fix = "Install missing Python package"
            elif "ImportError" in ctx.error_output:
                self._suggested_fix = "Check import statements and module availability"
            else:
                self._suggested_fix = "Review stack trace for root cause"

        elif ctx.error_type == "SECURITY_ERROR":
            self._suggested_fix = "Review permissions and security policies"

        elif ctx.error_type == "NETWORK_ERROR":
            self._suggested_fix = "Check network connectivity and service availability"

        else:
            similar = find_similar_lesson(ctx.error_output)
            if similar:
                self._suggested_fix = similar.get("solution", "")
                if hasattr(self, "_similar_lesson"):
                    self._similar_lesson = similar

        if hasattr(self, "_checkpoint_created"):
            self._checkpoint_created = False
        cp = create_checkpoint(f"before-fix-{ctx.error_type}")
        if hasattr(self, "_checkpoint_created"):
            self._checkpoint_created = cp.get("ok", False)

    def _learn(self) -> None:
        if self._context is None:
            return
        ctx = self._context

        fix = getattr(self, "_suggested_fix", "")
        if fix and ctx.error_type != "UNKNOWN":
            memory = get_memory_store()
            memory.add_lesson(
                pattern=ctx.error_message[:100],
                solution=fix,
                project=project_dir().name,
            )

    def _build_report(self) -> DetectiveReport:
        if self._context is None:
            return DetectiveReport(
                state=self.state,
                error_message="Unknown error",
                error_type="UNKNOWN",
                file_path="",
                line_number="",
            )
        ctx = self._context

        related = getattr(self, "_related_files", [])
        recent = getattr(self, "_recent_changes", [])
        diagnostics = getattr(self, "_diagnostics", [])
        similar = getattr(self, "_similar_lesson", None)
        fix = getattr(self, "_suggested_fix", "")
        cp_created = getattr(self, "_checkpoint_created", False)

        likelihood = "high" if ctx.error_type != "UNKNOWN" else "low"
        if ctx.error_type == "SYNTAX_ERROR":
            likelihood = "high"
        elif ctx.error_type == "SECURITY_ERROR":
            likelihood = "critical"

        return DetectiveReport(
            state=self.state,
            error_message=ctx.error_message,
            error_type=ctx.error_type,
            file_path=ctx.file_path,
            line_number=ctx.line_number,
            related_files=related,
            recent_changes=recent,
            diagnostics=diagnostics,
            similar_lesson=similar,
            suggested_fix=fix,
            likelihood=likelihood,
            checkpoint_created=cp_created,
        )

    def format_report(self, report: DetectiveReport) -> str:
        """Return a human-readable detective report."""
        return format_detective_report(report.to_dict())
