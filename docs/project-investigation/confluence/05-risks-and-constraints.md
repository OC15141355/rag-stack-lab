# 5. Risks and constraints

> **[MACRO: Page Properties]** Status DRAFT · Owner <author> · Last updated <date>

**Purpose:** the risks of making the change (and of not making it), and the constraints to plan around.
L = likelihood, I = impact.

## Risks of the change

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R1 | **Building on the sunset NeMo layer** (Deployment Management, Entity Store, Data Store, NIM Proxy); redo on Helix | H | H | Freeze it; build new model management on NIM Operator CRs; decision record; ask the NVIDIA account team |
| R2 | **Tickets assume capabilities in the wrong place** (operator API, user/session store, metadata-driven limits, operator promotion) | H | M | Re-scope as on *3a* |
| R3 | **Single-replica upgrades are outages** (operator rollout hard-coded `maxSurge: 0`) | H | M | Treat NIM upgrades as windows; replicas where GPUs allow |
| R4 | **Two controllers for the same NIMs** (Ansible-applied manifests, Deployment Management, GitOps) fight or drift | M | H | One owner per model: NIM CRs in git; retire the other paths per env |
| R5 | **Deleting a NIMCache deletes its weights PVC**; re-populating ~750 GB in an air-gap is slow | M | H | Prune/Delete protection; separate pre-staged PVCs; cache runbook |
| R6 | **Profile drift between envs** (QA doesn't validate PROD) | M | H | Pin profiles; match QA hardware to PROD |
| R7 | **Cutover needs GPUs you don't have spare** | H | M | Per-env windows; rehearsed rollback; keep PVCs |
| R8 | **Repo/branch sprawl** hides the real source of truth; changes land in the wrong place | H | M | Reconcile first (N1) |
| R9 | **New secrets added the old way** (manual/plaintext) | H | H | Agree a secret path before adding any |
| R10 | **Operator/CRD upgrade stream** (GPU Operator, NIM Operator, NIMs) | M | M | Pinned versions; upgrade runbook; DEV first |
| R11 | **Knowledge concentration**: manual steps known by few people | M | H | Automate and write runbooks as you go |

## Risks of not changing

| Risk | Impact |
|---|---|
| Environments can't be rebuilt reproducibly (8 of 14 install steps manual) | Slow recovery, config drift, hard audits |
| QA validates release-candidate images, not PROD's artefact | Untested changes reach PROD |
| No gateway, limits or metadata in front of the models | No usage control or attribution; any in-cluster client can call NIMs directly |
| Continued reliance on sunset NeMo services | No fixes from NVIDIA; forced migration later under pressure |
| Postgres behind NeMo services without tested backups _(if so)_ | Data loss |

## Constraints

- Fixed GPU hardware per environment (8× H200 nodes for the large model).
- Restricted network: images and weights mirrored in; no direct NGC from some envs.
- Existing delivery tooling: Ansible + GitLab (branches); some manual steps.
- PROD change approvals and windows.
- Team capacity; the person(s) who know the manual steps.
