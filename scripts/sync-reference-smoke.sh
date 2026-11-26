#!/usr/bin/env bash
# reference/platform-gitops/tools/smoke.py is a COPY of lab/smoke/smoke.py (the template must be self-contained).
# This regenerates it: the source plus a one-line provenance header. CI runs it and fails on any git diff.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
src=lab/smoke/smoke.py dst=reference/platform-gitops/tools/smoke.py
{ head -n 1 "$src"
  echo "# COPY of rag-stack-lab lab/smoke/smoke.py; regenerate with scripts/sync-reference-smoke.sh, never edit here."
  tail -n +2 "$src"; } > "$dst"
