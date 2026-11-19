# 3. Gap analysis

> **[MACRO: Page Properties]**
> | Status | DRAFT |
> | Owner | <you> |
> | Last updated | <date> |
> | Parent | Model deployment: move to NVIDIA operator approach |

**Purpose:** what differs between the current approach and NVIDIA's, and what must change. Ticket-by-ticket assessment is on the child page *3a*.


## Current vs NVIDIA approach

| Area | Current | NVIDIA operator approach | Change needed |
|---|---|---|---|
| Model definition | Plain manifests (Deployment/Service) | `NIMService` (+ `NIMCache`) CRs | Convert per model; keep Service name and `NIM_SERVED_MODEL_NAME` so consumers don't change |
| Weights | Manual helper pod → PVC | `NIMCache` download/pre-stage, or existing PVC via `spec.storage.pvc` | Phase 1: reuse PVC. Then automate staging (repeatable, checksummed) |
| Image pinning | RC tags in DEV/QA, specific version in PROD | Same pinned image/profile across envs | **Pin digests in all envs**; promote the exact digest QA tested |
| Profile selection | _TBC (auto?)_ | Pin profile in cache + service | Pin explicitly; confirm GPU parity per env |
| Metadata | Served name only | None provided (NeMo Entity Store is descriptive and deprecated) | Git model catalogue → generated Bifrost config + `models.json` |
| Token/rate limits | _TBC_ | None provided | Context limit in NIM config; rate/token limits in Bifrost |
| Promotion | Manual | None provided | MR-based promotion, smoke-test gate, protected-environment approvals |
| DB | None | None (NIM) / Postgres (NeMo stores) | Only if NeMo stores adopted |
| Health/GitOps | Deployment health | No Argo health for NIM CRDs | Add Lua health checks, sync waves, prune protection |
| Isolation | _TBC_ | NIM unauthenticated | NetworkPolicy, gateway-only |
| Speech (ASR/TTS) | Barebones manifest (Whisper believed) | **NVIDIA speech NIMs** (Whisper Large v3, Parakeet, Canary; Magpie TTS) fit the generic `NIMService` path (set `port: 9000`, `grpcPort: 50051`, `NIM_TAGS_SELECTOR`); operator ships a Riva TTS sample (v3.1.4, NIMService part commented out); no ASR sample. **Community Whisper is not a NIM**: keep as plain Deployment or replace with the Whisper NIM after an API test | Determine image source (A8); then choose path |

## What changes, by deployment, configuration and process

- **Deployment:** install GPU Operator (if missing) and NIM Operator per cluster; convert each
  model's manifests to `NIMService`; replace the helper-pod step with automated staging.
- **Configuration:** digest-pinned images; pinned profiles; per-env overlays (replicas, storage
  class, sizes); Argo health checks; NetworkPolicy; secrets via an agreed (non-plaintext) path.
- **Process:** promotion by MR with smoke-test gate and approvals; upgrade runbook (operator → CRDs
  → NIM, DEV first); cutover/rollback runbook per env; weight-staging runbook.
