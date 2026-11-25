# 2. NVIDIA-recommended approach (high level)

> **[MACRO: Page Properties]** Status DRAFT · Owner <author> · Sources checked 2026-11-19/20

**Purpose:** what NVIDIA's operator-based approach consists of, its current status, what it requires, and how it
handles environments. Every NVIDIA claim links to its source in *Appendix A*.

## Status first

| Component | What it does | Status |
|---|---|---|
| **GPU Operator** | Drivers, container toolkit, device plugin, GPU discovery, DCGM metrics | Current (Project: v25.10.0) |
| **NIM Operator**: `NIMCache`, `NIMService` (+ `NIMPipeline`, `NIMBuild`) | Caches model weights; runs NIMs (image, GPUs, replicas, storage, service, probes, autoscaling) | **Current**, v3.1.4 |
| NIM Operator: NeMo CRDs (`NemoEntitystore`, `NemoDatastore`, `NemoCustomizer`, `NemoEvaluator`, `NemoGuardrail`) | Deploy NeMo microservices | **Deprecated** (v3.1.3: "is deprecated") |
| **NeMo Microservices** (Deployment Management, NIM Proxy, Entity Store, Data Store, Customizer, Evaluator, Guardrails) | Platform services around NIMs | **Sunset 2026-10-01**; docs archived; "contact your NVIDIA account team" |
| NeMo Platform / **NeMo Helix** | Successor control plane | Pre-1.0 (0.5–0.10), no GA statement; see *NeMo Helix* |

## How NVIDIA's NeMo platform manages models (the model the tickets describe)

> **[MACRO: draw.io]**
> Client → **NIM Proxy** (unified inference endpoint) → NIM Services
> Admin → **Deployment Management** API (deploy/list/update/delete NIM) → **NIM Operator** → NIMService/NIMCache → pods
> **Entity Store** (namespaces, projects, models, datasets; Postgres) · **Data Store** (files for fine-tuning/eval)

From NVIDIA's (archived) docs:
- **Deployment Management:** "Provides an API to deploy NIM on a Kubernetes cluster and manage them through the NIM
  Operator microservice." It lists the NIM Operator as a prerequisite and configures autoscaling through the NIM
  Service `scale.hpa` fields.
- **NIM Proxy:** "Provides a unified endpoint that you can use to access all deployed NIM for inference tasks."
- **Entity Store:** "Provides tools to manage and organize general entities such as namespaces, projects, datasets,
  and models." It needs Postgres and a Data Store. It is not a user or session store.
- **Data Store:** "the default file storage solution for the NeMo microservices platform" (HF-compatible; Postgres +
  RWX PVC + object storage).

**This is the architecture the five tickets were written against, and it is the part NVIDIA has sunset.**

## The current part: NIM Operator

- `NIMCache` downloads or pre-stages weights to a PVC. The PVC is owned by the cache, so **deleting the cache
  deletes the weights.**
- `NIMService` runs the NIM. It can use a `NIMCache`, **an existing PVC** (`spec.storage.pvc`) or a hostPath. It
  sets replicas, GPUs, environment (e.g. `NIM_SERVED_MODEL_NAME`), the service and the probes.
- Pin the model **profile** in both cache and service, or different GPU types pick different profiles.
- **Rollout is hard-coded** `RollingUpdate`, `maxSurge: 0`, `maxUnavailable: 25%` (operator source v3.1.4), so
  **upgrading a single-replica NIM is an outage.**
- The interface is Kubernetes CRDs (`kubectl`/GitOps). The operator has no REST API of its own; Deployment
  Management was NVIDIA's API on top of it.

## Prerequisites

| Area | Requirement | Project |
|---|---|---|
| Kubernetes | ≥ 1.26 (NIM docs); operator README ≥ 1.28 | _TBC_ |
| GPU Operator | ≥ 24.3.0 | v25.10.0 ✅ |
| Storage | PVC per model cache; GLM 5.2 FP8 ≈ 750 GB+ (size ~1.5 TiB); RWX for multi-replica | RWX cache PVCs ✅ (manual) |
| Database | None for NIM Operator; **Postgres** for Entity Store / Data Store | _TBC_ |
| Networking | NIMs have **no client auth**, so restrict with NetworkPolicy; ingress for the gateway | No gateway yet |
| RBAC | Cluster-scope CRDs + ClusterRole for the operator | Installed (manual) |
| Secrets/config | NGC API key + pull secret (NGC key optional when fully pre-cached, v3.1.3+) | NGC secret manual |
| Air-gap | Mirror operator/NIM images; pre-stage caches | Cache pre-populator ✅ (manual) |

## Environments and promotion

NVIDIA documents **no DEV → QA → PROD promotion model** for NIMs, NeMo microservices or Helix. The standard
approach is per-environment overlays of the **same pinned spec** (image digest, profile, served name) in git,
promoted by merge request, with CI gates. Argo CD has no built-in health check for NIM CRDs, so add custom
health checks and protect caches from pruning.

> **[MACRO: Info panel]** Verified in lab (2026-11-25): NIM Operator 3.1.4 runs without a GPU (controller only), with the NeMo CRDs unused.
> A `NIMService` with `replicas: 0` reports NotReady, so Argo needs a custom health check; one is in the repo examples.
> The operator ClusterRole can read and write Secrets and create pods in all namespaces (rendered chart).
> The chart's default image is a floating tag (`release-3.0` with `Always` pull); pin by digest.
> Argo CD has no built-in health check for the NIM CRDs.
