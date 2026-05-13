# Optional Dependencies

The Claude Bridge core installation should be able to run without optional packages.
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

## Doctor Checks

`claude-bridge doctor` surfaces the following optional areas:

- dev toolchain: `pytest`, `pytest-asyncio`, `ruff`, `black`, `mypy`
- smart extra: `tiktoken`, `charset_normalizer`
- memory extra: `cryptography`
- indexing extra: `tree_sitter_language_pack`

Missing optional packages are not treated as errors for core usage; the doctor output should
display the relevant extra installation command.

## Related Documents

- `docs/known-issues-and-improvements.md`
- `docs/roadmap.md`
