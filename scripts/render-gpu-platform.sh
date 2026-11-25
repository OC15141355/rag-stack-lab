#!/usr/bin/env bash
# Render the two hand-applied GPU-platform charts with the EXACT inline values from their Applications and
# summarise them (scripts/helm_kinds.py). Default: write lab/gpu/argocd/rendered/*.txt.
# --check: diff against the committed files instead (exit 1 on any difference, e.g. a mutated Helm repo).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
out=lab/gpu/argocd/rendered; tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
check=0; [[ "${1:-}" == --check ]] && check=1
rc=0
render() {  # <application file> <namespace> <output name>
  uv run -q --with pyyaml python3 - "$1" "$tmp/values.yaml" > "$tmp/src" <<'PY'
import sys, yaml
s = yaml.safe_load(open(sys.argv[1]))["spec"]["source"]
yaml.safe_dump(s["helm"]["valuesObject"], open(sys.argv[2], "w"))
print(s["helm"]["releaseName"], s["chart"], s["targetRevision"], s["repoURL"])
PY
  read -r release chart ver repo < "$tmp/src"
  helm template "$release" "$chart" --repo "$repo" --version "$ver" -n "$2" --include-crds -f "$tmp/values.yaml" \
    | uv run -q --with pyyaml python3 scripts/helm_kinds.py > "$tmp/$3"
  if [[ $check == 1 ]]; then
    diff -u "$out/$3" "$tmp/$3" && echo "unchanged $out/$3" || rc=1
  else
    cp "$tmp/$3" "$out/$3"; echo "wrote $out/$3"
  fi
}
render lab/gpu/argocd/hand-applied/raglab-gpu-operator.yaml gpu-operator gpu-operator-v26.7.3.txt
render lab/gpu/argocd/hand-applied/raglab-nim-operator.yaml raglab-system k8s-nim-operator-3.1.4.txt
exit $rc
