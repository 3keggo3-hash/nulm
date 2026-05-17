# Nulm Public Alpha Release Polish Plan

## Summary

Make Nulm the public project name everywhere and prepare a credible public alpha release. The
release bar is not a broad marketing launch; it is a clean alpha with consistent branding,
passing release gates, and documented optional surfaces.

Compatibility default: `nulm` becomes the primary CLI/MCP-facing name, while existing
`claude-bridge` / `claude_bridge` surfaces remain as deprecated aliases for one release cycle.

## Release Blockers

- Align versions across `pyproject.toml`, `src/claude_bridge/__init__.py`, changelog, and release
  notes. Current known mismatch: package metadata is `0.1.1`, runtime `__version__` is `0.1.0`.
- Make CI and release gate fully green:
  - `ruff check .`
  - `black --check .`
  - `mypy src`
  - `pytest`
  - `python -m build`
  - `twine check dist/*`
  - `./scripts/release-gate.sh`
- Fix the current `mypy src` failures without weakening strict typing.
- Fix `ruff check .` failures. If `agents/autonomous/*` is non-release experiment code, exclude it
  explicitly with a documented rationale; otherwise clean it.
- Complete Nulm public naming:
  - README, docs, release notes, issue templates, workflow labels, dashboard/title text, CLI help,
    examples, and submission copy say Nulm.
  - `nulm` is the primary command in install and usage docs.
  - `claude-bridge` remains documented only as a compatibility alias.
- Document optional extras so users know what they enable:
  - `smart`
  - `memory`
  - `redis`
  - `policy-yaml`
  - `observability`
  - `tracing`
  - `streaming`
  - existing extras such as `treesitter` and `multi-format`
- Keep `scripts/release-gate.sh` present, Nulm-branded, and passing locally.

## Security And Coverage Hardening

- Treat `distributed_cache.py` as release-sensitive if the `redis` extra is publicly documented.
  Add focused tests for Redis/distributed-cache security and failure edge cases, or mark the Redis
  extra as experimental in docs until coverage improves.
- Add targeted tests for low-coverage release-relevant modules:
  - `_audit_query_parser.py`
  - `trust_score.py`
  - `update.py`
- Do not make full coverage cleanup a public-alpha blocker. Prefer focused tests around parsing,
  update checks, cache failure behavior, and security boundaries.
- Reduce silent exception swallowing only in critical paths for this release:
  - distributed cache
  - update checks
  - audit/query parsing
  - workflow execution paths
- Leave broad `except Exception: pass` cleanup as a follow-up hardening backlog unless it affects a
  release gate, security boundary, or user-visible failure mode.

## Branding And Interface Changes

- Add `nulm = "claude_bridge.cli:main"` as the primary script entry point.
- Keep `claude-bridge = "claude_bridge.cli:main"` as a deprecated compatibility script.
- Generate new example MCP configs with a `"nulm"` server key.
- Keep support for existing `"claude-bridge"` configs where possible.
- Do not rename the internal Python package directory from `claude_bridge` in this release; that
  would be a separate breaking migration.

## Deferred Work

- Windows CI is useful but not required for this public alpha unless the README claims Windows as a
  tested platform.
- `legacy` FastAPI/Uvicorn extras can remain for now if documented as legacy; remove or deprecate
  in a later minor release.
- Broad feature pruning, website/discoverability campaigns, and registry submissions belong after
  this alpha polish pass.

## Acceptance Criteria

- Fresh clone install docs consistently present the project as Nulm.
- `nulm --help` works and shows Nulm branding.
- `claude-bridge --help` still works as a compatibility alias.
- `nulm install --simple` produces a usable MCP config with the Nulm server key.
- Release validation commands pass locally and in GitHub Actions.
- Built artifacts pass `twine check dist/*`.
- Changelog and release notes accurately describe the alpha status and compatibility aliases.
