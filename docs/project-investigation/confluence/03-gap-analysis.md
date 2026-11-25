# 3. Gap analysis

> **[MACRO: Page Properties]** Status DRAFT · Owner <author> · Last updated <date>

**Purpose:** what differs between the current setup and NVIDIA's approach, and what must change in deployment,
configuration and process. The per-ticket assessment is on *3a*.

## Current vs NVIDIA approach

| Area | Current | NVIDIA approach (current parts) | Gap → change |
|---|---|---|---|
| GPU Operator | Installed manually | Required | **Automate install** (Ansible/GitOps), pin version |
| NIM Operator | Installed manually | Required | **Automate install**, pin version, upgrade runbook |
| Model definitions | LLM services applied by Ansible; possibly also via Deployment Management | `NIMService` (+ `NIMCache`) CRs | **One source of truth: NIM CRs in git**, per-env overlays |
| Weights | Cache pre-populator (manual) → RWX PVCs | `NIMCache` or existing PVC | **Automate cache population** (NIMCache or a Job), make it repeatable, protect PVCs |
| Model lifecycle API | NeMo Deployment Management (sunset) | None current (CRDs only) | **Freeze**; manage via git/CRDs |
| Inference endpoint | Inference service → NIM directly; NIM Proxy _TBC_ | Gateway of your choice | **Bifrost** in front; NetworkPolicy so only Bifrost reaches NIMs |
| Metadata | Served model name only | None current | **Git model catalogue** → Bifrost config + model list |
| Limits | None | None current | Context in NIM config; **rate/token limits in Bifrost** |
| Image pinning | RC tags DEV/QA, pinned PROD | Same pinned spec everywhere | **Digest-pin all envs** |
| Promotion | Manual | None provided | **MR promotion + smoke-test gates + approvals** |
| NeMo services | Deployed manually | Sunset / Helix | **Freeze**, then retire or migrate (decision) |
| Secrets | Mixed, some manual, plaintext seen | K8s Secrets | Agreed non-plaintext path |
| Repos/branches | Content spread across branches/repos | n/a | **Reconcile**: one repo layout, main = truth |
| GitOps health | n/a | No built-in NIM health in Argo | Custom health checks, sync waves |

> **[MACRO: Info panel]** Verified in lab (2026-11-25): a git catalogue generating Bifrost config works end to end, and limit changes propagate to a running gateway (`source_of_truth: config.json`), verified via read-back `GET /api/governance/rate-limits` (admin basic auth).
> **[MACRO: Info panel]** Verified in lab (2026-11-25): MR-based promotion with smoke evidence worked twice, dev to qa to prod. Promotion branches must use merge commits (not squash). "Require up to date" on env branches deadlocks the second promotion.

## What needs to change

**Deployment**
- Automate the manual steps: Traefik, GPU Operator, NIM Operator, NGC secret, cache population, NeMo (or its
  retirement).
- Define each model as `NIMService` (+ `NIMCache`) in git; keep Service names and `NIM_SERVED_MODEL_NAME` unchanged
  so consumers don't notice.
- Put Bifrost in front of the NIMs; apply a NetworkPolicy.

**Configuration**
- Pinned image digests and profiles; per-env overlays (replicas, storage class, sizes).
- A model catalogue that generates Bifrost config and limits.
- Argo health checks, sync waves, prune protection for caches (if Argo is used).

**Process**
- Promotion by merge request; smoke tests gate QA → PROD; protected-environment approvals; the MR history is the
  audit log.
- Runbooks: platform install, operator upgrades, cache population, cutover/rollback.
- Repo hygiene: one layout, environments as folders or overlays, main as the source of truth.

## Ticket coverage

See *3a. Ticket assessment*. In short, the existing tickets cover the **NeMo-layer** version of model management
(sunset) and **none of the automation, gateway or repo work**, which is where most of the real gap is.
