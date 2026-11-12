# NVIDIA NeMo microservices and the NIM proxy

## In one paragraph

NeMo microservices were NVIDIA's set of separately deployed services for the work around a model: generating training data, fine-tuning, evaluating, red-teaming and putting guardrails in front of it. One of them, the NIM Proxy, was a single front door that routed OpenAI-style requests to whichever NIMs were deployed in the cluster. **Important status change found while researching (checked 2026-11-13): NVIDIA's own archived docs state "NeMo Microservices will be sunset on October 1, 2026. All new development has moved to NeMo Platform."** The current docs hub at `docs.nvidia.com/nemo-helix/` describes a successor called NeMo Helix, with an "Inference Gateway" that plays the NIM Proxy's role. So you are most likely to meet this material in three forms: the old 25.x microservices (many existing guides), the 26.3 "NeMo Platform" rewrite, and Helix. This file explains the old design, because the names persist, and then what replaced it.

## The plain version

Think of a hospital. The doctors (the AI models) do the actual work. But a hospital also needs a records office, a lab that checks whether treatments work, a training department that teaches doctors new skills, a safety officer who stops dangerous orders, and a front desk where every phone call lands and gets passed to the right ward.

NeMo microservices were those support departments for AI models, each as its own small service you could install separately. The NIM Proxy was the front desk: one phone number, and it knew which ward (which model) to put you through to.

Without them, a team that wants to improve a model over time ends up with a pile of ad-hoc scripts: one for collecting data, another for fine-tuning, another for scoring, and a hand-written list of which model lives at which address. Each script has its own login and its own way of failing. The point of the services was a shared place to keep datasets and results, and one consistent way to run each step.

One more thing matters: NVIDIA has announced that this particular hospital is being closed and replaced by a new building (the NeMo Platform, now documented as NeMo Helix). The departments are mostly the same; the building is new.

If you remember only five things:

- NeMo microservices are support services around models, not models themselves.
- Most of them (storage, scoring, safety, routing) need no graphics card; fine-tuning and local model serving do.
- The NIM Proxy was just a router with one address in front of many model servers.
- NVIDIA announced the original product was sunset on 2026-10-01; new work is on NeMo Platform / NeMo Helix.
- Your serving layer (NIMs behind a gateway) does not depend on any of this.

## Why it exists

The problem is the loop after the first deployment: collect examples, fine-tune, evaluate, check safety, redeploy, repeat (NVIDIA calls this the "data flywheel"). Each step needs shared storage, a metadata catalogue, job scheduling on GPUs and access control.

What it resembles for you:

- Kubeflow-style pipelines and an MLflow/Hugging Face-hub-style store, but API-first and packaged by the GPU vendor.
- The **NIM Proxy** resembles **LiteLLM**: one OpenAI-compatible endpoint in front of many backends. Differences (from the docs): it only fronted NIMs that the platform itself deployed, it learned endpoints from NeMo Deployment Management and Entity Store rather than from a config file, and it had no documented spend tracking, key management or provider fallbacks in the pages I read. Do not treat it as a LiteLLM replacement.
- The deploy-a-NIM API resembles a thin wrapper around the NIM Operator (see file 01).

## How it works

### The 25.12 set of services (last 25.x docs read)

*Gloss: "functional" services do a job on a model; "infrastructure" services store things and route traffic.*

Functional, per the 25.12.0 overview:

- **Data Designer**: makes synthetic datasets from seeds, sampling and schemas.
- **Safe Synthesizer (Early Access)**: makes private versions of sensitive tabular data.
- **Customizer**: fine-tunes LLMs and embedding models (full supervised and parameter-efficient methods). Needs GPUs.
- **Evaluator**: academic benchmarks, custom automated evaluations, LLM-as-a-judge. The service has no GPU need; the models it calls run as NIMs.
- **Auditor (Early Access)**: scans models and agents for vulnerabilities and harmful output. No GPU.
- **Guardrails**: safety checks and content moderation on model endpoints. No GPU in the requirements page.

Infrastructure:

- **Data Store**: default file storage, exposing a Hugging Face Hub (`HfApi`) compatible API; needs Git/Git LFS and a file-locking-capable volume.
- **Entity Store**: metadata for namespaces, projects, datasets, models. A database-backed core service that other services depend on.
- **Deployment Management**: an API to deploy NIMs on Kubernetes through the NIM Operator.
- **NIM Proxy**: one endpoint for inference on all deployed NIMs.
- **NeMo Operator**: owns the CRDs (Kubernetes custom resource types) for Customizer fine-tuning jobs.
- **NeMo Core**: backend plumbing such as job scheduling.
- **NeMo Studio (Early Access)**: web UI.

NeMo Retriever appears in the docs hub as a NeMo microservice for RAG pipelines (retrieval models). I did not open its docs, so details here are limited: UNVERIFIED how it is deployed or which NIMs it uses.

### The NIM Proxy in detail

*Gloss: a router that knows where each model lives, so clients only need one address and a model name.*

Precisely, the proxy exposed OpenAI-compatible routes: `GET ${NIM_PROXY_BASE_URL}/v1/models`, `POST /v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, plus a classification route. It took the endpoint list from Deployment Management and Entity Store. The docs say it needs no GPU, about 1 CPU and 500 MiB, an ingress, and "load balancing capabilities for multiple model endpoints", with optional Guardrails integration for output filtering. In the minikube demo the base URLs were `http://nim.test` (proxy) and `http://nemo.test` (platform).

```
client --> NIM Proxy --> NIM (llama-3.1-8b-instruct)   <- created via Deployment Management
              |  \-----> NIM (embedding model)
              +-- learns endpoints from Deployment Management / Entity Store
              +-- optional: Guardrails on the output
Evaluator --> NIM Proxy (for judge and target models)
Customizer --> Data Store (datasets, checkpoints) + Entity Store (metadata)
```

### What replaced it (26.3 and Helix)

*Gloss: one bigger service instead of a fleet, with the router renamed.*

Release 26.3.0 notes: a new Python CLI and SDK (`nemo-platform`; command `nmp`), a single all-in-one Helm chart (`nemo-platform`) replacing the multi-chart setup, workspace-scoped APIs (`/v2/workspaces/{workspace}/...`), and authorization done by OPA policies compiled to WebAssembly inside each service (no auth sidecar). The 26.3 requirements page still lists NIM Proxy, Data Store, Entity Store, Deployment Management and the NeMo Operator, but the 26.3 overview talks about "the unified gateway".

The current docs (NeMo Helix, latest, versions 0.5 to 0.10 listed) say: Helix is "an open source control plane for improving and hardening production agents", with services Managed Agents, Optimization, Guardrails, Evaluator, Fine Tuning, garak (red-teaming), Data Designer, Anonymizer, Safe Synthesizer, and shared capabilities Models and Inference (the **Inference Gateway**), Secrets, Files, Entity Store, Jobs. UNVERIFIED: that Helix is the same product as "NeMo Platform" renamed; the docs hub names exist side by side and one search result claimed the rename, but I did not open a page stating it. The Helix docs also have a page "Upgrading from NeMo Evaluator".

The **Inference Gateway** is described as "a Layer 7 reverse proxy providing unified access to all inference endpoints". Three route patterns, all with `/-/` as separator and everything after it forwarded unchanged:

- Model entity: `/apis/inference-gateway/v2/workspaces/{ws}/model/{name}/-/*`
- Provider: `/apis/inference-gateway/v2/workspaces/{ws}/provider/{name}/-/*`
- OpenAI-compatible: `/apis/inference-gateway/v2/workspaces/{ws}/openai/-/*` (model in the body)

A **ModelProvider** is an upstream such as NVIDIA Build, OpenAI or Anthropic (API key held as a platform secret); a **VirtualModel** is a named route that can spread traffic across models or apply guardrail input/output rails. Models are served either from providers or from deployments, where `engine: vllm` is recommended and `engine: nim` is available for model-specific NIMs (`image_name`, `image_tag`) or model-free NIMs. Deployments run via Docker, Kubernetes or OpenShell executors. The gateway's health endpoints are `/health/ready` and `/health/live`; the docs stress that the NIM paths `/v1/health/*` return 404 there by design.

## How you run it

The old (25.x) deploy call, from the NeMo tutorial:

```bash
curl --location "http://nemo.test/v1/deployment/model-deployments" \
  -H 'Content-Type: application/json' -d '{
    "name": "llama-3.1-8b-instruct", "namespace": "meta",
    "config": {"model": "meta/llama-3.1-8b-instruct",
      "nim_deployment": {"image_name": "nvcr.io/nim/meta/llama-3.1-8b-instruct",
        "image_tag": "1.8", "pvc_size": "25Gi", "gpu": 1,
        "additional_envs": {"NIM_GUIDED_DECODING_BACKEND": "outlines"}}}}'
curl "${NIM_PROXY_BASE_URL}/v1/models"        # then list what the proxy knows
```

Creates a NIM through Deployment Management, then asks the proxy which models it serves. The tutorial says deployment takes about ten minutes and wants two data-centre GPUs free.

Current install (Helix, Kubernetes), from its Helm pages:

```bash
export NHX_NAMESPACE=nemo-helix NHX_HELM_CHART_VERSION=<chart-version>
kubectl create namespace "$NHX_NAMESPACE"
kubectl create secret docker-registry nvcrimagepullsecret --docker-server=nvcr.io \
  --docker-username='$oauthtoken' --docker-password="$NGC_API_KEY" -n "$NHX_NAMESPACE"
kubectl create secret generic ngc-api --from-literal=NGC_API_KEY="$NGC_API_KEY" -n "$NHX_NAMESPACE"
helm repo add nemo-helix https://helm.ngc.nvidia.com/nvidia/nemo-helix \
  --username '$oauthtoken' --password "$NGC_API_KEY"
helm show values nemo-helix/nemo-helix --version "$NHX_HELM_CHART_VERSION" > values.yaml
```

Namespace, image-pull and NGC secrets, then fetch the default values. In `values.yaml` set `existingSecret: ngc-api` and `imagePullSecrets: [{name: nvcrimagepullsecret}]`. Then `helm install` with the pinned version (the install page ends with it; not copied verbatim here, so check `kubectl`/`helm` flags there). Prerequisites: Helm 3, ReadWriteMany storage (shared jobs storage), ingress or Gateway API, GPU Operator for GPU jobs, optional Volcano for multi-node jobs, optional external PostgreSQL. Local trial path: `nemo setup` (Python 3.12 to 3.14, Linux or macOS, 8 GB RAM, no GPU needed when using a hosted provider).

Register NVIDIA's hosted models as a provider, from the Helix docs:

```bash
echo "$NVIDIA_API_KEY" | nemo secrets create "nvidia-api-key" --from-file -
nemo inference providers create "my-nvidia-build" \
  --host-url "https://integrate.api.nvidia.com/v1" --api-key-secret-name "nvidia-api-key"
nemo inference get-url --provider my-nvidia-build      # prints the base URL to give your clients
```

Store the key as a secret, create the provider, then print the gateway URL. Self-managed NIMs can instead be registered as a provider with their own `--host-url`. UNVERIFIED: that registering an in-cluster NIM Service URL as a provider works this way for NIMs not deployed by the platform; the pages show the provider flow only for hosted APIs and OpenAI/Anthropic.

NIM Operator route (separate from the above): the operator ships CRDs for `NIMCache`, `NIMService`, `NIMPipeline`, `NIMBuild`, and NeMo kinds `NemoCustomizer`, `NemoEvaluator`, `NemoGuardrail` (named in the operator README). UNVERIFIED: exact kind names for the Data Store and Entity Store resources; the source tree has `nemo_datastore_types.go` and `nemo_entitystore_types.go` only.

## GPU or not

| Service | GPU? | Source |
|---|---|---|
| Customizer | Yes: B200 180GB, A100 80GB or H100 80GB, count depends on model size | 26.3 requirements |
| Evaluator, Auditor, Guardrails, Entity Store, Data Store, Deployment Management, NIM Proxy, NeMo Operator | No | 26.3 requirements |
| Models you evaluate or guard with | Yes, they are NIMs elsewhere | same |
| Helix core, local trial | No; GPU only when serving local models or running GPU jobs (40 GB VRAM minimum, 80 GB recommended, CUDA 13+, Linux x86_64) | Helix system requirements |

Platform-wide minimum in the 26.3 page: two B200, A100 80GB or H100 80GB, 200 GB free disk, Kubernetes 1.30+, driver 560.35.03+.

## How it fits the stack

- **Relationship to NIMs**: NeMo services use NIMs; they are not NIMs themselves (Auditor, Data Store, etc. are plain CPU services). Deployment Management creates NIMs; the proxy/gateway routes to them; Evaluator and Guardrails call them for judge and target models.
- **Relationship to your gateway**: the platform gateway is an optional extra hop. If LiteLLM already fronts your NIMs, you can ignore the proxy and call NIM Services directly. Bring NeMo in only for fine-tuning, evaluation or guardrail workloads. The Helix docs show routing to OpenAI-compatible providers, which suggests LiteLLM could sit behind Helix or in front of it; UNVERIFIED either way.
- **Calls it**: the SDK/CLI (`nmp`, `nemo`), Studio UI, and agents or apps via REST.
- **It calls**: NGC (images and models), PostgreSQL (Evaluator needs one; Milvus is optional for RAG evals), Kubernetes API (to create NIM deployments and training jobs), NIM endpoints.
- **Authentication**: from 26.3 the docs describe workspace-scoped RBAC via embedded OPA policy and say auth can be switched off for local development.

## What goes wrong

- **Following an outdated guide**: 25.x tutorials use `nemo.test`, `nim.test`, Deployment Management and per-service Helm charts. In 26.3 the chart and CLI changed. Check the page's version before running commands, and note the archive banner.
- **Docs host moves**: `docs.nvidia.com/nemo/microservices/latest/` now redirects to `archive.docs.nvidia.com`; bookmarks to old APIs still work but are not maintained.
- **Pending forever**: a deployment waits for a GPU, an image pull or a storage class. Check the operator and pod events as with any NIMService.
- **404 on health checks**: probing `/v1/health/ready` on the gateway instead of `/health/ready`.
- **Storage errors**: Customizer and Data Store need file locking; RWX or a CSI driver without locks breaks jobs.
- **Tool calls failing through the gateway**: the Helix docs report an error when function tools are combined with `reasoning_effort` on `/v1/chat/completions`; the documented fix is `--default-extra-body '{"reasoning_effort":"none"}'` on the provider.
- **Key confusion**: the NGC key (`NGC_API_KEY`) pulls images and charts; the hosted-API key is also an NGC key with "Public API Endpoints" permission; the 26.3 getting-started page also asks for a separate build.nvidia.com token for cloud inference. Keep scopes minimal.
- **Sunset risk**: committing to the original microservices packages is committing to a product NVIDIA says was sunset on 2026-10-01. Ask your NVIDIA contact for migration terms.

## Check yourself

1. What is the difference between a "functional" and an "infrastructure" NeMo microservice? Name two of each.
2. What did the NIM Proxy route, where did it learn the endpoints from, and how does that differ from a LiteLLM config file?
3. Which services need a GPU, and why does Evaluator not need one even though it scores models?
4. What is the status of "NeMo Microservices" as of today, and which names replaced it?
5. Describe the three Inference Gateway route patterns and what `/-/` means.
6. Why would probing `/v1/health/ready` on the gateway give a 404, and which path is correct?
7. If your stack already serves NIMs behind LiteLLM, which NeMo pieces would you adopt, and which would you skip?
8. Which Kubernetes storage property do Customizer and Data Store require?

## References

All checked 2026-11-13.

- NeMo Microservices 25.12.0 overview (archived copy): https://archive.docs.nvidia.com/nemo/microservices/25.12.0/about/index.html
- NIM Proxy and Deployment Management task pages, 25.12.0: https://archive.docs.nvidia.com/nemo/microservices/25.12.0/run-inference/nim-proxy/index.html , `.../run-inference/nim-proxy/chat-completions.html`, `.../run-inference/deployment-management/index.html`, `.../get-started/tutorials/deploy-nims.html`
- NeMo Microservices 26.3.0 index (sunset banner), requirements, and release notes 26.3.0: https://archive.docs.nvidia.com/nemo/microservices/26.3.0/index.html , `.../26.3.0/requirements.html` , https://archive.docs.nvidia.com/nemo/microservices/latest/about/release-notes/current-release.html
- NVIDIA NeMo docs hub: https://docs.nvidia.com/nemo/
- NeMo Helix docs (latest; index lists 0.5 to 0.10): https://docs.nvidia.com/nemo-helix/latest/documentation/home.md , `.../models-and-inference.md`, `.../models-and-inference/deploy-models.md`, `.../kubernetes-deployment/setup/helm/prerequisites.md`, `.../kubernetes-deployment/setup/helm/install.md`, `.../reference/system-requirements.md`
- NVIDIA NIM Operator repository (README, CRD source files): https://github.com/NVIDIA/k8s-nim-operator
