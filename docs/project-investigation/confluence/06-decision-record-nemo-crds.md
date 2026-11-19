# 6. Decision record: NeMo microservices CRDs

> **[MACRO: Page Properties]**
> | Status | **[STATUS: PROPOSED]** |
> | Owner | <you> |
> | Deciders | <roles> |
> | Consulted | <roles; NVIDIA account team if engaged> |
> | Date | <date> |

> **[MACRO: Decision]** (or use a Decision page template)

## Decision (proposed)

1. Serve the Project's models with the **NIM Operator** (`NIMCache` + `NIMService`), with pinned image digests and profiles, applied through the existing delivery path.
2. Model metadata lives in a **versioned catalogue in git**. Bifrost config and the consumer catalogue are generated from it. Rate and token limits are enforced by **Bifrost**; the context limit is enforced by the **NIM**.
3. **DEV → QA → PROD promotion** goes through merge requests with smoke-test gates and protected-environment approvals. The audit trail is the MR and deployment history.
4. **Do not deploy NeMo Entity Store / Data Store via the deprecated operator CRDs.** Revisit if a fine-tuning or evaluation workflow is approved, evaluating NeMo Helix at that time.

## Context

- Today: plain manifests in a deployment repo; weights on a PVC filled manually by a helper pod; DEV/QA on release-candidate images, PROD pinned; no gateway or rate limiting (Bifrost planned).
- The planned tickets assumed an "NVIDIA-recommended NeMo microservices operator approach" with a model store, an entity store on Postgres, model metadata with token limits, and operator-driven promotion.
- As of 2026-11-19:
  - The NIM Operator (`NIMCache`, `NIMService`) is current (v3.1.4).
  - The operator's NeMo microservices CRDs are deprecated (v3.1.3 release notes; Entity Store docs page).
  - NeMo Microservices was sunset on 2026-10-01; development moved to NeMo Platform / Helix, which is pre-1.0 with no GA statement.
  - NVIDIA provides no model store, no operator REST API, no metadata-driven token enforcement and no promotion workflow.

## Consequences

- **Positive:** reproducible deployments; the same artefacts in every environment; a vendor-current path; fewer new components (no Postgres yet).
- **Negative:** the operator adds an upgrade stream and needs cluster-scope RBAC; the catalogue and promotion tooling are ours to build and maintain; single-replica upgrades are outages (hard-coded `maxSurge: 0`).
- **Tickets:** re-scoped as on page *3a*.

## Alternatives considered

| Option | Why not (now) |
|---|---|
| Stay as-is with targeted fixes | Leaves manual weight staging and hand-edited PROD images; acceptable short-term only |
| NeMo stores via the operator as a bridge | Deprecated CRDs; sunset product; likely redo on Helix |
| NeMo Helix now | Pre-1.0; aimed at agents, fine-tuning and evaluation, not serving; no documented NIM Operator integration; its gateway doesn't replace Bifrost |

## Triggers to revisit

- NVIDIA confirms a supported, near-term path for the NeMo stores, or Helix reaches GA with a migration guide.
- A fine-tuning or evaluation workflow is approved.
- The operator changes its NIM CRDs incompatibly.
