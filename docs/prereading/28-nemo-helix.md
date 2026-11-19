# NeMo Helix — what it is and whether you need it

## In one paragraph

NeMo Helix is NVIDIA's open-source (Apache 2.0 source) control plane for "improving and hardening production agents". It is the new home of the work that used to be called NeMo Microservices, after NVIDIA announced the old product's sunset on 2026-10-01. It bundles shared platform pieces (workspaces and entities, a files service, secrets, jobs, an Inference Gateway, a Models service) with workflow services (Evals, Guardrails, Fine-tuning, Data Designer, Safe Synthesizer, Anonymizer, garak scanning, agent management) and a UI called Studio (alpha). It is still 0.x: the latest documented release is 0.10.0 (2026-11-18), the docs give no GA statement, and the install is Helm-based with NGC credentials. Its centre of gravity is agents, evaluation and tuning. It is not a drop-in replacement for the old NIM Proxy, and it is not a general LLM gateway like Bifrost or LiteLLM. A platform that only serves LLM NIMs behind its own gateway has little reason to adopt it today; a platform that wants fine-tuning and evaluation workflows should evaluate it, knowing the API is still moving.

## The plain version

Picture a restaurant kitchen. Serving the food is the job of the line cooks: in your world, the NIMs that answer requests. But a serious kitchen also has a pantry with labelled shelves, a test kitchen where new recipes are tried and scored, a food-safety officer, a head chef's notebook of which recipe is which version, and a pass where every order is routed to the right station.

Helix is that back-of-house: the pantry (files), the notebook (entities), the tasting panel (evals), the safety officer (guardrails), the apprentice school (fine-tuning), and a pass (the Inference Gateway). It is built around the idea that you are improving an *agent* (a program that calls models and tools) over repeated cycles, not just serving a model.

Without something like it, those jobs end up as scripts and spreadsheets: one place for datasets, another for evaluation results, a hand-kept list of which model is where. If you only ever plate up the same dishes, though, you may not need the test kitchen at all.

Two cautions. First, Helix is young: version numbers are 0.x, releases came roughly every two to four weeks, and each release lists breaking changes. Second, "open source" covers the source code. The container images and the Helm chart come from NVIDIA's registry and need an NGC key, and may carry separate terms.

Five things to remember:

- Helix is a control plane for improving agents (evaluate, optimise, harden), not a model server.
- It replaces most of NeMo Microservices, but not by migration tooling: the docs offer no step-by-step migration guide.
- Its Inference Gateway routes to providers and models Helix knows about; it documents no rate limits, token budgets or spend tracking.
- The bundled Postgres is for quick installs only, and the chart needs shared RWX storage even when files live in S3.
- It is 0.x with breaking changes in every release; check the release notes before each upgrade.

## 1. What Helix is and isn't

*Gloss: Helix is a self-hosted toolbox for testing, tuning and securing agents and models, with its own small set of shared services underneath.*

**What it is.** The docs hub (`docs.nvidia.com/nemo-helix`) says it "runs on your infrastructure, plugs into your platform, and supports evaluating, testing, and measuring agent behavior through repeatable workflows". You reach it through REST APIs, a `nemo` CLI, a Python SDK (`nemo-helix`), and NeMo Studio. The GitHub README (`NVIDIA-NeMo/nemo-helix`) describes capabilities as modular plugins: agent execution, sandboxing, storage, secrets, authentication, model management and inference middleware. Each platform capability "has a default implementation that can be replaced".

**What it isn't.**
- Not a model server. It can launch NIMs (section 4), but that is a side feature.
- Not an LLM gateway in the Bifrost or LiteLLM sense (section 4).
- Not a RAG pipeline. It has RAG *evaluation* metrics, not retrieval serving.
- Not internet-facing software. The security page says it "is not intended to be internet-facing" and "does not have an internal notion of a user"; you add authorization externally (an Envoy-style proxy) or via its OIDC and policy-engine features (see section 3).

**Relationship to NeMo Microservices and "NeMo Platform".**
- NVIDIA's archived SDK docs say: "NeMo Microservices will be sunset on October 1, 2026. All new development has moved to NeMo Platform." The NGC chart listing for the old Helm chart says there will be no new releases. The NIM Operator's upgrade page says it is deprecating support for the NeMo Microservices CRDs in its next release and sends readers to the NeMo Platform docs. (File [02](02-nemo-microservices.md) covers the old design.)
- The same documentation tree appears under two names: `docs.nvidia.com/nemo-platform/...` and `docs.nvidia.com/nemo-helix/...`, with titles reading "NeMo Helix". A secondary news source says the v0.7.0 release completed a rename from NeMo Platform to NeMo Helix. UNVERIFIED: I did not find NVIDIA's own statement of the rename or its date. Treat "NeMo Platform" and "NeMo Helix" as the same lineage but confirm with NVIDIA.
- The Helix docs and README never mention NeMo Microservices, so the link is inferred from the sunset notice, the shared service names (Entity Store, Evaluator, Guardrails, Customizer, Data Designer, Safe Synthesizer, garak, Studio) and the "Upgrading from NeMo Evaluator" page.

**Relationship to NIM and the NIM Operator.** NIMs are the model containers; Helix can run them (deployments plugin, Docker or Kubernetes executors) or call them as a provider. The NIM Operator is a separate Kubernetes operator; the Helix docs I read never mention it (section 4).

**Licence.** The Governing Terms page says "The source code in the NVIDIA NeMo Helix repository is licensed under the Apache License 2.0." Container images, model weights, hosted services and binaries "may be governed by additional or different terms" such as the NVIDIA Software License Agreement. UNVERIFIED: whether the Helm chart and the `nvcr.io/nvidia/nemo-helix/*` images carry those extra terms; check the licence files shipped with them.

**Version and maturity.**
- 0.1.0 on 2026-05-20 (local install only, "no cluster required"); Kubernetes arrived later. The docs index lists 0.2.0 (2026-06-25) through 0.10.0.
- 0.10.0 is dated 2026-11-18 in the release-note index, but the page body still says it is "a planned date" and a "proposed cut". UNVERIFIED: whether 0.10.0 actually shipped on that day; the GitHub repo shows no published Releases.
- Studio is labelled alpha. The support-matrix page has no GA or support-lifecycle statement. Every minor release lists breaking changes (0.10.0 alone requires a new `auth.oidc.audience` setting, renames a job field, and removes one agent type). My reading: pre-GA.

## 2. Components and services

*Gloss: a short list of shared services at the bottom, and workflow services stacked on top that use them.*

Names come from the docs index and API reference for "latest". "Replaces" is my inference from names and the Evaluator upgrade page, not an NVIDIA mapping table.

| Component | What it does | Replaces / maps to in NeMo Microservices |
|---|---|---|
| Inference Gateway | Layer 7 reverse proxy giving one entry point to inference endpoints, by model, provider or OpenAI-compatible path | NIM Proxy (but see section 4: it also fronts external providers) |
| Models service (providers, models, deployments, deployment configs, adapters, prompts, virtual models) | Registers providers and models, deploys NIMs, defines virtual models (routing and middleware) | Deployment Management (partly), Entity Store model entities |
| Files / filesets | Versioned collections of files per workspace; local PVC or S3-compatible backend; Hugging Face-compatible file endpoints | Data Store |
| Entity Store (entities, workspaces, projects) | Shared metadata store; every resource is an entity scoped to a workspace | Entity Store (namespaces became workspaces) |
| Secrets | Workspace-scoped secrets, referenced by name from providers | New as a first-class service; UNVERIFIED whether it replaces anything |
| Jobs | Job scheduler with steps, attempts, results, logs, queueing | NeMo Core job plumbing |
| Evals | LLM-as-judge, similarity, RAG and agentic metrics; tasks, tasksets, experiments; Harbor and NeMo Gym runners | Evaluator (renamed; `/apis/evals/`) |
| Guardrails | Guardrail configs and checks; applied as middleware on virtual models (input and output rails) | Guardrails |
| Fine-tuning (Customizer) | SFT, DPO, LoRA, distillation, embedding and GRPO jobs; model entities and filesets as inputs | Customizer |
| Data Designer | Synthetic data generation; retrieval SDG | Data Designer |
| Safe Synthesizer | Privacy-preserving synthetic tabular data | Safe Synthesizer |
| Anonymizer | PII handling | New in this list |
| NeMo garak (vulnerability scanning) | Probe-based audits with JSONL and HTML reports; can target models through the Inference Gateway | Auditor |
| Managed Agents and Optimization | Register, deploy, run and optimise agents; traces and insights; governance "war-games" | New; no microservices equivalent |
| Intake (traces, spans, sessions, annotations, evaluations) | Collects OTLP and chat-completion traces for analysis | New |
| Access control | OIDC, scoped access keys, role bindings, a policy engine | New as documented here |
| NeMo Studio (alpha) | Browser UI over the services above | NeMo Studio (Early Access) |

Notes. Both Auditor and Guardrails carry over; Auditor is now garak. There is no NeMo Retriever entry in this index. UNVERIFIED where retrieval microservices went; the index only shows retrieval-related items as Evals RAG metrics and Retrieval SDG.

## 3. Architecture and deployment on Kubernetes

*Gloss: one Helm chart installs an API plus supporting services, and it expects shared storage, a database, and an NGC key before it will start.*

**Install.** From the install page (verbatim shape):

```sh
export NHX_NAMESPACE=nemo-helix
export NHX_HELM_CHART_VERSION=<chart-version>
helm repo add nemo-helix https://helm.ngc.nvidia.com/nvidia/nemo-helix \
  --username '$oauthtoken' --password "$NGC_API_KEY"
helm show values nemo-helix/nemo-helix --version "$NHX_HELM_CHART_VERSION" > values.yaml
helm upgrade --install nemo-helix nemo-helix/nemo-helix \
  --version "$NHX_HELM_CHART_VERSION" --namespace "$NHX_NAMESPACE" \
  --create-namespace -f values.yaml --wait --timeout 20m
```

Alternatives are a direct `.tgz` pull from the same NGC URL and release-candidate charts as OCI at `oci://ghcr.io/nvidia-nemo/nemo-helix/nemo-helix` (versions like `X.Y.Z-rc-YYYYMMDDHHMMSS`). Install takes about ten minutes. Minimum values: `existingSecret: ngc-api` and `imagePullSecrets: [{name: nvcrimagepullsecret}]`. UNVERIFIED: the chart version that matches app version 0.10.0; the pages leave `<chart-version>` blank.

**Prerequisites** (Prerequisites page):
- `kubectl`, Helm 3.x, and rights to create namespaces, secrets, RBAC, PVCs and cluster-scoped objects needed by chart dependencies.
- An NGC API key able to read the `nvidia/nemo-helix` org, used for two secrets: a docker-registry pull secret for `nvcr.io`, and a generic `ngc-api` secret.
- **ReadWriteMany storage** for shared jobs storage (EFS on EKS; an RWX-capable StorageClass elsewhere). The chart example sizes it at 200Gi. This is required even when files go to S3.
- An ingress controller or Gateway API (the chart supports Ingress, HTTPRoute and OpenShift Route; Traefik is named as an example Ingress controller; HTTPRoute TLS is not documented).
- GPU nodes only for GPU workloads (fine-tuning, local model serving). Support matrix: Linux x86_64, CUDA 13, R580+ driver, 40 GB VRAM minimum, 80 GB recommended. UNVERIFIED: whether a services-only install with no GPU workloads needs none at all; the pages imply so but do not say.
- Optional add-ons not in the chart: Volcano and Kyverno (multi-node jobs), OpenSandbox (sandboxed GRPO), Milvus. The chart does not install an OpenTelemetry collector.
- No Kubernetes version range, Postgres version, or NIM version is stated anywhere I read. UNVERIFIED.

**Database.** The embedded PostgreSQL "uses simplified authentication to enable quick installation... should not be used for production use, and an external PostgreSQL instance is recommended." Set `postgresql.enabled: false` and `externalDatabase`, either as a full URI from a secret (`uriSecret`, best for TLS) or host/port/user/database plus a password secret. The security page also mentions ClickHouse (bundled, can be replaced) for telemetry data.

**Object storage.** Files default to local storage on the RWX PVC (`/vol/files`). Production guidance prefers S3-compatible storage (AWS S3, MinIO, Ceph via `endpoint_url`) for performance; the platform does not create buckets or IAM for you. Only `local` and `s3` are documented.

**Secrets and auth.** Provider API keys live in the Secrets service, referenced by name. Authentication is OIDC (Entra ID and generic OIDC guides), plus scoped access keys; authorization uses roles, scopes and a policy engine. 0.10.0 makes `auth.oidc.audience` mandatory when OIDC is on. UNVERIFIED: whether auth is enabled by default in the chart; the security page does not say.

**Air-gap.** The install and security pages contain no air-gap or offline guidance, and no image-mirroring procedure. Images are in `nvcr.io/nvidia/nemo-helix/` and the chart pulls from NGC, so mirroring is possible in principle but is not documented. UNVERIFIED: any offline path. Note also that model providers such as NVIDIA Build and Tavily web search are internet services (the Tavily proxy sends nothing until a key is stored). A Telemetry and Privacy page exists; I did not read it.

**Other platforms.** Pages exist for OpenShift, minikube and kind. The Kubernetes distribution this lab uses is not covered; RWX and an NGC pull secret are the likely friction points.

For how this fits a NIM-operator-based estate, see [23](23-nemo-nim-operator-deployment.md) and the earlier investigations [03](../investigation/03-nvidia-recommended-deployment.md) and [04](../investigation/04-nemo-entity-and-data-store.md).

## 4. How Helix interacts with NIMs

*Gloss: Helix can start a NIM itself or just proxy to something already running, but it does not talk about the NIM Operator at all.*

**Does it deploy NIMs?** Yes, via a deployments plugin on one of three executors: Docker, Kubernetes, or OpenShell. The flow is `nemo inference deployment-configs create ... --engine nim` then `nemo inference deployments create ... --config ...`. On Kubernetes it downloads model files into a volume sized by `executor_config.disk_size` (default 50Gi). GPU count is set with `gpu` in the executor config (tensor-parallel times pipeline-parallel). The docs do not mention the NIM Operator or its `NIMService` CRDs on those pages. UNVERIFIED: whether Helix's Kubernetes executor creates raw Deployments or something else, and whether it can coexist cleanly with Operator-managed NIMs. Ask NVIDIA.

**Pointing at existing NIMs.** The Models and Inference page describes providers as "a routable inference host registered for an external API" and gives examples only for NVIDIA Build, OpenAI, Anthropic (and in the 0.1.0 notes, Gemini, Ollama, and "OpenAI-compatible endpoints"). So an existing OpenAI-compatible NIM Service should be registrable as a provider. UNVERIFIED: no page I read shows registering a self-hosted NIM that way; test it.

**Gateway overlap with Bifrost or LiteLLM.** There is overlap in shape (one OpenAI-compatible front door, secrets by name, multiple providers) and a wide gap in features.

| Aspect | Helix Inference Gateway | Bifrost / LiteLLM (see [06](06-bifrost-llm-gateway.md), [22](22-bifrost-deployment.md)) |
|---|---|---|
| Routing | By model, provider, or OpenAI path; virtual models; Switchyard (weighted random, stage router, LLM classifier) | Model lists, weights, fallbacks |
| Rate limits, token budgets, spend tracking | Not documented; the security page says rate limiting is something you must add | Core features |
| Fallbacks, load balancing | Not documented | Core features |
| Guardrails | Middleware on virtual models | Plugin or hook |
| Per-key access | Scoped access keys (`x-api-key` added in 0.10.0) with roles | Virtual keys with budgets |
| Purpose | Route traffic for evaluation, red-teaming and agent runs on one control plane | Production traffic governance |

My reading: the gateway exists so Helix's own jobs (evals, garak, agents) can reach models uniformly and so you can attach middleware such as closed-book evaluation. It is not positioned as the production front door for tenants. Running both is plausible: your gateway in front for client traffic, Helix pointed at models for its own jobs.

## 5. Model registry, metadata and promotion

*Gloss: there is a place to register models and their files, but the docs describe no promotion process or audit trail for them.*

**What exists.**
- **Model entities** (`/apis/models/v2/workspaces/{ws}/models`): a name, a pointer to a fileset holding the weights, an auto-populated model spec (architecture metadata), attached adapters (LoRA), a description, and a link back to the base model for fine-tuned models.
- **Filesets** (`/apis/files/v2/...`): named file collections with metadata update, upload, per-file HEAD, listing and a "refresh revision" call. The word "revision" suggests some versioning; UNVERIFIED how it behaves.
- **Deployment configs and deployments** are versioned (list, get-version, delete-version endpoints), as are some other entities.
- **Prompts** are a registered resource too.
- **Evaluations in Intake** have pin and unpin calls; experiments group runs.
- **Workspaces and projects** scope everything; members get roles.

**What the docs do not show.**
- Stages or promotion states (staging, production), approval gates, or a "champion" alias. The Entities page mentions none.
- Per-model token limits or quotas.
- A dedicated audit log. Access-control docs mention SIEM and audit rules in the migration notes, so identity-level events likely exist; UNVERIFIED whether there is a model-change audit trail.
- Any lineage from an evaluation result to a deployed model beyond naming conventions you maintain yourself.
- Access controls at the object level in the Data Store: the security page says there are none, and Helix can read everything, including adapters and training data.

If you need a registry with approvals, plan to wrap this with your own process or use a dedicated registry.

## 6. Migration from NeMo Microservices

*Gloss: NVIDIA publishes renaming notes for one service and says to call your account team for the rest.*

**Official guidance found.**
- Archived SDK docs: "If you use NeMo Microservices, please contact your NVIDIA account team to discuss next steps."
- NIM Operator upgrade page: points to the NeMo Platform docs for continuing.
- Helix docs: one migration-style page, **Upgrading from NeMo Evaluator**, plus "Migrating from Standalone Library" for Data Designer and a "Fabric 0.6 Upgrade" page. There is no page titled Migration and no full old-to-new mapping table.

**What the Evaluator page shows (a model for the pattern).** The Evaluator plugin became Helix Evals. The rename tool updates source files only, not "deployment configuration, databases, or serialized job artifacts". Config block `evaluator:` becomes `evals:` with no alias; env vars `NEMO_EVALUATOR_*` become `NEMO_EVALS_*`; CLI `nemo evaluator` becomes `nemo evals`; API prefix `/apis/evaluator/` becomes `/apis/evals/`; job sources are renamed so older jobs vanish from the Studio lists; roles such as `evaluator.*` stay.

**Mapping (inferred, mine).**

| Old (microservices) | Helix |
|---|---|
| NIM Proxy | Inference Gateway (`.../model/{name}/-/*`, `.../provider/{name}/-/*`, `.../openai/-/*`) |
| Entity Store namespaces | Workspaces; entities under `/apis/entities/v2/workspaces/{ws}/entities/{type}` |
| Data Store (Hugging Face API) | Files service with filesets, `/apis/files/v2/workspaces/{ws}/filesets` (HF-compatible file endpoints are mentioned in 0.10.0 fixes) |
| Deployment Management plus Operator | Models service deployments plugin |
| Evaluator | Evals (`/apis/evals/`) |
| Customizer, Guardrails, Data Designer, Safe Synthesizer | Same names, new resource shapes (guardrail configs under `/apis/guardrails/v2/workspaces/{ws}/configs`) |
| Auditor | NeMo garak |

**API changes to expect.** Everything is under `/apis/<service>/v2/workspaces/{workspace}/...`, with an OpenAPI 3.1 spec at `docs.nvidia.com/nemo-helix/openapi.json`. Old 25.x paths and payloads should be treated as incompatible; UNVERIFIED for any specific endpoint. Existing databases and datasets are not covered by any documented migration. For anything holding state in the old Data Store or Entity Store, plan to re-create or re-import.

## 7. When adopting Helix makes sense

*Gloss: adopt it for the improvement loop, not for the serving path.*

**Platform that only serves LLM NIMs behind its own gateway: probably not yet.**
- It would duplicate the gateway (section 4) and give you nothing for rate limits, budgets or fallbacks.
- It adds an NGC-gated chart, Postgres, ClickHouse, RWX storage and an immature auth model to run.
- It is pre-GA with a breaking change in every release, and has no documented air-gap path.
- The registry features are thin (section 5).
- NIM Operator already covers NIM lifecycle; Helix's deployments plugin would be a second way to do it.
- A cheap compromise: watch the project, and trial the Evals or garak pieces on a throwaway namespace pointing at your gateway.

**Platform that wants fine-tuning and evaluation workflows: worth a time-boxed trial.**
- Evals, Customizer, Data Designer and garak are the strongest parts, with extensive docs and tutorials.
- Workspaces plus jobs plus filesets give a coherent place to run and store the cycle.
- Risks: pinning to a chart version, the 0.x API, GPU capacity and scheduling (Volcano for multi-node), and unclear RWX and auth fit.
- Do it in a lab first, with an external Postgres and S3-compatible storage from day one.

**Either way**, ask whether you need the platform or just one library. Several services (Data Designer, garak, the Evaluator lineage) existed as standalone libraries first; the "Migrating from Standalone Library" page suggests that route still works.

## Questions to ask NVIDIA about Helix

1. Is NeMo Helix the renamed NeMo Platform, and is there a mapping from NeMo Microservices 25.x resources to Helix resources?
2. What is the support policy and GA timeline? What does 0.x commit to on API stability?
3. Are the Helm chart and `nvcr.io` images covered by the Apache 2.0 terms, or by NVIDIA product terms? What does production use require?
4. Is there a supported air-gapped install, including an image list and a chart mirror process?
5. Does Helix work with NIM Operator-managed NIMs, or does it want to launch NIMs itself? Which wins when both exist?
6. Does the Inference Gateway have any plan for rate limits, token budgets, fallbacks or spend tracking?
7. What is the intended model promotion and audit story (stages, approvals, change history)?
8. Which Kubernetes, PostgreSQL and CUDA versions are supported? Can the chart run with no GPUs?
9. Is authentication on by default in the chart, and what is the recommended production setup?
10. Is there a migration path for data held in the old Data Store and Entity Store?

## Check yourself

1. In one sentence, what is Helix, and what is it not?
2. Which part of Helix looks like the old NIM Proxy, and name two things the docs do not show that a production LLM gateway offers.
3. Why is RWX storage needed even if files are in S3?
4. Why not rely on the embedded Postgres?
5. Name two renames in the Evaluator to Evals upgrade page.
6. Give one reason a NIM-only platform should wait, and one reason a fine-tuning platform should try it.
7. How would you test whether Helix can register an existing NIM as a provider?

## References

Fetched 2026-11-19 unless noted.

- NeMo Helix docs hub: https://docs.nvidia.com/nemo-helix/
- Complete docs index (latest): https://docs.nvidia.com/nemo-helix/latest/llms.txt
- Home: https://docs.nvidia.com/nemo-helix/latest/documentation/home
- Release 0.10.0 (dated 2026-11-18, body says planned): https://docs.nvidia.com/nemo-helix/latest/documentation/reference/release-notes/release-0-10-0.md
- Release 0.1.0 (2026-05-20): https://docs.nvidia.com/nemo-helix/latest/documentation/reference/release-notes/release-0-1-0.md
- Helm prerequisites: https://docs.nvidia.com/nemo-helix/latest/documentation/kubernetes-deployment/setup/helm/prerequisites.md
- Helm install: https://docs.nvidia.com/nemo-helix/latest/documentation/kubernetes-deployment/setup/helm/install.md
- Database setup: https://docs.nvidia.com/nemo-helix/latest/documentation/kubernetes-deployment/setup/helm/database-setup.md
- File storage: https://docs.nvidia.com/nemo-helix/latest/documentation/kubernetes-deployment/setup/helm/file-storage.md
- Ingress: https://docs.nvidia.com/nemo-helix/latest/documentation/kubernetes-deployment/setup/helm/ingress.md
- Security: https://docs.nvidia.com/nemo-helix/latest/documentation/kubernetes-deployment/setup/security.md
- Models and inference: https://docs.nvidia.com/nemo-helix/latest/documentation/models-and-inference.md
- Deploy models: https://docs.nvidia.com/nemo-helix/latest/documentation/models-and-inference/deploy-models.md
- Virtual models: https://docs.nvidia.com/nemo-helix/latest/documentation/models-and-inference/virtual-models.md
- Entities: https://docs.nvidia.com/nemo-helix/latest/documentation/get-started/core-concepts/entities.md
- Model entities (Customizer): https://docs.nvidia.com/nemo-helix/latest/documentation/customizer-reference/manage-model-entities/overview.md
- Upgrading from NeMo Evaluator: https://docs.nvidia.com/nemo-helix/latest/documentation/evaluate-models/upgrading-from-evaluator.md
- Support matrix: https://docs.nvidia.com/nemo-helix/latest/documentation/reference/support-matrix.md
- Governing terms: https://docs.nvidia.com/nemo-helix/latest/documentation/reference/eula.md
- OpenAPI: https://docs.nvidia.com/nemo-helix/openapi.json
- GitHub repo (Apache-2.0, no published releases, ~150 stars): https://github.com/NVIDIA-NeMo/nemo-helix
- Old microservices sunset notice (archived SDK docs): https://docs.nvidia.com/nemo/microservices/26.3.0/pysdk/reference/inference/gateway.html
- NIM Operator deprecation note: https://docs.nvidia.com/nim-operator/3.1.2/nemo-upgrade.html
- Earlier lab files: [02](02-nemo-microservices.md), [../investigation/03](../investigation/03-nvidia-recommended-deployment.md), [../investigation/04](../investigation/04-nemo-entity-and-data-store.md)
