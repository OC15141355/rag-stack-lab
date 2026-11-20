# Model deployment: move to the NVIDIA NeMo microservices operator approach (Investigation)

> **[MACRO: Page Properties]**
> | Status | **[STATUS: DRAFT]** |
> | Owner | <author> |
> | Date | <date> |
> | Decision needed by | <date> |
> | Jira | <investigation ticket> |

> **[MACRO: Warning panel]** **NVIDIA sunset NeMo Microservices on 2026-10-01** ("all new development has moved
> to NeMo Platform", now NeMo Helix, pre-1.0) and **deprecated the NIM Operator's NeMo CRDs** (v3.1.3).
> The **NIM Operator itself (NIMCache/NIMService) is current.** This splits the "NVIDIA-recommended approach" into a
> part that is safe to build on and a part that isn't.

## Bottom line

The Project is **already partway onto NVIDIA's operator approach**: the GPU Operator (v25.10.0) and NIM Operator are
installed, a cache pre-populator exists, and NeMo microservices (including **Deployment Management**) are deployed.
The gaps are mainly: **(1) most of the platform is installed by hand**, so DEV/QA/PROD cannot be rebuilt reproducibly;
**(2) the NeMo layer the tickets build on is sunset**; **(3) there is no gateway, metadata or promotion process yet.**

**Recommendation:** standardise model serving on **NIM Operator CRs managed in git** (NIMService + NIMCache), automate
the manual install steps, put **Bifrost** in front with a **git model catalogue** for metadata and limits, and promote
via **merge requests gated by smoke tests**. **Freeze the NeMo microservices layer** (keep what's running, build
nothing new on it) and decide between retiring it and moving to Helix once Helix is GA, or sooner if a
fine-tuning/evaluation need appears.

## The five tickets at a glance

| Ticket | NVIDIA reality | Verdict |
|---|---|---|
| Model store | NeMo **Deployment Management** (CRUD API for NIM deployments via the NIM Operator) + Entity Store model records: **exists, but sunset** | **[STATUS: RE-SCOPE]** to git-managed NIMService/NIMCache + automated cache population |
| Entity store | NeMo Entity Store = namespaces/projects/datasets/model records, **not users/sessions**; deprecated route | **[STATUS: FREEZE / SPLIT]** keep as-is; users/sessions belong to the portal |
| Postgres backend | Needed by Entity Store (and Data Store); HA/backups/migrations are ours | **[STATUS: CONDITIONAL]** only if the NeMo layer is kept long-term |
| Model metadata | No NVIDIA component enforces token limits from metadata | **[STATUS: RE-SCOPE]** git catalogue → Bifrost (limits) + model list |
| DEV→QA→PROD promotion | Not provided by NVIDIA | **[STATUS: RE-SCOPE]** MR-based promotion + smoke-test gates |

Plus **new work**: automate the manual platform steps, reconcile the deployment repos/branches, Bifrost in front of
NIMs, NetworkPolicy, and a decision record on the NeMo layer. See *Gap analysis*.

## Effort (rough)

Recommended path across DEV/QA/PROD: **~30–50 person-days**, phased (see *Recommendation*). Building the tickets
as written on the sunset NeMo layer, plus the automation that is needed anyway: **~60–95+**, with redo risk.

## Decisions needed

1. Freeze the NeMo microservices layer and build new model management on NIM Operator CRs in git: **yes/no**
2. Bifrost as the single entry point for all model traffic (replacing NIM Proxy if it's in use): **yes/no**
3. Accept the re-scoped tickets and the new tickets: **yes/no**

## Pages

> **[MACRO: Children Display]**

1. Current state
2. NVIDIA-recommended approach
3. Gap analysis (→ 3a Ticket assessment)
4. NeMo Helix
5. Risks and constraints
6. Smoke tests
7. Recommendation, phasing and effort
8. Decision record: NeMo microservices layer
Appendices: Evidence · Speech models · Glossary

## Open questions

| # | Question | Owner |
|---|---|---|
| Q1 | What problem is the move meant to solve (repeatability, upgrades, vendor support, a feature)? | Lead |
| Q2 | Which NeMo microservices are deployed in each env (Deployment Management, Entity Store, Data Store, NIM Proxy, others), and is anything using them? | Platform |
| Q3 | Are the LLM services deployed as NIMService CRs (via Deployment Management or Ansible) or plain Deployments? | Platform |
| Q4 | Which branch/repo is the source of truth per environment? | Platform |
| Q5 | Is the DEV/QA release-candidate image tag ever re-pushed? Who changes PROD's version? | Platform |
| Q6 | Is there an NVIDIA account team to confirm the NeMo deprecation timeline and migration path? | Lead |
| Q7 | Is speech (Whisper) in scope? | Lead |
