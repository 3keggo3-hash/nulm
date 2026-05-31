#!/usr/bin/env bash
# Optional local hook helper: strip Cursor co-author trailers before commit.
# Install: cp scripts/strip-cursor-coauthor.sh .git/hooks/prepare-commit-msg && chmod +x .git/hooks/prepare-commit-msg
set -euo pipefail
msg_file="${1:?}"
if [[ "$(uname -s)" == "Darwin" ]]; then
  sed -i '' '/cursoragent@cursor\.com/Id' "$msg_file"
  sed -i '' '/^Made-with: Cursor/Id' "$msg_file"
else
  sed -i '/cursoragent@cursor\.com/Id' "$msg_file"
  sed -i '/^Made-with: Cursor/Id' "$msg_file"
fi
