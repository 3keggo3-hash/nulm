# Optional Dependencies

The Nulm core installation should be able to run without optional packages.
Optional features must perform graceful fallback at runtime, and `mypy src`
must not produce import errors in the core environment.

## Pattern

The preferred pattern for optional imports:

1. Declare a non-public typed variable initialized to `None`.
2. Import the desired symbol under a different alias.
3. After a successful import, assign it to the typed variable.
4. Use the `# type: ignore[import-not-found]` comment only on the optional import line.
5. Before runtime usage, check the availability flag or perform a `None` check.

Example:

```python
from typing import Any, Callable

_OptionalFunc = Callable[[bytes], Any]
_optional_func: _OptionalFunc | None = None
_OPTIONAL_AVAILABLE = False

try:
    from optional_package import func as _imported_optional_func  # type: ignore[import-not-found]

    _optional_func = _imported_optional_func
    _OPTIONAL_AVAILABLE = True
except ImportError:
    pass
```

## Public Extras

Install optional capabilities by selecting the extra that matches the feature you need:

| Extra | Install command | Enables |
| --- | --- | --- |
| `treesitter` | `pip install "nulm[treesitter]"` | Tree-sitter-backed code indexing. |
| `multi-format` | `pip install "nulm[multi-format]"` | Image/PDF reading through Pillow and PyPDF2. |
| `smart` | `pip install "nulm[smart]"` | Token-aware helpers using tiktoken and charset detection. |
| `recommended` | `pip install "nulm[recommended]"` | The practical local IDE set: Tree-sitter indexing, token helpers, image/PDF reading, and YAML policy files. |
| `memory` | `pip install "nulm[memory]"` | Encrypted local memory support through cryptography. |
| `policy-yaml` | `pip install "nulm[policy-yaml]"` | YAML guard-policy files through PyYAML. |
| `redis` | `pip install "nulm[redis]"` | Experimental Redis-backed distributed cache support. |
| `observability` | `pip install "nulm[observability]"` | Prometheus metrics integration. |
| `tracing` | `pip install "nulm[tracing]"` | OpenTelemetry tracing integration. |
| `streaming` | `pip install "nulm[streaming]"` | SSE streaming helpers through sse-starlette. |
| `legacy` | `pip install "nulm[legacy]"` | Legacy FastAPI/Uvicorn integration kept for compatibility. |

For most desktop or IDE MCP users, `nulm[recommended]` is the easiest install path. It keeps
experimental server features out of the default runtime while making the common readers and code
indexing helpers available without picking extras one by one.

The `redis` extra is optional and experimental for this alpha. Core Nulm usage must not require a
Redis server, and Redis connection failures must fall back safely to local/no-cache behavior.

## Doctor Checks

`nulm doctor` surfaces the following optional areas:

- dev toolchain: `pytest`, `pytest-asyncio`, `ruff`, `black`, `mypy`
- smart extra: `tiktoken`, `charset_normalizer`
- memory extra: `cryptography`
- indexing extra: `tree_sitter_language_pack`
- redis extra: `redis`
- policy-yaml extra: `PyYAML`
- observability extra: `prometheus-client`
- tracing extra: `opentelemetry-api`, `opentelemetry-sdk`
- streaming extra: `sse-starlette`

Missing optional packages are not treated as errors for core usage; the doctor output should
display the relevant extra installation command.

## Related Documents

- `docs/known-issues-and-improvements.md`
- `docs/roadmap.md`
