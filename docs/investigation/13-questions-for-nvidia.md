# Questions for the NVIDIA account team / support

NVIDIA's sunset notice for NeMo Microservices says to "contact your NVIDIA
account team to discuss next steps". If there's an NVIDIA AI Enterprise
relationship, these questions get answers that docs don't give, and written
answers carry weight in the decision.

Send them in one email, grouped, with your versions and environment summary
at the top.

## Context to include
- Kubernetes distribution and version (e.g. VKS on vSphere <ver>), GPU types
  per environment, GPU Operator version, vGPU vs passthrough.
- NIMs in use (model, NIM version), current deployment method.
- Air-gapped or restricted: yes/no per environment.

## Direction and support status
1. Is the NIM Operator the recommended way to deploy NIM LLMs on Kubernetes
   for our setup, compared with the `nim-llm` Helm chart? Any plans to change
   that?
2. The operator's NeMo microservices CRDs are deprecated. In which release
   will they be removed? Are security fixes provided for existing NeMo
   microservices images until then?
3. What is the supported migration path from NeMo microservices (Entity Store,
   Data Store, Customizer, Evaluator, Guardrails) to NeMo Platform / Helix?
   Is Helix GA, and when?
4. Is our combination (VKS version, vGPU/passthrough, GPU types, operator
   version) supported or validated?

## Models
5. For <large model> NIM: which profiles are supported on our GPUs? Is there
   an H100 profile? What PVC size should a NIMCache have, and what `/dev/shm`?
6. Recommended way to pin a profile and ensure identical behaviour across
   environments with different GPU types?
7. Tool calling and reasoning parsers for <models>: enabled by default in the
   NIM? How do we override them via the operator?
8. Recommended max context / concurrency settings for our GPU count?

## Air-gap and operations
9. Official procedure for mirroring the operator, NIM images and model caches
   into a private registry and PVCs (is there a manifest or tool)?
10. Do image digests work in `NIMService.spec.image`? Rollout strategy and
    zero-downtime upgrade guidance for large models?
11. Recommended ArgoCD/GitOps integration: health checks for NIM CRDs, sync
    ordering, cache protection?
12. Upgrade order and compatibility: operator ↔ CRDs ↔ NIM versions ↔ GPU
    Operator?

## Platform features we planned
13. Is there any NVIDIA-supported component for a model catalogue / metadata
    (context limits, capabilities) that gateways can consume?
14. Any NVIDIA guidance on DEV → QA → PROD promotion of NIMs?
15. Does Helix replace or overlap with an LLM gateway (Inference Gateway)? Is
    it intended to sit alongside a third-party gateway?

Record answers with date and sender, and quote them in the recommendation
document.
