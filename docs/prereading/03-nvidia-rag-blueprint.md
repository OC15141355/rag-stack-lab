# NVIDIA RAG Blueprint

## In one paragraph

The NVIDIA RAG Blueprint is a reference implementation of a retrieval-augmented generation (RAG) system built from NVIDIA NIM inference containers plus two small Python services: a RAG server (answers questions) and an ingestor server (loads documents). It ships as Docker Compose files and a Helm chart, and it is deliberately a starting point to fork, not a product. The default vector store is Elasticsearch (Milvus is the built-in alternative). There is no built-in graph database path, so Neo4j would be something you add yourself. **Status warning (checked 2026-11-13): the GitHub repo is archived (read-only) and its README carries a "Deprecation notice (Oct 2026): no longer actively maintained, new production use is not recommended".** Treat it as a well-documented architecture to learn from and copy parts of, not as an upstream you will track.

## The plain version

Imagine a very well-read assistant who has never seen your company's files. Ask about your warranty terms and they will confidently guess. Now give that assistant a good librarian. You ask the question, the librarian runs to the shelves, pulls the five most relevant pages, and slides them across the desk. The assistant reads those pages and answers from them, pointing at where each fact came from. That is this system. The assistant is the language model. The librarian is the search part. The filing clerk, who sorts new documents onto the shelves in the first place, is a second service that reads each file, including the tables and charts, and files it by meaning.

Without it, you either get confident guesses, or you paste whole documents into every question, which is slow, costly and often too big to fit. NVIDIA's blueprint is a worked example of all these pieces already wired together, with a web page to try it on. One honest caveat: NVIDIA has stopped maintaining it, so it is a good textbook, not a good foundation to depend on.

If you remember only five things:

- The system has two jobs: filing documents in (ingest) and answering questions from them (query).
- Search works by meaning, not just matching words, and a second "double-check" model re-sorts the results.
- Everything is a separate container, so any part can be swapped, including the search database.
- Default database is Elasticsearch; it has no built-in graph (Neo4j) feature.
- The project is archived, so copy the ideas and pin your own fork.

## Why it exists

Plain LLMs do not know your documents. RAG fixes that by looking up relevant text at question time and putting it in the prompt. If you run LiteLLM, you already know the last step: an OpenAI-style chat call. The blueprint is everything in front of that call, packaged as pieces that you can swap.

### RAG primer (the minimum you need)

- **Chunking.** Documents are cut into pieces (here: pages or fixed-size token windows) because you can only search and prompt with small units. Chunk size trades recall against noise. The blueprint's ingestor defaults to `APP_NVINGEST_CHUNKSIZE=512` and `APP_NVINGEST_CHUNKOVERLAP=150` (from `docker-compose-ingestor-server.yaml`), with PDFs split by page (`APP_NVINGEST_TEXTDEPTH=page`).
- **Embeddings.** An embedding model turns text into a vector (here 2048 numbers; `APP_EMBEDDINGS_DIMENSIONS=2048`). Texts with similar meaning land near each other. The same model must embed the chunks and the query, otherwise distances are meaningless.
- **Vector search.** The vector database finds the nearest chunks to the query vector (approximate nearest neighbour, usually an HNSW index). Think of it as a database index where "equal" is replaced by "close".
- **Hybrid search.** Vector search is weak on exact tokens (part numbers, acronyms, error codes). Keyword search (BM25, a classic term-frequency ranking) is strong there. Hybrid runs both and merges the rankings, by Reciprocal Rank Fusion (RRF, merge by rank position) or by weighted scores.
- **Reranking.** A reranker is a second, slower model that reads the query and each candidate chunk together and scores relevance. You retrieve broadly (top 100) then keep the best few (top 10). It is usually the cheapest accuracy gain.
- **Generation.** The surviving chunks plus the question go to an LLM, which answers and can cite sources.
- **Graph retrieval.** Plain RAG treats chunks as independent. Questions that need relationships across documents ("which suppliers share a subsidiary with X?") do poorly. Graph RAG extracts entities and relations into a graph database and traverses it, then feeds the result to the LLM. The blueprint does not do this (see below). Your own `09-neo4j-graph.md` covers the graph side.

## How it works

### Services (confirmed from the repo README, `service-port-gpu-reference.md`, compose files and Helm templates)

In plain terms: the system is a set of small programs, each doing one job, that talk to each other over the network. Precisely, these are the containers:

| Service | Container / Helm name | Port | Job |
|---|---|---|---|
| RAG server | `rag-server` | 8081 | Query API. Orchestrates rewrite, retrieve, rerank, generate. LangChain-based. CPU only. |
| Ingestor server | `ingestor-server` | 8082 | Document upload/collection API. Calls NV-Ingest, embeds, writes to the vector DB. CPU only. |
| Frontend | `rag-frontend` | 8090 host (3000 in container) | Sample web UI. |
| NV-Ingest runtime | `nv-ingest-ms-runtime` (`rag-nv-ingest` in Helm) | 7670 (HTTP), 7671, 8265 (Ray dashboard) | Document extraction pipeline. See `04-nv-ingest-extraction.md`. |
| LLM NIM | `nim-llm-ms` (`nim-llm`) | 8999 host / 8000 | Answer generation. Default `nemotron-3-super-120b-a12b`. |
| Embedding NIM | `nemotron-vlm-embedding-ms` (default), `nemotron-embedding-ms` (text-only, optional) | 9081 / 9080 | Default model `nvidia/llama-nemotron-embed-vl-1b-v2`. |
| Reranker NIM | `nemotron-ranking-ms` | 1976 | `nvidia/llama-nemotron-rerank-1b-v2`. |
| Extraction NIMs | page-elements, graphic-elements, table-structure, nemotron-ocr | 8000-8014 | Used by NV-Ingest, not by the query path. |
| Elasticsearch | `elasticsearch` (ECK-managed in Helm) | 9200 | Default vector store. CPU only. |
| Redis | `compose-redis-1` | 6379 | Task queue and ingest status. |
| SeaweedFS | `seaweedfs` | 9010/9011 | S3-compatible object store (replaced MinIO in 2.6.0). |

Optional pieces (all opt-in): NeMo Guardrails with Llama 3.1 NemoGuard 8B Content Safety and Topic Control NIMs; a VLM (`nemotron-3-nano-omni-30b-a3b-reasoning`) for answering over images; VLM captioning (`nemotron-nano-12b-v2-vl`) during ingest; a VLM reranker (`llama-nemotron-rerank-vl-1b-v2`); Nemotron Parse (alternate PDF extraction); Riva ASR for audio; self-reflection (an LLM checks context relevance and answer groundedness, loops up to `MAX_REFLECTION_LOOP`, default 3); query rewriting for multi-turn; query decomposition; and Agentic RAG (a LangGraph plan-and-execute pipeline, new in 2.6.0, enabled per request with `agentic: true` or deployment-wide with `ENABLE_AGENTIC_RAG`).

### Request path: a query

In plain terms: a question goes in, passes through look-up and sorting steps, and an answer comes out. Precisely:

```
client --POST /v1/generate--> rag-server :8081
   1. [optional] guardrails check on the input
   2. [optional] query rewriter  (LLM, uses chat history)
   3. embed query                -> embedding NIM
   4. vector (or hybrid) search  -> Elasticsearch, top vdb_top_k (default 100)
   5. [default on] rerank        -> reranker NIM, keep reranker_top_k (default 10)
   6. LLM generation             -> LLM NIM, streamed back with citations
   7. [optional] reflection / output guardrails
```

Stages 2, 4, 5, 6 are the traced spans `query-rewriter`, `retriever`, `context-reranker`, `llm-stream` (from `query-to-answer-pipeline.md`).

### Request path: an ingest

In plain terms: a new file is read, cut into pieces, given a numeric "meaning fingerprint", and filed in the database. Precisely:

```
client --POST /documents (multipart)--> ingestor-server :8082
   1. stores files, batches them (NV_INGEST_FILES_PER_BATCH=16, NV_INGEST_CONCURRENT_BATCHES=4)
   2. submits jobs to nv-ingest-ms-runtime :7670 (Redis is the message broker)
   3. NV-Ingest: split pages -> detect elements -> OCR / table / chart extraction -> chunk -> embed (embedding NIM)
   4. results return to the ingestor, which writes vectors + text + metadata to the vector DB via its VDB operator
   5. extracted images / structured elements go to SeaweedFS (for citations)
   6. optional LLM summary per document
```

Step 4 is why the blueprint's vector DB layer is in the blueprint code (`src/nvidia_rag/utils/vdb/`), not in NV-Ingest: NV-Ingest returns extracted records, and the blueprint's `ElasticVDB` class writes them (it extends the `nv_ingest_client` VDB base class).

### Vector stores, and what about OpenSearch and Neo4j

In plain terms: the vector store is the filing cabinet that can find pages by meaning, and the question is which cabinets fit. Precisely:

- **Built in** (from `src/nvidia_rag/utils/vdb/` and the compose comments): `elasticsearch` (default since 2.6.0), `milvus` (GPU-accelerated, profile `milvus`), `lancedb` (only with the experimental `INGESTOR_BACKEND=nrl` ingest path).
- **Hybrid search** is a setting, `APP_VECTORSTORE_SEARCHTYPE=dense|hybrid`, with `APP_VECTORSTORE_RANKER_TYPE=rrf|weighted` and `APP_VECTORSTORE_DENSE_WEIGHT` / `_SPARSE_WEIGHT`. The Elasticsearch class contains a hybrid path. The docs page `hybrid_search.md` itself is written for Milvus only.
- **Elasticsearch GPU indexing** needs an Elastic Enterprise licence and a custom GPU image; default is CPU.
- **OpenSearch: no built-in support.** The docs describe a "bring your own vector database" route: subclass `VDBRag`, register it in `_get_vdb_op` in `src/nvidia_rag/utils/vdb/__init__.py`, set `APP_VECTORSTORE_NAME` to your name, and rebuild the images. The docs' dependency example literally uses `opensearch-py>=3.0.0`, but that is an example snippet, not an OpenSearch implementation. UNVERIFIED: whether the shipped Elasticsearch client code works unmodified against an OpenSearch cluster (I did not test it, and Elasticsearch client libraries often refuse non-Elastic servers). Plan on writing an operator (`elastic_vdb.py` is the reference, ~1300 lines, and `notebooks/building_rag_vdb_operator.ipynb`).
- **Neo4j / graph: no built-in path.** A search of the docs and code found no Neo4j or graph-retrieval feature. The closest hooks are (a) a custom VDB operator, (b) retrieval-only mode (`retrieval-only-deployment.md`), and (c) Agentic RAG with tool-like sub-tasks. UNVERIFIED: whether Agentic RAG can be extended with a custom graph tool; I did not read `agentic-rag.md` in full. The pragmatic design is a graph retriever beside the blueprint whose results you merge before generation.

## How you run it

All commands are from the repo docs (`deploy-docker-self-hosted.md`, `deploy-docker-nvidia-hosted.md`, `deploy-helm.md`). Latest tag: `v2.6.2` (released 2026-08-20). The Helm doc pins the chart to `v2.6.0`.

**Docker Compose, self-hosted GPUs** (single node):

```bash
export NGC_API_KEY="nvapi-..."                     # NGC key; used to pull images and models
echo "${NGC_API_KEY}" | docker login nvcr.io -u '$oauthtoken' --password-stdin   # registry login
git clone https://github.com/NVIDIA-AI-Blueprints/rag.git && cd rag
mkdir -p ~/.cache/model-cache && export MODEL_DIRECTORY=~/.cache/model-cache     # NIM model cache
source deploy/compose/.env                         # loads on-prem endpoint variables
USERID=$(id -u) docker compose -f deploy/compose/nims.yaml up -d                 # all NIMs (wait for healthy)
docker compose -f deploy/compose/vectordb.yaml up -d                             # Elasticsearch
docker compose -f deploy/compose/docker-compose-ingestor-server.yaml up -d       # ingestor, NV-Ingest, Redis
docker compose -f deploy/compose/docker-compose-rag-server.yaml up -d            # rag-server + frontend
curl 'http://localhost:8081/v1/health?check_dependencies=true'                   # dependency health check
```

**Docker Compose with NVIDIA-hosted endpoints** (no local GPUs): in `deploy/compose/.env` uncomment the "Cloud NIM Endpoints" block (it points `APP_EMBEDDINGS_SERVERURL` at `https://integrate.api.nvidia.com/v1`, extraction NIMs at `https://ai.api.nvidia.com/v1/cv/nvidia/...`, and sets `APP_LLM_SERVERURL=""` so the hosted catalogue is used), then `source deploy/compose/.env` and skip `nims.yaml`. Needs about 50 GB disk. Expect HTTP 429 rate limits on ingests of more than about 10 files; the troubleshooting page suggests `NV_INGEST_FILES_PER_BATCH=1`, `NV_INGEST_CONCURRENT_BATCHES=1`, `MAX_INGEST_PROCESS_WORKERS=1`, `NV_INGEST_MAX_UTIL=8`.

**Kubernetes with Helm and the NIM Operator** (the path relevant to you):

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia --username='$oauthtoken' --password=$NGC_API_KEY
helm install nim-operator nvidia/k8s-nim-operator -n nim-operator --create-namespace   # NIM Operator: CRDs NIMCache/NIMService
helm repo add elastic https://helm.elastic.co && helm install elastic-operator elastic/eck-operator -n elastic-system --create-namespace
kubectl create namespace rag
helm upgrade --install rag -n rag https://helm.ngc.nvidia.com/nvidia/blueprint/charts/nvidia-blueprint-rag-v2.6.0.tgz \
  --username '$oauthtoken' --password "${NGC_API_KEY}" \
  --set imagePullSecret.password=$NGC_API_KEY --set ngcApiSecret.password=$NGC_API_KEY \
  --set nimOperator.nim-llm.image.tag=2.0.9 \
  --set 'nimOperator.nim-llm.env[6].name=NIM_PASSTHROUGH_ARGS' --set-string 'nimOperator.nim-llm.env[6].value=--max-num-seqs 384'
kubectl get nimcache,nimservice,pods -n rag        # model download progress (first run: 60-70 min)
kubectl port-forward -n rag service/rag-frontend 3000:3000 --address 0.0.0.0
```

The chart prerequisites: Kubernetes v1.34.2 on Ubuntu 22.04/24.04, Helm 3 (not 4), a default StorageClass, the NVIDIA GPU Operator, the NIM Operator, and the ECK operator (only if you keep chart-managed Elasticsearch). The chart has sub-chart dependencies: nv-ingest 26.3.0, seaweedfs, eck-elasticsearch, zipkin, opentelemetry-collector, kube-prometheus-stack (`Chart.yaml`). For GitOps you would render values once and own them in your repo; edit `deploy/helm/nvidia-blueprint-rag/values.yaml` and re-run the upgrade (their documented "Change a Deployment" flow).

**Switching vector store** (verified from `change-vectordb.md`; you must re-ingest, nothing migrates):

```bash
# Milvus, compose
docker compose -f deploy/compose/vectordb.yaml --profile milvus up -d
export APP_VECTORSTORE_NAME="milvus" APP_VECTORSTORE_URL="http://milvus:19530"
# then recreate ingestor-server and rag-server; in Helm set eck-elasticsearch.enabled=false and nv-ingest.milvusDeployed=true
```

**Call the API** (route list from the shipped OpenAPI schema; field names and defaults from the same schema, request body is my minimal example):

```bash
curl -N -X POST http://localhost:8081/v1/generate -H 'Content-Type: application/json' -d '{
  "messages":[{"role":"user","content":"What does the warranty exclude?"}],
  "collection_names":["multimodal_data"], "use_knowledge_base":true,
  "vdb_top_k":100, "reranker_top_k":10, "enable_reranker":true, "enable_citations":true}'
curl -F 'documents=@manual.pdf' -F 'data={"collection_name":"multimodal_data"}' http://localhost:8082/documents   # ingest (the data field shape is UNVERIFIED)
```

RAG server routes: `GET /v1/health`, `/v1/metrics`, `/v1/configuration`, `POST /v1/generate`, `/v1/chat/completions`, `/v1/search`, `GET /v1/summary`. Ingestor routes: `GET /health`, `/documents` (POST/PATCH/GET/DELETE), `/status`, `/collections` (GET/POST/DELETE), `POST /collection`, and metadata PATCH routes. `/v1/chat/completions` is the OpenAI-shaped route that a LiteLLM model entry could front. UNVERIFIED: how fully it honours OpenAI request fields, and whether it requires blueprint-specific extras; check the schema before wiring.

## How it fits the stack

- **Calls it:** the sample UI, your clients, or LiteLLM (as a custom OpenAI-compatible backend). Every per-request knob (`vdb_top_k`, `reranker_top_k`, `enable_*`, `model`, `llm_endpoint`, `embedding_endpoint`, `reranker_endpoint`, `vdb_endpoint`) is overridable per call.
- **It calls:** the NIM containers, which all speak OpenAI-style HTTP (`/v1/chat/completions`, `/v1/embeddings`). Because the LLM is addressed by URL (`APP_LLM_SERVERURL`), you can point it at LiteLLM or any OpenAI-compatible server instead of the bundled NIM. UNVERIFIED: whether non-NIM servers need extra care for the reranker (it uses NVIDIA's ranking API shape) and for reasoning-token handling.
- **Per-role keys:** `APP_LLM_APIKEY`, `APP_EMBEDDINGS_APIKEY`, `APP_RANKING_APIKEY` and more fall back to `NVIDIA_API_KEY`.
- **Observability (built in, off by default):** OpenTelemetry Collector plus Zipkin for traces, Prometheus metrics at `:8889/metrics` (compose), Grafana dashboards shipped as `deploy/config/rag-metrics-dashboard.json` and `agentic-rag-metrics-dashboard.json`. Enable with `APP_TRACING_ENABLED=True` (compose: `docker compose -f deploy/compose/observability.yaml up -d` with `OPENTELEMETRY_CONFIG_FILE` set). In Helm set `serviceMonitor.enabled`, `opentelemetry-collector.enabled`, `zipkin.enabled`, `kube-prometheus-stack.enabled` to true and install the Prometheus Operator CRDs first (chart version 26.0.1 in the doc). If you already run Prometheus Operator, enable only the ServiceMonitor and OTLP endpoints (`APP_TRACING_OTLPHTTPENDPOINT`, `APP_TRACING_OTLPGRPCENDPOINT`). Metrics: `retrieval_time_ms`, `context_reranker_time_ms`, `llm_ttft_ms`, `llm_generation_time_ms`, `rag_ttft_ms`.
- **Hardware (from `support-matrix.md`):** Ubuntu 22.04, driver 560+, CUDA 12.9+, 200 GB free disk. Docker self-hosted: the default LLM needs 2 GPUs (FP8, TP2); the doc says 3x H100 (or B200 or RTX PRO 6000) total. Helm defaults: 8x H100-80GB, or 5x H100-80GB with MIG. Each optional GPU service (VLM, captioning, VLM rerank, Nemotron Parse, audio) adds about one GPU unless you share. Guardrails need 2 more GPUs (48 GB each; tested on H100/A100; B200 unsupported; Helm deployment unsupported). H200 is not named in the blueprint's own matrix. UNVERIFIED: H200 sizing; infer from H100 counts only after testing.

## What goes wrong

- **First install looks hung.** Helm takes 60-70 minutes because NIMCache jobs download 100-150 GB of models with no progress bar. Watch `kubectl get nimcache,nimservice -n rag` and PVC sizes.
- **Pods Pending.** Missing default StorageClass, access-mode mismatch on the cache PVCs, or fewer free GPUs than the chart requests (it asks for exclusive GPUs per NIM).
- **Wrong embedding dimension.** Error "This model does not support 'dimensions', but a value of '2048' was provided." Set `APP_EMBEDDINGS_DIMENSIONS` to match, and re-ingest if you ever change model or dimension.
- **Hosted endpoint 429s** during ingest (see above).
- **Elasticsearch timeouts** on big documents: raise `ES_REQUEST_TIMEOUT` (docs example 1200). The troubleshooting page also notes slow VDB upload on Helm Elasticsearch.
- **Ingestor OOM** on large files: raise the ingestor memory limit (their example is 200Gi limit, 25Gi request) and set `SUMMARY_MAX_PARALLELIZATION=1`.
- **Image-only PDFs ingest empty.** Enable `APP_NVINGEST_EXTRACTINFOGRAPHICS` or captioning.
- **Service names change with the Helm release prefix.** Check `kubectl get svc -n rag` before pointing URLs.
- **Docker Engine 29.5.x** cannot pull required NGC images (per the doc).
- **Two LLM-side defaults changed in 2.6.x** (cloud default model became `nemotron-3-ultra-550b-a55b`, self-hosted image tag `2.0.9`). Pin image tags and chart version yourself.
- **Upstream risk.** Archived repo: no security patches. Plan an internal fork and pin NV-Ingest.

## Check yourself

1. What are the two custom services in the blueprint, and which port does each listen on?
2. Walk the query path and say which stages call a GPU model and which call only CPU services.
3. Why must the embedding model and `APP_EMBEDDINGS_DIMENSIONS` be identical at ingest and query time?
4. Where does the vector DB write happen on ingest: inside NV-Ingest or in the blueprint's ingestor? Why does that matter for adding OpenSearch?
5. List the three built-in vector store names, and describe the steps to add a fourth.
6. What does the blueprint offer for graph retrieval, and where would you attach Neo4j?
7. For a Helm install on H100s, how many GPUs does the default chart ask for, and what reduces that number?
8. Which metrics and trace spans would you look at to tell a slow retriever from a slow LLM?

## References

All checked 2026-11-13. Repo state: archived, last push 2026-11-03, latest tag v2.6.2 (published 2026-08-20), Helm chart v2.6.0, appVersion v2.6.0.

- https://github.com/NVIDIA-AI-Blueprints/rag (README, deprecation notice, component list)
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/support-matrix.md
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/service-port-gpu-reference.md
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/change-vectordb.md
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/elasticsearch-configuration.md
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/hybrid_search.md
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/deploy-docker-self-hosted.md
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/deploy-docker-nvidia-hosted.md
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/deploy-helm.md
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/observability.md and query-to-answer-pipeline.md
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/nemo-guardrails.md, self-reflection.md, release-notes.md, troubleshooting.md
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/api_reference/openapi_schema_rag_server.json and openapi_schema_ingestor_server.json
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/deploy/compose/.env, docker-compose-ingestor-server.yaml
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/deploy/helm/nvidia-blueprint-rag/Chart.yaml
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/src/nvidia_rag/utils/vdb/elasticsearch/elastic_vdb.py and src/nvidia_rag/ingestor_server/main.py
- Related lab notes: `04-nv-ingest-extraction.md`, `08-opensearch-elasticsearch-vector-search.md`, `09-neo4j-graph.md`
