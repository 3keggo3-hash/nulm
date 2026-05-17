# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Active development |

## Security Model

Nulm is a **policy-gated local runner**, not an OS or container sandbox. It provides
layered security controls:

- **Fail-closed by default** — mutating tools and shell commands require explicit approval.
- **Path boundaries** — all file operations resolve against configured project roots.
- **Command filtering** — dangerous patterns (`sudo`, `rm -rf`, `chmod 777`, pipe-to-shell) are
  blocked at the guard layer.
- **Sensitive file protection** — `.env`, `.pem`, `.key`, `id_rsa` files are blocked from
  reads/writes/patches.
- **Symlink hardening** — copy/move operations reject symlink attacks; writes use `O_CREAT | O_EXCL`.
- **Audit logging** — all tool calls are recorded as structured JSONL with secret masking.

See [docs/security-model.md](docs/security-model.md) for the full security documentation.

## Reporting a Vulnerability

**Do not report security vulnerabilities through public GitHub issues.**

Instead, please report them through GitHub's private vulnerability reporting:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Fill in the details of the vulnerability.

Alternatively, you may open a confidential advisory via
[GitHub Security Advisories](https://github.com/3keggo3-hash/nulm/security/advisories/new).

### What to Include

- A description of the vulnerability and its potential impact.
- Steps to reproduce or a proof-of-concept.
- The affected version(s).
- Any suggested mitigations or fixes.

### Response Timeline

- **Acknowledgment:** within 48 hours.
- **Initial assessment:** within 5 business days.
- **Resolution timeline:** depends on severity; critical issues will be prioritized.

## Scope

The following are considered in scope for security reports:

- Bypass of guard policy rules (command filtering, path boundaries, sensitive file protection).
- Symlink-based escape attacks against file operations.
- TOCTOU race conditions in write operations.
- Secret leakage through audit logs or tool responses.
- ReDoS through regex patterns in policy rules.
- SSRF through the URL reader tool.

The following are **out of scope**:

- Issues in optional dependencies (Tree-sitter, Pillow, PyPDF2, tiktoken) — report to upstream.
- Attacks requiring physical access or compromised Python runtime.
- Theoretical vulnerabilities without a practical exploit path.
- Denial of service through excessive resource consumption in a local-only tool.
