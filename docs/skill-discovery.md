# Skill Discovery and Governance

Nulm skills are local packages with metadata and Python code. V1 discovery is local-first:
the bridge can list, inspect, recommend, import reviewed packages, export packages, and run
registered skills. It does not fetch, install, or run internet skills automatically.

## Lifecycle

1. Register or import a local skill.
2. List or inspect registered metadata.
3. Recommend skills for a task using trigger phrases, context, tags, and description overlap.
4. Inspect package risk before import.
5. Run a registered skill only through the explicit execution path.

## CLI

```bash
nulm skill list --json
nulm skill inspect docs --json
nulm skill recommend "write release notes" --context docs --json
nulm skill packages ./packages --query release --json
nulm skill package-inspect ./packages/docs.tar.gz --json
nulm skill import ./packages/docs.tar.gz --json
nulm skill export docs ./packages/docs.tar.gz --json
```

High-risk packages require an explicit override:

```bash
nulm skill import ./packages/risky.tar.gz --allow-high-risk
```

## MCP Tools

- `list_skills`
- `inspect_skill`
- `recommend_skills`
- `inspect_skill_package`
- `run_skill`

Package install is intentionally CLI-only in V1. MCP can inspect packages but cannot import them.
`run_skill` is available only in the `full` tool profile.

## Risk Model

Package inspection reads tar members without extracting them. It rejects unsafe paths, links,
device files, duplicate members, invalid manifests, missing code, and oversized packages. It also
flags broad permissions and static code markers such as `exec`, `eval`, `subprocess`,
`os.system`, `shell=True`, and common network libraries.

Skill execution is not an OS sandbox. It is bounded by timeout, reduced environment, filtered
context, metadata permission checks, and the normal approval/profile surface.

## Review Loop

After skill governance changes, review agents should check:

- functionality: expected CLI/MCP behavior works;
- architecture: registry, marketplace, executor, and policy layers stay separate;
- security: shell/path/approval/secret behavior is not weakened;
- tests: edge cases and regressions are covered;
- product fit: recommendations are explainable and useful.
