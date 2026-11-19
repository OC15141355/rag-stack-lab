# 3a. Ticket assessment (existing + new tickets)

> **[MACRO: Page Properties]**
> | Status | DRAFT |
> | Owner | <you> |
> | Last updated | <date> |
> | Parent | Model deployment: move to NVIDIA operator approach |

**Purpose:** each existing NeMo operator ticket assessed against what NVIDIA actually provides, with a verdict and revised scope; plus missing tickets.

> **[MACRO: Jira issues]** embed the 5 existing tickets here (JQL: key in (...))

| Ticket | Verdict |
|---|---|
| Model store | **[STATUS: RE-SCOPE]** |
| Entity store | **[STATUS: SPLIT / DEFER]** |
| Postgres backend | **[STATUS: CONDITIONAL]** |
| Model metadata | **[STATUS: RE-SCOPE]** |
| DEV→QA→PROD promotion | **[STATUS: RE-SCOPE]** |

## Ticket-by-ticket assessment

**1. Model store.** *Scope: model artefacts (weights, NIM images, configs), CRUD via operator, integration with NeMo framework.*
- NVIDIA reality: there is **no NVIDIA "model store"**. The operator exposes **no CRUD API**; its
  interface is Kubernetes CRDs. The nearest NeMo pieces are the Data Store (HF-compatible file store
  for fine-tuning and evaluation workflows) and Entity Store model records (pointers). **Neither
  stores NIM images**, and no documented path was found for a NIM to serve weights *from* the Data
  Store. Implementing it as written would not change how GLM/Nemotron are actually deployed.
- Covered work: none of the real deployment change.
- **Verdict: re-scope** → *"Model deployment and weight staging via NIM Operator"*: `NIMService`
  per model (reusing existing PVCs first), automated and repeatable weight staging (`NIMCache` or
  a staging Job) replacing the helper pod, images in Harbor pinned by digest.
  Revised ACs: models added/updated/removed by CR changes in git; weights survive restarts and can
  be rebuilt reproducibly; runbook documented.

**2. Entity store.** *Scope: users, sessions, metadata; CRUD; persistence.*
- NVIDIA reality: the NeMo Entity Store "manages the registration objects, or pointers, of the
  model data" and is "the central registry for the organizational entities, like namespaces and
  projects" (NIM Operator docs). It is **not a user/session store**, it needs Postgres + Data Store,
  and its operator CRD is **deprecated**.
- **Verdict: split / defer.** (a) Users/sessions belong to the portal's own DB, so that's a separate
  ticket if needed. (b) NeMo Entity Store only if a NeMo workflow (fine-tuning/evaluation) is
  approved, decided against the deprecation and Helix.

**3. Postgres backend.** *Scope: Postgres for "operator state", schema + migrations, pooling/HA, backups.*
- NVIDIA reality: the **operator keeps no state in Postgres** (its state is Kubernetes objects).
  Postgres is required by the Entity Store and Data Store services. NVIDIA documents no migrations,
  HA or backups for it; those would be ours. Embedded Postgres is dev-only.
- **Verdict: conditional / defer** until ticket 2(b) is approved. If it is, reuse an existing
  Postgres service if one exists; HA + tested backups mandatory for PROD.

**4. Model metadata.** *Scope: description, token limits, family, capabilities; exposed via operator API to Bifrost, inference service, UI; limits enforced from metadata.*
- NVIDIA reality: **no operator API**; **no NVIDIA component exposes token limits to a gateway or
  enforces them from metadata**. Context window is enforced by the NIM engine (its max model length
  config); rate/token limits by the gateway (Bifrost). Entity Store model records are descriptive,
  and no context-window field was found in them.
- **Verdict: re-scope** → *"Model catalogue"*: one versioned catalogue in git (description, family,
  context window, max output, capabilities, limits per env); generated Bifrost config (limits
  enforced there) and `models.json` for the UI and inference service; NIM context set from it.
  Revised ACs: all models have complete entries; Bifrost limits derived from the catalogue;
  catalogue queryable (served JSON or Bifrost `/v1/models`). Must preserve the existing
  `chat/<model_name>` served names; test the slash through Bifrost's `provider/model` naming.

**5. DEV → QA → PROD promotion.** *Scope: pipeline, gates, approvals/audit, reproducibility.*
- NVIDIA reality: **not provided** by the operator, NeMo microservices or Helix.
- Current gap: RC tags in DEV/QA vs pinned PROD means QA may not test what PROD runs.
- **Verdict: keep the goal, re-scope the mechanism** → *"Model promotion via GitOps"*: digest-pinned
  versions per env in git; MR to promote; smoke tests (chat, streaming, tool calls, context, negative
  auth) gate QA → PROD; protected environments/approvals; audit = MR + deployment history.
  ACs unchanged in spirit.

## Missing tickets / follow-on work

| # | Ticket | Why |
|---|---|---|
| N1 | Verify prerequisites per env: K8s/VKS version, GPU Operator, storage classes, Pod Security policies | Hard prerequisites |
| N2 | Cluster-scope approval + install of NIM Operator (DEV → QA → PROD) | Operator is cluster-scoped |
| N3 | Mirror operator + pinned NIM images to Harbor; image/weights manifest | Air-gap |
| N4 | Automate weight staging (replace helper pod); measure cold start | Reproducibility; big-model risk |
| N5 | Convert model manifests to `NIMService`, preserving Service names and served model names | The core migration |
| N6 | Argo CD health checks, sync waves, cache prune protection (or Ansible ordering) | No built-in NIM health in Argo |
| N7 | NetworkPolicy: gateway-only access to NIMs | NIM has no client auth |
| N8 | Secret delivery for NGC key / pull secret (non-plaintext) | Security |
| N9 | Smoke-test suite + CI job as promotion gate | Needed by ticket 5 |
| N10 | Monitoring parity (NIM metrics, DCGM, alerts) | Don't lose visibility at cutover |
| N11 | Cutover/rollback runbook per env (single-replica upgrade = outage) | Operator rollout behaviour |
| N12 | ASR: confirm scope; confirm operator support for the ASR NIM; ASR smoke check | New scope found |
| N13 | Decision record: NeMo stores via deprecated CRDs vs Helix vs not needed; engage NVIDIA account team | Prevents building on sunset components |
| N14 | (If needed) Portal user/session storage | Was mis-assigned to Entity Store |

> **[MACRO: Jira issues]** filter for the new tickets once created
