# bootstrap/: the only Ansible left

Everything that runs on a cluster is rendered into `clusters/<env>/` and applied by CI (migration step 3) or
Argo CD (step 4). Ansible keeps only what must exist before Kubernetes can pull, schedule or decrypt anything,
and what cannot be expressed as a Kubernetes object:

| Task | Why it stays in Ansible | Done when |
|---|---|---|
| Node prerequisites: OS packages, kernel modules, host NVIDIA driver (`driver.enabled: false` in the GPU Operator values), container runtime | below Kubernetes; a driver bump is a planned outage per node | `nvidia-smi` passes on every GPU node |
| Registry trust: the internal registry's CA and pull credentials on every node | nodes pull from it before any Secret exists; no NGC in QA/PROD | a node pulls a digest from the internal registry |
| Weights transfer: copy a reviewed revision from the internal mirror into its PVC (`20-weights`) | moving 1.5 TB is a tracked operation, not a reconcile loop | the verify Job (`tools/verify_weights.py`) passes |
| Install Argo CD (migration step 4): chart + `argocd/config/argocd-cm.yaml`, then hand-apply `argocd/<env>/projects.yaml`, `root.yaml`, `weights.yaml` | Argo cannot install itself | `<env>-root` is Healthy |
| Age key: place this environment's key on its runner and in Argo's KSOPS secret | the one secret that cannot be in git | `sops -d` works on that runner only |

Not here: operators, CRDs, namespaces, policies, models, gateway, Secrets (all in git, rendered or SOPS). Any
Ansible task outside this table is a candidate for the catalogue.

Inventory files with real hosts are never committed. Keep playbooks idempotent and runnable from one
environment's runner at a time (that runner holds only that environment's key).
