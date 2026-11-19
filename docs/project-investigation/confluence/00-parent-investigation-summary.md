# Model deployment: move to NVIDIA operator approach (Investigation)

> **[MACRO: Page Properties]**
> | Status | DRAFT |
> | Owner | <you> |
> | Date | <date> |
> | Decision needed by | <date> |
> | Jira | <investigation ticket key> |

> **[MACRO: Warning panel]** NVIDIA sunset NeMo Microservices on 2026-10-01 and has deprecated the NIM Operator's
> NeMo CRDs. The model-serving part of the operator (NIMCache/NIMService) is current. See *2. NVIDIA-recommended approach*.

## Summary

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

## Child pages
> **[MACRO: Children Display]**

1. Current deployment approach
2. NVIDIA-recommended approach (high level)
3. Gap analysis → 3a. Ticket assessment
4. Risks and constraints
5. Recommendation, phasing and effort
6. Decision record: NeMo microservices CRDs
Appendices: Evidence · NeMo Helix · Speech models · Glossary

## Open questions

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
