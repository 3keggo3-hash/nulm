#!/usr/bin/env bash
# Release quality gate for Nulm.
# Usage: ./scripts/release-gate.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

# Use the local venv Python or fall back to python3
CB_PYTHON="${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}"
CB_PYTHON="${CB_PYTHON:-python3}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
TOTAL=0
SKIP=0

check() {
    local label="$1"
    shift
    TOTAL=$((TOTAL + 1))
    printf "  %-50s" "$label"
    if "$@" >/dev/null 2>&1; then
        printf "${GREEN}PASS${NC}\n"
        PASS=$((PASS + 1))
    else
        printf "${RED}FAIL${NC}\n"
        FAIL=$((FAIL + 1))
    fi
}

check_optional() {
    local label="$1"
    shift
    TOTAL=$((TOTAL + 1))
    printf "  %-50s" "$label"
    if "$@" >/dev/null 2>&1; then
        printf "${GREEN}PASS${NC}\n"
        PASS=$((PASS + 1))
    else
        printf "${YELLOW}SKIP${NC}\n"
        SKIP=$((SKIP + 1))
    fi
}

cd "$PROJECT_DIR"

echo "============================================"
echo "  Nulm - Release Quality Gate"
echo "============================================"
echo ""

# --- Lint & Type ---
echo "[1/6] Lint & Type"
check "  ruff check ." ruff check .
check "  mypy src" mypy src

# --- Tests ---
echo ""
echo "[2/6] Tests"
check "  pytest" pytest -q

# --- Policy validate (example) ---
echo ""
echo "[3/6] Policy Validate (example)"
POLICY_EXAMPLE=$(mktemp /tmp/cb-policy-XXXXXX.json)
cat > "$POLICY_EXAMPLE" <<'EOF'
{
  "rules": [
    {
      "name": "block-sudo",
      "scope": "run_shell",
      "conditions": [
        {"type": "regex", "field": "command", "patterns": ["sudo"]}
      ],
      "action": "deny",
      "message": "sudo is not allowed"
    }
  ]
}
EOF
check "  policy validate (JSON)" "$CB_PYTHON" -m claude_bridge.cli policy validate --path "$POLICY_EXAMPLE"

POLICY_YAML_EXAMPLE=$(mktemp /tmp/cb-policy-XXXXXX.yaml)
cat > "$POLICY_YAML_EXAMPLE" <<'EOF'
rules:
  - name: block-rm-rf
    scope: run_shell
    conditions:
      - type: regex
        field: command
        patterns: ["rm\\s+-rf"]
    action: deny
    message: "rm -rf is not allowed"
EOF
check_optional "  policy validate (YAML)" "$CB_PYTHON" -m claude_bridge.cli policy validate --path "$POLICY_YAML_EXAMPLE"
rm -f "$POLICY_EXAMPLE" "$POLICY_YAML_EXAMPLE"

# --- Audit replay smoke ---
echo ""
echo "[4/6] Audit & Replay Smoke"
check "  audit summary" "$CB_PYTHON" -m claude_bridge.cli audit summary
check "  replay --help" "$CB_PYTHON" -m claude_bridge.cli replay --help

# --- Package metadata ---
echo ""
echo "[5/6] Package Metadata"
check "  pyproject.toml exists" test -f pyproject.toml
check "  README.md exists" test -f README.md
check "  version is set" "$CB_PYTHON" -c "
import sys
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib
with open('pyproject.toml', 'rb') as f:
    d = tomllib.load(f)
assert d['project']['version']
"
check_optional "  build package" "$CB_PYTHON" -m build --no-isolation
check_optional "  twine check dist/*" "$CB_PYTHON" -m twine check dist/*

# --- Import smoke ---
echo ""
echo "[6/6] Import Smoke"
check "  import claude_bridge" "$CB_PYTHON" -c "import claude_bridge"
check "  import cli" "$CB_PYTHON" -c "from claude_bridge.cli import main"
check "  import server" "$CB_PYTHON" -c "from claude_bridge.server import mcp"
check "  python -m claude_bridge --help" "$CB_PYTHON" -m claude_bridge --help

echo ""
echo "============================================"
printf "  Results: ${GREEN}%d passed${NC}, " "$PASS"
if [ "$FAIL" -gt 0 ]; then
    printf "${RED}%d failed${NC}" "$FAIL"
else
    printf "%d failed" "$FAIL"
fi
if [ "$SKIP" -gt 0 ]; then
    printf ", ${YELLOW}%d skipped${NC}" "$SKIP"
fi
printf " (total: %d)${NC}\n" "$TOTAL"
echo "============================================"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
