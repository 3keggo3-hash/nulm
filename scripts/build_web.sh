#!/bin/bash
set -e

WEB_DIR="$(cd "$(dirname "$0")/../web" && pwd)"
TARGET_DIR="$(cd "$(dirname "$0")/../src/claude_bridge/web" && pwd)"

echo "Building web dashboard (outputs to src/claude_bridge/web)..."
cd "$WEB_DIR"

npm install --silent
npm run build

echo "Done. Built files in $TARGET_DIR:"
ls -la "$TARGET_DIR"