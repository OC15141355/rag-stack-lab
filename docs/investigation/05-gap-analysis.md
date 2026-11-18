# Gap analysis: current deployment vs NVIDIA's operator approach

A framework plus a generic draft, built from [03](03-nvidia-recommended-deployment.md)
and [04](04-nemo-entity-and-data-store.md). Copy it privately, then replace
the "current" column with evidence from your [current-state capture](02-current-state-capture.md).

## Summary (generic draft)

1. **"The NVIDIA-recommended NeMo microservices operator approach" is two
   things with different statuses.**
   - **NIM Operator for serving models** (`NIMCache`, `NIMService`): current
     and actively released. NVIDIA lists it alongside Helm as a supported way
     to deploy NIM LLMs, without calling one "the" recommendation (03 §1).
   - **NeMo microservices through the operator** (Entity Store, Data Store,
     Customizer, Evaluator, Guardrails CRDs): **deprecated** in the operator;
     NeMo Microservices itself was **sunset on 2026-10-01**. The successor
     (NeMo Platform, documented as NeMo Helix) is pre-1.0 (03 §2, 04 §7).
2. **There is no NVIDIA "model store".** Weights live in a `NIMCache` PVC;
   images live in a registry (NGC, mirrored into Harbor). Entity Store holds
   *pointers and records*, not artifacts (04 §3). Confirmed from NVIDIA's
   operator docs: Entity Store "manages the registration objects, or pointers,
   of the model data", "the central registry for the organizational entities,
   like namespaces and projects".
3. **Entity Store is not a user/session store.** Any user or session storage
   belongs to the portal's own database (04 §1).
4. **The operator has no REST "API"**: its interface is Kubernetes CRDs. No
   NVIDIA component exposes model metadata with token limits for a gateway to
   consume, and none enforces token limits from metadata (04 §5).
5. **No NVIDIA component provides DEV → QA → PROD promotion** with approvals
   and audit. That's a Git/CI/GitOps job (03 §5, 04 §6).
6. The real migration value is **lifecycle**: pinned profiles, cache
   pre-staging separate from serving, status conditions, scaling hooks and a
   consistent spec across environments (03 §4).

## 1. Current vs recommended

| Area | Current (fill in with evidence) | NVIDIA operator approach | Gap / change |
|---|---|---|---|
| How NIMs are defined | e.g. Helm values / manifests / Ansible templates | `NIMCache` + `NIMService` CRs | Rewrite per-model definitions as CRs |
| Who applies them | e.g. Ansible via GitLab CI per branch | Operator reconciles CRs; CRs applied by GitOps or Ansible | Decide the single owner of the CRs (Argo or Ansible); remove the old path per env |
| Weights | e.g. downloaded at pod start / pre-staged PVC | `NIMCache` downloads or uses a pre-populated PVC; air-gap supported | Pre-stage caches per env; size PVCs (~750 GB+ for the large model at FP8) |
| Profile selection | e.g. auto | Pinned by name in `NIMService` | Pin profiles; record them per env |
| Images | e.g. mirrored to Harbor by tag | Same; operator image added | Mirror the operator plus pinned NIM images |
| Prerequisites | e.g. GPU Operator vX? | GPU Operator required; cluster-scope CRDs/RBAC | Verify per env; get cluster-scope approval |
| Scaling | e.g. fixed replicas | `spec.scale` / HPA on custom metrics; scale-to-zero (3.1.3+) | Optional; decide per env |
| Health in GitOps | e.g. Deployment health | No built-in Argo health for NIM CRDs | Add Lua health checks and sync waves (cache before service); protect the cache PVC from pruning |
| Startup | e.g. probe timeouts | Operator startup-probe default 20 min | Raise for the large model; measure cold start |
| Model catalogue / metadata | e.g. hardcoded in gateway/UI | **Not provided** | Define one metadata source; generate gateway/UI config from it |
| Token / rate limits | e.g. none / gateway | **Not provided** (engine `max_model_len`; gateway budgets) | Configure in the gateway; keep context limits in the NIM spec |
| Promotion | e.g. branch merges | **Not provided** | Promote pinned versions via MRs with CI smoke-test gates and approvals |
| Entity/Data Store | e.g. none | Deprecated via operator; Helix pre-1.0 | Only if a workflow needs them (fine-tuning/eval); decide explicitly |
| Postgres | e.g. none / existing service | Required only for NeMo stores / Helix | Only needed if stores are adopted |
| Secrets | e.g. plaintext `.env` | NGC key + pull secret as K8s Secrets | Use an agreed secret path; don't add plaintext |
| Isolation | e.g. none | NIM has no client auth | NetworkPolicy: only the gateway reaches NIMs |

## 2. What changes, by layer

**Deployment**
- Install the NIM Operator (via the existing delivery path), CRDs first.
- Convert each model to `NIMCache` + `NIMService`.
- Retire the old Helm/manifest objects per environment (cutover, not dual
  ownership).

**Configuration**
- Pinned image tags (digests if supported: `UNVERIFIED`), pinned profiles,
  per-env values (replicas, resources, storage class).
- Argo health checks and sync waves, or Ansible ordering, so caches are ready
  before services.
- Gateway model config generated from one metadata source.

**Process**
- Promotion = an MR changing pinned versions for the next environment; QA
  smoke tests gate the PROD MR; MR approvals and git history = audit.
- Upgrade runbook: operator version, then CRDs, then NIM versions, in DEV
  first.
- Cache management runbook (pre-stage, verify, never prune casually).

**Per environment**
| | DEV | QA | PROD |
|---|---|---|---|
| Purpose in the migration | First install, learning, profile/cache validation | Rehearse cutover; smoke-test suite; prove parity with PROD hardware | Scheduled cutover window; rollback ready |
| Special care | Fast iteration | Must match PROD profiles | Change approval; capacity for cutover |

## 3. Planned work items vs reality

Generic themes. Map them to your real tickets privately.

| Theme | NVIDIA reality | Verdict | Suggested re-scope |
|---|---|---|---|
| **Model store**: weights, NIM images, configs; CRUD via operator | No such component. Weights → `NIMCache`; images → registry; config → CR spec | **Re-scope** | "Model deployment via NIM Operator": define `NIMCache` + `NIMService` per model, with pinned profile and image, persisted caches. ACs: models added/updated/removed via CR changes in git; caches survive restarts; documented runbook |
| **Entity store** for users, sessions, metadata | Entity Store holds NeMo organisational entities (namespaces, projects, model/dataset pointers), not users/sessions; deprecated via operator | **Split / defer** | (1) If users/sessions are needed, that belongs to the portal's DB: a separate ticket. (2) NeMo Entity Store only if a NeMo workflow (fine-tuning/eval) needs it, decided against the deprecation and Helix |
| **Postgres backend** for the stores | Needed only if NeMo stores or Helix are adopted; migrations, HA and backups are on you | **Defer / make conditional** | Keep only if (2) above is approved; reuse an existing Postgres service if one exists |
| **Model metadata** (description, token limits, family, capabilities) via operator API; limits enforced | Not an NVIDIA feature; no operator REST API | **Re-scope** | "Model catalogue": one versioned metadata file (git) per model → generates gateway config (limits enforced there) and the UI list; context limit set in the NIM spec. ACs: all models have entries; gateway limits derived from it; queryable (gateway `/v1/models` or a static endpoint) |
| **DEV → QA → PROD promotion** via operator, gates, approvals, audit | Not an NVIDIA feature | **Re-scope** | "Model promotion via GitOps": pinned versions per env in git; MR-based promotion; CI smoke tests against QA gate PROD; approvals on protected branches; audit = MR history. ACs unchanged in spirit |

## 4. Missing tickets / follow-on work (typical)

| # | Ticket | Why |
|---|---|---|
| N1 | Verify prerequisites per env (K8s/VKS version, GPU Operator version, storage classes, PSA/policies) | Hard prerequisites; unknowns block planning |
| N2 | Cluster-scope RBAC/CRD approval for the NIM Operator | Often the slowest dependency |
| N3 | Mirror the operator image and pinned NIM images; image/weights manifest | Air-gap |
| N4 | Pre-stage NIM caches per env; size PVCs; measure cold start | Large-model risk |
| N5 | GitOps integration: Argo health checks, sync waves, prune protection (or Ansible ordering) | No built-in health for NIM CRDs |
| N6 | NetworkPolicy: only the gateway reaches NIM services | NIM has no client auth |
| N7 | Secret path for the NGC key, pull secret and any DB creds (not plaintext) | Security |
| N8 | Smoke-test suite (chat, streaming, tool call, context limit) for promotion gates | Needed by promotion |
| N9 | Monitoring parity: NIM metrics, DCGM, dashboards, alerts for operator-managed NIMs | Don't lose visibility at cutover |
| N10 | Cutover and rollback plan per env | GPU capacity rarely allows side-by-side |
| N11 | Decision record: NeMo stores via deprecated CRDs vs Helix vs not needed | Stops work going into deprecated components |
| N12 | Runbooks: upgrade (operator/CRDs/NIM), cache management, troubleshooting | Operability |

## 5. Draft phasing and effort (generic; adjust after current-state capture)

| Phase | Outcome | Envs | Effort (assumptions below) |
|---|---|---|---|
| 0. Decide | Decision on NeMo stores / Helix (N11); tickets re-scoped; prerequisites verified (N1); RBAC requested (N2) | — | S (2–4 days) |
| 1. DEV | Operator installed; both models via `NIMCache` + `NIMService`; caches pre-staged; health checks; NetworkPolicy; secrets path | DEV | M–L (8–15 days) |
| 2. Catalogue + gates | Model metadata source → gateway config; smoke-test suite; promotion MR flow | DEV → QA | M (5–10 days) |
| 3. QA | Cutover rehearsal; parity with PROD profiles; runbooks | QA | M (4–8 days) |
| 4. PROD | Scheduled cutover with rollback; monitoring parity | PROD | M (4–8 days incl. window) |
| 5. Optional | NeMo stores or Helix, only if a workflow needs them, with Postgres (HA, backups) | DEV → … | L–XL (15–30+ days) |

Assumptions: GPU Operator already present in all envs; cluster-scope approval
within about a week; one engineer with part-time support from the person who
built the current setup; images and weights can be mirrored without new
network approvals. Each failed assumption moves an estimate up a size.

## 6. Questions this analysis can't answer without the team

From [01](01-questions-for-the-platform.md), the ones that change the verdicts:
A1 (the problem being solved), A3/H2 (NVIDIA account-team guidance), A4/A5
(which NeMo services, fine-tuning plans), C1/C2 (env topology and hardware),
D2/D3 (GPU Operator, cluster-scope approval), G1–G4 (metadata consumers,
limits, users/sessions).
