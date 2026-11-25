# 3a. Ticket assessment

> **[MACRO: Page Properties]** Status DRAFT · Owner <author> · Last updated <date>

**Purpose:** each existing NeMo operator ticket assessed against what NVIDIA provides, with a verdict, a revised
scope and revised acceptance criteria; plus missing tickets.

> **[MACRO: Jira issues]** the 5 existing tickets (JQL `key in (…)`)

| Ticket | Verdict |
|---|---|
| Model store | **[STATUS: RE-SCOPE]** |
| Entity store | **[STATUS: FREEZE / SPLIT]** |
| Postgres backend | **[STATUS: CONDITIONAL]** |
| Model metadata | **[STATUS: RE-SCOPE]** |
| DEV→QA→PROD promotion | **[STATUS: RE-SCOPE]** |

## 1. Model store

- **As written:** manage model artefacts (weights, NIM images, configs); CRUD via the operator; persistence;
  integrate with the NeMo framework.
- **NVIDIA reality:** the closest match is **NeMo Deployment Management** (API to deploy, list, update and delete NIMs
  through the NIM Operator) plus **Entity Store** model records. Both are part of **NeMo Microservices, sunset
  2026-10-01**. The NIM Operator alone has no REST API, only CRDs. NIM images live in the registry, never in a NeMo
  store. Weights live in cache PVCs.
- **Verdict: re-scope.** "Model deployment and cache management via NIM Operator CRs in git": `NIMService` +
  `NIMCache` per model, per-env overlays, automated cache population (replacing the manual pre-populator step), images
  pinned by digest in the registry.
- **Revised ACs:** models are added, updated and removed by CR changes merged to git (listed with `kubectl get
  nimservices` and in the catalogue); caches survive restarts and can be rebuilt reproducibly; runbook documented.

## 2. Entity store

- **As written:** users, sessions, metadata; CRUD; persistence.
- **NVIDIA reality:** the NeMo Entity Store holds namespaces, projects, datasets and model records/pointers. It is
  **not a user or session store.** It needs Postgres + Data Store; the operator route is deprecated; the product is
  sunset.
- **Verdict: freeze / split.** (a) If Entity Store is already deployed, leave it running and build nothing new on it.
  (b) Users/sessions: a separate portal ticket, if needed at all.
- **Revised ACs:** (a) current use of Entity Store documented (who calls it, for what); (b) portal ticket defined
  separately if needed.

## 3. Postgres backend

- **As written:** Postgres for "operator state", schema/migrations, pooling/HA, backups, DEV/QA/PROD.
- **NVIDIA reality:** the **NIM Operator keeps no state in Postgres** (its state is Kubernetes objects). Postgres
  backs Entity Store and Data Store. NVIDIA documents no migrations, HA or backups; those are ours.
- **Verdict: conditional.** Only if the NeMo layer is kept long-term or moved to Helix (whose embedded Postgres is
  "not for production"). If NeMo services are already running on a Postgres, **add backups now** regardless.
- **Revised ACs (if kept):** Postgres per env with tested restore; HA in PROD; owner and runbook.

## 4. Model metadata

- **As written:** description, token limits, family, capabilities; exposed via operator API to Bifrost, the
  inference service and the UI; limits enforced via metadata.
- **NVIDIA reality:** no NVIDIA component exposes token limits to a gateway or enforces them. Context length is
  enforced by the NIM engine; rate/token limits are a gateway job. Entity Store model records are descriptive only.
- **Verdict: re-scope.** "Model catalogue": a versioned file in git per model (description, family, context window,
  max output, capabilities, limits per env) → generates Bifrost config (limits enforced there) and `models.json` for
  the UI and inference service. Preserve the existing `chat/<model>` served names; test the slash through Bifrost's
  `provider/model` naming.
- **Revised ACs:** all models have complete entries; Bifrost limits are generated from the catalogue; the catalogue is
  queryable (served JSON / Bifrost `/v1/models`).

> **[MACRO: Info panel]** Verified in lab (2026-11-25): a git catalogue generating Bifrost config works end to end, and limit changes propagate to a running gateway (`source_of_truth: config.json`), verified via read-back `GET /api/governance/rate-limits` (admin basic auth).

## 5. DEV → QA → PROD promotion

- **As written:** pipeline, gates (smoke tests before PROD), approvals/audit, reproducibility.
- **NVIDIA reality:** not provided by the NIM Operator, NeMo Microservices or Helix.
- **Verdict: keep the goal, re-scope the mechanism.** Digest-pinned versions per env in git; promotion by MR; smoke
  tests (see *Smoke tests*) gate QA → PROD; protected environments/approvals; audit = MR + deployment history.
- **Revised ACs:** unchanged in spirit: promotion logged who/when/what; smoke tests gate QA → PROD; identical
  artefacts across envs.

> **[MACRO: Info panel]** Verified in lab (2026-11-25): MR-based promotion with smoke evidence worked twice, dev to qa to prod. Promotion branches must use merge commits (not squash). "Require up to date" on env branches deadlocks the second promotion.

## Missing tickets / follow-on work

| # | Ticket | Why |
|---|---|---|
| N1 | Reconcile deployment repos/branches into one layout; main = source of truth per env | Content is spread across branches and repos |
| N2 | Automate platform steps 2–4 (Traefik, NIM Operator, GPU Operator), pinned versions; fix install order (GPU Operator first) | Manual; not reproducible |
| N3 | Automate NGC secret (non-plaintext) and cache population (NIMCache or Job) | Manual steps 10–11 |
| N4 | Define LLM + speech models as NIMService/NIMCache CRs in git; keep served names/Service names | Core of the migration |
| N5 | Bifrost in front of NIMs; NetworkPolicy so only Bifrost reaches NIMs | No gateway/limits; NIMs unauthenticated |
| N6 | Smoke-test suite + CI job (gate) | Needed by promotion |
| N7 | Argo/GitOps health checks, sync waves, cache prune protection (if Argo) | No built-in NIM health |
| N8 | Inventory of NeMo services in use + freeze/retire plan; engage NVIDIA account team | Sunset product |
| N9 | Backups for any Postgres already used by NeMo services | Data-loss risk now |
| N10 | Runbooks: install, operator upgrade, cache population, cutover/rollback | Operability |
| N11 | Monitoring parity for NIMs (NIM metrics, DCGM, alerts) | Visibility |
| N12 | Speech model: confirm NIM vs community image; operator path | Scope |
