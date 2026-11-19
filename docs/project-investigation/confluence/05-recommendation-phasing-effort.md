# 5. Recommendation, phasing and effort

> **[MACRO: Page Properties]**
> | Status | DRAFT |
> | Owner | <you> |
> | Last updated | <date> |
> | Parent | Model deployment: move to NVIDIA operator approach |

**Purpose:** options considered, the recommended option, phasing, rough effort and what would change the recommendation.

> **[MACRO: draw.io]** Target state: same diagram as page 1, with Bifrost in front, NIMService/NIMCache, catalogue → Bifrost, MR-based promotion


**Option chosen: NIM Operator for serving + GitOps for metadata and promotion; NeMo stores
deferred.** Alternatives considered: (0) stay as-is with fixes (digest pinning, staging
automation); (2) also deploy NeMo Entity/Data Store via the deprecated CRDs as a bridge;
(3) NeMo Helix now: pre-1.0 (0.5–0.10 listed, no GA statement, Studio "alpha"); an agent/fine-tuning/eval control plane, not a serving replacement; its Inference Gateway documents no rate limits/budgets, so it doesn't replace Bifrost; launches NIMs via its own deployments plugin, with no stated NIM Operator integration; migration guidance = "contact your account team". Verdict: not yet for a serving-only platform; time-boxed trial if fine-tuning/eval is wanted.

## Phasing and effort (assumptions below)

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
