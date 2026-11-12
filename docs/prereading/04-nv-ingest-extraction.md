# NV-Ingest / NeMo Retriever Library (document extraction)

## In one paragraph

NV-Ingest turns messy documents (PDFs with tables, charts and scanned pages; Office files; HTML; images; audio) into clean text chunks plus structured metadata that you can embed and search. It does this by splitting documents into pages, running a small set of GPU vision models (page-layout detection, table-structure detection, chart-element detection, OCR) via NIM containers, and assembling the results into a fixed JSON schema. NVIDIA has since renamed it: the GitHub repo `NVIDIA/nv-ingest` now redirects to `NVIDIA/NeMo-Retriever`, and the product is called "NeMo Retriever Library" (older material says "NV-Ingest" or "NVIDIA Ingest"; the docs say they are the same thing). Important for you: the RAG Blueprint pins the old architecture (image `nv-ingest:26.3.0`), while the current release (26.8.x) has a reworked service. This note covers both and says which is which.

## The plain version

Think of a mail-room clerk who opens a huge pile of paperwork before it goes to the archive. A bad clerk just photocopies the text and throws away anything that is not plain sentences: the tables turn to jumbled words, the charts vanish, the scanned pages come out blank. A good clerk looks at every page, notices "this part is a table, that part is a chart, this is a scanned photo", reads each properly, and writes a tidy summary card for each piece. This software is the good clerk, and it uses a few specialised "eyes" (vision models) to do the looking.

If it did not exist, anything locked inside tables, figures and scans would never reach the search system, and the assistant would simply never be able to answer questions about it. The clerk is only as good as its inputs, and a search system cannot find what was never written down.

One thing to know: NVIDIA renamed it, and there are two generations. The blueprint uses the older one.

If you remember only five things:

- It reads documents page by page and treats text, tables, charts and scans differently.
- It needs graphics cards for its vision models, or can borrow NVIDIA's hosted ones over the internet.
- Its output is neat records of text plus labels, ready to be turned into searchable form.
- Getting those records into your database is a separate step you may have to write.
- The name has changed (nv-ingest to NeMo Retriever Library); pin the exact version.

## Why it exists

A naive pipeline does `pdftotext`, then chunks. That loses tables (columns collapse into a word stream), drops everything inside charts and scanned images, and ignores layout. For enterprise documents, much of the answer lives in tables and figures. Extraction quality bounds RAG quality: the best retriever cannot return a chunk that was never extracted.

What it resembles in your world: a batch ETL service in front of a data store, with an async job queue, parallel workers, and GPU model servers behind it, much like a media-transcoding pipeline. The models are called over HTTP/gRPC like any other inference backend.

## How it works

### Pipeline stages (from the overview docs and the 26.03/26.08 support matrices)

In plain terms: each page is inspected, its parts are sent to the right specialist model, and the findings are cut into pieces. Precisely:

```
file -> split into pages -> (text via PDFium)  ----------------------+
                         -> render page image                         |
                            -> page-elements model: find tables,      |
                               charts, infographics, images           |
                               -> table-structure model -> OCR -> markdown table
                               -> graphic-elements model -> OCR -> chart text
                            -> OCR for scanned/infographic regions    |
   -> chunk / split -> (optional) caption images with a VLM -> embed -> store/return
```

Models (names as in the 26.3.0 and 26.08 docs; all NIM containers):

| Role | Model | Notes |
|---|---|---|
| Page layout / element detection | `nemotron-page-elements-v3` | Finds tables, charts, infographics on each page image. |
| Table structure | `nemotron-table-structure-v1` | Rows, columns, cells; output is markdown. |
| Chart elements | `nemotron-graphic-elements-v1` | Titles, legends, axes, values inside charts. |
| OCR | `nemotron-ocr-v1` (26.3.0, used by the blueprint); `nemotron-ocr-v2` (26.08 docs) | Text from images. Older: PaddleOCR, still listed as optional by the blueprint. |
| Embedding | 26.3.0: `llama-nemotron-embed-1b-v2` family; 26.08 Helm default: "Nemotron 3.5 Embed 1B" (`nemotron-embed:latest`); the library tokenizer is `nvidia/Nemotron-3-Embed-1B-BF16` | Embedding model choice changed between releases; the blueprint overrides it (see below). |
| Optional PDF parser | Nemotron Parse (`method="nemotron_parse"`) | Slower, more accurate on scanned pages. |
| Optional captioning | `nemotron-nano-12b-v2-vl` (26.3.0) or `nemotron-3-nano-omni-30b-a3b-reasoning` (26.08) | Describes images. |
| Optional audio | Parakeet / Riva ASR | Not supported on H200 NVL or B200 per the 26.08 matrix. |
| Optional reranker | `llama-nemotron-rerank-1b-v2` / `-vl-1b-v2` | For retrieval testing. |

By default PDF text comes from PDFium (a non-ML library), and the vision NIMs handle tables, charts and infographics. The library "does not run one static pipeline": each job lists the tasks to run (extract, split, embed, caption, store, vdb_upload).

### Supported file types (26.08 overview)

avi, bmp, docx, html (converted to markdown), jpeg, json (as text), md (as text), mkv, mov, mp3, mp4, pdf, png, pptx, sh (as text), svg (needs `cairosvg`), tiff, txt, wav. The 26.3.0 docs list video containers (avi, mkv, mov, mp4) as "early access" and omit svg.

### Architecture, 26.3.0 (the version the blueprint pins)

In plain terms: jobs wait in a queue, a pool of workers picks them up, and the workers phone the model servers. Precisely (a "message broker" is just the queue software, here Redis; "Ray" is a Python framework that runs many workers in parallel):

```
ingestor-server --(Python client, port 7670 HTTP API)--> nv-ingest-ms-runtime
                                                            |  Redis list "ingest_task_queue" (message broker, :6379)
                                                            |  Ray workers in one container (dashboard :8265)
                                                            +--HTTP/gRPC--> page-elements, graphic-elements,
                                                                            table-structure, ocr, [embed], [vlm]
```

Facts from the blueprint's compose file: the runtime image is `nvcr.io/nvidia/nemo-microservices/nv-ingest:26.3.0`, it exposes 7670 (HTTP API), 7671 (a "simple broker" for dev) and 8265 (Ray dashboard), and uses `MESSAGE_CLIENT_TYPE=redis`, `MESSAGE_CLIENT_HOST=redis`. It needs a large `shm_size` (40 GB; Ray guidance is at least 30% of memory). Workers scale statically or dynamically (`INGEST_DISABLE_DYNAMIC_SCALING`, `INGEST_DYNAMIC_MEMORY_THRESHOLD=0.80`). Large PDFs can be pre-split into page chunks for parallelism (V2 API: `/v2/submit_job`, `/v2/fetch_job/{job_id}`; blueprint knobs `APP_NVINGEST_ENABLE_PDF_SPLIT_PROCESSING`, `APP_NVINGEST_PAGES_PER_CHUNK=16`). The V1 HTTP routes include `POST /v1/submit_job`, `GET /v1/fetch_job/{job_id}`, `GET /v1/status/{job_id}`.

### Architecture, 26.08.x (current release)

In plain terms: the newer version is rebuilt as a web service with a cleaner front door. Precisely:

The newer docs describe a "Retriever service" with a gateway, a job-creation REST contract (`POST /v1/ingest/job`, then multipart uploads to `/v1/ingest/job/{job_id}/document`), collections (`/v1/collections`), queries (`/v1/query`), and probes `GET /v1/live` and `GET /v1/health`. Results come back as a Ray Dataset or pandas DataFrame. The Python API is `create_ingestor(run_mode=...)` with modes `inprocess`, `batch` and `service`. The README says legacy ingestion APIs are being phased out and the default vector store in this line is LanceDB. UNVERIFIED: whether Redis remains in the 26.08 service data path; I did not find a statement either way, and the Helm chart README was not opened.

### Output schema

In plain terms: every extracted piece comes out as a labelled card. Precisely:

Each extracted object is a record with `content_metadata.type` (`text`, `structured` for tables/charts, `image`, `audio`), the text or markdown content, source metadata (file, page), optional embedding, and type-specific blocks (`text_metadata`, `table_metadata`, `image_metadata`, `audio_metadata`). Reference: `content-metadata.md`.

## How you run it

**Python library mode** (small jobs, under about 100 PDFs, hosted NIMs by default). 26.08 README example, trimmed:

```bash
uv venv --python 3.12 nr && source nr/bin/activate     # isolated env
export NVIDIA_API_KEY=nvapi-...                        # build.nvidia.com key for hosted NIMs
# install per the nemo_retriever quickstart in the repo (package name changed across releases; UNVERIFIED which PyPI name is current)
```
```python
from nemo_retriever import create_ingestor
ing = (create_ingestor(run_mode="batch")
       .files(["data/multimodal_test.pdf"])
       .extract(extract_text=True, extract_tables=True, extract_charts=True)
       .embed()
       .vdb_upload())          # LanceDB by default
df = ing.ingest()              # returns a pandas DataFrame
```

**Docker Compose service, 26.3.0 era** (from the legacy quickstart):

```bash
git clone https://github.com/nvidia/NeMo-Retriever && cd NeMo-Retriever
docker login nvcr.io                                  # user $oauthtoken, password = NGC key
# .env needs NGC_API_KEY and NIM_NGC_API_KEY
docker compose --profile retrieval up                 # NIMs + runtime + Milvus; first start takes 10-15 min
```

**Kubernetes**: install the NeMo Retriever Helm chart (`nemo_retriever/helm` in the repo; the README says GA chart version `26.8.1`). It deploys four core NIMs through the NIM Operator: `page_elements`, `table_structure`, `ocr`, `vlm_embed`. Gotcha straight from the docs: each is an independent `NIMService` requesting `nvidia.com/gpu: 1`, so on a plain cluster that is **four exclusive GPUs**, even though the models would fit on one A10G-class card. Fix with GPU time-slicing (at least four advertised slots plus `nodeSelector` pinning) or MIG. Optional NIMs (rerank, Parse, Omni captioning, audio, answer LLM) each add another GPU. The chart ships air-gapped install instructions.

**In the blueprint** (no separate install; `deploy/compose/docker-compose-ingestor-server.yaml` and the Helm sub-chart `nv-ingest 26.3.0`). The blueprint configures NV-Ingest through `APP_NVINGEST_*` env vars on the ingestor: `EXTRACTTEXT/TABLES/CHARTS/INFOGRAPHICS/IMAGES`, `PDFEXTRACTMETHOD` (`pdfium`, `nemotron_parse`, None), `CHUNKSIZE=512`, `CHUNKOVERLAP=150`, `TEXTDEPTH=page`, and the NIM URLs (`PAGEELEMENTSURL`, `GRAPHICELEMENTSURL`, `OCRURL`, `TABLESTRUCTUREURL`). Standalone use without the ingestor server is documented in `nv-ingest-standalone.md` (deploy only `nv-ingest-ms-runtime` and `redis`; citations are then disabled).

**Hosted versus local GPUs.** Point each model at a URL. Hosted defaults (26.08 matrix): `https://ai.api.nvidia.com/v1/cv/nvidia/nemotron-page-elements-v3`, `.../nemotron-table-structure-v1`, `.../nemotron-ocr-v2`, embeddings at `https://integrate.api.nvidia.com/v1/embeddings`. In the blueprint runtime the equivalents are env vars set as `YOLOX_HTTP_ENDPOINT`, `YOLOX_INFER_PROTOCOL=http`, `YOLOX_GRAPHIC_ELEMENTS_HTTP_ENDPOINT`, `YOLOX_TABLE_STRUCTURE_HTTP_ENDPOINT`, `OCR_HTTP_ENDPOINT`, `OCR_INFER_PROTOCOL=http`, plus `NVIDIA_API_KEY`; local mode uses gRPC to `page-elements:8001` etc. Hosted endpoints need documents to leave your network: only use them for non-sensitive test data.

## How it fits the stack

- **Called by:** the blueprint's ingestor-server (Python client to `:7670`), or your own scripts via the Python client, the CLI, or REST.
- **Calls:** the extraction NIMs (HTTP or gRPC), an embedding NIM (OpenAI-style `/v1/embeddings`), optionally a VLM captioner, optionally Nemotron Parse. Redis (26.3.0) as broker; SeaweedFS/MinIO-style S3 for image offload.
- **How output reaches the vector store.** NV-Ingest itself ships built-in uploaders (Milvus in 26.3.0, LanceDB in 26.08) through a `VDB` base-class interface in `nv_ingest_client.util.vdb`. The blueprint does not use those: its `ElasticVDB` (a subclass of that interface) writes the returned records into Elasticsearch in `write_to_index`. Other stores are written by subclassing the same interface: the 26.08 docs list Elasticsearch (via the blueprint), Pinecone and Teradata as partner implementations. For OpenSearch you would write such a subclass (see `08-opensearch-elasticsearch-vector-search.md`). For Neo4j you would consume the records yourself: the content/page/table structure is a natural source for nodes and edges (see `09-neo4j-graph.md`).
- **Experimental alternative inside the blueprint:** `INGESTOR_BACKEND=nrl` swaps NV-Ingest for the in-process NeMo Retriever Library, but that path supports only LanceDB (the ingestor raises otherwise).
- **Observability:** OpenTelemetry (`OTEL_EXPORTER_OTLP_ENDPOINT`) to Zipkin for traces, Prometheus for metrics (per legacy telemetry docs); the Ray dashboard on 8265. The blueprint also reports ingest counters (documents, elements, pages) via OTel.
- **Resources (26.3.0 docs):** production guidance 256 GB RAM and 32 CPU cores, one GPU with at least 24 GB (core pipeline fits one A10G-class or better; ~150 GB disk); more RAM and CPU improve parallelism and memory use can approach host capacity. Optional features need dedicated extra GPUs. H100, H200 NVL, A100, L40S, B200 and RTX Pro 6000 are listed as supported.

## What goes wrong

- **Pods Pending on GPU (Helm).** See the four-GPU rule above. `kubectl describe pod` shows insufficient `nvidia.com/gpu`.
- **Out of memory / "can't start new thread" / "too many open files".** Big batches or many workers. Reduce concurrency (`MAX_INGEST_PROCESS_WORKERS`, `NV_INGEST_MAX_UTIL`), raise limits, or use static scaling with a memory threshold.
- **Redis memory growth.** Documents are queued base64-encoded and fragmented; big concurrent jobs pile up in Redis (called out in the scaling-modes doc).
- **HTTP 429 from hosted endpoints.** Throttle as in the blueprint doc (batch of 1, one worker).
- **HTTP 422 "invalid image URL" from hosted Page Elements.** Hosted accepts only inline base64 images under about 180,000 characters; the client downscales at 512,000, which is too late for hosted. Lower `dpi` and keep `render_mode="fit_to_model"`.
- **Nemotron Parse model/endpoint mismatch.** Hosted Build, legacy v1.2 and native 3.5 use different request contracts; do not mix endpoints in one list.
- **Image-only pages yield empty text.** Enable infographic extraction or captioning; scanned PDFs benefit from `extract_method="nemotron_parse"`.
- **Version and naming drift.** Docs for the same tag mix `nv_ingest_client`, `nemo_retriever.client`, and `nemo_retriever`; the repo moved. Pin the container tag and read the docs at that tag, not at `main`. NVIDIA also states that NVIDIA AI Enterprise support does not cover the NeMo Retriever Library itself, only some of the individual NIMs.
- **Embedding mismatch.** Chunks embedded by one model cannot be queried with another; changing it means re-ingesting.
- **First start is slow:** NIMs take 10-15 minutes to load models.

## Check yourself

1. Why does PDF-to-text with a plain parser lose information that NV-Ingest recovers? Name the three vision models involved.
2. What is the difference between NV-Ingest 26.3.0 (blueprint) and the 26.08 service in terms of broker, API routes and default vector store?
3. How does a document travel from `POST /documents` on the blueprint's ingestor to a row in Elasticsearch?
4. Which environment variables switch an extraction NIM from a local gRPC endpoint to a hosted HTTP endpoint?
5. Why can the default Helm chart need four GPUs even though the models fit in one card's memory, and what are two ways to avoid it?
6. What would you have to implement to land NV-Ingest output in OpenSearch, and where would Neo4j hook in?
7. What happens to retrieval if you change the embedding model after ingesting?
8. Name three symptoms that point to memory pressure in the runtime, and a setting for each.

## References

All checked 2026-11-13.

- https://github.com/NVIDIA/nv-ingest (redirects to NVIDIA/NeMo-Retriever). Releases seen: 26.8.2 (2026-09-30), 26.08.1 (2026-08-27), 26.5.0, 26.3.0 (2026-03-18). README says latest supported release is branch 26.08, GA PyPI/Helm `26.8.1`.
- https://github.com/NVIDIA/NeMo-Retriever/blob/main/docs/docs/extraction/overview.md, concepts.md, deployment-options.md, prerequisites-support-matrix.md, vdbs.md, environment-config.md, troubleshoot.md, content-metadata.md (26.08 line)
- At tag 26.3.0 (the version pinned by the blueprint): docs/docs/extraction/overview.md, support-matrix.md, prerequisites.md, scaling-modes.md, quickstart-guide.md, data-store.md, telemetry.md, v2-api-guide.md
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/deploy/compose/docker-compose-ingestor-server.yaml (runtime image, ports, env vars)
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/nv-ingest-standalone.md, troubleshooting.md, release-notes.md
- https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/src/nvidia_rag/ingestor_server/main.py and src/nvidia_rag/utils/vdb/elasticsearch/elastic_vdb.py
- Not opened (so nothing here depends on them): docs.nvidia.com rendered pages, the Helm chart README, the `nemo_retriever` CLI reference.
