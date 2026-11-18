# Risks and constraints

A starter register of risks that apply to most migrations of this kind.
Copy it privately, delete the ones that don't apply, and add the
platform-specific ones from your current-state capture.

Scoring: **Likelihood** and **Impact** each Low / Medium / High. **Rating** =
the higher of the two, bumped up one if both are High. Each risk needs an
owner and a mitigation, or an explicit "accepted".

## Strategic and vendor

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R1 | **Building on deprecated components.** NeMo Microservices sunset 2026-10-01; the operator's NeMo CRDs are deprecated. New work on Entity/Data Store via the operator may need redoing on Helix | H | H | Decide explicitly: (a) don't adopt the deprecated stores, (b) adopt as a short-lived bridge with an exit plan, or (c) evaluate Helix. Get the NVIDIA account team's position in writing |
| R2 | **Successor maturity.** Helix may be new or changing quickly; APIs may move | M | M | Pilot in DEV only; pin versions; keep the integration thin |
| R3 | **Requirement mismatch.** Planned items assume features NVIDIA components don't have (operator "API", user/session store, token enforcement, promotion workflow) | H | M | Re-scope items to the correct owner (gateway, pipeline, portal); see the gap analysis |
| R4 | **Vendor support boundaries.** Unsupported combinations (VKS + vGPU + operator version) may not get help | M | M | Check support matrices; record versions |

## Technical

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R5 | **Large-model cache handling.** A ~750 GB FP8 model makes NIMCache downloads, PVC sizing and cold starts slow and fragile | H | M | Pre-stage caches; measure cold start; size PVC with headroom; don't recreate caches casually |
| R6 | **Profile drift.** Auto-selected NIM profiles differ by GPU type between environments, so QA doesn't validate PROD | M | H | Pin profiles explicitly; match QA hardware to PROD or document the difference |
| R7 | **Two controllers, one resource.** Ansible/Helm and the operator (or Argo) both manage NIM objects and fight | M | M | One owner per layer; migrate per environment with a clean cutover |
| R8 | **Cluster-scope access.** The operator needs CRDs and ClusterRoles; approvals may be slow or refused | M | H | Raise early (D3 in the questions); prepare an RBAC summary |
| R9 | **GPU Operator prerequisites missing or old** in some env | M | H | Verify per env before planning |
| R10 | **Air-gap mirroring.** Operator, NIM and any NeMo images plus model caches all need mirroring; one missing image blocks the rollout | H | M | Build an image/weights manifest and a mirroring checklist; dry-run in DEV |
| R11 | **Capacity during cutover.** Running old and new side by side needs double GPUs; there usually aren't any | H | H | Cut over per env during a window; rehearse in DEV/QA; have a fast rollback |
| R12 | **Upgrade cadence.** The operator adds its own upgrade stream (operator, CRDs, NIMs) | M | M | Upgrade runbook; pin versions; test in DEV first |

## Data and security

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R13 | **Secrets.** New secrets (NGC key, pull secret, DB creds) added the same way as the existing plaintext `.env` | H | H | Agree a secret path before adding any (ansible-vault, CI variables, External Secrets) |
| R14 | **Unauthenticated NIM endpoints.** NIMs don't check client auth; anything in-cluster can bypass the gateway | M | H | NetworkPolicy so only the gateway reaches NIMs |
| R15 | **Postgres operations.** A new database is a new backup, HA, patching and on-call burden | M | M | Reuse an existing Postgres service if there is one; otherwise use an operator with tested backups and restores |
| R16 | **Audit requirements for promotion** not met by tooling alone | M | M | Use the existing change process (merge requests with approvals) as the audit log |

## Delivery

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R17 | **Scope creep** from "operator" to "full NeMo platform" | M | M | Phase it; separate the model-deployment migration from optional NeMo services |
| R18 | **Knowledge concentration.** One person understands the current deployment | M | H | Pair on it; write runbooks as you go |
| R19 | **Unknown current state.** Planning before the current state is documented | M | H | Finish current-state capture (02) first |

## Constraints (not risks: facts to plan around)

- GPU hardware per environment (type, count) is fixed in the short term.
- Restricted networking: no direct internet from some environments.
- Change management for PROD (approvals, windows).
- Tooling: Ansible + GitLab is the existing delivery path; Argo CD present.
- Team capacity and other priorities.

## Risk of *not* changing

Write these down too, so the comparison is fair. Examples: inconsistent
deployments across environments, manual upgrade steps, no reproducible model
pinning, and drift between branches.
