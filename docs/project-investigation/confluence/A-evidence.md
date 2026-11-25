# Appendix A: Evidence

> **[MACRO: Page Properties]** Status DRAFT · Owner <author>

**Purpose:** the sources behind each claim. Long outputs sit in **[MACRO: Expand]** blocks. Hostnames, IPs and
tokens are redacted.

## Project (repos, team)

| Claim | Evidence | Date |
|---|---|---|
| 14-step install sequence with manual steps 2–4, 8 (partly), 9–11, 13 | Platform deployment notes in the deployment repo `<path>` | 2026-11-20 |
| Operators vendored: gpu-operator-v25.10.0, k8s-nim-operator, nemo-deployment-management, opensearch-operator, opensearch-cluster | `<repo>/operators/` on branch `<branch>` | 2026-11-20 |
| NIM Operator CRDs present (NIMCache, NIMService, NIMBuild, NIMPipeline, …) | `<repo>/…/crds/` | 2026-11-20 |
| `nemo-common` chart (HPA, RBAC, Service templates) | `<repo>/…/nemo-deployment-management/charts/` | 2026-11-20 |
| Cache pre-populator with RWX PVCs | `<repo>/…/cache-prepopulator/` | 2026-11-20 |
| `NIM_SERVED_MODEL_NAME` = `chat/<model>` | LLM service manifests `<path>` | 2026-11-19 |
| DEV/QA RC tags; PROD pinned | Team; manifests `<path>` | 2026-11-19 |
| No gateway / rate limiting | Team | 2026-11-19 |

> **[MACRO: Expand]** raw command outputs from the return sheet, one per command

## NVIDIA sources (checked 2026-11-19/20)

| Claim | Source |
|---|---|
| NeMo Microservices sunset 2026-10-01; "all new development has moved to NeMo Platform" | https://archive.docs.nvidia.com/nemo/microservices/latest/ |
| Deployment Management: "Provides an API to deploy NIM on a Kubernetes cluster and manage them through the NIM Operator"; NIM Proxy: "unified endpoint"; Entity Store: "namespaces, projects, datasets, and models" | https://archive.docs.nvidia.com/nemo/microservices/25.9.0/about/index.html |
| Deployment Management requires the NIM Operator; configures NIM Service `scale.hpa` | https://archive.docs.nvidia.com/nemo/microservices/25.9.0/set-up/deploy-as-microservices/deployment-management.html |
| Operator NeMo CRDs deprecated; Entity Store = "registration objects, or pointers, of the model data" | https://docs.nvidia.com/nim-operator/3.1.2/entity-store.html · release notes v3.1.3 |
| `NIMService.spec.storage.pvc`, `spec.replicas` | https://github.com/NVIDIA/k8s-nim-operator tag v3.1.4 `api/apps/v1alpha1/nimservice_types.go` |
| Rollout `RollingUpdate`, `maxSurge: 0`, `maxUnavailable: 25%` | same repo, tag v3.1.4, `manifests/deployment.yaml` |
| Helix versions 0.5–0.10, no GA statement, Studio "alpha" | https://docs.nvidia.com/nemo-helix |
| Speech NIMs (ports 9000/50051, `NIM_TAGS_SELECTOR`); Riva TTS operator sample | docs.nvidia.com/nim/speech/latest; operator tag v3.1.4 `config/samples/…/grpcroutes/llm.yaml` |

## Lab evidence

| Fact | Where verified |
|---|---|
| NIM Operator 3.1.4 runs without a GPU; scaled-to-zero NIMService needs a custom Argo health check | PR #6, #9, #10; findings doc, "Acceptance status" |
| Operator ClusterRole reads/writes Secrets, creates pods cluster-wide | PR #6, #9; findings doc, "Things that affect work" |
| Bifrost `key_ids` deny-by-default; `args` break entrypoint; prompt logging default | PR #5, #8, #9; findings doc, "Things that affect work" |
| Catalogue generates Bifrost config; rate-limit change propagates (30 to 28, read-back 28 in dev/qa/prod) | PR #19, #20, #21; findings doc, "Acceptance status" row 3 |
| MR promotion dev to qa to prod with smoke evidence; merge commits required | PR #14, #15, #20, #21; findings doc, "Things that affect work" |
| Smoke 9 passed / 1 skipped / 0 failed per env; gateway limit marker; reasoning-token budget | PR #12, #13, #16; findings doc, "Acceptance status" row 2 and "Live with real key" |
| GitHub push protection misses `nvapi-` keys | Findings doc, "Acceptance status" row 6 |
| Secret change via `envFrom` needs `rollout restart` | PR #12; findings doc, "Live with real key" |

