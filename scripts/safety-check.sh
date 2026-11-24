#!/usr/bin/env bash
# Run before `git add`. Exit 0 = PASSED. Scans worktree (tracked + untracked, not ignored) and the index.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
GITLEAKS_IMAGE="ghcr.io/gitleaks/gitleaks@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9"
fail=0
uv run --quiet --with pyyaml python3 scripts/check_secrets.py || fail=1
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks dir . --config .gitleaks.toml --no-banner --redact || fail=1
  gitleaks git . --config .gitleaks.toml --no-banner --redact --staged || fail=1
elif command -v docker >/dev/null 2>&1; then
  docker run --rm -v "$PWD:/repo" -w /repo "$GITLEAKS_IMAGE" dir /repo --config /repo/.gitleaks.toml --no-banner --redact || fail=1
else
  echo "safety-check: neither gitleaks nor docker available; structural check only (NOT a pass)" >&2
  exit 2
fi
[[ $fail -eq 0 ]] && echo "PASSED" || { echo "FAILED"; exit 1; }
