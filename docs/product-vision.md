# Claude Bridge — Product Vision

> **Last updated:** 2026-05-08
> **Status:** Canonical product direction

Claude Bridge is a **local-first MCP agent runtime** for Claude Desktop and other MCP clients.
It gives an agent controlled access to local files, shell commands, patches, workflows, code
indexing, and project memory while keeping policy, approval, audit, and replay visible.

The short version:

> A secure, local-first MCP workspace layer for running useful coding agents with explicit
> approvals, deterministic policy controls, auditability, bounded orchestration, and an optional
> second-opinion AI advisor.

---

## Current Direction

Claude Bridge started as a Python MCP server for file, shell, and patch tools. The original pivot
framed it as an AI-assisted security layer. That security layer remains essential, but the product
has broadened: the goal is now to become the local control plane between an MCP client and a real
developer workspace.

Security is the governance backbone, not the whole product. The user-facing value is that an agent
can inspect, edit, validate, plan, critique, checkpoint, and explain work in a local project without
turning the machine into an unbounded execution surface. Claude Bridge should also be able to sit
between the coding agent and execution as a debate partner: not only asking "is this allowed?", but
also "is this the right next step, is the scope too broad, is there a safer or more direct plan, and
does this match the user's intent?"

## What We Are Building

- **Local MCP tool runtime:** file read/write, patching, move/copy, shell, process sessions,
  multi-format readers, URL reading, indexing, relevance, and workflow helpers.
- **Governed execution layer:** built-in hard denies, path boundaries, approval presets, custom
  guard policy, rules engine, role-aware policy, and tool profiles.
- **Audit and decision memory:** structured JSONL audit, secret masking, decision extraction,
  filtering, replay, appeal, anomaly scoring, and trust score.
- **Agent workflow surface:** bounded agent-loop tools, context packs, validation suggestions,
  workflow presets, prompt shortcuts, and compact intent helpers.
- **Meta-agent layer:** local plan files, approach exploration, deterministic self-critique, and
  git-backed checkpoints.
- **Optional AI Advisor / debate layer:** local deterministic provider plus Anthropic, OpenAI, and
  Ollama provider interfaces. The current code surface is named `ai_evaluator`, but the product role
  is broader than permission checking: it reviews proposed actions for necessity, scope, safety,
  and fit with the user's intent. It cannot override built-in hard denies.
- **Team and compliance foundations:** policy-as-code, policy diff, role bundles, compliance
  readiness docs, and CI-oriented validation.

## What We Are Not Building Now

- **No browser extension / Web LLM bridge in the current roadmap.** The previous Phase 5 Web LLM
  Extension idea is cancelled for now and should be treated as historical context only.
- **No mandatory cloud service for core use.** The core server stays local-first and stdio-based.
- **No remote policy marketplace yet.** A local policy hub may come first; remote registry/SaaS
  remains a later business decision.
- **No model-hosting product.** Claude Bridge does not ship model weights or become an LLM host.
- **No silent auto-approval expansion.** Approval mode, path boundaries, and hard denies remain
  explicit controls.

## Product Pillars

### 1. Useful Local Agent Work

The bridge should make Claude Desktop feel capable inside a real codebase: find relevant files,
read just enough context, patch safely, run validation, summarize changes, and stop with a clear
state.

### 2. Safety You Can Inspect

Every risky action should have a policy path: built-in guard, user rule, AI advisory decision,
approval request, audit record, and replayable outcome where possible.

### 3. Productive Disagreement

Claude Bridge should make room for structured disagreement before execution. The AI Advisor can
challenge the primary agent's plan, ask for narrower context, recommend a safer validation path, or
suggest that a proposed tool call is premature. This is advisory by default, but it should be visible
in audit records and useful to the user as a second opinion.

### 4. Bounded Orchestration

Agent loops should be small, inspectable, and reversible. Plans, approaches, self-critique, and
checkpoints exist to make longer work safer rather than more autonomous by default.

### 5. Local-First Extensibility

Optional providers, multi-format readers, URL tools, update checks, and team policy features should
extend the local runtime without making core startup fragile or cloud-dependent.

## Current State

Completed or mostly implemented:

- Core MCP file, shell, patch, workflow, indexing, relevance, smart, and insights tools.
- Structured tool responses and explicit error codes.
- Guard policy, rules engine, decision model, audit logging, redaction, replay, and appeal.
- Shell/file/path hardening including symlink and traversal protections.
- Rule-based anomaly detection and trust score MVP.
- Team policy, policy diff, and policy-as-code documentation.
- AI Advisor provider interface with local, Anthropic, OpenAI, and Ollama providers, currently
  implemented under the `ai_evaluator` module name.
- Tool profiles for essential, standard, and full MCP surfaces.
- Meta-agent MVP: plans, approach explorer, self-critique, checkpoints.
- SSRF-constrained `read_url`.

Still needs product hardening:

- Documentation alignment across roadmap files.
- Release quality gates and cross-platform validation.
- Provider latency measurement, keychain-backed secret storage, and provider test hardening.
- Enforced workspace/time restrictions for team roles.
- Large-scale audit search/indexing.
- Baseline aging and optional enforcement policy for anomaly detection.
- More modular `server.py`, `workflow_tools.py`, and `cli.py`.
- Expanded onboarding and feature-parity polish.

## Roadmap Shape

### Phase A — Alignment and Release Readiness

Unify docs, remove contradictory Web LLM Extension references, stabilize package metadata, run the
full quality gate, and keep the public README honest about current capabilities.

### Phase B — Runtime Architecture and Performance

Finish tool-profile filtering, lazy registration/imports, cache bounds, parser caches, and large
module splits without changing the public MCP contract.

### Phase C — AI Provider Completion

Harden Anthropic/OpenAI/Ollama provider behavior, add latency metadata, fail-closed telemetry,
secure local key storage, and evolve evaluator prompts toward second-opinion critique instead of
only allow/deny/ask permission advice.

### Phase D — Team Policy Enforcement

Move role workspace/time restrictions from policy definitions into actual pre-execution enforcement
and CI examples.

### Phase E — Audit, Anomaly, and Trust

Scale audit search, add AI consistency reports, add baseline aging, and decide whether high anomaly
scores should remain advisory or become configurable ask/deny behavior.

### Phase F — Meta-Agent Maturity

Make plans, approach comparison, self-critique, checkpoints, and workflow sessions more useful as a
coherent local agent workbench.

### Phase G — Feature Parity and Ecosystem

Improve onboarding, update workflows, multi-format readers, in-memory code execution if safe, and
local policy hub support.
