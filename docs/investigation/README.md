# Investigation kit: moving model deployment to NVIDIA's operator-based approach

A reusable kit for one investigation: **what it takes to move a self-hosted
LLM platform from its current model-deployment approach to NVIDIA's
operator-based approach** (NIM Operator, and the NeMo microservices it can
deploy), across DEV, QA and PROD. It covers steps, prerequisites, gaps, risks
and effort, and checks the planned work items against what NVIDIA's
components actually do.

This repo is public. Everything here is generic. Real names, ticket IDs,
hostnames, configs and findings about a specific platform go in your
**private** copy of the templates, never in this repo.

## What's in the kit

| # | File | What it is | You fill it in? |
|---|---|---|---|
| 01 | [Questions for the existing platform](01-questions-for-the-platform.md) | Question bank, grouped by area, with who to ask | Answers go private |
| 02 | [Current-state capture](02-current-state-capture.md) | Template: how models are deployed today, per environment | Yes (private) |
| 03 | [NVIDIA-recommended deployment](03-nvidia-recommended-deployment.md) | Research: what NVIDIA recommends now, prerequisites, lifecycle | Read |
| 04 | [Entity Store, Data Store and the planned items](04-nemo-entity-and-data-store.md) | Research: what NVIDIA's stores actually do, mapped to typical work items | Read |
| 05 | [Gap analysis](05-gap-analysis.md) | Framework plus a generic draft: current vs recommended, item-by-item | Yes (private copy) |
| 06 | [Risks and constraints](06-risks-and-constraints.md) | Risk register, pre-filled with the generic risks | Yes (private copy) |
| 07 | [Recommendation document template](07-recommendation-template.md) | The structure of the final document and the one-page team summary | Yes (private) |
| 08 | [Target-state reference](08-target-state-reference.md) | NIMCache/NIMService manifests (field names checked against operator v3.1.4 CRDs), kustomize overlays per env, Argo health checks, NetworkPolicy | Read; adapt examples |
| 09 | [Model catalogue and promotion](09-model-catalogue-and-promotion.md) | Design + runnable examples: metadata catalogue, generated gateway config, MR-based promotion | Read; adapt examples |
| 10 | [Smoke tests as promotion gates](10-smoke-tests.md) | Stdlib-only test script for any OpenAI-compatible endpoint (tested against a mock) | Run it |
| 11 | [Decision record draft](11-decision-record-draft.md) | ADR for the "serve via NIM Operator, don't build on deprecated NeMo CRDs" decision | Yes (private) |
| 12 | [Cutover and rollback runbook](12-cutover-runbook-template.md) | Per-environment cutover template with rollback | Yes (private) |
| 13 | [Questions for NVIDIA](13-questions-for-nvidia.md) | For the account team / support: direction, models, air-gap, planned features | Send |

Personal pages, for you rather than the team:

- [Investigation best practices](../notes/investigation-best-practices.md)
- [Understanding notes: operators, stores, metadata, promotion](../notes/understanding-model-platform-concepts.md)
- [Working journal template](../notes/working-journal-template.md)

## How to run the investigation

```
Week 1                                   Week 2
├─ Day 1-2  Capture current state (02)   ├─ Gap analysis (05), item by item
│           Ask questions (01)           ├─ Risks (06)
├─ Day 3    Read 03 + 04                 ├─ Phasing + effort
├─ Day 4-5  Verify assumptions on the    ├─ Draft recommendation (07)
│           real cluster (read-only)     └─ Review with 1-2 people, then share
```

1. **Current state first.** Don't evaluate a change before you can describe,
   with evidence, what exists today in each environment. Use 02.
2. **Recommended state from primary sources.** NVIDIA's docs changed a lot in
   late 2026 (NeMo Microservices sunset, NeMo CRDs deprecated in the
   operator). Use 03 and 04, and re-check anything you'll quote.
3. **Gaps, item by item.** For each planned work item: does an NVIDIA
   component do this, partly, or not at all? Who should own it (operator,
   gateway, pipeline, DB)?
4. **Risks and effort.** Include the risk of *doing* the change and the risk
   of *not* doing it.
5. **Recommendation.** Options, a recommended one, phasing, rough effort,
   ticket changes, and open questions. Then a one-page summary for the team.

## The key finding to verify first

Earlier research for this repo found that
- **NeMo Microservices was sunset on 2026-10-01** (NVIDIA's docs now live on
  an archive site; "all new development has moved to NeMo Platform"), and
- **the NIM Operator's NeMo CRDs are deprecated** as of operator v3.1.3.

The **NIM Operator itself** (NIMCache, NIMService) is current. If this holds
when you check it, "the NVIDIA-recommended NeMo microservices operator
approach" splits in two:

- **Model deployment via NIM Operator:** current and recommended. Likely the
  core of the migration.
- **NeMo microservices (Entity Store, Data Store, …) via the operator:**
  deprecated. Building new work on it needs an explicit decision, and the
  Helix successor should be evaluated.

Make sure the team sees this early, before effort goes into deprecated
components.
