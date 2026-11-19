# 2. NVIDIA-recommended approach (high level)

> **[MACRO: Page Properties]**
> | Status | DRAFT |
> | Owner | <you> |
> | Last updated | <date> |
> | Parent | Model deployment: move to NVIDIA operator approach |

**Purpose:** what NVIDIA provides and recommends today, its status, and what it requires. Every NVIDIA claim links to a source with the date checked.

> **[MACRO: Warning panel]** Status matters: see 4.1 first.


## Status first

| Component | Status (2026-11-19) | Source |
|---|---|---|
| NIM Operator: `NIMCache`, `NIMService` (+ `NIMPipeline`, `NIMBuild`) | **Current**, v3.1.4 | NIM Operator release notes / GitHub |
| NIM Operator: NeMo CRDs (`NemoEntitystore`, `NemoDatastore`, `NemoCustomizer`, `NemoEvaluator`, `NemoGuardrail`) | **Deprecated** ("deprecating support for the NeMo Microservices CRDs and deployments in the next release"; 3.1.3: "is deprecated") | NIM Operator docs, Entity Store page; release notes |
| NeMo Microservices (the product) | **Sunset 2026-10-01**; docs archived; "contact your NVIDIA account team" | archive.docs.nvidia.com |
| Successor: NeMo Platform / NeMo Helix | Pre-1.0 (0.x), UI "alpha" | docs.nvidia.com/nemo-helix |

Note: NVIDIA's NIM for LLMs docs list Helm charts and the NIM Operator side by side for Kubernetes,
without naming one as *the* recommendation.

## Required operator components and services

- **Always:** NVIDIA GPU Operator (≥ 24.3.0); NIM Operator (Helm chart `nvidia/k8s-nim-operator`,
  cluster-scoped CRDs + controller); per model, a `NIMService` and (optionally) a `NIMCache`.
- **For the NeMo microservices approach as ticketed, additionally:** Entity Store (`NemoEntitystore`,
  needs Postgres + a Data Store endpoint), Data Store (`NemoDatastore`, needs Postgres, an RWX PVC,
  object storage, several secrets), and an external Postgres per environment.

## Deployment prerequisites

| Area | Requirement |
|---|---|
| Kubernetes | ≥ 1.26 per the NIM docs (README says ≥ 1.28 for the operator; use the stricter one). VKS support not explicitly listed by NVIDIA **(unverified)** |
| GPU Operator | ≥ 24.3.0; driver mode on VKS (vGPU/passthrough) per VMware + NVIDIA docs |
| Storage | PVC for weights (GLM 5.2 at FP8 ≈ 750 GB+, so size ~1.5 TiB with headroom); RWO fine for single-replica, RWX for multi-replica/multi-node; the NeMo Data Store needs RWX + object storage |
| DB | None for NIM. Postgres for Entity/Data Store (external; embedded is dev-only) |
| Networking | NIM has **no client auth**, so a NetworkPolicy should allow only Bifrost (and monitoring) to reach NIM Services; intra-node NVLink for TP8 |
| RBAC | Cluster-scope install (CRDs, ClusterRole); namespace-scope for CRs |
| Secrets / config | NGC API key + image pull secret (NGC key optional when everything is pre-cached, v3.1.3+); DB creds if NeMo stores |
| Air-gap | Mirror operator + NIM images to Harbor; pre-stage weights; `NIMCache` without `authSecret` when fully cached |

## Environment and promotion model

NVIDIA documents **no DEV → QA → PROD promotion model** for NIMs or NeMo microservices. The
standard pattern on Kubernetes is per-environment overlays of the same pinned spec (image digest,
model profile, served name), promoted through Git with CI gates. Argo CD needs custom health
checks for NIM CRDs, which it doesn't ship.

Two operator facts that shape the environment model (confirmed in operator source v3.1.4):
- **Upgrades of a single-replica NIM are outages.** The Deployment strategy is hard-coded
  `RollingUpdate`, `maxSurge: 0`, `maxUnavailable: 25%`, and there is no spec field to change it.
- **Deleting a `NIMCache` deletes its PVC (the weights).** Protect caches from GitOps pruning.
