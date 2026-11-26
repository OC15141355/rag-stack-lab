# bootstrap/: the only Ansible left

Everything that runs on a cluster is rendered into `clusters/<env>/` and applied by CI (migration step 3) or
Argo CD (step 4). Ansible keeps only what must exist before Kubernetes can pull, schedule or decrypt anything,
and what cannot be expressed as a Kubernetes object:

| Task | Why it stays in Ansible | Done when |
|---|---|---|
| Node prerequisites: OS packages, kernel modules, host NVIDIA driver (`driver.enabled: false` in the GPU Operator values), container runtime | below Kubernetes; a driver bump is a planned outage per node | `nvidia-smi` passes on every GPU node |
| Registry trust: the internal registry's CA and pull credentials on every node | nodes pull from it before any Secret exists; no NGC in QA/PROD | a node pulls a digest from the internal registry |
| Weights transfer: copy a reviewed revision from the internal mirror into its PVC | moving 1.5 TB is a tracked operation, not a reconcile loop | the transfer log names the revision and MANIFEST.sha256 |
| Install Argo CD (migration step 4): chart + `argocd/config/argocd-cm.yaml` (health checks) + `argocd/config/cmp-plugin.yaml` as a repo-server sidecar with sops, then hand-apply `argocd/<env>/projects.yaml`, `root.yaml`, `weights.yaml` | Argo cannot install itself | `<env>-root` is Synced |
| Age key: put this environment's key in its runner's protected variable `SOPS_AGE_KEY_<ENV>` and in Argo's plugin Secret | the one secret that cannot be in git | `sops -d` works on that runner and in that Argo only |

## Weights: the exact order (every model, every environment)

1. **PVC**: CI `weights:<env>` (or Argo `<env>-weights`) applies `clusters/<env>/20-weights/*.yaml`: the PVC with
   reclaimPolicy Retain, and the verify script. It is empty.
2. **Transfer** (this directory's playbook): copy the revision named in the PVC's `platform-gitops/source-uri`
   annotation from the internal mirror into the PVC, including `MANIFEST.sha256`. Never into a PVC of another
   revision.
3. **Verify**: only when the transfer finished, run CI `verify:<env>` (or sync `<env>-weights-verify` by hand). It
   applies `clusters/<env>/20-weights/verify/`, and the Job checks the manifest hash, every file, and that no
   unlisted file exists, then writes the marker. A failed Job fails the step at once.
4. **Service**: CI `services:<env>` (or the services app). The NIMService's init container refuses to start without
   the marker, and the services job checks the verify Jobs first.

Not here: operators, CRDs, namespaces, policies, models, gateway, Secrets (all in git, rendered or SOPS). Any
Ansible task outside this table is a candidate for the catalogue.

Inventory files with real hosts are never committed. Keep playbooks idempotent and runnable from one
environment's runner at a time (that runner holds only that environment's key).
