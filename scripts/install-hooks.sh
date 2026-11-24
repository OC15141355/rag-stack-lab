#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
mkdir -p .githooks
ln -sf ../scripts/pre-commit.sh .githooks/pre-commit
chmod +x scripts/pre-commit.sh scripts/safety-check.sh
git config core.hooksPath .githooks
echo "hooks installed (core.hooksPath=.githooks)"
