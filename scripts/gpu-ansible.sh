#!/usr/bin/env bash
# Run a bootstrap playbook in GPU-session mode. ALWAYS passes the session inventory and -e gpu_session=true, so a
# forgotten flag cannot point a Phase A playbook at the rented VM (or the reverse). Usage: scripts/gpu-ansible.sh playbooks/01-platform.yml [extra args]
set -euo pipefail
RG=${RG:-$HOME/.raglab-gpu}
[[ $# -ge 1 ]] || { echo "usage: $0 playbooks/NN-name.yml [ansible-playbook args]" >&2; exit 2; }
for a in "$@"; do
  case "$a" in
    -i|-i*|--inventory*|gpu_session=*|-e\ gpu_session*) echo "gpu-ansible: do not pass inventory or gpu_session; the wrapper sets both" >&2; exit 2;;
  esac
done
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)/lab/bootstrap"
exec ansible-playbook -i "$RG/inventory.ini" -e gpu_session=true "$@"
