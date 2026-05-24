# Docs

This directory houses persistent and reference documentation for the project.

## Status Classification

### Active / Canonical

These documents are considered the primary reference for current product direction, technical
behavior, or operational flow.

- `product-vision.md`
  Current canonical product vision: local-first agent quality and execution layer.
- `agent-quality-layer-plan.md`
  Canonical long-term plan for the AI-backed quality layer, prompt improvement, token strategy,
  chat-driven safe config, and result review.
- `agent-quality-chat-flows.md`
  Current non-expert chat flow examples for Agent Quality tools and quality workflows.
- `roadmap.md`
  Technical implementation phases and current technical status. Links to
  `product-vision.md` for the updated product vision.
- `multi-agent-architecture-audit.md`
  Deep technical audit of the current Master/Sub-Agent architecture and proposed production-grade
  orchestration design.
- `multi-agent-execution-roadmap.md`
  Prioritized 3-6 month execution roadmap for measurable multi-agent runtime improvements.
- `agent-runtime-remaining-work-plan.md`
  Implementation blueprint for the remaining MissionBrief, DAG scheduler, verifier, conflict, and
  behavioral-enforcement work.
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
- Cross-document sections named `Related Documents` should use `docs/...` paths for consistency.

### Historical Notes

Old execution plans, competitive analyses, and scratch notes are intentionally not canonical
documentation. When their useful decisions are absorbed into the active docs above, the historical
Markdown files can be removed instead of preserved as parallel roadmaps.

## Directory Rules

The following types of documents belong here:

- product or technical documentation
- audit and performance reports
- roadmap and strategy documents
- publishing, operations, or usage guides

Do not place task tracking or temporary work notes here:

- active work may live under `tasks/` while it is genuinely current
- completed or superseded task notes should be summarized into durable docs, then removed
- old plans should not duplicate `product-vision.md`, `roadmap.md`, or
  `agent-quality-layer-plan.md`

Note:

- `benchmarks/README.md` is a dedicated usage guide that lives alongside the benchmark
  directory.
