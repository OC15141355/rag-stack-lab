# 1. Current deployment approach

> **[MACRO: Page Properties]**
> | Status | DRAFT |
> | Owner | <you> |
> | Last updated | <date> |
> | Parent | Model deployment: move to NVIDIA operator approach |

**Purpose:** how models are deployed today, which environments are affected, and what they depend on.

## Scope and method

- **Question:** what is required to move the Project's model deployment from the current approach to the
  NVIDIA-recommended NeMo microservices operator approach, across DEV, QA and PROD, and how this
  maps to the five existing NeMo operator tickets.
- **In scope:** the LLM NIMs (GLM 5.2, Nemotron 3 Super), the ASR model (scope to confirm),
  deployment, storage, metadata, DB, promotion.
- **Method:** current-state review with the team; NVIDIA docs and NIM Operator source code at tag
  v3.1.4; mapping each ticket's acceptance criteria to NVIDIA components.

## Current deployment approach

| Aspect | Current state | Evidence / source |
|---|---|---|
| Packaging | **Plain Kubernetes manifests** (no Helm, no operator) in a dedicated **deployment repo** | Team, 2026-11-19 |
| Applied by | Manifests live in a repo; **likely applied by Ansible** _(confirm: playbook/role or CI job referencing them)_ | Team, 2026-11-19 |
| Models | GLM 5.2 and Nemotron 3 Super (LLM NIMs); a **speech model, believed Whisper** (ASR; TTS possible) (barebones) | Team |
| Weights | On a **PVC**, populated **manually with a helper pod**, not automated | Team |
| Replicas | _Unknown_, likely 1 per model _(check `replicas:` in manifests)_ | Team |
| Configuration | Minimal; reportedly no context-length/tool-calling settings. The only notable setting is `NIM_SERVED_MODEL_NAME` (e.g. `chat/<model_name>`), which is the name consumers call | Team |
| Image versions | **DEV and QA track a release-candidate image; PROD is pinned to a specific image version** | Team |
| Metadata | None beyond the served model name | Team |
| Database | None for model deployment | Team |
| Promotion | Manual: PROD image version changed by hand _(process/approver TBC)_ | Inferred, _confirm_ |
| Request path | Portal → inference service → **NIM directly**; **no gateway, no rate limiting** today; Bifrost planned in front | Team, 2026-11-19 |
| Auth | Keycloak SSO; bearer token; validation believed to be at **Traefik** (forward-auth), backend may trust Traefik-injected identity headers _(confirm via IngressRoute middlewares)_ | Team + observation (port-forward bypass → 404 on user lookup) |
| GPUs per env | **8× H200** believed (what GLM 5.2 FP8 needs); **QA ≈ PROD** assumed for hardware and config _(confirm DEV)_ | Team |

**Environments affected:** DEV, QA and PROD are all affected. DEV and QA differ from PROD in image
pinning (release candidate vs fixed), so QA does not currently validate the exact artefact that runs
in PROD **(confirm whether the RC tag is re-pushed or mutable)**.

> **[MACRO: draw.io]** Current request path: browser → Traefik (Keycloak SSO) → portal → inference service → NIM (no gateway)

## Operational dependencies

| Dependency | Today | With NIM Operator | With NeMo stores (as ticketed) |
|---|---|---|---|
| **Storage** | Weights PVC per env, filled by helper pod | Same PVC reusable (`NIMService.spec.storage.pvc`, confirmed in v3.1.4 source); later `NIMCache` or an automated staging Job | Plus Data Store: RWX PVC for Git history, object storage for large files, Postgres for metadata |
| **Metadata** | Served model name only | Not provided by NVIDIA; needs a catalogue (git) feeding Bifrost | Entity Store model records (descriptive; no token-limit contract found) |
| **DB** | None | None (the operator keeps its state as Kubernetes objects) | **Postgres required** for Entity Store and Data Store; HA, backups, migrations are ours |
| **Promotion** | Manual image edit for PROD | Not provided; Git MRs + CI smoke gates + protected environments | Not provided |
| Images / registry | Harbor (assumed) | Plus operator image; pinned NIM digests | Plus Entity Store, Data Store images |
| Secrets | _(current method; plaintext `.env` seen elsewhere in the IaC)_ | NGC key (optional when caches pre-staged), pull secret | Plus DB creds, Data Store secrets (5 secret refs on the CRD) |
| Cluster scope | None | Operator CRDs + ClusterRole + GPU Operator ≥ 24.3.0 | Same |
