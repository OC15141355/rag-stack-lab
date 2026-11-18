# Recommendation document — template

Two deliverables:
1. **The recommendation document**: complete and structured, the reference
   the team works from.
2. **A one-page summary**: what most people will actually read. It goes at
   the top of the document and in the chat or email when you share it.

Write the summary **last**, but put it **first**.

---

## Part 1: One-page summary (template)

```markdown
# <Title>: moving model deployment to NVIDIA's operator approach

**Status:** draft for review · **Author:** <you> · **Date:** <date> · **Decision needed by:** <date>

## Bottom line
<2–3 sentences. What you recommend and why, in plain words.>

## What I found
- Current approach: <one line>
- NVIDIA's recommended approach today: <one line; include the deprecation/sunset fact if confirmed>
- Biggest gaps: <3 bullets max>

## Recommendation
<Option name>, in <N> phases:
1. <Phase 1>: <outcome> (<effort>)
2. <Phase 2>: …
3. <Phase 3>: …

## Ticket changes
- Keep: <n tickets>   - Re-scope: <n>   - New: <n>   - Drop/defer: <n>
  (detail in section 8)

## Top risks
1. <risk>: <mitigation>
2. …
3. …

## Decisions needed
1. <decision>: options <a/b>, recommended <a>
2. …

## Open questions
- <question>: owner <role>
```

---

## Part 2: Full document (section structure)

### 1. Purpose and scope
- What was investigated, and why (the problem being solved, from question A1).
- In scope / out of scope.
- Inputs: who was consulted, what was read, which environments were inspected.
  Give dates, because NVIDIA's docs are moving.

### 2. Current state
From your private 02, cleaned up:
- How models are deployed today (diagram plus one paragraph).
- A per-environment table (DEV / QA / PROD).
- Operational dependencies (storage, registry, secrets, DB, gateway,
  monitoring).
- How a model change happens today, step by step.
- Known pain points, with evidence.

### 3. NVIDIA's recommended approach (high level)
From [03](03-nvidia-recommended-deployment.md) and
[04](04-nemo-entity-and-data-store.md), each fact with a source link and the
date checked:
- What NVIDIA recommends now, and its status: GA, deprecated, sunset.
- Required components and services.
- Deployment prerequisites (table): Kubernetes, GPU Operator, storage, DB,
  networking, RBAC, secrets/config.
- Model lifecycle under the operator: cache, profile, service, upgrade.
- What NVIDIA does and doesn't provide for environments and promotion.

### 4. Target state for this platform
What the platform would look like after the change, per environment. A
diagram, plus who owns what: operator, gateway, pipeline, DB, portal.

### 5. Gap analysis
From [05](05-gap-analysis.md):
- Current vs recommended (table).
- What needs to change in deployment, configuration and process.
- Planned work items vs reality (table).

### 6. Options considered
At least three, each with pros, cons, effort and risk:
- **Option 1:** NIM Operator for model deployment, no deprecated NeMo stores;
  metadata/limits in the gateway, promotion in GitOps.
- **Option 2:** as Option 1 plus NeMo Entity/Data Store via the operator, as a
  bridge.
- **Option 3:** NIM Operator plus NeMo Helix for platform services.
- **Option 0:** stay as-is, with targeted fixes. Always include the baseline.

A comparison table: criteria (fit to the problem, vendor support status,
effort, risk, operational burden, reversibility) × options.

### 7. Recommendation
- Recommended option, and *why* in terms of the problem in section 1.
- What would change the recommendation (triggers).

### 8. Ticket mapping
| Existing ticket (theme) | Verdict (keep / re-scope / split / defer / drop) | Why | Revised scope + ACs |
|---|---|---|---|

Plus **new tickets** (prerequisites, follow-ons) with one-line scope and ACs.

### 9. Implementation sequence and effort
- Phases, each with an outcome, the environments touched, entry/exit criteria
  and an effort range (T-shirt size or person-days), plus its assumptions.
- Dependencies between phases (what blocks what).
- A rough timeline, assuming <capacity>.

Effort guide (adjust to the team):
| Size | Person-days | Typical example |
|---|---|---|
| S | 1–3 | Install operator in DEV; one NIMService for one model |
| M | 4–10 | Mirroring + pre-staged caches for both models; Argo/Ansible integration |
| L | 10–20 | Per-env rollout with cutover windows; promotion pipeline with gates |
| XL | 20+ | New platform service (e.g. Postgres + NeMo/Helix stores) with HA, backups, runbooks |

Always state assumptions ("assumes GPU Operator present in all envs", "assumes
cluster-scope approval within 1 week").

### 10. Risks and constraints
From [06](06-risks-and-constraints.md): the top risks in the body, the full
register in an appendix.

### 11. Decisions needed and open questions
Numbered, each with an owner and a date needed.

### Appendices
- A. Evidence (commands run, files read, redacted outputs).
- B. Full risk register.
- C. References (official URLs plus date checked).
- D. Glossary (operator, CRD, NIMCache, NIMService, Entity Store, …).

---

## Writing rules that make it useful

- **Lead with the decision**, not the research journey.
- **Every claim about NVIDIA has a link and a date.** Every claim about the
  current platform has evidence.
- **Separate fact from opinion:** "NVIDIA's docs state…" vs "I recommend…".
- **Tables over prose** for comparisons; prose for reasoning.
- **Name owners** for decisions and open questions.
- **Be kind to the existing setup.** Explain why it's the way it is before
  saying what should change.
- **Show your uncertainty.** "Unverified" or "needs confirmation from X" is
  better than a confident guess.
- Get one or two people to review before sharing widely, including someone
  who built the current setup.
