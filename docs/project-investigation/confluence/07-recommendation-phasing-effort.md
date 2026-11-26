# 7. Recommendation, phasing and effort

> **[MACRO: Page Properties]** Status DRAFT · Owner <author> · Last updated <date>

**Purpose:** the options considered, the recommendation, implementation sequence and rough effort.

## Options

| | Option | Pros | Cons |
|---|---|---|---|
| 0 | **Stay as-is** with targeted fixes (pin digests, script manual steps) | Least effort | Keeps the sunset NeMo layer and the manual installs; no gateway/metadata/promotion |
| 1 | **Recommended:** NIM Operator CRs in git + automation + Bifrost + catalogue + MR promotion; **freeze** the NeMo layer | Vendor-current; reproducible; uses what's already installed; least new infrastructure | Catalogue/promotion tooling is ours; operator upgrade stream |
| 2 | Build the tickets as written on NeMo Deployment Management / Entity Store / Postgres | Matches the original plan; API for model CRUD | Sunset product; deprecated CRDs; Postgres to operate; redo on Helix likely |
| 3 | Move to NeMo Helix now | Where NVIDIA development is | Pre-1.0; different architecture; no air-gap path documented; scope beyond serving |

**Recommendation: Option 1.** It answers the tickets' intent (registered, listed, versioned models; metadata and
limits; gated promotion) with components NVIDIA still supports, plus the automation the platform needs anyway.

> **[MACRO: Info panel]** Verified in lab (2026-11-25): the recommended Option 1 was prototyped end to end in a lab
> (operator CRs via Argo CD, Bifrost, catalogue, promotion and smoke gates); see `docs/raglab-phase-a-findings.md`.
> Effort estimates are unchanged. The lab build took about 2 days of agent-assisted work, which supports the phase sizes.

> **[MACRO: Info panel]** Target structure (2026-11-26): Option 1 as a lifecycle, not per-model deployments. One
> `main` with a folder per environment (no environment branches); a catalogue listing what runs where per environment
> (platform components and models, with NVIDIA support dates); per-environment manifests generated from it and reviewed
> as the exact change; promotion DEV → QA → PROD by merge request with recorded smoke evidence; Ansible reduced to
> cluster bootstrap. It is adoptable in steps, each useful alone, starting before Argo CD or Bifrost exist. Two NVIDIA
> dates make this time-sensitive: Production Branch 6 and the model-specific Llama/Nemotron LLM NIMs reach end of
> support in January 2027. Reference design and working template: `reference/platform-gitops/` in the lab repo.

**What would change it:** NVIDIA confirms a supported, near-term path for the NeMo layer; Helix goes GA with a
migration guide; a fine-tuning/evaluation workflow is approved (then trial Helix).

## Phasing

| Phase | Outcome | Envs | Effort |
|---|---|---|---|
| **0. Decide and inventory** | Decision record agreed; NeMo services in use inventoried; tickets re-scoped; NVIDIA account team contacted | — | S · 2–4 days |
| **1. Repo reconciliation** | One deployment repo layout; env overlays; main = truth; the branch content merged or retired | — | M · 4–8 days |
| **2. Automate the platform layer** | Traefik, GPU Operator, NIM Operator installs automated and pinned (GPU Operator first); NGC secret via an agreed path | DEV → QA → PROD | M · 5–10 days |
| **3. Models as CRs + cache automation** | GLM, Nemotron (and speech) as NIMService/NIMCache in git, same served names; cache population automated; prune protection | DEV | M · 5–10 days |
| **4. Gateway, catalogue, gates** | Bifrost in front + NetworkPolicy; catalogue → Bifrost config; smoke tests in CI; MR promotion with approvals | DEV → QA | M · 6–10 days |
| **5. QA then PROD cutover** | Rehearsed cutover + rollback; digest-pinned identical artefacts; monitoring parity | QA, PROD | M · 6–10 days |
| **6. NeMo layer** | Retire unused NeMo services, or keep frozen with Postgres backups; revisit Helix at GA | all | S–L · 2–15 days |

**Total (Option 1): ~30–50 person-days.** Option 2 (tickets as written, plus the automation still needed):
~60–95+, with redo risk.

**Assumptions:** Kubernetes versions compatible with the installed operators; cluster-scope changes approvable within
about a week; one engineer with part-time help from whoever knows the manual steps; Bifrost deployment handled by its
own workstream (integration only here); speech model is small/simple. Each failed assumption moves a phase up a size.

## Sequence and dependencies

```
0 Decide ─▶ 1 Repos ─▶ 2 Platform automation ─▶ 3 Models as CRs ─▶ 4 Gateway/catalogue/gates ─▶ 5 QA → PROD
                                                                                                └▶ 6 NeMo layer
```
Phase 4 can start in parallel with 3 once Bifrost is up in DEV.
