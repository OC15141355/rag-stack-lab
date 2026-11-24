#!/usr/bin/env bash
# Runs Argo CD's own Lua engine on the fixtures. Needs argocd CLI v3.6.2.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
python3 - "$tmp/argocd-cm.yaml" <<'PY'
import sys, yaml
v = yaml.safe_load(open("lab/argocd/argocd-values.yaml"))
cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "argocd-cm"}, "data": v["configs"]["cm"]}
yaml.safe_dump(cm, open(sys.argv[1], "w"))
PY
fail=0
while read -r f want; do
  got=$(argocd admin settings resource-overrides health "tests/health/$f" --argocd-cm-path "$tmp/argocd-cm.yaml" 2>&1 | awk '/^STATUS:/{print $2}')
  [[ "$got" == "$want" ]] && echo "ok   $f $got" || { echo "FAIL $f got=$got want=$want"; fail=1; }
done < tests/health/expected.txt
exit $fail
