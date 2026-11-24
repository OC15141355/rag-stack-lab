#!/usr/bin/env bash
# git pre-commit hook: structural check on staged files + gitleaks on the staged diff.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# bash 3.2 compatible (macOS /bin/bash): no mapfile
staged=()
while IFS= read -r f; do staged+=("$f"); done < <(git diff --cached --name-only --diff-filter=ACMR)
[[ ${#staged[@]} -eq 0 ]] && exit 0
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
for f in "${staged[@]}"; do mkdir -p "$tmp/$(dirname "$f")"; git show ":$f" > "$tmp/$f" 2>/dev/null || true; done
uv run --quiet --with pyyaml python3 scripts/check_secrets.py --root "$tmp" "${staged[@]}"
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks git . --config .gitleaks.toml --no-banner --redact --staged
else
  command -v docker >/dev/null 2>&1 || { echo "pre-commit: need gitleaks or docker; refusing commit" >&2; exit 1; }
  docker run --rm -v "$tmp:/scan:ro" -v "$PWD/.gitleaks.toml:/cfg.toml:ro" \
    ghcr.io/gitleaks/gitleaks@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9 \
    dir /scan --config /cfg.toml --no-banner --redact \
  || { echo "pre-commit: gitleaks found secrets; refusing commit" >&2; exit 1; }
fi
