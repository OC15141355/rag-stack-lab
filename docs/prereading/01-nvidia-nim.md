# NVIDIA NIM inference microservices

## In one paragraph

A NIM (NVIDIA Inference Microservice) is a container image that packages one AI model together with a tuned inference engine and a ready-made HTTP server. You start it on a machine with NVIDIA GPUs and it serves an OpenAI-compatible API (`/v1/chat/completions` and friends). It is closest to "vLLM plus a model-specific launch recipe, health endpoints and Prometheus metrics, sold as one image". In the current NIM for LLMs line (documentation release 2.0.13, checked 2026-11-13) the container wraps vLLM, or SGLang for some models such as GLM-5.2, behind a thin proxy. NVIDIA publishes both GLM-5.2 and Nemotron 3 Super as NIMs; GLM-5.2 needs a full 8x H200 node (or Blackwell) at its listed profile, so an H100 node is not enough for it.

## The plain version

Imagine you want fresh espresso at the office. You could buy beans, a grinder, a boiler and a milk frother, then spend a week learning the right grind, temperature and pressure for your particular beans. Or you could buy a commercial coffee machine that arrives already set up for one specific bean blend, with a power button, a water-level light and a counter that tells you how many cups it made.

A NIM is the second option, for AI models. The "beans" are the model's learned numbers (very large files). The "machine" is software that has already been tuned to run those numbers quickly on NVIDIA graphics cards. You plug it in, wait for it to warm up, and then anything that already knows how to talk to ChatGPT-style services can talk to it.

Without something like this, every team has to work out for itself how many graphics cards the model needs, which settings make it fast, how to ask it to call tools, and how to tell whether it is healthy. People get these wrong in quiet ways: the model loads but is slow, or runs out of memory only when a long request arrives.

If you remember only five things:

- A NIM is one model in one container, set up by the people who make the graphics cards.
- It speaks the same "language" as OpenAI's API, so existing tools connect without changes.
- It reports "alive" and "ready" separately, because loading a huge model takes many minutes.
- The size of the graphics cards decides which model versions fit; bigger models need several cards working together.
- Downloading the model needs a key from NVIDIA; talking to the finished service does not (in the pages I read).

## Why it exists

The problem: serving a large language model well is fiddly. You pick an engine (vLLM, SGLang, TensorRT-LLM), a precision (BF16, FP8, NVFP4), how many GPUs to split across (tensor parallelism, "TP"), a KV-cache memory fraction, a reasoning parser and a tool-call parser. Model vendors change these per model. NVIDIA tests combinations per GPU type and ships the winning one as a "profile" inside the image.

What it resembles, for you:

- **vLLM** you run yourself: a NIM is vLLM (or SGLang) plus NVIDIA's tested launch flags per GPU, plus a management layer. The docs say the NIM metrics at `/v1/metrics` are vLLM's own, unrenamed, so existing vLLM dashboards work.
- **A plain Helm deployment of an inference server**: the NIM chart and operator do the same job but understand model caches and GPU profiles.
- **LiteLLM**: LiteLLM is a gateway in front of many providers. A NIM is one backend behind such a gateway. It does not route between models; it serves one.

## How it works

*Gloss: the container is a small server wrapped around an engine, and it decides at start-up which pre-tested recipe to use for the GPUs it finds.*

Precisely, the NIM LLM container runs two processes: the inference engine (vLLM; SGLang for GLM-5.2) and an nginx-style proxy on the external port (default 8000). The engine listens on 8001, loopback only. If either dies, the container exits so Kubernetes can reschedule it (fail-fast supervision). Only explicitly listed paths are exposed; everything else returns 404.

```
 client --> :8000 proxy --+--> /v1/health/live    (answered by proxy, always fast)
                          +--> /v1/health/ready   (200 only once model loaded)
                          +--> /v1/chat/completions, /v1/completions, /v1/embeddings ...
                          +--> /v1/metrics, /v1/models, /v1/metadata
                                   |
                                   v
                          :8001 engine (vLLM / SGLang) --> GPUs
```

*Gloss: a "profile" is a saved recipe: which engine, which number format, how many GPUs.*

Precisely, each model-specific image ships a manifest listing profiles. A profile name looks like `<backend>-<precision>-tp<N>-pp1[-lora]`, for example `sglang-fp8-tp8-pp1`. Precision is the number format of the weights (BF16 = 2 bytes per parameter, FP8 = 1, NVFP4 = 0.5). TP is tensor parallelism: one layer is split across N GPUs. At start-up NIM detects the GPUs, estimates VRAM per profile, and picks one. `NIM_MODEL_PROFILE=<id>` overrides it. `list-model-profiles` prints "compatible", "low memory" and "incompatible" groups.

*Gloss: weights are not inside the image; they are downloaded to a cache on first start.*

Precisely, the image carries the manifest, not the weights. They are downloaded into `NIM_CACHE_PATH` (mounted at `/opt/nim/.cache` in the Docker examples). The `download-to-cache` command pre-populates the cache; `create-model-store` produces a plain directory for transfer.

*Gloss: the NIM can be told to think out loud, and to call functions, in the standard OpenAI format.*

Precisely, for GLM-5.2 the profiles preconfigure a `glm45` reasoning parser and a `glm47` tool-call parser. Reasoning comes back in `choices[].message.reasoning_content`, tool calls in `choices[].message.tool_calls`. Thinking is toggled per request with `chat_template_kwargs.enable_thinking`. For other models you pass `--enable-auto-tool-choice --tool-call-parser <name>`; without them `tool_choice: "auto"` returns HTTP 400.

### API surface (NIM LLM 2.0.13)

- Inference: `POST /v1/chat/completions` (streaming via SSE), `/v1/completions`, `/v1/responses` (OpenAI Responses), `/v1/messages` (Anthropic-compatible), `/v1/embeddings`, `/tokenize`, `/detokenize`.
- Management: `/v1/health/live`, `/v1/health/ready`, `/v1/metadata`, `/v1/version`, `/v1/license`, `/v1/manifest`, `/v1/metrics`, `/v1/models`.
- Tracing: `X-Request-Id` and W3C `traceparent` headers are forwarded to the engine on inference routes. Spans are only produced if the engine gets `--otlp-traces-endpoint`.
- Client auth: the API reference says `/v1/messages` does not validate `x-api-key`, and the SDK examples use a dummy key. I found no client-authentication setting in the pages read. UNVERIFIED: that no built-in client auth exists at all; assume the NIM must sit behind your gateway or a NetworkPolicy.

### Hosted versus self-hosted, and which key is which

- **Hosted**: `https://integrate.api.nvidia.com/v1` (OpenAI-compatible), models listed on build.nvidia.com. Trial use is under the NVIDIA API Trial Terms of Service. Authentication is `Authorization: Bearer <key>`. The NeMo docs say the key is an NGC API key with "Public API Endpoints" permission. Keys start `nvapi-`. Rate limits: UNVERIFIED. Forum posts mention about 40 requests per minute on free accounts; the official FAQ only says limits vary per model and are shown in your account.
- **Self-hosted**: pull from `nvcr.io` (user `$oauthtoken`, password = NGC API key). Per the 2.0.13 docs some images and models need no key ("keyless access"); gated, private and Production Branch assets do. Hugging Face models need `HF_TOKEN`.

### Hardware: H100 versus H200 in practice

From the GLM-5.2 guide: the performance-tuned profiles are **H200 x8, FP8, TP8, at least 135 GB VRAM per GPU, 250,000 token configured maximum context** and **B200 x4, NVFP4, TP4, at least 175 GB per GPU, 500,000 tokens**. The generic GLM-5.2 profiles list H200 as the only Hopper GPU; verified GPUs are B200, B300, GB200, GB300, H200. H100 is not listed for GLM-5.2.

Back-of-envelope using the docs' own formula (parameters x bytes per parameter): GLM-5.2 has 753 billion parameters, so FP8 weights are about 753 GB. Eight H100-80GB give 640 GB, so they cannot hold it. Eight H200 give far more, which is why the profile works. The H200's per-GPU memory figure itself I did not read from NVIDIA; I used only the 135 GB minimum in the guide. UNVERIFIED: the exact H200 total memory (commonly quoted as 141 GB).

Nemotron 3 Super (120B total, 12B active parameters) is far smaller. The NIM support matrix lists BF16, FP8 and NVFP4 profiles from TP1 to TP8, an H200 FP8 TP4 throughput profile, and H100-80GB-HBM3 among verified GPUs. A NVIDIA RAG blueprint page says 3x H100 for Docker-based self-hosting and 9x H100-80GB for its Helm install (that figure includes the other services in the blueprint). The model's own card says minimum "8x H100-80GB"; that card describes the BF16 checkpoint, not the NIM profile. The numbers disagree because they describe different precisions and packages; confirm with `list-model-profiles` on your node.

## How you run it

Prerequisites on the host (docs): NVIDIA driver 580 or later, CUDA 12.9+, Docker 24+, NVIDIA Container Toolkit 1.14+. Container access needs a free NVIDIA Developer Program membership or an NVIDIA AI Enterprise licence.

**Docker, GLM-5.2 (from the NVIDIA guide)**

```bash
# Check that containers can see GPUs
docker run --rm --runtime=nvidia --gpus all ubuntu nvidia-smi

# Persistent cache, writable by group 0
export LOCAL_NIM_CACHE=~/.cache/nim
mkdir -p "$LOCAL_NIM_CACHE" && sudo chgrp -R 0 "$LOCAL_NIM_CACHE" && sudo chmod -R g+rwX "$LOCAL_NIM_CACHE"

# Log in and pull
printf '%s' "$NGC_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin
docker pull nvcr.io/nim/zai-org/glm-5.2:2.1.3

# List profiles; pick the SGLang throughput, feat_lora=false one for your GPU
docker run --rm --gpus all -e NGC_API_KEY nvcr.io/nim/zai-org/glm-5.2:2.1.3 list-model-profiles

# Pre-download that profile into the cache
docker run --rm --gpus all -e NGC_API_KEY -v "$LOCAL_NIM_CACHE:/opt/nim/.cache" \
  nvcr.io/nim/zai-org/glm-5.2:2.1.3 download-to-cache -p "$NIM_MODEL_PROFILE"

# Serve
docker run --rm --name glm-5-2-nim --gpus all --shm-size=32g \
  -e NGC_API_KEY -e NIM_MODEL_PROFILE -e NIM_SERVED_MODEL_NAME=zai-org/GLM-5.2 \
  -v "$LOCAL_NIM_CACHE:/opt/nim/.cache" -p 8000:8000 \
  nvcr.io/nim/zai-org/glm-5.2:2.1.3
```

Each step: check GPU access, create the cache, authenticate, pull, list recipes, pre-fetch weights, then run with a fixed public model name. For Podman, the same flags work with the NVIDIA CDI device (`--device nvidia.com/gpu=all`); UNVERIFIED, the NIM docs I read only show Docker.

```bash
curl --fail http://localhost:8000/v1/health/ready      # 200 only after model load
curl -s http://localhost:8000/v1/models                # the exact model id to use
curl -s http://localhost:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model":"zai-org/GLM-5.2","max_tokens":1024,
  "messages":[{"role":"user","content":"Explain GPU computing in one sentence."}],
  "chat_template_kwargs":{"enable_thinking":false}}'
```

Readiness, model list and a request with thinking off.

**Kubernetes with the Helm chart** (`nim-llm` from the NGC Helm registry):

```bash
helm fetch "https://helm.ngc.nvidia.com/nim/charts/nim-llm-${HELM_CHART_VERSION}.tgz" \
  --username='$oauthtoken' --password="${NGC_API_KEY}"
tar -xzf nim-llm-${HELM_CHART_VERSION}.tgz
helm install my-nim nim-llm/ -f values.yaml
```

Fetch the chart and install. Minimal `values.yaml` keys from the docs: `image.repository`, `image.tag`, `model.ngcAPISecret`, `imagePullSecrets`, `persistence`, `resources.limits."nvidia.com/gpu"`, `customArgs`, `env`. The chart makes a StatefulSet by default; set `statefulSet.enabled: false` and `deployment.strategy.type: Recreate` when you have no spare GPU for a rolling update.

**Kubernetes with the NIM Operator** (needs the GPU Operator, Kubernetes 1.26+, a storage provisioner; docs show operator chart 3.1.2):

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && helm repo update
kubectl create namespace nim-operator
helm upgrade --install nim-operator nvidia/k8s-nim-operator -n nim-operator --version=3.1.2
```

```yaml
apiVersion: apps.nvidia.com/v1alpha1
kind: NIMCache            # downloads the model once to a PVC
metadata: {name: glm52, namespace: nim-service}
spec:
  source:
    ngc:
      modelPuller: nvcr.io/nim/zai-org/glm-5.2:2.1.3   # image tag from the GLM guide
      pullSecret: ngc-secret
      authSecret: ngc-api-secret
      model: {engine: "sglang", tensorParallelism: "8"}
  storage:
    pvc: {create: true, size: "800Gi", volumeAccessMode: ReadWriteOnce}   # size is my guess
---
apiVersion: apps.nvidia.com/v1alpha1
kind: NIMService          # runs the pods
metadata: {name: glm52, namespace: nim-service}
spec:
  image: {repository: nvcr.io/nim/zai-org/glm-5.2, tag: "2.1.3", pullSecrets: [ngc-secret]}
  authSecret: ngc-api-secret
  storage: {nimCache: {name: glm52, profile: ''}}
  resources: {limits: {nvidia.com/gpu: 8}}
  expose: {service: {type: ClusterIP, port: 8000}}
  metrics: {enabled: true, serviceMonitor: {additionalLabels: {}}}
```

The structure follows the operator page, which uses a Llama example; the GLM values (tensorParallelism 8, 8 GPUs, PVC size) are my adaptation. UNVERIFIED: that this exact GLM manifest applies cleanly. The operator also offers `NIMPipeline` and `NIMBuild` kinds (seen in the operator source tree), and `spec.scale.hpa` for autoscaling on `vllm:num_requests_waiting` (vLLM-backed images; metric names differ on SGLang).

**Air-gapped.** Phase 1 (online): `download-to-cache` or `create-model-store`, mirror every image the chart references (the chart can add an init container using `buildpack-deps:bookworm`), copy the cache across. Phase 2 (offline): mount the cache and do **not** set `NGC_API_KEY` or `HF_TOKEN`. NVIDIA supplies `airgap-bundle.sh` helper scripts.

## How it fits the stack

- **Calls it**: your gateway (LiteLLM), via an OpenAI-compatible provider entry pointing at the NIM Service on port 8000; the NeMo platform's inference gateway (see file 02); Prometheus (scrape `/v1/metrics`); kubelet probes (`/v1/health/ready` as startup probe: the operator defaults to up to 20 minutes, raise `failureThreshold` for huge models).
- **It calls**: nothing at runtime, once the cache is warm. At start-up it calls NGC (or Hugging Face) to download weights unless the cache is populated.
- **Gateway notes**: set `NIM_SERVED_MODEL_NAME` so the `model` string is stable. For GLM-5.2, pass `chat_template_kwargs` through your gateway (LiteLLM can forward `extra_body`) or thinking will not be controllable. Read `reasoning_content` if you display reasoning.

## What goes wrong

- **Pod restarts during load**: startup probe too short for a 750 GB model. Symptoms: restarts, `/v1/health/ready` 503 then killed. Raise `startupProbe.failureThreshold`.
- **Out of memory**: wrong profile for the GPU, or too long a context. `list-model-profiles` shows "low memory" with a suggested `--max-model-len`. `NIM_KVCACHE_PERCENT` sets the engine's memory fraction (GLM H200 profile: 0.90).
- **Profile mismatch**: image backend must match profile backend (the SGLang image loads only `sglang-*` profiles).
- **Cache permission errors**: the container runs as group 0; the cache needs `chgrp 0` and `g+rwX`.
- **HTTP 400 on `tool_choice: auto`**: tool parser flags missing (not an issue for GLM-5.2 where profiles set them).
- **Empty answer, `finish_reason: "length"`**: thinking consumed the token budget; raise `max_tokens` or disable thinking.
- **NFS/CIFS cache hangs**: the env-var docs warn that an unreachable NFS/CIFS/FUSE mount for `NIM_CACHE_PATH` breaks start-up.
- **Wrong health path against a gateway**: `/v1/health/*` exists only on the NIM, not on the NeMo platform gateway.
- **Air-gap surprises**: an `NGC_API_KEY` left set in the offline phase; unmirrored init-container images.

## Observability

`/v1/metrics` returns the engine's native Prometheus metrics, unmodified: request latency, throughput, queue depth, token counts, GPU utilisation per the docs. Names differ between vLLM and SGLang, so list them on your own deployment before building alerts. Logs go to stderr; set `NIM_JSONL_LOGGING=true` for JSON Lines and `NIM_LOG_LEVEL` (default WARNING).

## What is known about the two models

**GLM-5.2** (Z.ai; NVIDIA states it is not developed by NVIDIA). 753B parameters, mixture of experts, 1M-token context on the model card (1,048,576 in the catalog specification). Capabilities listed: function calling, structured output, reasoning. Self-hosted NIM: `nvcr.io/nim/zai-org/glm-5.2:2.1.3`, SGLang backend, H200 (8x, FP8) or B200 (4x, NVFP4) tuned profiles, with configured max context 250k and 500k respectively. Hosted: build.nvidia.com, `z-ai/glm-5.2`, listed 2026-07-02. Terms: NVIDIA Open Model Agreement, with MIT noted as additional information. UNVERIFIED: a 736 GB disk requirement seen in a search snippet (NGC page not opened).

**Nemotron 3 Super** (NVIDIA; `nvidia/nemotron-3-super-120b-a12b`). 120B total, 12B active, hybrid Mamba-2 + MoE + attention with multi-token prediction; reasoning toggled by `enable_thinking`; up to 1M context on the model card; released 2026-03-11; licence NVIDIA Nemotron Open Model License. Image `nvcr.io/nim/nvidia/nemotron-3-super-120b-a12b` (RAG blueprint example tag 1.8.0). Recommended sampling: temperature 1.0, top_p 0.95. UNVERIFIED: the context window of the NIM profiles specifically; the NIM's tool-call parser flags; the NIM 2.x image tag. A related but different model, "Nemotron 3.5 Super VL 120B-A12B", also has a 2.0.13 NIM guide; do not confuse it.

## Licensing

Per the NIM Offerings page: "NIM" (fast access to new models) and "NIM Certified Feature Branch" are available at no charge under their licence terms, with community support only. Production Branch requires an active NVIDIA AI Enterprise subscription, which also brings enterprise support, CVE handling and FIPS/STIG options where applicable. Container download needs a free NVIDIA Developer Program membership or an AI Enterprise licence (a 90-day evaluation is offered). Model weights have their own licences (see above). Whether Developer Program terms permit your production use: UNVERIFIED, read the licence.

## Check yourself

1. What two processes run in a NIM LLM container, and which one answers `/v1/health/live`?
2. What does a profile name such as `sglang-fp8-tp8-pp1` encode, and how does NIM choose one?
3. Why can eight H100-80GB not serve GLM-5.2 at its listed FP8 weight size, while eight H200 can?
4. Which key is needed to download a model, which to call the hosted endpoint, and does the self-hosted NIM check a client key?
5. In what order do NIMCache and NIMService act, and what does the NIMService mount?
6. How would you pre-stage a model for a cluster with no internet, and which env vars must stay unset there?
7. Which Prometheus metrics does a NIM expose, and why must you check names before reusing a vLLM dashboard on an SGLang image?
8. What request field controls GLM-5.2 thinking, and where does the reasoning text appear in the response?

## References

All checked 2026-11-13.

- NVIDIA NIM for LLM and VLM documentation, release 2.0.13: overview, architecture, API reference, logging and observability, environment variables, model profiles, air-gap deployment, Helm and Kubernetes, NIM Operator deployment, support matrix, NIM offerings, prerequisites, tool calling, release notes. Base: https://docs.nvidia.com/nim/large-language-models/2.0.13/ (for example `reference/architecture.html`, `deployment/kubernetes-deployment/nim-operator-deployment.html`, `reference/support-matrix.html`)
- Get Started with GLM-5.2 (same release): https://docs.nvidia.com/nim/large-language-models/2.0.13/get-started/advanced/get-started-glm-5-2.html
- GLM-5.2 model card on build.nvidia.com (markdown form): https://build.nvidia.com/z-ai/glm-5.2.md
- Nemotron 3 Super 120B-A12B model card on build.nvidia.com: https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b.md
- NVIDIA RAG Blueprint 2.5.0, using Nemotron-3-Super-120B-A12B NIM: https://docs.nvidia.com/rag/2.5.0/nemotron3-super-deployment.html
- NVIDIA NIM Operator install page (operator chart 3.1.2): https://docs.nvidia.com/nim-operator/latest/install.html ; source tree: https://github.com/NVIDIA/k8s-nim-operator
- NVIDIA NIM FAQ and developer forum threads on rate limits (only skimmed in search results, not opened): https://forums.developer.nvidia.com/t/nvidia-nim-faq/300317
