# Decision record (draft): NeMo microservices stores via the operator

An architecture decision record (ADR) template, pre-filled with the generic
version of the decision this investigation is likely to need. Copy it
privately; fill in the context and the consulted people; take it to the
decision meeting.

```markdown
# ADR-<n>: Adopt NIM Operator for model serving; do not build on deprecated NeMo operator CRDs

- Status: Proposed | Accepted | Superseded by ADR-<m>
- Date: <date>
- Deciders: <roles>
- Consulted: <roles, incl. NVIDIA account team if engaged>

## Context
- We serve <N> LLMs as NIMs in DEV, QA and PROD, deployed via <current approach>.
- Planned work assumed an "NVIDIA-recommended NeMo microservices operator approach" including
  a model store, entity store (Postgres-backed), model metadata with token limits, and
  operator-driven promotion.
- As of <date checked>:
  - The NIM Operator (NIMCache, NIMService) is actively released (v<x>).
  - The operator's NeMo microservices CRDs are deprecated (release notes v3.1.3).
  - NeMo Microservices was sunset on 2026-10-01; development moved to NeMo Platform / Helix (pre-1.0).
  - NVIDIA provides no model store, operator REST API, metadata-driven token enforcement,
    or promotion workflow (see investigation docs 03/04/05).

## Decision
1. Serve models with the NIM Operator (`NIMCache` + `NIMService`), pinned images and profiles,
   applied by <GitOps tool / Ansible>.
2. Model metadata lives in a versioned catalogue in git; gateway config and the consumer
   catalogue are generated from it; limits are enforced by the gateway (rate/token) and NIM
   (context).
3. Promotion DEV→QA→PROD is via merge requests with smoke-test gates and protected-environment
   approvals; the audit trail is MR + deployment history.
4. Do not deploy NeMo Entity Store / Data Store via the deprecated operator CRDs.
   Revisit if <trigger: a fine-tuning/evaluation workflow is approved>, evaluating NeMo Helix
   at that time.

## Consequences
- Positive: <reproducible deployments, consistent envs, vendor-current path, fewer components>.
- Negative: <operator adds an upgrade stream; cluster-scope RBAC; custom catalogue tooling>.
- Neutral: <tickets re-scoped as per gap analysis section 3>.

## Alternatives considered
- Stay as-is with targeted fixes: <why not / when acceptable>.
- Adopt NeMo stores via operator as a bridge: <risk: deprecated; redo on Helix>.
- Adopt NeMo Helix now: <risk: pre-1.0; scope beyond serving>.

## Triggers to revisit
- NVIDIA guidance changes (e.g. Helix GA with a supported migration path).
- A workflow requiring NeMo services (customisation, evaluation) is approved.
- The operator drops or changes NIM CRDs incompatibly.
```

## How to use it

- Keep ADRs short: one decision each. If the meeting splits the decision
  (e.g. serving accepted, stores deferred), write two.
- Record **what was known when** (dates, versions). It's what makes the
  decision defensible later.
- Link it from the recommendation doc and from the re-scoped tickets.
