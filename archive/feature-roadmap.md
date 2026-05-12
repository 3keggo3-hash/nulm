# Claude Bridge Feature Roadmap

## Vision

Claude Bridge becomes an **Agent Quality Layer** — not just an MCP server, but an intelligent agent coordinator that improves prompts, critiques plans, coordinates sub-agents, reduces token waste, and maintains security boundaries while providing a seamless user experience.

---

## PART 1: Core Architecture

### 1.1 Skill System

**Type**: Hybrid (session + persistent with approval)

**Location**: `.claude-bridge/skills/`

**Format**:
```
skills/
  skill_name.v1.json     # Metadata + trigger conditions
  skill_name.py          # Executable code snippet
```

**Skill JSON Schema**:
```json
{
  "name": "bridge-doctor",
  "version": "1.0",
  "trigger_phrases": ["sistem Problem", "çalışmıyor", "hata"],
  "trigger_context": ["shell", "security", "config"],
  "auto_load": true,
  "permissions": ["read", "analyze"],
  "code": "def run(context): ..."
}
```

**Auto-Skill Creation Flow**:
1. Complex/long task completes
2. System asks: "Bunu skill olarak kaydetmemi ister misin?"
3. User approves → skill saved to `.claude-bridge/skills/`
4. Skill indexed and available for future use
5. **NOT autonomous** — always requires user approval

**Skill Categories**:
- `analysis_*` — Diagnostic and inspection skills
- `security_*` — Guard and validation skills
- `optimization_*` — Performance improvement skills
- `workflow_*` — Process automation skills

---

### 1.2 Multi-Agent System

**Architecture**: Single orchestrator + N sub-agents

**Design Principle**: User sees only the orchestrator. Sub-agents are invisible implementation details.

```
User Input
    │
    ▼
┌─────────────────────────────────────────┐
│           Orchestrator Agent            │
│  • Intent parsing                       │
│  • Task decomposition                   │
│  • Result synthesis                     │
└─────────────────────────────────────────┘
    │          │           │           │
    ▼          ▼           ▼           ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│ Git    │ │Security│ │ Debug  │ │Research│
│ Agent  │ │ Agent  │ │ Agent  │ │ Agent  │
└────────┘ └────────┘ └────────┘ └────────┘
```

**Sub-Agent Types**:

| Agent | Permissions | Specialty |
|-------|-------------|-----------|
| `git_agent` | git commands, file read | Version control operations |
| `security_agent` | analyze, suggest | Security audit, vulnerability detection |
| `debug_agent` | test commands, log read | Error investigation, fixes |
| `research_agent` | file read, search | Codebase analysis, documentation |
| `review_agent` | read all files | Quality review, self-critique |

**Inter-Agent Communication**:
- Shared memory space (dict) passed via context
- Each agent returns: `{status, findings, artifacts, next_steps}`
- Orchestrator synthesizes results into single response

**Task Distribution**:
```python
async def distribute_task(task: str) -> dict:
    subtasks = decompose_task(task)  # LLM-based decomposition
    results = await asyncio.gather(*[
        agent.execute(subtask) for agent in relevant_agents
    ])
    return synthesize_results(results)
```

---

## PART 2: Feature Catalog

### 2.1 Autopilot Score (0-100 Risk Score)

**Description**: Every shell command receives a numerical risk score before execution.

**Format**: `{score}/100 — {category}: {reason}`

**Scoring Matrix**:

| Score | Category | Example |
|-------|----------|---------|
| 0-20 | Safe | `ls`, `echo`, `git status` |
| 21-40 | Low Risk | `pip install`, file read |
| 41-60 | Medium | `rm` without recursive, git commit |
| 61-80 | High | `rm -r`, `curl` with pipes |
| 81-99 | Critical | `rm -rf /`, `| bash` |
| 100 | Blocked | Destructive patterns without backup |

**Display Format**:
```
🔒 72/100 — HIGH: recursive delete detected
   → Backup exists: yes
   → Suggested alternative: rm -v (verbose, safer)
```

**Integration Points**:
- `run_shell` tool — pre-execution scoring
- `ai_evaluator.py` — extended with score attribute
- Audit log — every score recorded

---

### 2.2 Bridge Detective (Error Detective)

**Description**: Automatic error investigation workflow.

**Flow**:
```
Error occurs
    │
    ▼
┌──────────────────────────────────────────────┐
│ 1. CLASSIFY                                  │
│    • SyntaxError → file location             │
│    • RuntimeError → stack trace analysis     │
│    • SecurityError → alert + block           │
│    • NetworkError → connectivity check       │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│ 2. LOCATE                                    │
│    • Find related files                      │
│    • Check recent changes (git blame)        │
│    • Cross-reference with LESSONS_LEARNED    │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│ 3. INVESTIGATE                               │
│    • Run diagnostic commands                 │
│    • Check dependencies                      │
│    • Verify permissions                      │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│ 4. SOLVE                                     │
│    • Propose minimal fix                     │
│    • Apply if approved                        │
│    • Create rollback checkpoint              │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│ 5. LEARN                                     │
│    • Add to LESSONS_LEARNED                  │
│    • Update skill if valuable                │
└──────────────────────────────────────────────┘
```

**Output Format**:
```
🔍 Bridge Detective Report
══════════════════════════
Error: ModuleNotFoundError: No module named 'yaml'
File: src/config.py:12
 likelihood: high

Recent changes:
  src/config.py - 2 hours ago - added yaml import

Suggested fix:
  pip install pyyaml

Apply? [y/N]
```

---

### 2.3 Plan → Onay → Uygula → Test → Rapor Workflow

**Description**: Mandatory workflow for all agent operations.

**States**:
```
IDLE → PLANNING → APPROVAL_PENDING → APPLYING → TESTING → REPORTING → DONE
                ↑
                │ (user rejects)
                └─────────────────── REJECTED
```

**PLANNING Phase**:
- Orchestrator creates step-by-step plan
- Each step includes: action, files affected, risk score, rollback plan
- User sees estimated steps and total risk

**APPROVAL_PENDING Phase**:
```
┌─────────────────────────────────────┐
│ 📋 Plan Review                      │
├─────────────────────────────────────┤
│ Step 1: Read src/app.py            │
│         Risk: 5/100 ✓               │
├─────────────────────────────────────┤
│ Step 2: Modify app.py              │
│         Risk: 25/100 ⚠️             │
│         Backup: will be created     │
├─────────────────────────────────────┤
│ Step 3: Run tests                   │
│         Risk: 10/100 ✓              │
├─────────────────────────────────────┤
│ Total Risk: 32/100                  │
│ Est. duration: ~30 seconds         │
├─────────────────────────────────────┤
│ [Approve] [Modify] [Cancel]        │
└─────────────────────────────────────┘
```

**APPLYING Phase**:
- Steps executed sequentially
- Each step logged to audit
- Rollback checkpoint before modifications

**TESTING Phase**:
- Run relevant tests
- If fail: revert + report
- If pass: proceed to reporting

**REPORTING Phase**:
```
┌─────────────────────────────────────┐
│ ✅ Operation Complete               │
├─────────────────────────────────────┤
│ Files modified: 3                   │
│ Tests run: 12 (passed)              │
│ Risk score: 28/100                  │
│ Backups: 2 created                  │
├─────────────────────────────────────┤
│ Changed files:                      │
│   • src/app.py                      │
│   • tests/test_app.py               │
│   • README.md                       │
└─────────────────────────────────────┘
```

---

### 2.4 Three-Layer Memory

**Structure**:

```python
memory = {
    "user_profile": {
        "name": "...",
        "language": "tr",
        "skill_level": "intermediate",
        "preferences": {...},
        "trusted_agents": ["git", "research"]
    },
    "project_memory": {
        "path": "/path/to/project",
        "language": "python",
        "entry_points": ["src/main.py"],
        "test_command": "pytest",
        "risk_areas": ["src/security/", ".env"],
        "custom_rules": [...]
    },
    "lessons_learned": [
        {
            "pattern": "ModuleNotFoundError with yaml",
            "solution": "pip install pyyaml",
            "project": "claude-bridge",
            "timestamp": "2026-05-11",
            "hits": 3
        },
        ...
    ]
}
```

**Storage**: `.claude-bridge/memory.json` (encrypted for sensitive data)

**Auto-population**:
- `user_profile`: inferred from interactions
- `project_memory`: created on first `bridge doctor`
- `lessons_learned`: updated after each error fix

---

### 2.5 Permission Cards

**Description**: Human-readable permission requests instead of raw commands.

**Format**:
```
┌─────────────────────────────────────────┐
│ 🔐 Permission Card                      │
├─────────────────────────────────────────┤
│ Agent: debug_agent                      │
│ Action: Read error logs                 │
│ Files: /var/log/app.error               │
│ Risk: 5/100                             │
├─────────────────────────────────────────┤
│ "Uygulama loglarındaki hataları         │
│  incelemek istiyorum"                   │
├─────────────────────────────────────────┤
│ [Allow Once] [Allow Always] [Deny]      │
└─────────────────────────────────────────┘
```

**vs Raw Format**:
```
# Old (scary)
request_approval_fn("run_shell", {"command": "cat /var/log/app.error"})

# New (friendly)
PermissionCard(
    agent="debug_agent",
    action="Read error logs",
    reason="Kullanıcı hata ayıklama istedi",
    risk=5,
    files=["/var/log/app.error"]
)
```

---

### 2.6 User Intent Engine (Niyet Motoru)

**Description**: Understands vague complaints and maps to specific actions.

**Examples**:

| User Input | System Interpretation |
|------------|----------------------|
| "Bu çalışmıyor ya" | → Run diagnostics, check recent changes |
| "Yavaşladı" | → Check resource usage, analyze bottlenecks |
| "Bir şey eksik" | → Verify dependencies, check config |
| "Güvenli mi?" | → Run security audit on target |

**Implementation**:
```python
INTENT_PATTERNS = {
    "error_complaint": ["çalışmıyor", "hata", "crash", "broken"],
    "performance_concern": ["yavaş", "slow", "performance"],
    "security_concern": ["güvenli mi", "secure", "risk"],
    "missing_feature": ["eksik", "missing", "yok"],
}

def parse_intent(user_input: str) -> IntentResult:
    # Use LLM or pattern matching
    # Return: intent_type, confidence, suggested_actions
```

**Response Format**:
```
Anladım — "bu çalışmıyor" diyorsunuz.
Olası 3 senaryo:
  1. Bağımlılık hatası (60% olasılık)
  2. Konfigürasyon sorunu (30% olasılık)
  3. Kod hatası (10% olasılık)

Hangi kontrolleri yapayım?
  [Bağımlılıkları kontrol et] [Loglara bak] [Son değişiklikleri incele]
```

---

### 2.7 Snapshot / Rollback Guarantee

**Description**: Every modification creates a checkpoint before changes.

**Snapshot Types**:

| Type | Scope | Retention |
|------|-------|-----------|
| `pre_task` | Modified files only | Until task complete |
| `pre_session` | All project | Until session end |
| `named` | User-specified | Until explicitly deleted |

**Commands**:
```bash
bridge snapshot create --name "before-feature-x"
bridge snapshot list
bridge snapshot restore --name "before-feature-x"
bridge snapshot delete --name "old-snapshot"
```

**Storage**: `.claude-bridge/snapshots/` (git-compatible or tar)

**Rollback Flow**:
```
Before modification:
  1. Create snapshot
  2. Store in snapshots/
  3. Update snapshot index

After failure:
  1. Load snapshot
  2. Restore files
  3. Verify integrity
```

---

### 2.8 Bridge Doctor

**Description**: Auto-diagnostic tool that fixes problems automatically.

**Checks**:
- [ ] MCP configuration valid
- [ ] Required directories exist
- [ ] Dependencies installed
- [ ] Permissions correct
- [ ] Config syntax valid
- [ ] Skill index loaded

**Auto-fix Examples**:

| Problem | Fix |
|---------|-----|
| Missing MCP config | Create from template |
| Syntax error in config | Highlight and suggest fix |
| Missing dependencies | Prompt to install |
| Outdated skills index | Rebuild index |

**Output**:
```
🔧 Bridge Doctor
═════════════════
✓ MCP configuration valid
✓ Dependencies installed
⚠️  2 issues found

Issue 1: Missing skill index
  → Auto-fix: Rebuilding index...
  → Fixed!

Issue 2: Old config format (v1 → v2)
  → Suggestion: Run 'bridge migrate'
  → Or auto-migrate now? [y/N]

Report saved to: .claude-bridge/doctor-report.md
```

---

### 2.9 Toolset Permissions (Agent-Based)

**Description**: Table of which agent can execute which tools.

**Default Permissions**:

| Agent | Allowed Tools | Denied Tools |
|-------|---------------|--------------|
| `orchestrator` | all | none |
| `git_agent` | git, file_read | shell, network |
| `security_agent` | analyze, audit | write, delete |
| `debug_agent` | test, log_read | git_write, shell_destructive |
| `research_agent` | file_read, search, index | write, execute |
| `review_agent` | file_read | all_mutations |

**Runtime Override**:
```python
# Per-session permission boost
"git_agent": {
    "allow": ["shell"],  # Temporary elevation
    "duration": 300  # 5 minutes
}
```

---

### 2.10 Audit Log

**Schema**:
```json
{
  "timestamp": "2026-05-11T21:30:00Z",
  "operation": "file_modify",
  "agent": "git_agent",
  "details": {
    "files": ["src/app.py"],
    "lines_changed": 12,
    "risk_score": 25,
    "backup_created": true,
    "test_passed": true
  },
  "parent_operation": "feature-x-implementation"
}
```

**Commands**:
```bash
bridge audit list --today
bridge audit export --format=csv --since=2026-05-01
bridge audit search --agent=git_agent --risk=high
```

**Retention**: 30 days default, configurable

---

### 2.11 Project Map

**Description**: Auto-generated project understanding stored at `.claude-bridge/project-map.md`

**Generated On**:
- First `bridge doctor` run
- `bridge init` completion
- Manual trigger: `bridge map --refresh`

**Content**:
```markdown
# Project Map: my-project

## Overview
- Language: Python 3.10+
- Framework: FastAPI
- Test Framework: pytest

## Entry Points
- `src/main.py` — Application entry
- `cli.py` — CLI interface

## Risk Areas
- `src/security/` — Elevated permissions required
- `.env` — Contains secrets

## Custom Guards
- No `rm -rf` outside temp/
- Require approval for network calls

## Skills
- `bridge-doctor` (loaded)
- `git-helper` (loaded)

## Last Updated
2026-05-11
```

---

### 2.12 Self-Review (Mandatory)

**Description**: Every agent task passes through a reviewer before completion.

**Review Checklist**:
```python
REVIEW_CHECKLIST = [
    "Has security posture improved or degraded?",
    "Are all modified files intentional?",
    "Did the change match user request exactly?",
    "Are tests still passing?",
    "Any new dependencies added?",
    "Any secrets accidentally exposed?",
    "Is rollback point available?"
]
```

**Output**:
```
🔍 Self-Review Report
═════════════════════
Status: ⚠️  WARNINGS

Warnings:
  • 2 unused imports in app.py
  • Test coverage decreased by 3%

Recommendations:
  • Run 'bridge optimize --remove-unused'
  • Add tests for new function

[Approve with warnings] [Request changes] [Block]
```

---

### 2.13 Closed Learning Loop

**Description**: System learns from outcomes to improve future performance.

**Loop**:
```
User Feedback
    │
    ▼
┌─────────────────────────────────────────┐
│ 1. RECORD                                │
│    • Store interaction in lessons_learned │
│    • Update success/failure metrics      │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ 2. PATTERN                               │
│    • Detect recurring issues             │
│    • Identify successful strategies      │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ 3. RECOMMEND                             │
│    • Suggest skill creation              │
│    • Adjust risk scores                  │
│    • Modify tool permissions             │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ 4. VALIDATE                              │
│    • Test on similar future tasks         │
│    • Track improvement metrics           │
└─────────────────────────────────────────┘
```

**NOT Autonomous**: All learning requires user confirmation before becoming active.

---

### 2.14 Token Budget Manager

**Description**: Automatic model routing based on task complexity. User NEVER sees or selects models.

**Profiles**:

| Profile | Model | Use Case | Cost |
|---------|-------|----------|------|
| `essential` | claude-haiku | Status checks, simple edits | $0.001/1K |
| `balanced` | claude-sonnet | General tasks | $0.003/1K |
| `quality` | claude-opus | Complex analysis | $0.015/1K |

**Auto-Selection Logic**:
```python
def select_model(task: str, context: dict) -> str:
    complexity = measure_complexity(task, context)
    if complexity < 0.3:
        return "claude-haiku"  # essential
    elif complexity < 0.7:
        return "claude-sonnet"  # balanced
    else:
        return "claude-opus"  # quality

def measure_complexity(task: str, context: dict) -> float:
    # Based on: token count, file count, recursion depth, pattern complexity
    score = 0.0
    score += len(task.split()) * 0.01
    score += context.get("file_count", 0) * 0.05
    score += context.get("nested_depth", 0) * 0.1
    return min(score, 1.0)
```

**Budget Tracking**:
```python
BUDGET_WARNING = 80  # % of monthly budget
BUDGET_LIMIT = 100   # hard cap

# Automatic rollback to essential when limit reached
# User sees only: "Token usage optimized automatically"
```

**Integration**:
- `ai_evaluator.py` — Extended with auto-model-select
- `config.py` — Budget profile settings
- Dashboard shows only: "Token: 45% used" (no model names)

---

### 2.15 Undecided Mode (Ne yapacağını bilmiyorum)

**Description**: When user input is vague, system does architectural analysis instead of blind code generation.

**Trigger Conditions**:
- User says "biraz karışık", "nasıl yapacağımı bilmiyorum"
- No specific files mentioned
- No clear success criteria
- New project context

**Flow**:
```
User: "Web sitemi hızlandırmak istiyorum ama nasıl yapacağımı bilmiyorum"
    │
    ▼
┌─────────────────────────────────────────┐
│ ANALYSIS MODE (not coding)              │
├─────────────────────────────────────────┤
│ 1. Project scan                         │
│    • Language, framework detection       │
│    • Entry points identified            │
│    • Performance hotspots found         │
│    • Dependencies analyzed              │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ 2. OPTIONS PRESENTATION                 │
├─────────────────────────────────────────┤
│ Possible approaches (ranked by impact): │
│                                          │
│ A. [55%] Lazy loading + code splitting  │
│    • Est. improvement: 40% faster        │
│    • Risk: low                          │
│    • Effort: 2 hours                    │
│                                          │
│ B. [30%] CDN for static assets         │
│    • Est. improvement: 25% faster       │
│    • Risk: very low                    │
│    • Effort: 30 minutes                 │
│                                          │
│ C. [15%] Database query optimization   │
│    • Est. improvement: 35% faster        │
│    • Risk: medium                       │
│    • Effort: 4 hours                    │
├─────────────────────────────────────────┤
│ [Choose A] [Choose B] [Explain more]    │
└─────────────────────────────────────────┘
```

**Output Format**:
```
🎯 Architectural Analysis Complete

Problem: Web site performansı
Root causes found: 3
  1. Large JS bundle (2.4MB) → code splitting recommended
  2. No asset caching → CDN recommended
  3. N+1 queries in API → query optimization recommended

Recommended approach: A (Code splitting + lazy loading)
Estimated improvement: 40%
Next step: [Apply] [Modify] [Details]
```

**Key Principle**: System proposes, user approves. Never starts coding without a plan.

---

## PART 3: Implementation Phases

### Phase 1: Foundation (1-2 weeks)

- [ ] **Autopilot Score** — Integrate 0-100 risk scoring into `run_shell`
- [ ] **Bridge Detective** — Error classification and investigation workflow
- [ ] **Permission Cards** — Replace raw command display with cards

**Files Modified**:
- `src/claude_bridge/_shell_run.py` — Add risk scoring
- `src/claude_bridge/tool_utils.py` — Add PermissionCard class
- `src/claude_bridge/detective.py` — NEW: Investigation workflow

---

### Phase 1.5: Budget & Uncertainty (1 week)

- [ ] **Token Budget Manager** — Automatic model routing (essential/balanced/quality)
- [ ] **Undecided Mode** — Architectural analysis when user is uncertain

**Files Modified**:
- `src/claude_bridge/ai_evaluator.py` — Add auto-model-select
- `src/claude_bridge/config.py` — Budget profile settings
- `src/claude_bridge/analysis_mode.py` — NEW: Architectural analysis

---

### Phase 2: Workflow (2-3 weeks)

- [ ] **Plan → Onay → Uygula → Test → Rapor** — Mandatory workflow
- [ ] **Snapshot/Rollback** — Checkpoint system
- [ ] **Audit Log** — Operation recording

**Files Modified**:
- `src/claude_bridge/workflow_engine.py` — NEW: State machine
- `src/claude_bridge/snapshot.py` — NEW: Checkpoint system
- `src/claude_bridge/audit.py` — NEW: Operation log

---

### Phase 3: Intelligence (3-4 weeks)

- [ ] **Intent Engine** — Vague input → specific actions
- [ ] **Project Map** — Auto-generate project understanding
- [ ] **Three-Layer Memory** — USER/PROJECT/LESSONS structure
- [ ] **Self-Review** — Mandatory review pass

**Files Modified**:
- `src/claude_bridge/intent_engine.py` — NEW: Intent parsing
- `src/claude_bridge/memory.py` — NEW: Memory management
- `src/claude_bridge/project_map.py` — NEW: Project analysis
- `src/claude_bridge/reviewer.py` — NEW: Self-review

---

### Phase 4: Multi-Agent (4-6 weeks)

- [ ] **Orchestrator** — Task decomposition
- [ ] **Sub-agents** — Specialized agents (git, security, debug, research)
- [ ] **Toolset Permissions** — Agent-based restrictions
- [ ] **Inter-agent communication** — Shared memory

**Files Modified**:
- `src/claude_bridge/orchestrator.py` — NEW: Main coordinator
- `src/claude_bridge/agents/` — NEW: Agent implementations
- `src/claude_bridge/permissions.py` — NEW: Permission matrix

---

### Phase 5: Skills (6-8 weeks)

- [ ] **Skill System** — Core infrastructure
- [ ] **Skill Registry** — Index and loading
- [ ] **Auto-Skill Creation** — Learn from completions
- [ ] **Skill Marketplace** — Import/export skills

**Files Modified**:
- `src/claude_bridge/skills/` — NEW: Skill system
- `src/claude_bridge/skill_registry.py` — NEW: Skill management
- `src/claude_bridge/skill_builder.py` — NEW: Auto-creation

---

## PART 4: Technical Decisions

### 4.1 Storage

| Data | Format | Location |
|------|--------|----------|
| Config | JSON | `.claude-bridge/config.json` |
| Memory | JSON (encrypted) | `.claude-bridge/memory.json` |
| Skills | JSON + Python | `.claude-bridge/skills/` |
| Snapshots | Tar/gz | `.claude-bridge/snapshots/` |
| Audit | JSONL | `.claude-bridge/audit/` |
| Logs | Markdown | `.claude-bridge/logs/` |

### 4.2 Security

- Memory encrypted at rest (Fernet symmetric encryption)
- Secrets in memory cleared after use
- Skills run in sandboxed subprocess
- Agent permissions enforced at runtime

### 4.3 Performance

- Lazy loading for skills
- Memory cache with TTL
- Async task distribution for agents
- Snapshot compression

---

## PART 5: Success Metrics

| Feature | Metric | Target |
|---------|--------|--------|
| Autopilot Score | Adoption rate | 80% of commands scored |
| Bridge Detective | Auto-resolve rate | 40% of errors |
| Workflow | User approval rate | 90% first-time |
| Snapshot | Rollback usage | 5% of tasks |
| Skills | Skill reuse rate | 3 uses/skill avg |
| Intent Engine | Correct interpretation | 85% |
| Memory | Lesson hit rate | 50% reduction in repeat errors |

---

## Appendix A: Competitor Analysis

| Feature | Claude Bridge | Hermes | Manus | Open Code |
|---------|--------------|--------|-------|-----------|
| Autopilot Score | 0-100 score | No | No | No |
| Permission Cards | Yes | No | No | No |
| Bridge Detective | Yes | No | No | No |
| Mandatory Workflow | Plan→Approve→Test | No | Partial | No |
| 3-Layer Memory | Yes | Partial | No | No |
| Auto-Skill (approved) | Yes | No | Yes | No |
| Intent Engine | Yes | No | No | No |
| Token Budget Manager | Auto model routing | No | No | No |
| Undecided Mode | Architectural analysis | No | No | No |

**Key Differentiators**:
1. **Autopilot Score** — Unique numerical risk format
2. **Permission Cards** — Human-readable UX
3. **Intent Engine** — Turkish language support
4. **Closed Learning Loop** — User-approved only
5. **Turkish Error Translation** — Native UX layer
6. **Auto Model Routing** — Invisible to user, automatic optimization
7. **Undecided Mode** — Proposes before coding

---

*Last Updated: 2026-05-11*
*Version: 0.1.0-draft*