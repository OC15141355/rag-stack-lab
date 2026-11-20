# 8. Decision record: NeMo microservices layer

> **[MACRO: Page Properties]**
> | Status | **[STATUS: PROPOSED]** |
> | Owner | <author> |
> | Deciders | <roles> |
> | Consulted | <roles; NVIDIA account team if engaged> |
> | Date | <date> |

> **[MACRO: Decision]**

## Decision (proposed)

1. **Model serving is managed as NIM Operator CRs (`NIMService` + `NIMCache`) in git**, per-env overlays, pinned
   image digests and profiles. One owner per model.
2. **The NeMo microservices layer (Deployment Management, Entity Store, Data Store, NIM Proxy, as deployed) is
   frozen:** kept running where something depends on it; no new features built on it. Inventory, then retire unused
   services.
3. **Bifrost is the single entry point** for model traffic; NIMs reachable only from Bifrost (NetworkPolicy).
4. **Model metadata is a git catalogue** generating Bifrost config (limits enforced there) and the consumer model
   list. Context limits are set in NIM config.
5. **Promotion DEV → QA → PROD is by merge request,** gated by smoke tests, with protected-environment approvals.
6. **Revisit the NeMo layer** when Helix is GA with a migration path, or when a fine-tuning/evaluation workflow is
   approved.

## Context

- The Project already runs the GPU Operator (v25.10.0), the NIM Operator and NeMo microservices including
  Deployment Management, mostly installed by hand.
- The tickets describe NVIDIA's NeMo platform model management (Deployment Management API, Entity Store, Postgres,
  metadata, promotion).
- As of 2026-11-19/20: NeMo Microservices **sunset 2026-10-01**; the operator's NeMo CRDs **deprecated** (v3.1.3); NIM
  Operator NIM CRDs **current** (v3.1.4); Helix **pre-1.0**. NVIDIA provides no promotion workflow or metadata-driven
  limit enforcement.

## Consequences

- **Positive:** reproducible, vendor-current serving; uses the operators already installed; no new database needed
  now; one clear source of truth.
- **Negative:** we own the catalogue and promotion tooling; NIM upgrades are outages for single replicas; the
  frozen NeMo services carry some risk until retired.
- **Tickets:** re-scoped as on *3a*; new tickets N1–N12.

## Alternatives

Options 0, 2 and 3 on *7. Recommendation*.
