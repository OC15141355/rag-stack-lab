#!/usr/bin/env bash
# Runs Argo CD's own Lua engine on the template's health checks (reference/platform-gitops/argocd/config/argocd-cm.yaml)
# against tests/reference/health/*.yaml. Needs the argocd CLI.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
cm=reference/platform-gitops/argocd/config/argocd-cm.yaml dir=tests/reference/health
fail=0
nfix=$(ls "$dir"/*.yaml | wc -l | tr -d ' ')
nexp=$(grep -c . "$dir/expected.txt")
[[ "$nfix" == "$nexp" ]] || { echo "FAIL fixture count $nfix != expected.txt lines $nexp"; exit 1; }
while read -r f want; do
  got=$(argocd admin settings resource-overrides health "$dir/$f" --argocd-cm-path "$cm" 2>&1 | awk '/^STATUS:/{print $2}')
  [[ "$got" == "$want" ]] && echo "ok   $f $got" || { echo "FAIL $f got=$got want=$want"; fail=1; }
done < "$dir/expected.txt"
exit $fail
