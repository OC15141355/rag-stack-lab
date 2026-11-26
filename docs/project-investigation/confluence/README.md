# Confluence pages: final set

One file = one Confluence page. "Project" is a placeholder name. These files are the source of truth; edit them
and re-paste.

```
00 Model deployment: move to the NVIDIA NeMo microservices operator approach   ← parent / summary
 ├─ 01 Current state
 ├─ 02 NVIDIA-recommended approach
 ├─ 03 Gap analysis
 │    └─ 03a Ticket assessment
 ├─ 04 NeMo Helix
 ├─ 05 Risks and constraints
 ├─ 06 Smoke tests
 ├─ 07 Recommendation, phasing and effort
 ├─ 08 Decision record: NeMo microservices layer
 └─ Appendices
      ├─ A Evidence
      ├─ B Speech models under the NIM Operator
      └─ C Glossary
```

## Supporting material elsewhere in this repo

| Page | Backed by |
|---|---|
| 02 NVIDIA approach | [investigation/03](../../investigation/03-nvidia-recommended-deployment.md), [prereading/23](../../prereading/23-nemo-nim-operator-deployment.md) |
| 03a Ticket assessment | [investigation/04](../../investigation/04-nemo-entity-and-data-store.md), [investigation/09](../../investigation/09-model-catalogue-and-promotion.md) |
| 04 NeMo Helix | [prereading/28](../../prereading/28-nemo-helix.md) |
| 06 Smoke tests | [investigation/10](../../investigation/10-smoke-tests.md), [examples/smoke](../../../examples/smoke/) |
| 07 Recommendation | [investigation/08](../../investigation/08-target-state-reference.md) (target state), [investigation/12](../../investigation/12-cutover-runbook-template.md) (cutover) |
| 09 Target architecture review | [platform GitOps design](../../superpowers/specs/2026-11-26-platform-gitops-lifecycle-design.md), [reference template](../../../reference/platform-gitops/), [Phase B findings](../../raglab-phase-b-findings.md) |
| B Speech models | [investigation/14](../../investigation/14-speech-nims-under-the-operator.md) |
| Open question Q6 (NVIDIA) | [investigation/13](../../investigation/13-questions-for-nvidia.md) |

## Mapping to the ticket's acceptance criteria

| Acceptance criterion | Page |
|---|---|
| Current deployment approach; environments affected | 01 |
| Operational dependencies (storage, metadata, DB, promotion) | 01 |
| NVIDIA approach: components, prerequisites, environment/promotion model | 02 (+ 04) |
| Gap analysis: differences; what must change | 03 |
| Which existing tickets cover the work; missing tickets | 03a |
| Risks/constraints | 05 |
| Recommendation: sequence/phasing; effort | 07 (+ 08, 09) |
| Summary to share | 00 |

## Placeholders to replace in Confluence

| Marker | Do |
|---|---|
| `[MACRO: Page Properties]` + quoted table | Page Properties macro |
| `[MACRO: Warning/Info/Note panel]` | The matching panel |
| `[STATUS: …]` | Status lozenge (RE-SCOPE yellow, FREEZE/DEFER grey, CONDITIONAL purple, NEW blue, KEEP green) |
| `[MACRO: Jira issues]` | Jira macro with JQL |
| `[MACRO: draw.io]` | Draw the described diagram |
| `[MACRO: Expand]` | Expand macro around long outputs |
| `[MACRO: Children Display]` | Children Display macro |
| `[MACRO: Decision]` | Decision macro / template |
| `<author>`, `<date>`, `<repo>`, `<path>`, `<branch>` | Fill in |
| `_TBC_` | Fill from the return sheet, or move to Open questions on 00 |

## Still open before publishing

- [ ] Return-sheet answers merged (TBCs on 01, 02, 03)
- [ ] Q2/Q3 answered: which NeMo services run, and how LLM services are actually created (Ansible manifests vs NIMService vs Deployment Management)
- [ ] Re-read 00 and 03a in your own words
- [ ] No hostnames, IPs, tokens or secrets
- [ ] Pre-review with whoever knows the manual install steps
- [ ] Status DRAFT → IN REVIEW → final
