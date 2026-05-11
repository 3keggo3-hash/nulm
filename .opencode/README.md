# opencode Setup

DCP is enabled in `.opencode/opencode.json`:

```jsonc
{
  "plugin": ["@tarquinen/opencode-dcp@latest"]
}
```

Project DCP settings live in `.opencode/dcp.jsonc`.

Task-specific RTK rules live in `rules/`.

Load only the matching file:

- tests: `rules/testing.md`
- MCP/API work: `rules/api.md`
- refactors/moves: `rules/refactor.md`
- shell/security work: `rules/security.md`
