# Claude Bridge — Product Vision

> **Last updated:** 2026-05-08
> **Status:** Canonical product direction

Claude Bridge is a **local-first agent quality and execution layer** for Claude Desktop and other
MCP clients. It gives an agent controlled access to local files, shell commands, patches,
workflows, code indexing, and project memory while adding the missing middle layer: intent
clarification, context strategy, plan critique, token optimization, result quality review, and safe
configuration guidance.

The short version:

> A secure, local-first MCP workspace layer that helps ordinary user requests become professional
> software work: clearer plans, better context choices, safer execution, stronger quality checks,
> and explicit approvals.

---

## Current Direction

Claude Bridge started as a Python MCP server for file, shell, and patch tools. The first product
pivot framed it as an AI-assisted security layer. That security layer remains essential, but the
product has broadened again: the goal is now to become the local control plane and quality layer
between an MCP client and a real developer workspace.

The release decision follows from that: do not hurry into a broad public launch as a "safe MCP
server." First, reshape the product around the Agent Quality Layer. That is what makes Claude Bridge
different from a normal MCP tool collection: it should help users get better code, better plans, and
better workflow settings without needing deep prompting or engineering-process expertise.

Security is the governance backbone, not the whole product. The user-facing value is that a user
should not need to know how to write a perfect engineering prompt. They should be able to describe
what they want in ordinary language, and Bridge should help turn that into scoped plans, relevant
context, safe tool use, cleaner code, better tests, and lower token waste.

Claude Bridge should sit between the coding agent and execution as a senior collaborator: not only
asking "is this allowed?", but also "is this the right next step, is the scope too broad, what
context is actually needed, how can token use be reduced, is there a better approach, and does the
result meet a professional quality bar?"

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
- **Agent Quality Layer:** intent normalization, prompt improvement, context strategy, plan
  critique, result quality review, creative alternatives, token optimization, and safe MCP config
  recommendations. The current `ai_evaluator` code is an early security-advisor slice, not the full
  target layer.
- **Optional provider-backed advisor:** local deterministic provider plus Anthropic, OpenAI, Ollama,
  and other provider interfaces where configured. Provider advice cannot override built-in hard
  denies.
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
  explicit controls. Chat-driven settings may recommend safer profiles, but cannot quietly weaken
  policy.

## Product Pillars

### 1. Useful Local Agent Work

The bridge should make Claude Desktop feel capable inside a real codebase: find relevant files,
read just enough context, patch safely, run validation, summarize changes, and stop with a clear
state.

### 2. Safety You Can Inspect

Every risky action should have a policy path: built-in guard, user rule, AI advisory decision,
approval request, audit record, and replayable outcome where possible.

### 3. Agent Quality By Default

Claude Bridge should make professional work easier even when the user gives an imprecise prompt. It
should clarify intent, create acceptance criteria, choose a context plan, challenge broad or risky
implementation plans, recommend validation, and review the result.

### 4. Productive Disagreement

The advisor can challenge the primary agent's plan, ask for narrower context, recommend a safer
validation path, or suggest that a proposed tool call is premature. This is advisory by default, but
it should be visible in audit records and useful to the user as a second opinion.

### 5. Self-Tuning Local Workflow

Bridge should be configurable from chat for safe settings: tool profiles, context budget, workflow
defaults, advisor provider choice, and timeout values. It must explain tradeoffs, ask for approval
before mutation, audit changes, and reject secrets or policy-weakening changes through ordinary MCP
payloads.

### 6. Bounded Orchestration

Agent loops should be small, inspectable, and reversible. Plans, approaches, self-critique, and
checkpoints exist to make longer work safer rather than more autonomous by default.

### 7. Local-First Extensibility

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

- Agent Quality Layer MCP tools are implemented as an advisory MVP and need real-world polish.
- Agent-facing config changes through `apply_bridge_config_change` are limited to safe allowlisted
  keys; broader admin/runtime config remains explicit and should not be model-generated.
- Documentation alignment is mostly complete, but public examples still need use-case hardening.
- Release quality gates and cross-platform validation.
- Provider latency measurement, keychain-backed secret storage, and provider test hardening.
- Enforced workspace/time restrictions for team roles.
- Large-scale audit search/indexing.
- Baseline aging and optional enforcement policy for anomaly detection.
- More modular `server.py`, `workflow_tools.py`, and `cli.py`.
- Expanded onboarding and feature-parity polish.

## Roadmap Shape

### Phase A — Product Repositioning and Docs

Reposition the project from "security-controlled MCP runtime" to "agent quality and execution
layer." Keep public docs honest about which pieces exist today and which are still planned.

### Phase B — Agent Quality Contract

Introduce a structured advisor contract for intent, plan, context, token, quality, and config
recommendations. Keep provider output strictly parsed and fail-safe.

### Phase C — Safe Chat-Driven Config

Let users inspect, explain, suggest, apply, and reset safe Bridge settings from chat. Do not allow
chat payloads to set secrets, widen path boundaries casually, or weaken shell hard denies.

### Phase D — Prompt, Plan, and Quality Workflows

Add request improvement, plan critique, result quality review, and next-prompt generation. Wire the
advisor into workflows at clear boundaries.

### Phase E — Runtime Architecture and Performance

Continue module splits, lazy imports, cache bounds, parser caches, and release hardening without
breaking the public MCP contract.

### Phase F — Governance, Audit, and Team Policy

Scale audit search, improve replay/appeal, enforce role restrictions, add policy examples, and keep
anomaly scoring advisory unless explicitly configured otherwise.

### Phase G — Ecosystem and Public Release Polish

Improve onboarding, package install, optional dependencies, local policy hub support, examples, and
public release messaging.

For the detailed long-term implementation plan, see
[`docs/agent-quality-layer-plan.md`](./agent-quality-layer-plan.md).
