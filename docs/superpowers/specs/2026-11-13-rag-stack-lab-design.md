# rag-stack-lab — design

Date: 2026-11-13
Status: awaiting review

## Purpose

A personal learning lab for an NVIDIA-style enterprise RAG stack on Kubernetes.
The goal is end-to-end understanding: what each component is, why it is in the
stack, how it is deployed and operated, and the commands and references needed
to work with it. The learner must be able to rebuild the whole thing from the
runbooks without help and explain each layer.

The repo is neutral: it contains no employer, customer, or project names.

## The system being learned

| Layer | Components |
|---|---|
| Platform | Kubernetes (Tanzu in the target environment, RKE2 in the lab), Volcano GPU scheduling, H100/H200-class GPUs, Harbor, Podman |
| Developer loop | Dev containers, Tilt, Cline against the inference service |
| Edge / gateway | Traefik, NIM proxy (Bifrost deferred) |
| Model serving | NVIDIA NIMs, NeMo microservices, a uv-run Python inference service consumed by Cline |
| RAG data path | NV-Ingest / NeMo extraction, OpenSearch (Elastic as comparison), Neo4j |
| App | React/TypeScript frontend, Python/FastAPI backend |
| Cross-cutting | OpenTelemetry |
| Reference architecture | NVIDIA RAG Blueprint |

## Constraints

- **Lab cluster**: homelab RKE2, six nodes, about 30 GB RAM free in total
  (largest single-node headroom about 12 GB). Everything runs single-replica
  with explicit resource requests and limits.
- **GPU**: the only NVIDIA card is a GTX 1070 (8 GB). It cannot run LLM NIMs.
  At design time the node advertises 0 allocatable GPUs; fixing that is a
  prerequisite of module 13, not of earlier modules.
- **Models**: all NIM calls in homelab modules go to NVIDIA's hosted endpoints,
  which expose the same API as self-hosted NIMs. This needs an NVIDIA developer
  account and API key, supplied by the learner and stored as a Kubernetes
  Secret created by hand (never committed).
- **Tanzu**: licensed, so not hands-on. Covered as a read-only "what differs
  from plain Kubernetes" section.
- **GPU-only topics** (self-hosting a NIM, the NIM Operator, NeMo microservices
  that need a GPU, Volcano scheduling real GPU jobs) are done in short rented
  cloud GPU sessions driven by a runbook, then torn down.
- **Only public or synthetic documents** are ingested, since model calls leave
  the network.

## Repo layout

```
README.md                      how to use the lab, module index, progress table
docs/00-map/                   architecture, one request traced end to end, glossary
modules/NN-name/
  LESSON.md                    what, why, how it works, failure modes
  RUNBOOK.md                   commands from nothing to working, with expected output
  CHECKS.md                    positive and negative consumer-side probes
  REFS.md                      official doc links, command cheat sheet
  manifests/                   YAML and Helm values used by the runbook
docs/superpowers/specs/        design docs
LEARNING.md                    log of what clicked and what is still fuzzy
```

## Modules

| # | Module | Covers | Where |
|---|---|---|---|
| 0 | Map | Whole architecture, one request traced, glossary | docs |
| 1 | Images | Podman, Harbor, mirroring NGC images for a disconnected environment | homelab |
| 2 | Platform | Kubernetes pieces the stack relies on; Tanzu differences (read-only) | homelab |
| 3 | Dev loop | Dev containers (devcontainer.json, features, Podman as the engine); Tilt (Tiltfile, live update, building to Harbor, deploying to a dev namespace) | laptop + homelab |
| 4 | Traefik | IngressRoute, middlewares, TLS, coexisting with the existing ingress controller | homelab |
| 5 | Inference + Cline | NIM API via hosted endpoints; the uv inference service; running it from its repo (inside the dev container and under Tilt); configuring Cline to use it for agentic coding, including what the endpoint must support (OpenAI-compatible chat completions, streaming, context window) and how to diagnose it when Cline fails | laptop + homelab |
| 6 | Gateway | The NIM proxy and the role of an LLM gateway, contrasted with LiteLLM. Bifrost is deferred: it is not in the target stack yet, and gets added here when it is | homelab |
| 7 | Vector search | OpenSearch kNN and hybrid search; Elastic differences | homelab |
| 8 | Graph | Neo4j, Cypher, graph-backed retrieval | homelab |
| 9 | Ingestion | NV-Ingest and extraction | homelab |
| 10 | RAG Blueprint | Assembling 5–9 as the blueprint does; NeMo Retriever and other NeMo microservices | homelab |
| 11 | App | FastAPI backend, React/TS frontend, developed in the dev container with Tilt | homelab |
| 12 | OpenTelemetry | Traces and metrics across every hop into the existing Grafana stack | homelab |
| 13 | Volcano | Queues, gang scheduling, on CPU then on the GTX 1070 | homelab |
| 14 | GPU day | Self-hosted NIM, NIM Operator, Volcano with real GPU jobs | rented GPU |

## How a module is produced and used

1. Claude checks the component's current official documentation before writing
   anything. Component names, chart versions and config keys are taken from the
   docs, not from memory. This matters most for NeMo microservices, the NIM
   proxy.
2. Claude writes the runbook and executes it on the homelab. A runbook is not
   done until every command in it has been run and every check in `CHECKS.md`
   has passed, including the negative probes.
3. Claude writes the lesson: explanation first, with the mechanism, the reason
   it is in this stack, and how it relates to tools the learner already runs.
4. The learner reads the lesson, deletes the module's resources, and rebuilds
   from the runbook, predicting the result of key commands before running them.
5. The learner explains the module back in a few sentences; gaps go in
   `LEARNING.md`.

For module 11 the learner writes the application code with stepped hints;
Claude supplies only scaffolding unrelated to the concept being learned.

## Lab environment

- Namespaces prefixed `raglab-`, one per layer where it helps isolation.
- Deployed by hand with `kubectl` and `helm` from the runbooks. Not managed by
  ArgoCD, so teardown and rebuild are free of GitOps reconciliation.
- Teardown for every module is a documented command in its runbook.
- Hostnames under `*.yagura.dev`, routed by the lab's Traefik on its own
  IngressClass so the existing ingress controller is untouched.
- Secrets are created imperatively from the learner's shell; manifests in git
  reference them by name only.
- Harbor placement (in-cluster or on the Docker host) is decided in module 1
  after measuring its footprint.

## Delivery slices

- **Slice 1 (this spec's implementation plan)**: repo skeleton, module 0, and
  modules 1–6. Exit condition: Cline, on the laptop, completes an agentic
  coding task through the lab inference service, with the request travelling
  Traefik → inference service → hosted NIM; a code change to the inference service
  reaches the cluster through Tilt; and the learner has rebuilt modules 1–6
  from the runbooks.
- **Slice 2**: modules 7–10 (data path and blueprint).
- **Slice 3**: modules 11–12 (app and observability).
- **Slice 4**: modules 13–14 (Volcano and the GPU day).

Each later slice gets its own short spec and plan.

## Out of scope

- High availability, production sizing, and backup of lab data.
- Running Tanzu.
- Fine-tuning or model customisation.
- Any real or sensitive documents.

## Risks

- **Memory pressure**: OpenSearch, Neo4j, Harbor and NV-Ingest together may
  exceed headroom. Mitigation: explicit limits, and scale earlier modules to
  zero when a later one needs the room.
- **Hosted endpoint limits**: free-tier credits or rate limits may throttle
  ingestion. Mitigation: small corpus; note the limits in module 5.
- **Fast-moving components**: NVIDIA docs change often. Mitigation:
  each `REFS.md` records the versions the runbook was validated against and the
  date.
