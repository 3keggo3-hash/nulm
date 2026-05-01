"""Indexing and file-search helpers for Claude Bridge."""

from __future__ import annotations

import ast
import fnmatch
import importlib
import json
import os
import re
import threading
import time
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from pathspec import PathSpec

from claude_bridge.relevance import _tokenize_names, _tokenize_text

_INDEX_CACHE: dict[str, dict[str, Any]] = {}
_INDEX_CACHE_LOCK = threading.RLock()
_MAX_INDEX_CACHE_ENTRIES = 32
_MAX_SEARCH_FILE_BYTES = 512 * 1024
_BINARY_SNIFF_BYTES = 512
_DISK_CACHE_VERSION = 1
_MAX_DISK_CACHE_FILES = 32
_MAX_DISK_CACHE_AGE_SECONDS = 7 * 24 * 60 * 60
_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
}
_INDEXABLE_SUFFIXES = {
    ".py",
    ".gd",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".cs",
    ".rb",
    ".php",
}

_JS_TS_FUNCTION_PATTERNS = (
    re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE),
    re.compile(r"^\s*async\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE),
    re.compile(
        r"^\s*(?:export\s+)?async\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        re.MULTILINE,
    ),
    re.compile(
        r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
        re.MULTILINE,
    ),
    re.compile(
        r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?[A-Za-z_][A-Za-z0-9_]*\s*=>",
        re.MULTILINE,
    ),
    re.compile(
        r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*<",
        re.MULTILINE,
    ),
)
_JS_TS_CLASS_PATTERN = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    re.MULTILINE,
)
_JS_TS_IMPORT_PATTERNS = (
    re.compile(r'^\s*import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]', re.MULTILINE),
    re.compile(r'^\s*import\s+[\'"]([^\'"]+)[\'"]', re.MULTILINE),
    re.compile(r'require\(\s*[\'"]([^\'"]+)[\'"]\s*\)'),
)
_RUST_FUNCTION_PATTERN = re.compile(
    r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    re.MULTILINE,
)
_RUST_STRUCT_PATTERN = re.compile(
    r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    re.MULTILINE,
)
_RUST_IMPORT_PATTERN = re.compile(
    r"^\s*use\s+([A-Za-z_][A-Za-z0-9_:]*)",
    re.MULTILINE,
)
_GO_FUNCTION_PATTERN = re.compile(
    r"^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)
_GO_STRUCT_PATTERN = re.compile(
    r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s+struct\b",
    re.MULTILINE,
)
_GO_IMPORT_BLOCK_PATTERN = re.compile(r"import\s*\((.*?)\)", re.DOTALL)
_GO_IMPORT_LINE_PATTERN = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*\s+)?\"([^\"]+)\"", re.MULTILINE
)
_GO_SINGLE_IMPORT_PATTERN = re.compile(
    r"^\s*import\s+(?:[A-Za-z_][A-Za-z0-9_]*\s+)?\"([^\"]+)\"", re.MULTILINE
)
_JAVA_KOTLIN_CLASS_PATTERN = re.compile(
    r"^\s*(?:public\s+|private\s+|protected\s+|internal\s+|open\s+|final\s+|abstract\s+|sealed\s+)*"
    r"(?:class|interface|enum|object)\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    re.MULTILINE,
)
_JAVA_FUNCTION_PATTERN = re.compile(
    r"^\s*(?:public|private|protected|static|final|synchronized|abstract|native|\s)+"
    r"[\w<>\[\], ?]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)
_KOTLIN_FUNCTION_PATTERN = re.compile(
    r"^\s*(?:public|private|protected|internal|suspend|inline|open|override|tailrec|\s)*fun\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:<[^>]+>)?\s*\(",
    re.MULTILINE,
)
_JAVA_KOTLIN_IMPORT_PATTERN = re.compile(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_.*]*)", re.MULTILINE)
_CS_CLASS_PATTERN = re.compile(
    r"^\s*(?:public|private|protected|internal|sealed|abstract|static|partial|\s)*(?:class|interface|enum|struct)\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    re.MULTILINE,
)
_CS_FUNCTION_PATTERN = re.compile(
    r"^\s*(?:public|private|protected|internal|static|virtual|override|async|sealed|partial|\s)+[\w<>\[\], ?]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)
_CS_IMPORT_PATTERN = re.compile(r"^\s*using\s+([A-Za-z_][A-Za-z0-9_.]*)\s*;", re.MULTILINE)
_RUBY_CLASS_PATTERN = re.compile(r"^\s*(?:class|module)\s+([A-Za-z_][A-Za-z0-9_:]*)", re.MULTILINE)
_RUBY_FUNCTION_PATTERN = re.compile(
    r"^\s*def\s+(?:self\.)?([A-Za-z_][A-Za-z0-9_!?=]*)", re.MULTILINE
)
_RUBY_IMPORT_PATTERN = re.compile(r"^\s*require(?:_relative)?\s+[\"']([^\"']+)[\"']", re.MULTILINE)
_PHP_CLASS_PATTERN = re.compile(
    r"^\s*(?:final\s+|abstract\s+)?(?:class|interface|trait)\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    re.MULTILINE,
)
_PHP_FUNCTION_PATTERN = re.compile(r"function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
_PHP_IMPORT_PATTERN = re.compile(r"^\s*use\s+([A-Za-z_\\][A-Za-z0-9_\\]*)\s*;", re.MULTILINE)

Extractor = Callable[[Path, str], dict[str, Any]]
ExtractorWithBackend = Callable[[Path, str], tuple[dict[str, Any], str]]


def _normalize_js_ts_import(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        return ""
    if cleaned.startswith("./") or cleaned.startswith("../"):
        parts = [part for part in cleaned.split("/") if part not in {".", "..", ""}]
        return parts[0] if parts else cleaned
    if cleaned.startswith("@"):
        scoped_parts = [part for part in cleaned.split("/") if part]
        if len(scoped_parts) >= 2:
            return "/".join(scoped_parts[:2])
    return cleaned.split("/")[0]


def _normalize_rust_import(raw: str) -> str:
    return raw.split("::")[0].strip()


def _normalize_go_import(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        return ""
    return cleaned.split("/")[-1]


def _normalize_dotted_import(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        return ""
    return cleaned.split(".")[0]


def _extract_go_imports(source: str) -> list[str]:
    imports: set[str] = set()
    for block in _GO_IMPORT_BLOCK_PATTERN.finditer(source):
        for match in _GO_IMPORT_LINE_PATTERN.finditer(block.group(1)):
            normalized = _normalize_go_import(match.group(1))
            if normalized:
                imports.add(normalized)
    for match in _GO_SINGLE_IMPORT_PATTERN.finditer(source):
        normalized = _normalize_go_import(match.group(1))
        if normalized:
            imports.add(normalized)
    return sorted(imports)


def _extract_python_symbols(_: Path, source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    return {
        "functions": sorted(
            {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
        ),
        "classes": sorted({node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}),
        "imports": sorted(
            {
                alias.name.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }
            | {
                (node.module or "").split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            }
        ),
        "language": "python",
    }


def _extract_js_ts_symbols(file: Path, source: str) -> dict[str, Any]:
    functions = sorted(
        {
            match.group(1)
            for pattern in _JS_TS_FUNCTION_PATTERNS
            for match in pattern.finditer(source)
        }
    )
    classes = sorted({match.group(1) for match in _JS_TS_CLASS_PATTERN.finditer(source)})
    imports = sorted(
        {
            normalized
            for pattern in _JS_TS_IMPORT_PATTERNS
            for match in pattern.finditer(source)
            for raw in [match.group(1).strip()]
            for normalized in [_normalize_js_ts_import(raw)]
            if normalized
        }
    )
    return {
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "language": "typescript" if file.suffix in {".ts", ".tsx"} else "javascript",
    }


def _extract_rust_symbols(_: Path, source: str) -> dict[str, Any]:
    functions = sorted({match.group(1) for match in _RUST_FUNCTION_PATTERN.finditer(source)})
    classes = sorted({match.group(1) for match in _RUST_STRUCT_PATTERN.finditer(source)})
    imports = sorted(
        {
            normalized
            for match in _RUST_IMPORT_PATTERN.finditer(source)
            for normalized in [_normalize_rust_import(match.group(1))]
            if normalized
        }
    )
    return {"functions": functions, "classes": classes, "imports": imports, "language": "rust"}


def _extract_go_symbols(_: Path, source: str) -> dict[str, Any]:
    functions = sorted({match.group(1) for match in _GO_FUNCTION_PATTERN.finditer(source)})
    classes = sorted({match.group(1) for match in _GO_STRUCT_PATTERN.finditer(source)})
    return {
        "functions": functions,
        "classes": classes,
        "imports": _extract_go_imports(source),
        "language": "go",
    }


def _extract_java_symbols(_: Path, source: str) -> dict[str, Any]:
    functions = sorted({match.group(1) for match in _JAVA_FUNCTION_PATTERN.finditer(source)})
    classes = sorted({match.group(1) for match in _JAVA_KOTLIN_CLASS_PATTERN.finditer(source)})
    imports = sorted(
        {
            _normalize_dotted_import(match.group(1))
            for match in _JAVA_KOTLIN_IMPORT_PATTERN.finditer(source)
        }
    )
    return {"functions": functions, "classes": classes, "imports": imports, "language": "java"}


def _extract_kotlin_symbols(_: Path, source: str) -> dict[str, Any]:
    functions = sorted({match.group(1) for match in _KOTLIN_FUNCTION_PATTERN.finditer(source)})
    classes = sorted({match.group(1) for match in _JAVA_KOTLIN_CLASS_PATTERN.finditer(source)})
    imports = sorted(
        {
            _normalize_dotted_import(match.group(1))
            for match in _JAVA_KOTLIN_IMPORT_PATTERN.finditer(source)
        }
    )
    return {"functions": functions, "classes": classes, "imports": imports, "language": "kotlin"}


def _extract_csharp_symbols(_: Path, source: str) -> dict[str, Any]:
    functions = sorted({match.group(1) for match in _CS_FUNCTION_PATTERN.finditer(source)})
    classes = sorted({match.group(1) for match in _CS_CLASS_PATTERN.finditer(source)})
    imports = sorted(
        {match.group(1).split(".")[0] for match in _CS_IMPORT_PATTERN.finditer(source)}
    )
    return {"functions": functions, "classes": classes, "imports": imports, "language": "csharp"}


def _extract_ruby_symbols(_: Path, source: str) -> dict[str, Any]:
    functions = sorted({match.group(1) for match in _RUBY_FUNCTION_PATTERN.finditer(source)})
    classes = sorted(
        {match.group(1).split("::")[-1] for match in _RUBY_CLASS_PATTERN.finditer(source)}
    )
    imports = sorted(
        {_normalize_js_ts_import(match.group(1)) for match in _RUBY_IMPORT_PATTERN.finditer(source)}
    )
    return {"functions": functions, "classes": classes, "imports": imports, "language": "ruby"}


def _extract_php_symbols(_: Path, source: str) -> dict[str, Any]:
    functions = sorted({match.group(1) for match in _PHP_FUNCTION_PATTERN.finditer(source)})
    classes = sorted({match.group(1) for match in _PHP_CLASS_PATTERN.finditer(source)})
    imports = sorted(
        {match.group(1).split("\\")[0] for match in _PHP_IMPORT_PATTERN.finditer(source)}
    )
    return {"functions": functions, "classes": classes, "imports": imports, "language": "php"}


def _extract_gdscript_symbols(_: Path, source: str) -> dict[str, Any]:
    functions: list[str] = []
    classes: list[str] = []
    imports: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("func "):
            fn_name = stripped[5:].split("(")[0].strip()
            if fn_name:
                functions.append(fn_name)
        elif stripped.startswith("class_name "):
            class_name = stripped[len("class_name ") :].strip()
            if class_name:
                classes.append(class_name)
        elif stripped.startswith("extends "):
            imports.append(stripped[len("extends ") :].strip().split(".")[0])
        elif stripped.startswith("const ") and "preload(" in stripped:
            imports.append("preload")
    return {
        "functions": sorted(set(functions)),
        "classes": sorted(set(classes)),
        "imports": sorted(set(imports)),
        "language": "gdscript",
    }


_EXTRACTORS_BY_SUFFIX: dict[str, Extractor] = {
    ".py": _extract_python_symbols,
    ".js": _extract_js_ts_symbols,
    ".jsx": _extract_js_ts_symbols,
    ".ts": _extract_js_ts_symbols,
    ".tsx": _extract_js_ts_symbols,
    ".rs": _extract_rust_symbols,
    ".go": _extract_go_symbols,
    ".java": _extract_java_symbols,
    ".kt": _extract_kotlin_symbols,
    ".cs": _extract_csharp_symbols,
    ".rb": _extract_ruby_symbols,
    ".php": _extract_php_symbols,
    ".gd": _extract_gdscript_symbols,
}
_TREE_SITTER_LANGUAGE_NAMES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "c_sharp",
    ".rb": "ruby",
    ".php": "php",
}
_DEFAULT_TREE_SITTER_RULES = {
    "functions": {
        "function_definition",
        "method_definition",
        "function_declaration",
        "method_declaration",
        "func_literal",
        "anonymous_function",
    },
    "classes": {
        "class_definition",
        "class_declaration",
        "interface_declaration",
        "struct_item",
        "struct_declaration",
        "enum_declaration",
        "trait_declaration",
        "object_declaration",
        "module",
    },
    "imports": {
        "import_statement",
        "import_declaration",
        "use_declaration",
        "using_directive",
        "require_call",
    },
    "function_fields": ("name", "identifier"),
    "class_fields": ("name", "identifier"),
    "import_fields": ("source", "path", "module", "value", "name"),
}
_TREE_SITTER_RULES_BY_LANGUAGE = {
    "javascript": {
        **_DEFAULT_TREE_SITTER_RULES,
        "functions": {
            "function_declaration",
            "generator_function_declaration",
            "method_definition",
            "lexical_declaration",
            "variable_declarator",
        },
        "classes": {"class_declaration"},
        "imports": {"import_statement", "call_expression"},
        "function_fields": ("name", "property", "identifier"),
        "class_fields": ("name", "identifier"),
        "import_fields": ("source", "arguments", "argument"),
    },
    "typescript": {
        **_DEFAULT_TREE_SITTER_RULES,
        "functions": {
            "function_declaration",
            "method_definition",
            "generator_function_declaration",
            "abstract_method_signature",
        },
        "classes": {
            "class_declaration",
            "interface_declaration",
            "abstract_class_declaration",
            "type_alias_declaration",
        },
        "imports": {"import_statement", "import_require_clause"},
        "function_fields": ("name", "property", "identifier"),
        "class_fields": ("name", "identifier", "type"),
        "import_fields": ("source", "argument", "path"),
    },
    "tsx": {
        **_DEFAULT_TREE_SITTER_RULES,
        "functions": {
            "function_declaration",
            "method_definition",
            "generator_function_declaration",
            "abstract_method_signature",
            "lexical_declaration",
            "variable_declarator",
        },
        "classes": {
            "class_declaration",
            "interface_declaration",
            "abstract_class_declaration",
            "type_alias_declaration",
        },
        "imports": {"import_statement", "import_require_clause"},
        "function_fields": ("name", "property", "identifier"),
        "class_fields": ("name", "identifier", "type"),
        "import_fields": ("source", "argument", "path"),
    },
    "java": {
        **_DEFAULT_TREE_SITTER_RULES,
        "functions": {"method_declaration", "constructor_declaration"},
        "classes": {"class_declaration", "interface_declaration", "enum_declaration"},
        "imports": {"import_declaration"},
        "function_fields": ("name", "identifier"),
        "class_fields": ("name", "identifier"),
        "import_fields": ("path", "name"),
    },
    "kotlin": {
        **_DEFAULT_TREE_SITTER_RULES,
        "functions": {"function_declaration", "getter", "setter", "secondary_constructor"},
        "classes": {
            "class_declaration",
            "object_declaration",
            "interface_declaration",
            "type_alias",
        },
        "imports": {"import_header"},
        "function_fields": ("name", "identifier"),
        "class_fields": ("name", "identifier", "type"),
        "import_fields": ("path", "identifier"),
    },
    "c_sharp": {
        **_DEFAULT_TREE_SITTER_RULES,
        "functions": {"method_declaration", "constructor_declaration", "local_function_statement"},
        "classes": {
            "class_declaration",
            "interface_declaration",
            "struct_declaration",
            "enum_declaration",
        },
        "imports": {"using_directive"},
        "function_fields": ("name", "identifier"),
        "class_fields": ("name", "identifier"),
        "import_fields": ("name", "path"),
    },
    "rust": {
        **_DEFAULT_TREE_SITTER_RULES,
        "functions": {"function_item"},
        "classes": {"struct_item", "enum_item", "trait_item", "impl_item"},
        "imports": {"use_declaration"},
        "function_fields": ("name", "identifier"),
        "class_fields": ("name", "type", "identifier"),
        "import_fields": ("argument", "path"),
    },
    "go": {
        **_DEFAULT_TREE_SITTER_RULES,
        "functions": {"function_declaration", "method_declaration"},
        "classes": {"type_declaration", "type_spec", "interface_type"},
        "imports": {"import_declaration", "import_spec"},
        "function_fields": ("name", "identifier"),
        "class_fields": ("name", "type", "identifier"),
        "import_fields": ("path", "name"),
    },
    "ruby": {
        **_DEFAULT_TREE_SITTER_RULES,
        "functions": {"method", "singleton_method"},
        "classes": {"class", "module"},
        "imports": {"call"},
        "function_fields": ("name", "identifier"),
        "class_fields": ("name", "constant"),
        "import_fields": ("method", "arguments", "argument"),
    },
    "php": {
        **_DEFAULT_TREE_SITTER_RULES,
        "functions": {"function_definition", "method_declaration"},
        "classes": {"class_declaration", "interface_declaration", "trait_declaration"},
        "imports": {"namespace_use_declaration", "require_expression", "include_expression"},
        "function_fields": ("name", "identifier"),
        "class_fields": ("name", "identifier"),
        "import_fields": ("clause", "path", "argument"),
    },
}
_TREE_SITTER_GET_PARSER_CANDIDATES = (
    ("tree_sitter_languages", "get_parser"),
    ("tree_sitter_language_pack", "get_parser"),
)


def clear_index_cache() -> None:
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE.clear()


def get_cached_index(cache_key: str) -> dict[str, Any] | None:
    with _INDEX_CACHE_LOCK:
        return _INDEX_CACHE.get(cache_key)


def set_cached_index(cache_key: str, snapshot: tuple[Any, ...], payload: dict[str, Any]) -> None:
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE[cache_key] = {"snapshot": snapshot, "payload": payload}
        while len(_INDEX_CACHE) > _MAX_INDEX_CACHE_ENTRIES:
            oldest_key = next(iter(_INDEX_CACHE))
            _INDEX_CACHE.pop(oldest_key, None)


def public_index_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in payload.items() if not key.startswith("_")},
        "files": [
            {
                key: value
                for key, value in item.items()
                if key
                not in {
                    "content",
                    "path_tokens",
                    "function_tokens",
                    "class_tokens",
                    "import_tokens",
                    "content_tokens",
                }
            }
            for item in payload["files"]
        ],
    }


def _cache_dir() -> Path:
    raw = os.environ.get("CLAUDE_BRIDGE_CACHE_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg:
        return (Path(xdg).expanduser() / "claude-bridge").resolve()
    return (Path.home() / ".cache" / "claude-bridge").resolve()


def _disk_cache_path(target: Path) -> Path:
    digest = sha256(str(target).encode("utf-8")).hexdigest()
    return _cache_dir() / f"index-{digest}.json"


def _load_disk_cache(target: Path) -> dict[str, Any] | None:
    cache_path = _disk_cache_path(target)
    if not cache_path.exists():
        return None
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("version") != _DISK_CACHE_VERSION:
        return None
    payload = raw.get("payload")
    return payload if isinstance(payload, dict) else None


def _write_disk_cache(target: Path, payload: dict[str, Any]) -> None:
    cache_path = _disk_cache_path(target)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"version": _DISK_CACHE_VERSION, "payload": payload}, ensure_ascii=False),
        encoding="utf-8",
    )
    _prune_disk_cache(cache_path.parent)


def _prune_disk_cache(cache_dir: Path) -> None:
    try:
        entries = sorted(
            [path for path in cache_dir.glob("index-*.json") if path.is_file()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    now = time.time()
    for path in entries:
        try:
            age_seconds = max(0.0, now - path.stat().st_mtime)
        except OSError:
            continue
        if age_seconds > _MAX_DISK_CACHE_AGE_SECONDS:
            try:
                path.unlink()
            except OSError:
                pass
    if len(entries) <= _MAX_DISK_CACHE_FILES:
        return
    for path in entries[_MAX_DISK_CACHE_FILES:]:
        try:
            path.unlink()
        except OSError:
            pass


def _file_signature(file: Path, root: Path) -> dict[str, Any]:
    stat = file.stat()
    return {
        "relative_path": file.relative_to(root).as_posix(),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def _token_metadata_for_index_entry(
    *,
    relative_path: str,
    functions: list[str],
    classes: list[str],
    imports: list[str],
    content: str,
) -> dict[str, list[str]]:
    return {
        "path_tokens": sorted(_tokenize_text(relative_path)),
        "function_tokens": sorted(_tokenize_names(functions)),
        "class_tokens": sorted(_tokenize_names(classes)),
        "import_tokens": sorted(_tokenize_names(imports)),
        "content_tokens": sorted(_tokenize_text(content)),
    }


def _snapshot_key(snapshot: tuple[Any, ...]) -> str:
    return sha256(repr(snapshot).encode("utf-8")).hexdigest()


def _file_cache_from_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = payload.get("_file_cache")
    return raw if isinstance(raw, dict) else {}


def read_gitignore_patterns(project_root: Path) -> list[str]:
    gitignore = project_root / ".gitignore"
    if not gitignore.exists():
        return []

    patterns: list[str] = []
    try:
        lines = gitignore.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


def build_gitignore_spec(patterns: list[str]) -> PathSpec | None:
    if not patterns:
        return None
    return PathSpec.from_lines("gitignore", patterns)


def is_ignored(
    path: Path,
    root: Path,
    project_root: Path,
    patterns: list[str],
    spec: PathSpec | None,
) -> bool:
    if not patterns:
        return False

    relative_to_project = path.relative_to(project_root).as_posix()
    relative_to_root = path.relative_to(root).as_posix()
    basename = path.name

    if spec is not None:
        return spec.match_file(relative_to_project) or spec.match_file(relative_to_root)

    for pattern in patterns:
        normalized = pattern.lstrip("./")
        if (
            fnmatch.fnmatch(relative_to_project, normalized)
            or fnmatch.fnmatch(relative_to_root, normalized)
            or fnmatch.fnmatch(basename, normalized)
        ):
            return True
    return False


def iter_source_files(
    root: Path,
    project_root: Path,
    *,
    max_depth: int = 12,
    is_within_root: Callable[[Path, Path], bool],
) -> list[Path]:
    patterns = read_gitignore_patterns(project_root)
    spec = build_gitignore_spec(patterns)
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth > max_depth:
            dirnames.clear()
            continue
        for filename in filenames:
            file_path = Path(dirpath) / filename
            resolved_path = file_path.resolve()
            if not is_within_root(resolved_path, project_root):
                continue
            if any(part in _SKIP_DIRS for part in file_path.parts):
                continue
            if file_path.suffix not in _INDEXABLE_SUFFIXES:
                continue
            if is_ignored(file_path, root, project_root, patterns, spec):
                continue
            files.append(file_path)
    return sorted(files)


def is_likely_binary(file_path: Path, n: int = _BINARY_SNIFF_BYTES) -> bool:
    """Check if a file is likely binary by reading the first *n* bytes.

    Only a null byte in the initial window is treated as a binary signal.
    This avoids reading the entire file just for the binary check.
    """
    try:
        with open(file_path, "rb") as fh:
            head = fh.read(n)
    except OSError:
        return True
    if not head:
        return False
    return b"\x00" in head


def iter_searchable_files(
    root: Path,
    project_root: Path,
    *,
    max_depth: int = 12,
    is_within_root: Callable[[Path, Path], bool],
    is_binary_bytes: Callable[[bytes], bool],
    include_glob: str | None = None,
) -> list[Path]:
    patterns = read_gitignore_patterns(project_root)
    spec = build_gitignore_spec(patterns)
    files: list[Path] = []
    if not root.is_dir():
        if root.is_file():
            try:
                if is_likely_binary(root):
                    return []
                raw = root.read_bytes()
            except OSError:
                return []
            if len(raw) <= _MAX_SEARCH_FILE_BYTES and not is_binary_bytes(raw):
                if not is_ignored(root, project_root, project_root, patterns, spec):
                    files.append(root)
        return sorted(files)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth > max_depth:
            dirnames.clear()
            continue
        for filename in filenames:
            file_path = Path(dirpath) / filename
            resolved_path = file_path.resolve()
            if not is_within_root(resolved_path, project_root):
                continue
            if any(part in _SKIP_DIRS for part in file_path.parts):
                continue
            if include_glob and not fnmatch.fnmatch(file_path.name, include_glob):
                continue
            if is_ignored(file_path, root, project_root, patterns, spec):
                continue
            try:
                if is_likely_binary(file_path):
                    continue
                raw = file_path.read_bytes()
            except OSError:
                continue
            if len(raw) > _MAX_SEARCH_FILE_BYTES or is_binary_bytes(raw):
                continue
            files.append(file_path)
    return sorted(files)


def extract_symbols(file: Path, source: str) -> dict[str, Any]:
    return _EXTRACTORS_BY_SUFFIX[file.suffix](file, source)


def _load_tree_sitter_parser(language_name: str) -> Any | None:
    for module_name, attr_name in _TREE_SITTER_GET_PARSER_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        get_parser = getattr(module, attr_name, None)
        if get_parser is None:
            continue
        try:
            return get_parser(language_name)
        except Exception:
            continue
    return None


def _iter_tree_sitter_nodes(node: Any) -> list[Any]:
    nodes = [node]
    children = getattr(node, "children", None) or []
    for child in children:
        nodes.extend(_iter_tree_sitter_nodes(child))
    return nodes


def _tree_sitter_node_text(source_bytes: bytes, node: Any) -> str:
    inline_text = getattr(node, "_text", None)
    if isinstance(inline_text, str):
        return inline_text
    start = getattr(node, "start_byte", None)
    end = getattr(node, "end_byte", None)
    if start is None or end is None:
        return ""
    try:
        return source_bytes[start:end].decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _tree_sitter_identifier_text(
    source_bytes: bytes, node: Any, field_names: tuple[str, ...]
) -> str:
    child_by_field_name = getattr(node, "child_by_field_name", None)
    if callable(child_by_field_name):
        for field_name in field_names:
            child = child_by_field_name(field_name)
            if child is not None:
                text = _tree_sitter_node_text(source_bytes, child).strip()
                if text:
                    return text
    for child in getattr(node, "children", None) or []:
        child_type = getattr(child, "type", "")
        if child_type in {"identifier", "constant", "type_identifier", "name"}:
            text = _tree_sitter_node_text(source_bytes, child).strip()
            if text:
                return text
    return ""


def _normalize_tree_sitter_import(text: str) -> str:
    stripped = text.strip().strip("\"'")
    if not stripped:
        return ""
    if "::" in stripped:
        return stripped.split("::")[0]
    if "\\" in stripped:
        return stripped.split("\\")[0]
    if stripped.startswith("./") or stripped.startswith("../"):
        parts = [part for part in stripped.split("/") if part not in {"", ".", ".."}]
        return parts[0] if parts else stripped
    if stripped.startswith("@"):
        scoped_parts = [part for part in stripped.split("/") if part]
        if len(scoped_parts) >= 2:
            return "/".join(scoped_parts[:2])
    if "/" in stripped:
        parts = [part for part in stripped.split("/") if part not in {"", ".", ".."}]
        if parts:
            return parts[0]
    if "." in stripped:
        return stripped.split(".")[0]
    return stripped


def _normalize_tree_sitter_import_for_language(language_name: str, text: str) -> str:
    stripped = text.strip().strip("\"'")
    if not stripped:
        return ""
    if language_name in {"javascript", "typescript", "tsx", "ruby"}:
        return _normalize_js_ts_import(stripped)
    if language_name == "go":
        return _normalize_go_import(stripped)
    if language_name == "rust":
        return _normalize_rust_import(stripped)
    if language_name in {"java", "kotlin"}:
        return _normalize_dotted_import(stripped)
    if language_name == "c_sharp":
        return stripped.split(".")[0]
    if language_name == "php":
        return stripped.split("\\")[0]
    return _normalize_tree_sitter_import(stripped)


def _tree_sitter_rules_for_language(language_name: str) -> dict[str, Any]:
    return _TREE_SITTER_RULES_BY_LANGUAGE.get(language_name, _DEFAULT_TREE_SITTER_RULES)


def _extract_tree_sitter_symbols(file: Path, source: str) -> dict[str, Any] | None:
    language_name = _TREE_SITTER_LANGUAGE_NAMES.get(file.suffix)
    if language_name is None:
        return None
    parser = _load_tree_sitter_parser(language_name)
    if parser is None:
        return None

    source_bytes = source.encode("utf-8")
    try:
        tree = parser.parse(source_bytes)
    except Exception:
        return None

    rules = _tree_sitter_rules_for_language(language_name)
    functions: set[str] = set()
    classes: set[str] = set()
    imports: set[str] = set()

    for node in _iter_tree_sitter_nodes(getattr(tree, "root_node", None)):
        node_type = getattr(node, "type", "")
        if node_type in rules["functions"]:
            identifier = _tree_sitter_identifier_text(source_bytes, node, rules["function_fields"])
            if identifier:
                functions.add(identifier)
        elif node_type in rules["classes"]:
            identifier = _tree_sitter_identifier_text(source_bytes, node, rules["class_fields"])
            if identifier:
                classes.add(identifier.split("::")[-1])
        elif node_type in rules["imports"]:
            import_text = _tree_sitter_identifier_text(source_bytes, node, rules["import_fields"])
            raw_text = import_text or _tree_sitter_node_text(source_bytes, node)
            text = _normalize_tree_sitter_import_for_language(language_name, raw_text)
            if text:
                imports.add(text)

    if not (functions or classes or imports):
        return None

    fallback_language = extract_symbols(file, source)["language"]
    return {
        "functions": sorted(functions),
        "classes": sorted(classes),
        "imports": sorted(imports),
        "language": fallback_language,
    }


def extract_symbols_with_backend(file: Path, source: str) -> tuple[dict[str, Any], str]:
    tree_sitter_symbols = _extract_tree_sitter_symbols(file, source)
    if tree_sitter_symbols is not None:
        return tree_sitter_symbols, "tree_sitter"
    return extract_symbols(file, source), "fallback"


def build_index(
    path: str,
    *,
    resolve_path: Callable[[str], Path],
    infer_project_root: Callable[[Path], Path],
    is_within_root: Callable[[Path, Path], bool],
) -> dict[str, Any]:
    target = resolve_path(path)
    if not target.exists():
        raise FileNotFoundError(path)
    if not target.is_dir():
        raise NotADirectoryError(path)

    project_root = infer_project_root(target)
    source_files = iter_source_files(target, project_root, is_within_root=is_within_root)
    snapshot = tuple(
        (file.relative_to(target).as_posix(), file.stat().st_mtime_ns) for file in source_files
    )
    snapshot_key = _snapshot_key(snapshot)
    cache_key = str(target)
    cached = get_cached_index(cache_key)
    if cached and cached["snapshot"] == snapshot:
        return {**cached["payload"], "cached": True}

    disk_cached = _load_disk_cache(target)
    if disk_cached is not None and disk_cached.get("_snapshot_key") == snapshot_key:
        set_cached_index(cache_key, snapshot, disk_cached)
        return {**disk_cached, "cached": True}

    reusable_file_cache: dict[str, dict[str, Any]] = {}
    if cached:
        reusable_file_cache = _file_cache_from_payload(cached["payload"])
    elif disk_cached is not None:
        reusable_file_cache = _file_cache_from_payload(disk_cached)

    indexed_files: list[dict[str, Any]] = []
    next_file_cache: dict[str, dict[str, Any]] = {}
    python_file_count = 0
    for file in source_files:
        signature = _file_signature(file, target)
        relative_path = signature["relative_path"]
        cached_file = reusable_file_cache.get(relative_path)
        if (
            cached_file is not None
            and cached_file.get("mtime_ns") == signature["mtime_ns"]
            and cached_file.get("size") == signature["size"]
        ):
            content = str(cached_file.get("content", ""))
            functions = list(cached_file["functions"])
            classes = list(cached_file["classes"])
            imports = list(cached_file["imports"])
            token_metadata = {
                "path_tokens": list(cached_file.get("path_tokens", [])),
                "function_tokens": list(cached_file.get("function_tokens", [])),
                "class_tokens": list(cached_file.get("class_tokens", [])),
                "import_tokens": list(cached_file.get("import_tokens", [])),
                "content_tokens": list(cached_file.get("content_tokens", [])),
            }
            if (
                "content_tokens" not in cached_file or "path_tokens" not in cached_file
            ) and content:
                token_metadata = _token_metadata_for_index_entry(
                    relative_path=relative_path,
                    functions=functions,
                    classes=classes,
                    imports=imports,
                    content=content,
                )
            entry = {
                "path": relative_path,
                "functions": functions,
                "classes": classes,
                "imports": imports,
                "language": cached_file["language"],
                "parser_backend": cached_file["parser_backend"],
                **token_metadata,
            }
            next_file_cache[relative_path] = {
                **signature,
                "functions": functions,
                "classes": classes,
                "imports": imports,
                "language": cached_file["language"],
                "parser_backend": cached_file["parser_backend"],
                **token_metadata,
            }
        else:
            try:
                source = file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            try:
                symbols, parser_backend = extract_symbols_with_backend(file, source)
            except SyntaxError:
                continue
            token_metadata = _token_metadata_for_index_entry(
                relative_path=relative_path,
                functions=list(symbols["functions"]),
                classes=list(symbols["classes"]),
                imports=list(symbols["imports"]),
                content=source,
            )
            entry = {
                "path": relative_path,
                "functions": symbols["functions"],
                "classes": symbols["classes"],
                "imports": symbols["imports"],
                "language": symbols["language"],
                "parser_backend": parser_backend,
                **token_metadata,
            }
            next_file_cache[relative_path] = {
                **signature,
                "functions": list(symbols["functions"]),
                "classes": list(symbols["classes"]),
                "imports": list(symbols["imports"]),
                "language": symbols["language"],
                "parser_backend": parser_backend,
                **token_metadata,
            }
        if file.suffix == ".py":
            python_file_count += 1
        indexed_files.append(entry)

    payload = {
        "root": target.relative_to(project_root).as_posix() or ".",
        "files": indexed_files,
        "python_files": python_file_count,
        "source_files": len(indexed_files),
        "parser_backends": sorted({item["parser_backend"] for item in indexed_files}),
        "cached": False,
        "_snapshot_key": snapshot_key,
        "_file_cache": next_file_cache,
    }
    set_cached_index(cache_key, snapshot, payload)
    try:
        _write_disk_cache(target, payload)
    except OSError:
        pass
    return payload
