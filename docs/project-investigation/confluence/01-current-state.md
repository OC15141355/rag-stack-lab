# 1. Current state

> **[MACRO: Page Properties]** Status DRAFT · Owner <author> · Last updated <date>

**Purpose:** how models and the platform are deployed today, which environments are affected, and the operational
dependencies. Facts come from the deployment repos and the team, with evidence in *Appendix A*.

## Platform install sequence (as documented)

| Step | Layer | Component | How it's applied | Automated? |
|---|---|---|---|---|
| 1 | Platform | Registry credentials | Ansible | ✅ |
| 2 | Platform | Traefik ingress | Manual | ❌ |
| 3 | Platform | NIM Operator | Manual | ❌ |
| 4 | Platform | GPU Operator (v25.10.0) | Manual | ❌ |
| 5 | Foundation/data | Volcano CRDs + storage | Ansible | ✅ |
| 6 | Foundation/data | Bootstrap service | Ansible | ✅ |
| 7 | Foundation/data | Monitoring stack | Ansible | ✅ |
| 8 | Foundation/data | OpenSearch cluster (operator + cluster) | Ansible + manual | ◐ |
| 9 | Application | ML libraries population | Manual | ❌ |
| 10 | Application | NGC secret | Manual | ❌ |
| 11 | Application | Model cache population (cache pre-populator, RWX PVCs) | Manual | ❌ |
| 12 | Application | LLM services | Ansible | ✅ |
| 13 | Application | NeMo microservices | Manual | ❌ |
| 14 | Application | App services + UI | Ansible | ✅ |

**8 of 14 steps are fully or partly manual**, including every NVIDIA-specific step except the LLM services.

> **[MACRO: Note panel]** Step order matters: the NIM Operator (3) is installed before the GPU Operator (4) in the
> documented sequence. NVIDIA lists the GPU Operator as a prerequisite of the NIM Operator. Confirm whether the order
> is real or just how the list was written.

## What's in the repos

| Area | Found | Notes |
|---|---|---|
| Operators folder | `gpu-operator-v25.10.0`, `k8s-nim-operator`, `nemo-deployment-management`, `opensearch-operator`, `opensearch-cluster`, operator overrides | Vendored operator installs |
| NIM Operator CRDs | `apps.nvidia.com` CRDs: NIMCache, NIMService, NIMBuild, NIMPipeline, … | Operator is present; CRs for models _TBC_ |
| NeMo | `nemo-deployment-management` with charts; a `nemo-common` chart (templates for HPA, RBAC, Service) | Deployment Management deploys NIMs through the NIM Operator (NVIDIA docs) |
| Model cache | `cache-prepopulator` with RWX PVC manifests | Manual step 11 |
| Model manifests | LLM service manifests applied by Ansible; `NIM_SERVED_MODEL_NAME` (e.g. `chat/<model>`) is the main setting | Whether these are NIMService CRs or plain Deployments: _TBC_ |
| Platform deployment | `platform-deployment` | |
| Branches | Relevant content found on a branch, not necessarily main | Source of truth per env _TBC_ |

## Models

| Model | Type | Notes |
|---|---|---|
| GLM 5.2 | LLM NIM | 8× H200 believed (FP8 profile) |
| Nemotron 3 Super | LLM NIM | |
| Whisper (believed) | Speech (ASR) | Barebones; NIM vs community image _TBC_ |

Image versions: **DEV and QA use a release-candidate image; PROD is pinned to a specific version.**

## Request path and access

- Portal → inference service → **NIM directly. No gateway or rate limiting today**; Bifrost is planned.
- User identity via Keycloak SSO, validated at the ingress (Traefik) _(confirm middleware)_.

> **[MACRO: draw.io]** Current: Browser → Traefik (SSO) → Portal → Inference service → NIM Services (GLM, Nemotron,
> Whisper); NIM Operator + Deployment Management + cache PVCs alongside.

## Environments

| | DEV | QA | PROD |
|---|---|---|---|
| Image tags | Release candidate | Release candidate | Pinned |
| Hardware/config | _TBC_ | ≈ PROD (assumed) | 8× H200 (believed) |
| Install method | Same 14-step sequence, manual steps per env | ← | ← |

## Operational dependencies

| Dependency | Current state |
|---|---|
| Storage | RWX PVCs for model cache, populated manually by the cache pre-populator |
| Metadata | Only the served model name |
| Databases | Whatever the deployed NeMo services require (Entity Store needs Postgres) _TBC which_ |
| Promotion | Manual: PROD image changed by hand |
| Registry | Registry credentials via Ansible; NGC secret manual |
| Secrets | Mixed (Ansible, manual); plaintext `.env` seen in IaC |
| Monitoring | Monitoring stack via Ansible |
| GPU scheduling | Volcano CRDs installed |
