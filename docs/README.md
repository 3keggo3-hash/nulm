# Docs

This directory houses persistent and reference documentation for the project.

## Status Classification

### Active / Canonical

These documents are considered the primary reference for the current product direction, technical behavior, or operational flow.

- `product-vision.md`
  Current canonical product vision: local-first, security-controlled MCP agent runtime.
- `roadmap.md`
  Technical implementation phases and current technical status. Links to
  `product-vision.md` for the updated product vision.
- `known-issues-and-improvements.md`
  Known gaps, risks, and improvement suggestions.
- `optional-dependencies.md`
  Canonical guide for the optional dependency pattern and doctor checks.
- `publishing-checklist.md`
  Pre-release and publishing checklist.
- `security-model.md`
  Security model: trust boundary, approval modes, guard policy layer, audit logging.
- `compliance-readiness.md`
  Compliance readiness: access control, audit trail, policy enforcement, data protection.
- `policy-pr-workflow.md`
  CI-friendly policy-as-code PR workflow: policy diff, simulate, validate.
- `ai-collaboration-token-budget.md`
  Practical rules for reducing token/context burn during AI collaboration sessions.
- `overnight-autopilot-plan.md`
  Unattended low-risk execution plan for overnight maintenance slices.

### Completed / Reference

These documents are not the master plan; they are retained under `archive/` as completed analyses,
audits, or historical decision records.

- `archive/competitive-analysis-desktopcommander.md`
  DesktopCommanderMCP comparison and findings.
- `archive/performance-and-completion-audit.md`
  Performance, completion, and UX audit report. Actionable items from its content
  have been converted into newer canonical plans and docs.
- `archive/product-roadmap.md`
  Historical strategy and the earlier AI security layer pivot. The Phase 5 Web LLM
  Extension idea was cancelled, so this should not be treated as canonical in new plans.

### In Progress / Task Tracking

The task lifecycle is not maintained under `docs/`. Active work and completed records:

- `tasks/active/`
- `tasks/done/`
- `tasks/needs-review.md`

### Candidates for Review or Archival

Use `tasks/needs-review.md` as the source of truth for pending doc review/archival decisions.

## Directory Rules

The following types of documents belong here:

- product or technical documentation
- audit and performance reports
- roadmap and strategy documents
- publishing, operations, or usage guides

Do not place task tracking or temporary work notes here:

- active work goes in `tasks/active/`
- completed task records go in `tasks/done/`
- old plans and notes that are no longer canonical go in `archive/`

Note:

- `benchmarks/README.md` is a dedicated usage guide that lives alongside the benchmark
  directory; whether it needs to stay close to benchmark material is tracked in
  `tasks/needs-review.md`.
