# rag-stack-lab

A personal lab for learning an NVIDIA-style enterprise chat and RAG stack on
Kubernetes, end to end: what each part is, why it is there, how it is run, and
the commands and references needed to work with it.

## Start here

1. Read [the map](docs/00-map/README.md). It shows the whole system and the
   reading order.
2. Work through the pre-reading in [docs/prereading/](docs/prereading/) in that
   order. Each document ends with "Check yourself" questions.
3. Note what clicked and what is still fuzzy in [LEARNING.md](LEARNING.md).

Hands-on modules (lesson, runbook, checks, references) are added under
`modules/` as they are built and validated. The plan is in
[the design spec](docs/superpowers/specs/2026-11-13-rag-stack-lab-design.md).

## Pre-reading index

| # | Document | Stage |
|---|---|---|
| 01 | [NVIDIA NIM](docs/prereading/01-nvidia-nim.md) | Chat |
| 02 | [NeMo microservices](docs/prereading/02-nemo-microservices.md) | RAG |
| 03 | [NVIDIA RAG Blueprint](docs/prereading/03-nvidia-rag-blueprint.md) | RAG |
| 04 | [NV-Ingest and extraction](docs/prereading/04-nv-ingest-extraction.md) | RAG |
| 05 | [Traefik](docs/prereading/05-traefik.md) | Chat |
| 07 | [OpenTelemetry](docs/prereading/07-opentelemetry.md) | Chat |
| 08 | [OpenSearch and Elasticsearch vector search](docs/prereading/08-opensearch-elasticsearch-vector-search.md) | RAG |
| 09 | [Neo4j and graph retrieval](docs/prereading/09-neo4j-graph.md) | RAG |
| 10 | [Tanzu Kubernetes](docs/prereading/10-vmware-tanzu-kubernetes.md) | Platform |
| 11 | [Volcano and GPU scheduling](docs/prereading/11-volcano-gpu-scheduling.md) | Platform |
| 12 | [Harbor, Podman and images](docs/prereading/12-harbor-podman-images.md) | Platform |
| 13 | [Dev containers](docs/prereading/13-dev-containers.md) | Dev loop |
| 14 | [Tilt](docs/prereading/14-tilt.md) | Dev loop |
| 15 | [Cline with a self-hosted model](docs/prereading/15-cline-with-a-self-hosted-model.md) | Coding assistant |
| 16 | [uv, FastAPI and React primer](docs/prereading/16-uv-fastapi-react-primer.md) | Chat |
| 17 | [Clio-style conversation insights](docs/prereading/17-clio-conversation-insights.md) | Insights |
| 18 | [Reading an established repo](docs/prereading/18-reading-an-established-repo.md) | Method |

Number 06 is reserved for the LLM gateway, which is deferred.

## How to read the pre-reading

Every document opens with **The plain version**: an everyday-language
explanation with one analogy and five things to remember. Read that first,
then the technical sections. If the plain version does not make sense, that
is a defect in the document; note it in `LEARNING.md`.

The documents were researched against vendor documentation on 2026-11-13.
Anything that could not be confirmed from a source is marked `UNVERIFIED:`.
Treat those lines as open questions, not facts, and check the linked
references before relying on a command in a real environment.
