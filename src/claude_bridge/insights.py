"""Project insight utilities: stats, TODO counter, recent files, git log, language detection, notes, diff."""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".rs": "Rust",
    ".go": "Go",
    ".rb": "Ruby",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".php": "PHP",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".ps1": "PowerShell",
    ".lua": "Lua",
    ".r": "R",
    ".jl": "Julia",
    ".zig": "Zig",
    ".nim": "Nim",
    ".dart": "Dart",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".gd": "GDScript",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".md": "Markdown",
    ".xml": "XML",
    ".graphql": "GraphQL",
    ".proto": "Protocol Buffers",
    ".tf": "HCL",
}

_TODO_PATTERNS = {
    "TODO": re.compile(r"\bTODO\b"),
    "FIXME": re.compile(r"\bFIXME\b"),
    "HACK": re.compile(r"\bHACK\b"),
    "XXX": re.compile(r"\bXXX\b"),
    "BUG": re.compile(r"\bBUG\b"),
    "OPTIMIZE": re.compile(r"\bOPTIMIZE(?:ME)?\b"),
    "DEPRECATED": re.compile(r"\bDEPRECATED\b"),
}
_LOCAL_MODULE_INDEX_CACHE: dict[tuple[str, int], set[str]] = {}

_IGNORED_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "venv",
    ".venv",
    "env",
    ".tox",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",
    ".claude-bridge",
    ".research",
    "benchmarks/baselines",
}

_IGNORED_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".svg",
    ".mp3",
    ".mp4",
    ".wav",
    ".avi",
    ".mov",
    ".zip",
    ".tar",
    ".gz",
    ".rar",
    ".7z",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".sqlite",
    ".db",
    ".lock",
    ".log",
}


def _filter_dirnames(dirpath: str, dirnames: list[str], root: Path) -> None:
    kept: list[str] = []
    rel_base = str(Path(dirpath).relative_to(root))
    for d in dirnames:
        full = f"{rel_base}/{d}" if rel_base != "." else d
        skip = False
        if d in _IGNORED_DIRS:
            skip = True
        else:
            for entry in _IGNORED_DIRS:
                if "/" in entry and (full == entry or full.startswith(entry + "/")):
                    skip = True
                    break
                if "*" in entry and (
                    fnmatch.fnmatch(full, entry) or fnmatch.fnmatch(full, "**/" + entry)
                ):
                    skip = True
                    break
        if not skip:
            kept.append(d)
    dirnames[:] = kept


def _should_skip(path: Path) -> bool:
    if path.is_symlink():  # FIX: skip symlinks
        return True
    parts = path.parts
    for part in parts:
        if part in _IGNORED_DIRS:
            return True
    path_str = "/".join(parts)
    for entry in _IGNORED_DIRS:
        if "/" in entry and path_str.startswith(entry + "/"):
            return True
        if "*" in entry and (
            fnmatch.fnmatch(path_str, "**/" + entry) or fnmatch.fnmatch(path_str, entry)
        ):
            return True
    if path.suffix.lower() in _IGNORED_EXTENSIONS:
        return True
    if path.name.startswith(".") and path.suffix == "":
        return True
    return False


def _count_lines_safe(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except (OSError, UnicodeDecodeError):
        return 0


def project_stats(root: Path, max_depth: int = 10) -> dict[str, Any]:
    root = root.resolve()
    total_files = 0
    total_lines = 0
    total_bytes = 0
    lang_lines: dict[str, int] = defaultdict(int)
    lang_files: dict[str, int] = defaultdict(int)
    extension_files: dict[str, int] = defaultdict(int)

    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth > max_depth:
            dirnames.clear()
            continue
        _filter_dirnames(dirpath, dirnames, root)

        for filename in filenames:
            file_path = Path(dirpath) / filename
            if _should_skip(file_path):
                continue

            try:
                file_size = file_path.stat().st_size
            except OSError:
                continue

            total_files += 1
            total_bytes += file_size
            ext = file_path.suffix.lower()
            extension_files[ext] += 1

            if ext in _LANGUAGE_MAP:
                lang = _LANGUAGE_MAP[ext]
                lines = _count_lines_safe(file_path)
                lang_lines[lang] += lines
                lang_files[lang] += 1
                total_lines += lines

    sorted_langs = sorted(lang_lines.items(), key=lambda x: x[1], reverse=True)
    sorted_extensions = sorted(extension_files.items(), key=lambda x: x[1], reverse=True)[:20]

    return {
        "root": str(root),
        "total_files": total_files,
        "total_code_lines": total_lines,
        "total_bytes": total_bytes,
        "total_bytes_human": _human_size(total_bytes),
        "languages": [
            {"language": lang, "lines": lines, "files": lang_files.get(lang, 0)}
            for lang, lines in sorted_langs
        ],
        "top_extensions": [
            {"extension": ext or "(none)", "files": count} for ext, count in sorted_extensions
        ],
    }


def todo_scan(root: Path, max_depth: int = 10) -> dict[str, Any]:
    root = root.resolve()
    findings: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)

    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth > max_depth:
            dirnames.clear()
            continue
        _filter_dirnames(dirpath, dirnames, root)

        for filename in filenames:
            file_path = Path(dirpath) / filename
            if _should_skip(file_path):
                continue
            if file_path.suffix.lower() not in _LANGUAGE_MAP and file_path.suffix.lower() not in {
                ".md",
                ".txt",
                ".rst",
                ".yaml",
                ".yml",
                ".toml",
            }:
                continue

            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, 1):
                        line_stripped = line.strip()
                        if not line_stripped or (
                            line_stripped.startswith("#")
                            and line_stripped.endswith("#")
                            and not any(p.search(line) for p in _TODO_PATTERNS.values())
                        ):
                            continue
                        for tag, pattern in _TODO_PATTERNS.items():
                            if pattern.search(line):
                                rel = str(file_path.relative_to(root))
                                findings.append(
                                    {
                                        "file": rel,
                                        "line": line_num,
                                        "tag": tag,
                                        "content": line_stripped[:120],
                                    }
                                )
                                counts[tag] += 1
            except OSError:
                continue

    findings.sort(key=lambda x: (x["tag"], x["file"], x["line"]))
    sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)

    return {
        "root": str(root),
        "total_markers": len(findings),
        "by_tag": [{"tag": tag, "count": count} for tag, count in sorted_counts],
        "findings": findings[:200],
        "truncated": len(findings) > 200,
    }


def recent_files(root: Path, limit: int = 15) -> dict[str, Any]:
    root = root.resolve()
    entries: list[dict[str, Any]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        _filter_dirnames(dirpath, dirnames, root)
        for filename in filenames:
            file_path = Path(dirpath) / filename
            if _should_skip(file_path):
                continue
            try:
                stat = file_path.stat()
                rel = str(file_path.relative_to(root))
                entries.append(
                    {
                        "file": rel,
                        "size": stat.st_size,
                        "size_human": _human_size(stat.st_size),
                        "modified": stat.st_mtime,
                        "extension": file_path.suffix.lower(),
                    }
                )
            except OSError:
                continue

    entries.sort(key=lambda x: x["modified"], reverse=True)
    return {
        "root": str(root),
        "total_files_scanned": len(entries),
        "recent": entries[:limit],
    }


def language_distribution(root: Path) -> dict[str, Any]:
    stats = project_stats(root, max_depth=10)
    langs = stats["languages"]
    total = sum(lang["lines"] for lang in langs) or 1

    return {
        "root": str(root),
        "languages": [
            {
                **lang,
                "percent": round(lang["lines"] / total * 100, 1),
            }
            for lang in langs
        ],
        "dominant": langs[0]["language"] if langs else None,
    }


def git_log_summary(root: Path, limit: int = 10) -> dict[str, Any]:
    root = root.resolve()
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={limit}", "--format=%H%x00%an%x00%ae%x00%s%x00%at", "--"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=root,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"error": "git not available or not a git repo", "root": str(root)}

    if result.returncode != 0:
        return {"error": "git command failed", "root": str(root)}

    commits: list[dict[str, Any]] = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\x00")
        if len(parts) < 5:
            continue
        commits.append(
            {
                "hash": parts[0][:12],
                "author": parts[1],
                "message": parts[3][:120],
                "timestamp": int(parts[4]) if parts[4].isdigit() else 0,
            }
        )

    try:
        blame_result = subprocess.run(
            ["git", "shortlog", "-sn", "--all", "--"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=root,
            timeout=10,
        )
        contributors: list[dict[str, Any]] = []
        if blame_result.returncode == 0:
            for line in blame_result.stdout.strip().splitlines():
                match = re.match(r"^\s*(\d+)\s+(.+)$", line)
                if match:
                    contributors.append(
                        {
                            "commits": int(match.group(1)),
                            "author": match.group(2).strip(),
                        }
                    )
    except (OSError, subprocess.TimeoutExpired):
        contributors = []

    return {
        "root": str(root),
        "recent_commits": commits,
        "total_shown": len(commits),
        "contributors": contributors[:10],
    }


def git_diff_summary(root: Path, target: str = "HEAD") -> dict[str, Any]:
    root = root.resolve()
    if not re.match(r"^[a-zA-Z0-9/_.\-]{1,200}$", target):  # FIX: sanitize target param
        return {"error": "invalid target parameter", "root": str(root)}
    try:
        result = subprocess.run(
            ["git", "diff", "--numstat", target, "--"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=root,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"error": "git not available", "root": str(root)}

    if result.returncode != 0:
        return {"error": "git diff failed", "root": str(root)}

    raw = result.stdout.strip()
    if not raw:
        return {"root": str(root), "changed": False, "message": "No changes"}

    files: list[dict[str, Any]] = []
    total_insertions = 0
    total_deletions = 0

    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        ins_str, del_str = parts[0], parts[1]
        if not ins_str or not del_str or ins_str == "-" or del_str == "-":
            continue
        try:
            insertions = int(ins_str)
            deletions = int(del_str)
        except ValueError:
            continue
        filename = parts[2].strip()
        changed_lines = insertions + deletions
        total_insertions += insertions
        total_deletions += deletions
        files.append(
            {
                "file": filename,
                "changed_lines": changed_lines,
                "insertions": insertions,
                "deletions": deletions,
            }
        )

    return {
        "root": str(root),
        "target": target,
        "changed": True,
        "files": files,
        "total_files": len(files),
        "total_insertions": total_insertions,
        "total_deletions": total_deletions,
    }


def dependency_map(root: Path, max_depth: int = 8) -> dict[str, Any]:
    root = root.resolve()
    graph: dict[str, list[str]] = defaultdict(list)
    local_modules = _build_local_module_index(root, max_depth=max_depth)

    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth > max_depth:
            dirnames.clear()
            continue
        _filter_dirnames(dirpath, dirnames, root)

        for filename in filenames:
            file_path = Path(dirpath) / filename
            if file_path.suffix != ".py":
                continue
            if _should_skip(file_path):
                continue
            try:
                tree = ast.parse(file_path.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError):
                continue

            rel = str(file_path.relative_to(root))
            imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        imports.add(top)
                elif isinstance(node, ast.ImportFrom):
                    if node.level > 0:
                        continue
                    if node.module:
                        top = node.module.split(".")[0]
                        imports.add(top)
                    elif node.names:
                        imports.add(node.names[0].name.split(".")[0])

            for imp in imports:
                if imp in local_modules or imp.startswith("claude_bridge"):
                    graph[rel].append(imp)

    nodes = len(graph)
    edges = sum(len(v) for v in graph.values())
    most_connected = sorted(graph.items(), key=lambda x: len(x[1]), reverse=True)[:10]

    return {
        "root": str(root),
        "nodes": nodes,
        "edges": edges,
        "most_connected": [{"file": f, "imports": deps} for f, deps in most_connected],
    }


def _build_local_module_index(root: Path, max_depth: int = 8) -> set[str]:
    cache_key = (str(root.resolve()), max_depth)
    cached = _LOCAL_MODULE_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return set(cached)
    modules: set[str] = set()
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).relative_to(root).parts)
            if depth > max_depth:
                dirnames.clear()
                continue
            _filter_dirnames(dirpath, dirnames, root)
            current_dir = Path(dirpath)
            if (current_dir / "__init__.py").exists():
                modules.add(current_dir.name)
            for filename in filenames:
                if filename.endswith(".py"):
                    modules.add(Path(filename).stem)
    except OSError:
        return set()
    _LOCAL_MODULE_INDEX_CACHE[cache_key] = set(modules)
    return modules


def _is_local_module(name: str, root: Path, max_depth: int = 8) -> bool:
    if name.startswith("claude_bridge"):
        return True
    try:
        return name in _build_local_module_index(root, max_depth=max_depth)
    except OSError:
        return False


def duplicate_code_scan(root: Path, min_lines: int = 4, max_depth: int = 6) -> dict[str, Any]:
    root = root.resolve()
    blocks: dict[str, list[tuple[str, int]]] = defaultdict(list)

    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth > max_depth:
            dirnames.clear()
            continue
        _filter_dirnames(dirpath, dirnames, root)

        for filename in filenames:
            file_path = Path(dirpath) / filename
            if file_path.suffix not in {".py", ".js", ".ts", ".rs", ".go"}:
                continue
            if _should_skip(file_path):
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            lines = content.splitlines()
            for i in range(len(lines) - min_lines + 1):
                block = "\n".join(lines[i : i + min_lines]).strip()
                if len(block) < min_lines * 5:
                    continue
                if re.match(r"^(import |from |#)", block):
                    continue
                rel = str(file_path.relative_to(root))
                key = block[:200]
                if key not in blocks or (rel, i + 1) != blocks[key][-1]:
                    blocks[key].append((rel, i + 1))

    duplicates: list[dict[str, Any]] = []
    for block, locations in blocks.items():
        if len(locations) >= 2:
            loc_strings = [f"{r}:{ln}" for r, ln in locations]
            duplicates.append(
                {
                    "block_preview": block[:80],
                    "occurrences": len(locations),
                    "locations": loc_strings,
                }
            )

    duplicates.sort(key=lambda x: x["occurrences"], reverse=True)
    return {
        "root": str(root),
        "total_blocks_scanned": len(blocks),
        "duplicates_found": len(duplicates),
        "top_duplicates": duplicates[:20],
        "truncated": len(duplicates) > 20,
    }


_NOTES_FILE = ".claude-bridge-notes.json"


def _notes_path(root: Path) -> Path:
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
    override = os.environ.get("CLAUDE_BRIDGE_NOTES_DIR", "").strip()
    if override:
        base_dir = Path(override).expanduser().resolve()
    else:
        xdg_state_home = os.environ.get("XDG_STATE_HOME", "").strip()
        if xdg_state_home:
            base_dir = (Path(xdg_state_home).expanduser() / "claude-bridge" / "notes").resolve()
        else:
            base_dir = (Path.home() / ".claude-bridge" / "notes").resolve()
    return base_dir / f"{digest}.json"


def save_note(root: Path, note: str) -> dict[str, Any]:
    notes_path = _notes_path(root)
    notes: list[dict[str, Any]] = []
    if notes_path.exists():
        try:
            notes = json.loads(notes_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            notes = []

    entry = {
        "note": note,
        "created_at": time.time(),
    }
    notes.append(entry)

    if len(notes) > 100:
        notes = notes[-100:]

    try:
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(notes_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(notes, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, str(notes_path))
        finally:
            # Clean up the temp file if it still exists (os.replace removes
            # it on success, so this is a no-op in the happy path).
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except OSError as exc:
        return {"ok": False, "error": str(exc)}

    return {"ok": True, "saved": True, "total_notes": len(notes)}


def read_notes(root: Path, limit: int = 20) -> dict[str, Any]:
    notes_path = _notes_path(root)
    if not notes_path.exists():
        return {"notes": [], "total": 0}

    try:
        import json as _json

        notes = _json.loads(notes_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"notes": [], "total": 0}

    return {
        "notes": notes[-limit:],
        "total": len(notes),
    }


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
