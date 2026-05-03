# Policy-as-Code PR Workflow

This document describes the CI-friendly policy-as-code workflow for
reviewing and validating team policy changes via pull requests.

## Overview

The `claude-bridge policy` subcommand provides tools to integrate
role-based access control changes into a standard PR review cycle:

| Command | Purpose |
|---------|---------|
| `policy diff --base OLD --head NEW` | Compare two policy files for semantic changes |
| `policy simulate --role ROLE ...` | Test how a role processes a tool request |
| `policy validate --path FILE` | Validate a policy file |

All commands support `--json` output for CI pipelines.

## PR Workflow

### 1. Author opens a PR that changes a policy file

Policy files live in the team's repository (e.g., `team-policy.yaml`
or `.claude-bridge/rules.yaml`). When a role definition or rule is
changed, the diff highlights what changed before a human reviewer
looks at the PR.

### 2. CI runs `policy diff` on every commit

```bash
# Compare main branch (base) against PR head
claude-bridge policy diff --base main-policy.yaml --head pr-policy.yaml --json
```

Exit code **1** means: validation errors, inheritance problems, or
meaningful diffs detected.  The reviewer sees a structured JSON
payload describing:

- Roles added or removed
- Permission changes (tool, action, scope)
- Restriction changes
- Inheritance changes (extends)
- Validation errors
- Inheritance issues (circular chains, missing bases, self-references)

### 3. Reviewer examines the structured diff

```json
{
  "status": "modified",
  "base": "main",
  "head": "feat/contractor-read",
  "roles_added": [],
  "roles_removed": [],
  "role_diffs": [
    {
      "role": "contractor",
      "status": "modified",
      "permission_diffs": [
        {
          "tool": "read_file",
          "status": "added",
          "new_action": "allow"
        }
      ]
    }
  ],
  "validation_errors": {"base": [], "head": []},
  "inheritance_errors": {"base": [], "head": []}
}
```

### 4. Optional: simulate specific tool calls

Reviewers can check whether a new role definition has unintended side
effects by simulating tool calls:

```bash
# Simulate as junior trying to write to a production path
claude-bridge policy simulate \
  --path pr-policy.yaml \
  --tool write_file \
  --param path=/prod/config.yaml \
  --role junior \
  --json
```

Expected output when the role's `production_env` restriction applies:

```json
{
  "tool": "write_file",
  "role": "junior",
  "action": "deny",
  "source": "builtin_guard",
  "risk_level": "critical",
  "reason": "Role restriction (junior): production environment changes are not allowed"
}
```

### 5. Adoption checklist

- [ ] Policy file is stored in the repo (under `.claude-bridge/` or `policies/`)
- [ ] PR template asks authors to explain role/permission changes
- [ ] CI job runs `policy diff --json` and fails on inheritance errors
- [ ] CI job runs `policy simulate` smoke tests against critical paths
- [ ] Reviewer checklist includes verifying the diff output

## CI Integration Examples

### GitHub Actions

```yaml
- name: Policy diff
  run: |
    claude-bridge policy diff \
      --base origin/main:team-policy.yaml \
      --head team-policy.yaml \
      --json > policy-diff.json
  continue-on-error: true

- name: Simulate critical paths
  run: |
    claude-bridge policy simulate \
      --path team-policy.yaml \
      --tool write_file \
      --param path=/prod/config.yaml \
      --role contractor \
      --json
```

### GitLab CI

```yaml
policy-diff:
  script:
    - claude-bridge policy diff --base main-policy.yaml --head $CI_PROJECT_DIR/policy.yaml --json
  artifacts:
    reports:
      json: policy-diff.json
```
