# Claude Bridge — Technical Roadmap

> **📌 Current Product Direction:** Claude Bridge is positioned as a
> **local-first, security-controlled MCP agent runtime** for Claude Desktop and other MCP clients.
> The security layer is the backbone of the product; the main goal is to consolidate file, shell,
> patch, workflow, audit, replay, AI evaluator, and meta-agent tools into a single auditable local
> runtime layer. For the canonical product vision, see [`docs/product-vision.md`](./product-vision.md).
> The previous AI-security-layer-focused strategy is retained in `product-roadmap.md`
> as a historical reference.

> **Rule:** Do not move to the next feature until the current one is completed.
> **Criterion:** Each phase must have its own test suite.

---

## Phase 0 — Foundation Stabilization
**Status:** Security model made fail-closed, install flow simplified, hybrid parser architecture added, multi-language symbol extraction expanded, and tests brought up to 185 passed.

Remaining items:
- [x] Approval flow for `run_shell` (block dangerous commands)
- [x] Return meaningful messages to Claude on errors (instead of empty/crash)
- [ ] Non-macOS platform testing (Linux first, Windows later)
- [x] Large repo benchmark command
- [x] Tree-sitter present/absent integration matrix
- [x] Gold dataset for relevance quality
- [x] README: installation, security warnings, limitations
- [x] Brief troubleshooting guide for Claude Desktop logs
- [x] Report failed git commit status more clearly to user for `patch_file`
- [x] Create example command matrix of allowed/blocked shell commands
- [x] Clarify behavior for long-running or interactive shell commands (`timeout`, no TTY, no stdin)
- [x] Establish structured error format for tool outputs (`code`, `message`, `details`)
- [x] Multi-root workspace switching and subfolder navigation support
- [x] Improve file discovery in secondary ecosystems like Godot / GDScript

**Output:** Someone else should be able to install and use it without crashes.

**End criteria for this phase:**
- First setup from Claude Desktop must complete in under 10 minutes
- On failed commands, the user should understand what to do next
- The same repo must work with the same basic flow on macOS and Linux
- Multi-language indexing must be verified with the same test matrix whether Tree-sitter is installed or not
- Relevance quality must be protected against regression with at least a small gold dataset
- Large repo performance must be trackable with a repeatable benchmark

### Remaining Key Risks

- Relevance score is still keyword-based; semantic intent and cross-file relationship capabilities are limited.
- Relevance score is now token and field-aware but still not embedding or graph-based; deep semantic relationship capabilities are limited.
- Large repo benchmark command was added, but there is no threshold-based performance gate in CI yet.
- Real end-to-end Claude Desktop-like validation is missing on Linux and Windows.
- Tree-sitter integration is optional, so the risk of behavioral differences due to package version mismatches persists.
- Index cache is in-process memory; disk cache or incremental updates may be needed for very large mono-repo scenarios.

---

## Phase 1 — Slash Commands
**Estimated duration:** 1-2 weeks
**Technology:** MCP `prompts` API

Commands:
- `/review` — review selected file or directory, list issues
- `/optimize` — performance and readability suggestions
- `/test` — write tests for current code
- `/explain` — explain code in Turkish or English
- `/commit` — summarize changes, suggest commit message
- `/todo` — scan TODO comments, sort by priority

**Criterion:** Typing `/` in Claude Desktop should show the commands.

**Current status:**
- [x] `/review` prompt prototype
- [x] `/optimize` prompt prototype
- [x] `/test` prompt prototype
- [x] `/todo` prompt prototype
- [x] `/explain` prompt prototype
- [x] `/commit` prompt prototype

**Open decisions:**
- Should prompts return only templates, or be parameterized based on current file/folder selection?
- Should commands like `/review` and `/test` directly initiate a tool call, or just produce a good starting prompt?

---

## Phase 2 — Codebase Indexing
**Estimated duration:** 3-4 weeks
**Technology:** AST parsing + embedding or simple symbolic index

What it does:
- Scans file structure when a project is opened
- Extracts function/class/import map
- For "where could this bug be?" Claude selects which files to read on its own
- Automatically skips `.gitignore` and large files

**Critical question:** If embedding is used, which model? Local (nomic-embed) or API? Using an API incurs cost.

**Criterion:** On a 10,000+ line codebase, Claude should find the correct file on the first try.

**Current status:**
- [x] Initial symbolic index prototype (`index_codebase`)
- [x] Function/class/import extraction with Python `ast`
- [x] Basic skip list (`.git`, `venv`, `__pycache__`, `node_modules`, cache folders)
- [x] Initial query tool (`find_relevant_files`)
- [x] Using index results in workflow discovery (`run_workflow(..., execute=true)`)
- [x] Proper interpretation of `.gitignore` file
- [x] Index storage / reuse
- [x] Content-level search and improved relevance scoring
- [x] Masked audit records carrying policy decisions, CLI filters, and deterministic rule
  replay added

**Open technical decisions:**
- When should the index be updated: at startup, on file change, or via manual command?
- Should the index file be kept inside the repo or in a cache directory?
- Should the first version start with a symbolic index without embedding?

---

## Phase 3 — Agentic Loop
**Estimated duration:** 1-2 months
**Technology:** Tool call → result → tool call again loop
**Status:** ✅ Completed

What it does:
- "Make this test pass" is given as input
- Claude reads code, modifies it, runs the test
- If the test fails, it reads the error and fixes it again
- Continues until it passes or max iterations are reached

**Safety boundaries (completed):**
- [x] Maximum iteration count
- [x] Total file modification limit
- [x] Set of shell commands allowed to run in a single step
- [x] Rollback policy: snapshot on failure
- [x] Per-step verification with validation command
- [x] Result compaction and session summary

---

## Phase 4 — Multi-Model Routing
**Status:** ✅ Completed
**Estimated duration:** 2-3 weeks (after Phase 3)
**Technology:** Task classifier + model selector

Logic:
- Simple question / explanation → Haiku (fast, cheap)
- Code writing / refactor → Sonnet
- Architectural decision / complex analysis → Opus
- User can override: `--model opus`

**Critical question:** Claude Desktop currently leaves model selection to the user; a separate layer is needed for automatic routing via API.

**Criterion:** Cost should drop 40%+ for the same quality of output (measurable).

**Note:** This phase only makes sense if a separate API orchestration layer exists. If we are only working within Claude Desktop, it can be deferred.

---

## Phase 5 — Git Integration
**Estimated duration:** 2-3 weeks
**Status:** ✅ Completed

What it does:
- [x] Automatic commit before each agentic loop step (safety net)
- [x] Feed `git diff` output to Claude
- [x] Git status, log, branch operations
- [ ] Auto-generate PR description
- [ ] Suggest conflict resolution

**Criterion:** If the agentic loop breaks something, it should be reversible with a single command.

---

## Phase 6 — Web Interface (Optional)
**Status:** ✅ Completed
**Estimated duration:** 3-4 weeks
**Condition:** Do not start until Phases 1-3 are stable.

What it does:
- Use from browser instead of Claude Desktop
- Session history
- Project-based context management
- Team usage (multi-user)

**Critical warning:** At this point, direct competition with Claude Code begins. Anthropic ToS must be reviewed again.

---

## Things That Will Never Be Done

- Asking users for API keys and storing them on own servers — security disaster
- Downloading and running model weights — license violation
- Selling Claude's output to another service — clear ToS violation

---

## Priority Matrix

| Phase | Difficulty | User Value | Priority |
|-------|-----------|-----------|----------|
| 0 — Stabilization | Low | High | **Now** |
| 1 — Slash Commands | Low | Medium | **Next** |
| 2 — Indexing | High | High | 3rd |
| 3 — Agentic Loop | Very High | Very High | 4th |
| 4 — Multi-Model | Medium | Medium | 5th |
| 5 — Git | Medium | High | 6th |
| 6 — Web Interface | High | Medium | Last |

---

## Stabilization Roadmap

1. Record baseline benchmark results on 2-3 large real repos
2. Continue growing the gold relevance dataset with real queries from bug reports
3. Define tighter repo-based thresholds for benchmark outputs
4. Upgrade the Linux smoke pipeline to real Claude Desktop-like end-to-end validation
5. Safely add the Windows pipeline
6. Begin an incremental/perf improvement round for index cache and relevance scoring

### Next Concrete Tasks
- Document benchmark results with real open-source repo examples
- Add Java, Ruby, and mixed mono-repo cases to the relevance dataset
- Try query result caching or token-based pre-indexing for `find_relevant_files`
- Perform first cross-platform validation on Linux
- Add a separate CI job for the optional Tree-sitter dependency

---

*This file is updated when each phase is completed.
