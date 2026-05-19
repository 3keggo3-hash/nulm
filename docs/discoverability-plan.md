# Discoverability Plan

## MCP Registry Integration

### smithery.ai

Register Nulm on [smithery.ai](https://smithery.ai) to reach Cursor, Windsurf, and other
MCP clients that use smithery as their server discovery backend.

**Steps:**
1. Create smithery account and verify repository ownership
2. Use the existing `nulm install` command as the installation instruction
3. Add description: "Local-first agent quality and execution layer for Claude Desktop and MCP clients"
4. Tag: `python`, `mcp-server`, `nulm`, `agent-quality`, `local-ai`, `developer-tools`

### mcp.get

Submit to [mcp.get](https://mcp.get) registry for MCP client discovery. Same metadata as smithery
submission.

### npm/mcp GitHub Topic

The repository already carries `mcp-server` and `nulm` GitHub Topics. These surface in
GitHub's MCP server search results.

## GitHub Actions CI/CD Recommendation

Add a `publish.yml` workflow to automate releases:

```yaml
name: Publish

on:
  release:
    types: [published]

jobs:
  pypi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - run: pip install build
      - run: python -m build
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          password: ${{ secrets.PYPI_TOKEN }}
```

Add to `.github/workflows/` and configure `PYPI_TOKEN` in repository secrets.

Use the existing `ci.yml` workflow on every push and PR:

```yaml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ["3.10", "3.11", "3.12"]
      - run: pip install -e .[dev]
      - run: pytest
      - run: ruff check .
      - run: mypy src
```

## Documentation Language Expansion

### Target Languages

1. **中文 (Chinese)**: Translate `README.md` to `README.zh.md`
   - High MCP adoption in China
   - Reach developers on Chinese platforms (OSC, v2ex)

2. **日本語 (Japanese)**: Translate key docs
   - Strong developer community

### Translation Priorities

| Document | Priority | Rationale |
|---|---|---|
| `README.md` | High | First impression for discovery |
| `docs/security-model.md` | Medium | Technical trust signal |
| `docs/agent-quality-chat-flows.md` | Medium | Usage examples |

### Implementation

Use `docs/` as the target directory for translations:

- `docs/README.zh.md`
- `docs/README.ja.md`

Keep translations in sync with the English canonical version; update as part of the release
checklist.
