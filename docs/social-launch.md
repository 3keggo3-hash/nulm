# Social launch copy

Draft posts for Nulm (`pip install nulm`). Adjust links and tone per subreddit rules.

Repository: https://github.com/3keggo3-hash/nulm  
PyPI: https://pypi.org/project/nulm/

---

## X (Twitter) — short

**Post 1**

I built Nulm — a local MCP server that lets AI clients work inside your repo without unrestricted filesystem/shell access.

- Path-safe file ops + patches
- Guarded shell (`shell=False`, blocked `sudo`, `curl|bash`, etc.)
- Audit log of every tool call
- Works with Claude Desktop, Cursor, VS Code

`pip install nulm` → `nulm install --simple`

Alpha, MIT, feedback welcome: https://github.com/3keggo3-hash/nulm

**Post 2 (thread hook)**

Most MCP setups give the model broad local access. Nulm is the opposite: fail-closed by default, approvals for mutating tools, structured audit trail.

Not a sandbox — a policy-gated local runner. macOS/Linux/WSL best tested; Windows core MCP works too.

---

## X — Turkish

**Kısa**

Nulm: AI istemcisine proje klasöründe çalışma izni verirken dosya/shell erişimini sınırlayan yerel MCP sunucusu.

- Guarded shell + patch
- Audit log
- Claude Desktop / Cursor / VS Code

`pip install nulm` → `nulm install --simple`

https://github.com/3keggo3-hash/nulm — alpha, geri bildirim arıyorum.

---

## Reddit — r/Python, r/LocalLLaMA, r/MachineLearning

**Title:** `[Project] Nulm — local MCP server with guarded filesystem/shell access and audit logging (Python 3.10+)`

**Body:**

I've been working on **Nulm**, a local-first MCP server for developers who want an AI client (Claude Desktop, Cursor, VS Code, etc.) to operate inside a project **without** handing it unrestricted filesystem or shell access.

**What it does today (core, tested):**
- Read/list/search files within configured project roots
- Apply SEARCH/REPLACE patches with preview
- Run shell commands through a guarded path (`shell=False`, blocks `sudo`, `rm -rf`, `curl|bash`, sensitive paths like `.env`)
- Structured audit logging (JSONL) with replay
- `nulm install` writes MCP client config for Claude Desktop / VS Code / generic stdio

**What it is not:** an OS/container sandbox. It's a policy-gated local runner — fail-closed by default, mutating tools need approval unless you explicitly opt in.

**Install:**
```bash
pip install nulm
nulm install --simple
```

Optional extras (`nulm[recommended]`) add Tree-sitter indexing, PDF/image readers, token helpers. On Windows, start with core `nulm` if optional native deps fail; WSL recommended for full parity.

**Links:**
- GitHub: https://github.com/3keggo3-hash/nulm
- PyPI: https://pypi.org/project/nulm/

Alpha / MIT. I'm actively looking for feedback from real MCP setups — bugs, missing guard rules, client integration pain points. Issues and Discussions welcome.

---

## Reddit — r/ClaudeAI, r/cursor

**Title:** `Local MCP layer for Claude/Cursor: path boundaries, guarded shell, audit trail (Nulm)`

**Body:**

If you use Claude Desktop or Cursor with MCP and worry about the model having too much local access, I built **Nulm** as a middle layer:

1. Configure allowed project roots
2. File read/write/patch only inside those roots (`.env`, keys blocked)
3. Shell commands analyzed and blocked for high-risk patterns before execution
4. Every tool call logged — you can replay and review later

Setup is two commands:
```bash
pip install nulm
nulm install --target claude-desktop --project-dir /path/to/your/project
```
Then restart the client and start a new chat.

Works on macOS/Linux; Windows core MCP is supported (WSL if you want dashboard terminal + optional Tree-sitter without DLL headaches).

Looking for people running this in real workflows — what guard rules are missing? Which MCP clients break?

https://github.com/3keggo3-hash/nulm

---

## Reddit — r/mcp

**Title:** `Nulm — stdio MCP server for guarded local file/shell tools + audit (Python)`

**Body:**

Sharing **Nulm**, a Python MCP server focused on **local execution with guardrails** rather than remote tool hosting.

**Tools (standard profile):** `read_file`, `list_directory`, `search_in_files`, `patch_file`, `run_shell`, `index_codebase`, `find_relevant_files`, workflows, etc.

**Security model:**
- Path resolution against `CLAUDE_BRIDGE_PROJECT_DIR` + `CLAUDE_BRIDGE_ALLOWED_ROOTS`
- Custom guard policy JSON (`.claude-bridge-guard.json`)
- Client-managed approval or local auto-approve (explicit opt-in)
- Audit JSONL with replay

**Generic stdio entry:**
```json
{
  "command": "<python-from-nulm-install>",
  "args": ["-m", "claude_bridge.mcp_server"],
  "env": {
    "CLAUDE_BRIDGE_PROJECT_DIR": "/absolute/path",
    "CLAUDE_BRIDGE_AUTO_APPROVE": "0",
    "CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL": "1"
  }
}
```

`nulm setup` / `nulm install` generates this for Claude Desktop, VS Code, and generic clients.

PyPI: `nulm` | GitHub: https://github.com/3keggo3-hash/nulm

Happy to register on smithery/mcp.get if there's interest — feedback on schema size and tool profiles especially welcome.

---

## Hacker News — Show HN

**Title:** `Show HN: Nulm – MCP server with guarded local file/shell access and audit logging`

**Body:**

Nulm is a Python MCP server that wraps AI clients with path-safe file operations, guarded shell execution, and audit logging — no remote service required.

Problem: many MCP setups expose broad filesystem/shell access to the model. Nulm starts fail-closed: mutating tools and shell need approval; dangerous commands and sensitive paths are blocked by default; everything is logged.

Install: `pip install nulm && nulm install --simple`

GitHub: https://github.com/3keggo3-hash/nulm

Alpha quality — CI on Linux/macOS/Windows. Looking for feedback from production MCP users.

---

## Posting checklist

- [ ] Pin GitHub repo description + topics (`mcp-server`, `nulm`, `developer-tools`)
- [ ] Verify PyPI page shows correct author and README
- [ ] Post when CI is green on `windows-latest`
- [ ] Respond to comments with `nulm doctor` for Windows setup help
- [ ] Do not claim OS-level sandboxing — say "policy-gated local runner"
