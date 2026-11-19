# Appendix A: Evidence

> **[MACRO: Page Properties]** Status DRAFT · Owner <you>

**Purpose:** the commands run, files read and sources checked behind each claim. Long outputs sit in
**[MACRO: Expand]** blocks. Hostnames, IPs and tokens are redacted.

## Current state (from the deployment repo and cluster)

| Claim | Evidence | Date |
|---|---|---|
| Models deployed as plain manifests | `<repo path @ commit>` | |
| Replicas per model | `grep replicas:` output | |
| Image tags per env | `grep image:` output | |
| GPUs per model | `grep nvidia.com/gpu` output | |
| Weights PVC size/class/mode | PVC manifest | |
| Helper pod source and command | `<file>` | |
| Speech model image and ports | `<file>` | |
| How manifests are applied | `.gitlab-ci.yml` / playbook | |
| GPU Operator present | `kubectl get pods -A \| grep gpu-operator` | |
| Auth validated at Traefik | IngressRoute middlewares | |

> **[MACRO: Expand]** paste raw outputs here, one expand per command

## NVIDIA sources (checked 2026-11-19)

| Claim | Source |
|---|---|
| NeMo Microservices sunset 2026-10-01; "all new development has moved to NeMo Platform" | https://archive.docs.nvidia.com/nemo/microservices/latest/ |
| NIM Operator NeMo CRDs deprecated; Entity Store = "registration objects, or pointers, of the model data", "registry for the organizational entities, like namespaces and projects" | https://docs.nvidia.com/nim-operator/3.1.2/entity-store.html · v3.1.3 release notes |
| `NIMService.spec.storage.pvc` (reuse existing PVC); `spec.replicas` | https://github.com/NVIDIA/k8s-nim-operator, tag v3.1.4, `api/apps/v1alpha1/nimservice_types.go` |
| Rollout hard-coded `RollingUpdate`, `maxSurge: 0`, `maxUnavailable: 25%` | same repo, tag v3.1.4, `manifests/deployment.yaml` |
| Riva TTS sample for the operator | same repo, tag v3.1.4, `config/samples/nim/serving/standalone/routers/grpcroutes/llm.yaml` |
| Helix versions 0.5–0.10, no GA statement, Studio "alpha" | https://docs.nvidia.com/nemo-helix |
| NIM for LLMs supports Helm charts and the NIM Operator side by side | NIM for LLMs Kubernetes docs |
