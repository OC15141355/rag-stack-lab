# Appendix C: Glossary

| Term | Meaning |
|---|---|
| **NIM** | NVIDIA Inference Microservice: a container with a model plus an optimised inference server and a standard API |
| **NIM Operator** | Kubernetes operator (CRDs + controller) that deploys and manages NIMs |
| **CRD** | Custom Resource Definition: a new Kubernetes object type (e.g. `NIMService`) |
| **Operator "API"** | The Kubernetes API for its CRDs (`kubectl apply/get/delete`). There is no separate REST API |
| **NIMCache** | Operator resource that pre-downloads or holds a model's weights on a PVC. Deleting it deletes its PVC |
| **NIMService** | Operator resource that runs a NIM (image, GPUs, replicas, storage, service, probes) |
| **Profile** | A NIM's optimised configuration (engine, precision, tensor parallelism) for a GPU type. Pin it so environments match |
| **NeMo Microservices** | NVIDIA's former suite (Entity Store, Data Store, Customizer, Evaluator, Guardrails). Sunset 2026-10-01 |
| **Entity Store** | NeMo service holding records/pointers for namespaces, projects, models and datasets. Not a user/session store |
| **Data Store** | NeMo service: a Hugging Face-compatible file store for datasets and fine-tuned models |
| **Deployment Management** | NeMo service: an API to deploy, list, update and delete NIMs through the NIM Operator. Sunset with NeMo Microservices |
| **NIM Proxy** | NeMo service: a single inference endpoint routing to all deployed NIMs. Sunset; Bifrost covers this role |
| **Cache pre-populator** | The Project's manual step that fills model-cache PVCs before NIMs start |
| **NeMo Helix** | Successor platform ("NeMo Platform"), pre-1.0 |
| **Bifrost** | LLM gateway: keys, routing, rate/token limits, logging, in front of the NIMs |
| **Model catalogue** | Proposed versioned file in git describing each model; generates gateway config |
| **Digest pinning** | Referencing an image by its content hash (`@sha256:…`) so the exact artefact is reproducible |
| **Promotion** | Moving the exact tested artefact and config DEV → QA → PROD, with gates and approvals |
| **Smoke test** | A quick automated check (chat, streaming, tool calls, context, auth) used as a promotion gate |
| **`maxSurge: 0`** | Rollout setting where the old pod stops before the new one starts. With one replica, an upgrade is an outage |
| **RWO / RWX** | PVC access modes: ReadWriteOnce (one node) / ReadWriteMany (many nodes) |
