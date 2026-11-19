# Appendix B: Reference: NeMo Helix

> **[MACRO: Page Properties]** Status DRAFT · Owner <you> · Checked 2026-11-19

**Purpose:** what NeMo Helix is, so the team can judge it as an alternative to the deprecated NeMo microservices.

## In short

- **What it is:** NVIDIA's open-source control plane for improving and hardening production agents. It is where NeMo Microservices development moved ("NeMo Platform"). It covers fine-tuning, evaluation, guardrails, files, entities, jobs, secrets and an inference gateway.
- **Maturity:** versions 0.5–0.10 are listed; there is no GA statement; NeMo Studio is labelled "alpha"; release notes list breaking changes. (docs.nvidia.com/nemo-helix)
- **Install:** Helm chart `nemo-helix/nemo-helix` from `helm.ngc.nvidia.com/nvidia/nemo-helix`; NGC key; RWX storage; the embedded Postgres is not for production; no air-gap guidance found.
- **NIMs:** it can launch NIMs through its own deployments plugin; no documented integration with the NIM Operator.
- **Gateway:** its Inference Gateway is a reverse proxy with virtual models and middleware. It documents no rate limits, budgets or fallbacks, so it **does not replace Bifrost**.
- **Registry/metadata/promotion:** it has model entities and filesets, but no token-limit metadata, promotion stages or model-change audit trail were found.
- **Migration from NeMo Microservices:** the only official guidance is "contact your NVIDIA account team"; one service-specific page exists (Evaluator). APIs moved to `/apis/<service>/v2/workspaces/{ws}/...`.

## Verdict for the Project

| If the Project… | Then |
|---|---|
| only serves NIMs behind Bifrost | **Not yet.** Use the NIM Operator; revisit when Helix is GA |
| wants fine-tuning / evaluation workflows | **Time-boxed trial in DEV**, pinned version, thin integration |

## Questions for NVIDIA

- When will Helix be GA? Is there a supported migration path from NeMo Microservices?
- Is there an air-gapped install path and image list?
- Does Helix integrate with NIM Operator-managed NIMs, or replace that?
- Are the chart and images covered by the same licence as the source?
