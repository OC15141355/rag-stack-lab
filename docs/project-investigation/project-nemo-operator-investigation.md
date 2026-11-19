# Project: moving model deployment to the NVIDIA NeMo microservices operator approach

**Investigation findings** · Status: DRAFT for review · Author: Declan · Date: 2026-11-19
Sources checked: NVIDIA NIM Operator docs and source (v3.1.4), NIM for LLMs docs, archived NeMo
Microservices docs (25.9.0), NeMo Helix docs. Every NVIDIA claim below was checked on 2026-11-19;
anything not confirmed from a source is marked **(unverified)**.

> Working draft. "Project" is a placeholder name.

---

## 0. Summary for the team

**Bottom line.** The NVIDIA operator approach is two separate things. They have different
statuses, and the tickets mix them up:

1. **NIM Operator for deploying the models** (`NIMCache` + `NIMService`). This is current, actively
   released (v3.1.4), and a clear improvement over our hand-written manifests and manually
   populated weights PVC. **Recommend adopting it.**
2. **NeMo microservices through the operator** (Entity Store, Data Store and friends).
   **NVIDIA has deprecated these operator CRDs** (NIM Operator 3.1.3 release notes), and
   **NeMo Microservices was sunset on 2026-10-01** ("all new development has moved to NeMo
   Platform", now documented as NeMo Helix, which is pre-1.0). **Recommend not building new work
   on these**, unless NVIDIA confirms a supported path.

**How the five tickets fare against what NVIDIA actually provides:**

| Ticket | Deliverable as written? | Main reason |
|---|---|---|
| Model store | **No, as written** | NVIDIA has no "model store". Weights → NIM Operator cache/PVC; images → Harbor; there is no CRUD in the operator |
| Entity store | **Partly** | NeMo Entity Store exists (deprecated route) but holds namespaces/projects/model and dataset *pointers*, **not users/sessions** |
| Postgres backend | **Only if Entity/Data Store are adopted** | The operator itself keeps no state in Postgres; the NeMo services do |
| Model metadata | **No, as written** | No "operator API"; no NVIDIA component holds token limits for Bifrost or enforces them |
| DEV→QA→PROD promotion | **No, as written** | No NVIDIA promotion workflow. Has to be GitLab/Argo with gates and approvals |

**Recommendation in one line:** move model serving to the NIM Operator (reusing the existing
weights PVCs first), automate weight staging, pin images by digest in every environment, put model
metadata in a git catalogue that feeds Bifrost, and promote via merge requests gated by smoke
tests. Defer the NeMo stores and Postgres until a workflow needs them, and evaluate Helix then.
Rough effort: **~25–40 person-days** for the recommended path across DEV/QA/PROD, versus
**~55–90+** for the tickets as written (section 7).

**Decisions needed:** (1) whether to build on the deprecated NeMo CRDs; (2) whether ASR is in
scope; (3) the re-scoped tickets (section 5.3).

---

## 1. Scope and method

- **Question:** what is required to move the Project's model deployment from the current approach to the
  NVIDIA-recommended NeMo microservices operator approach, across DEV, QA and PROD, and how this
  maps to the five existing NeMo operator tickets.
- **In scope:** the LLM NIMs (GLM 5.2, Nemotron 3 Super), the ASR model (scope to confirm),
  deployment, storage, metadata, DB, promotion.
- **Method:** current-state review with the team; NVIDIA docs and NIM Operator source code at tag
  v3.1.4; mapping each ticket's acceptance criteria to NVIDIA components.

## 2. Current deployment approach (AC: how they are deployed; environments affected)

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

## 3. Operational dependencies (AC)

| Dependency | Today | With NIM Operator | With NeMo stores (as ticketed) |
|---|---|---|---|
| **Storage** | Weights PVC per env, filled by helper pod | Same PVC reusable (`NIMService.spec.storage.pvc`, confirmed in v3.1.4 source); later `NIMCache` or an automated staging Job | Plus Data Store: RWX PVC for Git history, object storage for large files, Postgres for metadata |
| **Metadata** | Served model name only | Not provided by NVIDIA; needs a catalogue (git) feeding Bifrost | Entity Store model records (descriptive; no token-limit contract found) |
| **DB** | None | None (the operator keeps its state as Kubernetes objects) | **Postgres required** for Entity Store and Data Store; HA, backups, migrations are ours |
| **Promotion** | Manual image edit for PROD | Not provided; Git MRs + CI smoke gates + protected environments | Not provided |
| Images / registry | Harbor (assumed) | Plus operator image; pinned NIM digests | Plus Entity Store, Data Store images |
| Secrets | _(current method; plaintext `.env` seen elsewhere in the IaC)_ | NGC key (optional when caches pre-staged), pull secret | Plus DB creds, Data Store secrets (5 secret refs on the CRD) |
| Cluster scope | None | Operator CRDs + ClusterRole + GPU Operator ≥ 24.3.0 | Same |

## 4. NVIDIA-recommended approach (high level) (AC)

### 4.1 Status first

| Component | Status (2026-11-19) | Source |
|---|---|---|
| NIM Operator: `NIMCache`, `NIMService` (+ `NIMPipeline`, `NIMBuild`) | **Current**, v3.1.4 | NIM Operator release notes / GitHub |
| NIM Operator: NeMo CRDs (`NemoEntitystore`, `NemoDatastore`, `NemoCustomizer`, `NemoEvaluator`, `NemoGuardrail`) | **Deprecated** ("deprecating support for the NeMo Microservices CRDs and deployments in the next release"; 3.1.3: "is deprecated") | NIM Operator docs, Entity Store page; release notes |
| NeMo Microservices (the product) | **Sunset 2026-10-01**; docs archived; "contact your NVIDIA account team" | archive.docs.nvidia.com |
| Successor: NeMo Platform / NeMo Helix | Pre-1.0 (0.x), UI "alpha" | docs.nvidia.com/nemo-helix |

Note: NVIDIA's NIM for LLMs docs list Helm charts and the NIM Operator side by side for Kubernetes,
without naming one as *the* recommendation.

### 4.2 Required operator components and services

- **Always:** NVIDIA GPU Operator (≥ 24.3.0); NIM Operator (Helm chart `nvidia/k8s-nim-operator`,
  cluster-scoped CRDs + controller); per model, a `NIMService` and (optionally) a `NIMCache`.
- **For the NeMo microservices approach as ticketed, additionally:** Entity Store (`NemoEntitystore`,
  needs Postgres + a Data Store endpoint), Data Store (`NemoDatastore`, needs Postgres, an RWX PVC,
  object storage, several secrets), and an external Postgres per environment.

### 4.3 Deployment prerequisites

| Area | Requirement |
|---|---|
| Kubernetes | ≥ 1.26 per the NIM docs (README says ≥ 1.28 for the operator; use the stricter one). VKS support not explicitly listed by NVIDIA **(unverified)** |
| GPU Operator | ≥ 24.3.0; driver mode on VKS (vGPU/passthrough) per VMware + NVIDIA docs |
| Storage | PVC for weights (GLM 5.2 at FP8 ≈ 750 GB+, so size ~1.5 TiB with headroom); RWO fine for single-replica, RWX for multi-replica/multi-node; the NeMo Data Store needs RWX + object storage |
| DB | None for NIM. Postgres for Entity/Data Store (external; embedded is dev-only) |
| Networking | NIM has **no client auth**, so a NetworkPolicy should allow only Bifrost (and monitoring) to reach NIM Services; intra-node NVLink for TP8 |
| RBAC | Cluster-scope install (CRDs, ClusterRole); namespace-scope for CRs |
| Secrets / config | NGC API key + image pull secret (NGC key optional when everything is pre-cached, v3.1.3+); DB creds if NeMo stores |
| Air-gap | Mirror operator + NIM images to Harbor; pre-stage weights; `NIMCache` without `authSecret` when fully cached |

### 4.4 Environment and promotion model

NVIDIA documents **no DEV → QA → PROD promotion model** for NIMs or NeMo microservices. The
standard pattern on Kubernetes is per-environment overlays of the same pinned spec (image digest,
model profile, served name), promoted through Git with CI gates. Argo CD needs custom health
checks for NIM CRDs, which it doesn't ship.

Two operator facts that shape the environment model (confirmed in operator source v3.1.4):
- **Upgrades of a single-replica NIM are outages.** The Deployment strategy is hard-coded
  `RollingUpdate`, `maxSurge: 0`, `maxUnavailable: 25%`, and there is no spec field to change it.
- **Deleting a `NIMCache` deletes its PVC (the weights).** Protect caches from GitOps pruning.

## 5. Gap analysis (AC)

### 5.1 Current vs NVIDIA approach

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

### 5.2 What changes, by deployment, configuration and process

- **Deployment:** install GPU Operator (if missing) and NIM Operator per cluster; convert each
  model's manifests to `NIMService`; replace the helper-pod step with automated staging.
- **Configuration:** digest-pinned images; pinned profiles; per-env overlays (replicas, storage
  class, sizes); Argo health checks; NetworkPolicy; secrets via an agreed (non-plaintext) path.
- **Process:** promotion by MR with smoke-test gate and approvals; upgrade runbook (operator → CRDs
  → NIM, DEV first); cutover/rollback runbook per env; weight-staging runbook.

### 5.3 Ticket-by-ticket assessment (AC: which existing tickets cover the work)

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

### 5.4 Missing tickets / follow-on work (AC)

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

## 6. Risks and constraints (AC)

| Risk | L | I | Mitigation |
|---|---|---|---|
| Building on deprecated NeMo CRDs / sunset product | H | H | Don't adopt without a decision record and NVIDIA's written position (N13) |
| Tickets assume features NVIDIA doesn't have | H | M | Re-scope as in 5.3 |
| Upgrades are outages for single-replica 8-GPU models (`maxSurge: 0`, hard-coded) | H | M | Treat upgrades as windows; consider replicas where GPUs allow |
| QA validates RC images, not PROD's artefact | M | H | Digest pinning + MR promotion |
| Manual weight staging is not reproducible | H | M | Automate (N4) |
| Large-model cache size/cold start (~750 GB) | H | M | Pre-stage; size PVC; measure cold start in DEV |
| Cluster-scope approval delays | M | H | Raise early (N2) |
| GPU capacity prevents side-by-side cutover | H | M | Per-env cutover windows; rollback plan; keep PVCs |
| Argo pruning a `NIMCache` deletes weights | M | H | Prune/Delete protection annotations |
| NIM endpoints reachable bypassing Bifrost | M | H | NetworkPolicy (N7) |
| New secrets added in plaintext | H | H | Agree a secret path first (N8) |
| ASR NIM support under the operator unknown | M | M | Verify (N12) |
| Operator adds an upgrade stream | M | M | Pin versions; upgrade runbook |

**Constraints:** fixed GPU hardware per env; restricted networking and Harbor mirroring; existing
Ansible + GitLab branch delivery; PROD change approvals; team capacity.

## 7. Recommendation (AC)

**Option chosen: NIM Operator for serving + GitOps for metadata and promotion; NeMo stores
deferred.** Alternatives considered: (0) stay as-is with fixes (digest pinning, staging
automation); (2) also deploy NeMo Entity/Data Store via the deprecated CRDs as a bridge;
(3) NeMo Helix now: pre-1.0 (0.5–0.10 listed, no GA statement, Studio "alpha"); an agent/fine-tuning/eval control plane, not a serving replacement; its Inference Gateway documents no rate limits/budgets, so it doesn't replace Bifrost; launches NIMs via its own deployments plugin, with no stated NIM Operator integration; migration guidance = "contact your account team". Verdict: not yet for a serving-only platform; time-boxed trial if fine-tuning/eval is wanted.

### Phasing and effort (assumptions below)

| Phase | Outcome | Envs | Effort |
|---|---|---|---|
| 0. Decide and prep | Decision record (N13); tickets re-scoped; prerequisites verified (N1); cluster-scope approval requested (N2); ASR scope (N12) | — | S: 2–4 days |
| 1. DEV migration | Operator installed; GLM + Nemotron as `NIMService` on **existing PVCs**; same served names; NetworkPolicy; Argo health; secrets path | DEV | M: 5–10 days |
| 2. Pinning, catalogue, gates | Digest pinning in all envs; model catalogue → Bifrost config; smoke tests in CI; promotion MR flow | DEV → QA | M: 5–10 days |
| 3. QA cutover | Rehearsed cutover + rollback; QA pinned to the same artefacts PROD will get | QA | S–M: 3–6 days |
| 4. PROD cutover | Window cutover; monitoring parity | PROD | S–M: 3–6 days |
| 5. Weight staging automation | Helper pod replaced by `NIMCache` or a staging Job; reproducible rebuild per env | all | M: 4–8 days |
| 6. Optional | NeMo stores or Helix + Postgres (HA/backups), only if a workflow needs them | DEV → … | L–XL: 15–30+ days |

**Recommended path (phases 0–5): ~22–44 person-days.**
**Tickets as written (Entity Store + Data Store + Postgres per env + custom metadata integration +
promotion, on deprecated CRDs, plus the serving migration that is still needed):
~55–90+ person-days**, with redo risk when the CRDs are removed.

Assumptions: GPU Operator present or quick to install in all envs; cluster-scope approval within about a
week; manifests are simple (confirmed "barebones"); one engineer plus part-time support from whoever
built the current setup; ASR excluded or trivial. Each failed assumption moves a phase up one size.

**What would change this recommendation:** NVIDIA confirms a supported, near-term path for the
NeMo stores; a fine-tuning/evaluation workflow is approved; Helix reaches GA with a migration guide.

## 8. Open questions

| # | Question | Owner |
|---|---|---|
| Q1 | What problem is the move meant to solve (repeatability, upgrades, support, a feature)? | Lead |
| Q2 | Where did "NVIDIA-recommended NeMo microservices operator" come from, and when? Is the team aware of the sunset/deprecation? | Lead |
| Q3 | How are manifests applied today (Ansible/GitLab, Argo, kubectl)? | Platform |
| Q4 | Is the RC tag mutable? Who changes PROD's image, and how is it chosen? | Platform |
| Q5 | What does the helper pod do (source, tool, duration)? PVC access mode and size? | Platform |
| Q6 | GPU types/counts per env; are profiles pinned? | Platform |
| Q7 | Is ASR in scope; which NIM? | Lead |
| Q8 | GPU Operator present in all envs; can we get cluster-scope approval? | Platform lead |
| Q9 | Who needs users/sessions stored, and where does that live today? | App devs |
| Q10 | Is there an NVIDIA account team to confirm the deprecation timeline and migration path? | Lead |

## Appendix A: References (checked 2026-11-19)

- NIM Operator source, tag v3.1.4: `api/apps/v1alpha1/nimservice_types.go` (storage.pvc, replicas), `manifests/deployment.yaml` (rollout strategy): https://github.com/NVIDIA/k8s-nim-operator
- NIM Operator docs, NeMo Entity Store page (deprecation notice; entity description): https://docs.nvidia.com/nim-operator/3.1.2/entity-store.html
- NeMo Microservices archive (sunset 2026-10-01): https://archive.docs.nvidia.com/nemo/microservices/latest/
- NeMo Helix: https://docs.nvidia.com/nemo-helix
- Supporting research and examples (generic): learning repo `docs/investigation/03–13`, `examples/`
