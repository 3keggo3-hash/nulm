# X (Twitter) posts — copy-paste ready

Attach images from `assets/social/` where noted.

---

## Pinned post (launch)

**Image:** `assets/social/nulm-post-launch.png`

**Text:**

Nulm is a local MCP server for developers who want AI clients inside a project — without unrestricted filesystem or shell access.

✓ Path-safe file ops + patches
✓ Guarded shell (blocks sudo, curl|bash, .env reads, …)
✓ Audit log of every tool call

```bash
pip install nulm
nulm install --simple
```

Works with Claude Desktop, Cursor, VS Code.

Alpha · MIT · feedback welcome ↓
https://github.com/3keggo3-hash/nulm

---

## Post 2 — security angle

**Text only (no image):**

Most MCP setups give the model broad local access.

Nulm starts fail-closed: mutating tools need approval, risky shell patterns are blocked, sensitive paths like `.env` are denied, and everything is logged.

Not an OS sandbox — a policy-gated local runner.

`pip install nulm`

---

## Post 3 — Windows

**Text:**

Windows users: core Nulm MCP works natively.

If `nulm[recommended]` fails (Tree-sitter DLL), install core only:

```bash
py -m pip install nulm
nulm install --simple
```

WSL = full parity (dashboard terminal + indexing).

`nulm doctor` shows platform notes.

---

## Post 4 — demo prompt

**Text:**

After `nulm install`, try in Claude Desktop:

"Use Nulm to inspect auth.py in my project and list any security risks before changing code."

Nulm keeps work inside configured roots and logs what ran.

---

## Post 5 — thread starter (optional)

**1/4** I built Nulm because I wanted MCP power without handing an AI client the keys to my whole machine.

**2/4** It's Python, stdio MCP, local-only. File tools respect project roots. Shell goes through analysis + guard rules. Audit JSONL for replay.

**3/4** `nulm install` writes Claude Desktop / VS Code config. `nulm doctor` checks your OS and optional deps.

**4/4** Alpha on PyPI: https://pypi.org/project/nulm/ — GitHub issues open. What guard rule is missing in your stack?

---

## Turkish pinned variant

**Görsel:** `nulm-post-launch.png`

Nulm: AI istemcisine proje içinde çalıştırırken dosya ve shell erişimini sınırlayan yerel MCP sunucusu.

✓ Güvenli dosya / patch
✓ Guarded shell
✓ Audit log

```bash
pip install nulm
nulm install --simple
```

Claude Desktop · Cursor · VS Code

https://github.com/3keggo3-hash/nulm
