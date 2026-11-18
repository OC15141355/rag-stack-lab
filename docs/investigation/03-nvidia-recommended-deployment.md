# NVIDIA-recommended model deployment (as of 2026-11)

Research date: 2026-11-19. Sources are official NVIDIA documentation unless marked. Background on what NIM, the NIM Operator and the NeMo microservices are is in [01-nvidia-nim](../prereading/01-nvidia-nim.md), [02-nemo-microservices](../prereading/02-nemo-microservices.md) and [23-nemo-nim-operator-deployment](../prereading/23-nemo-nim-operator-deployment.md); this file does not repeat it. Items I could not confirm are marked `UNVERIFIED:`.

## Summary

- NVIDIA does not name one winner for NIM LLMs on Kubernetes. The current NIM for LLMs Kubernetes page says the NIM "supports deployment on Kubernetes using Helm charts, NIM Operator, and other orchestration platforms" and lists them side by side. Neither is labelled "recommended".
- The "NeMo microservices operator" path is not a recommended path any more. The NeMo Microservices product was sunset on 2026-10-01, and the NIM Operator says "Support for managing NeMo Microservices CRDs and deployments is deprecated" (3.1.3 notes).
- The part of the NIM Operator that serves NIM LLMs (`NIMCache`, `NIMService`, `NIMPipeline`, `NIMBuild`) is not deprecated. It is still actively released (3.1.4 is the latest notes entry). For the two NIM LLMs in scope, "the operator approach" now means the NIM half only.
- NeMo Helix is the successor lineage for the NeMo services, not for the NIM Operator. It is a different product (a model/agent/evaluation platform with a gateway), versions 0.x, with no GA label found in the docs I could read. Treat it as pre-1.0.
- Helix does not replace "how NIM LLMs get onto GPUs". It can deploy a NIM through its gateway, but the docs I found describe that as one option next to vLLM. It should not be assumed to be a model-weights store.
- The operator's real wins over a hand-written Helm/manifest setup are: model pre-staging as its own object (`NIMCache`), profile pinning in the spec, status conditions, built-in HPA wiring, multi-node via LeaderWorkerSet, and an optional NGC key for air-gapped use (3.1.3).
- NVIDIA documents no DEV/QA/PROD promotion model. Environment promotion is standard Kubernetes and GitOps practice. NIM CRDs have no health check shipped for ArgoCD; one must be added as a Lua check.
- Air-gapped is supported but thin in the docs: pre-populate the PVC, omit the auth secret, optionally use a mirrored local registry (S3, HTTPS, JFrog). Container image mirroring to a registry such as Harbor is the operator's own job and is not described on the air-gap page I read.
- For a ~750 GB FP8 model the single sizing fact to plan around is the PVC: the doc examples use 50 to 80 Gi for small models. A GLM-5.2-class cache needs well over 750 Gi plus headroom, on storage that can be mounted by the pods that need it.
- Net: moving from Helm to the operator is a modest-risk change of packaging and lifecycle ownership, not a change of runtime. Moving to Helix is a separate decision that should not be bundled in.

## The plain version

Think of a restaurant that serves one very large dish. The ingredients (the model files) are enormous, and fetching them from the supplier takes a long time. In a hand-run kitchen, whoever starts the stove also goes to the supplier, and if the stove restarts, they may go again.

The NIM Operator is a kitchen manager. You give it two order slips. One says "keep this ingredient in the cold room" (`NIMCache`): it fetches the model once into storage and checks it. The other says "run this dish on these burners" (`NIMService`): it starts the NIM container, points it at the cold room, waits until it is ready, and reports back. If you change the slip, the manager reconciles the kitchen to match.

The Helm chart is a recipe card plus a kitchen kit. It is just as valid, and NVIDIA still publishes it, but you do the managing yourself, and the ingredients are fetched as part of the pod starting unless you arrange otherwise.

The NeMo microservices operator was a second manager for a different set of side dishes (customisation, evaluation, guardrails). That restaurant has closed. The successor, Helix, is a new restaurant with a different menu, run by different staff. It is not a drop-in replacement, and it is not the place the main dish comes from.

So for the two LLMs, the question is only "do we want a kitchen manager (operator) or a recipe card (Helm)", and the closed-restaurant news does not apply to that choice.

## 1. What NVIDIA recommends today for NIM LLMs on Kubernetes

*Plain gloss: NVIDIA offers three routes, shows two of them equally, and does not say one is the one to use.*

Current NIM for LLMs docs, "Kubernetes Deployment" page, say it "supports deployment on Kubernetes using Helm charts, NIM Operator, and other orchestration platforms," then ask the reader to "Select your deployment or platform below." The section lists: Helm and Kubernetes, KServe, OpenShift, Run:ai, NIM Operator Deployment. Managed clouds (GKE, EKS, AKS) are sent to their own guides. The Helm page does not say the Operator is preferred; it lists the Operator page only as a next step.

| Route | What it is | NVIDIA positioning | Fit here |
|---|---|---|---|
| NIM Operator | Controller plus CRDs: `NIMCache`, `NIMService`, `NIMPipeline`, `NIMBuild` (TensorRT-LLM engine build and cache) | Equal-status page in the NIM LLM docs; separate docs site, release every few weeks; "government ready" designation from 3.0.1 | Strongest on lifecycle features |
| `nim-llm` Helm chart | Chart from NGC; values for image, persistence, resources, multi-node | Equal-status page; the page is the more detailed "how", with versions | Closest to what exists today |
| Plain manifests | Hand-written Deployment/StatefulSet | Not documented as a route. `UNVERIFIED:` that no plain-manifest guide exists; I found none | Same as Helm minus the chart |

Chart facts from the Helm page (latest): Kubernetes v1.26 or later, Helm 3.0.0 or later, an NGC API key, a storage class supporting persistent volumes, and optionally the LeaderWorkerSet CRD and controller for multi-node. The example sets `image.tag: "2.1.6"`, `persistence.accessMode: ReadWriteMany` and `size: 50Gi`, and a startup probe on `/v1/health/ready`.

Operator facts from the NIM LLM operator page: needs Kubernetes 1.26 or later, the GPU Operator, a storage provisioner, an NGC API key and "NIM Operator 3.0.2 or later".

**Honest position on "recommended".** I found no NVIDIA sentence that says "use the Operator, not Helm" for NIM LLMs. NVIDIA's own blueprint docs (for example the RAG Blueprint's "Deploy ... on Kubernetes with NIM Operator" page) use the Operator, which suggests it is the path NVIDIA itself prefers for assembled stacks, but that is inference, not a quote. `UNVERIFIED:` any explicit "recommended" wording.

## 2. Is "NeMo microservices operator" still a recommended path?

*Plain gloss: no; the NeMo half of the operator is deprecated and the product behind it is sunset, but the NIM half is untouched.*

Quoted text:

- Archived NeMo Microservices docs: NeMo Microservices "will be sunset on October 1, 2026." "All new development has moved to NeMo Platform." Users are asked to "contact your NVIDIA account team to discuss next steps." The archive says it is "no longer actively maintained, validated, or updated" and should not guide current decisions.
- NIM Operator release notes, v3.1.3: "Support for managing NeMo Microservices CRDs and deployments is deprecated." The notes link to the NeMo Platform for continued use.
- NIM Operator release notes, v3.1.1 (earlier warning): "The NIM Operator is deprecating support for the NeMo Microservices CRDs and deployments in the next release."
- No removal release is named in anything I read.

Important correction to the framing: v3.1.3 (the notes page gives no dates; the 2026-10-28 date is from the earlier file's check of GitHub releases) also **added** NIM features: NGC key optional, scale to zero, Multi-node-with-Ray samples, and support for NIM for LLMs 3.0 and 2.x. v3.1.4 is a bug fix for profile auto-selection. The operator is deprecating only the `NemoCustomizer`, `NemoEvaluator`, `NemoGuardrail`, `NemoDatastore` and `NemoEntitystore` kinds.

**What the Helix equivalent is.** Helix is the new home for the NeMo services' capabilities. Overview wording: "Run Helix locally or on Kubernetes, and access it through REST APIs, a CLI or a Python SDK." Capability groups: Models and Inference (model providers, virtual models, gateway), Files, Secrets, Entities, jobs; a UI called "NeMo Studio (alpha)". Helm install is `helm upgrade --install` from the NGC Helm repository with a pinned chart version.

**Is it GA?** Not stated anywhere I could read.

- Versions are 0.x. The first public release was 0.1.0 on 2026-05-20, "local-first ... no cluster required". The 0.5.0 notes describe local setup and user-managed Kubernetes deployment, "not a managed hosted-service release".
- The docs index lists versions 0.5 to 0.10. The newest notes page I could read is headed "v0.10.0 - 2026-11-18" and says the date "is a planned date, and the content can change before the release ships." A search surfaced 0.7.1 (2026-10-09) as a republished container set. So the newest *shipped* version is `UNVERIFIED:` between 0.7.x and 0.9.x; 0.10.0 may not yet be cut.
- Product naming: the Helm install docs sit under both `docs.nvidia.com/nemo-platform` and `docs.nvidia.com/nemo-helix`. `UNVERIFIED:` that NVIDIA states "NeMo Platform" was renamed "NeMo Helix"; the Helix landing page does not use the phrase.
- Conclusion: pre-1.0, treat as preview in practice. No GA, support or SLA statement found.

Helix is not a drop-in for the CRDs. The earlier file notes renamed config blocks and no automatic migration. For the two NIM LLMs this is irrelevant unless the platform also runs the customisation, evaluation or guardrails microservices; in that case that is a separate migration with its own file.

## 3. Required components and prerequisites

*Plain gloss: a GPU-ready Kubernetes cluster, the GPU Operator, big shared storage, and two secrets; no database for NIM.*

| Area | Requirement | Source and notes |
|---|---|---|
| Kubernetes | 1.26 or later for NIM LLM (Helm and Operator pages). Operator platform-support page gives no explicit minimum; says only that kubectl must match the cluster and Helm 3 or later. | `UNVERIFIED:` whether VKS/Tanzu is a tested platform; the platform-support page does not mention it. Check that the VKS release is at or above 1.26 and that GPU nodes are exposed as ordinary worker nodes. |
| GPU Operator | NIM Operator "requires NVIDIA GPU Operator version 24.3.0 or higher". It brings the driver (or a pre-installed host driver), container toolkit, device plugin, Node Feature Discovery, GPU Feature Discovery and DCGM exporter. | On VKS, GPU nodes with pre-installed vGPU or passthrough drivers are a platform concern. `UNVERIFIED:` the right GPU Operator driver mode on VKS; follow the VMware and NVIDIA GPU Operator docs, not the NIM docs. |
| Storage | `NIMCache` creates a PVC: `spec.storage.pvc` with `create`, `size`, `storageClass` (omit for default), `volumeAccessMode`, `subPath`. Doc examples: 50 Gi (single small model), 80 Gi (vLLM/SGLang example). | For a ~750 GB FP8 checkpoint, plan at least 1 to 1.5 TiB per cached copy. `UNVERIFIED:` the exact size NVIDIA states for GLM-5.2; its get-started page returned no readable text. Check the model card and `kubectl describe nimcache` after caching. Models over about 49 B parameters hit a known "Too many open files" error (3.0.0 known issue); raise the container runtime's file limit on GPU nodes. |
| RWO vs RWX | Examples use `ReadWriteOnce` (single model) and `ReadWriteMany` (multi-NIM). Helm example uses `ReadWriteMany`. The cache docs say one cached model can serve several pods "when the volume uses network storage". | An 8-GPU pod on one node can run from RWO. Multi-replica, multi-node (LWS) or rolling updates that overlap two pods on different nodes need RWX, or one cache per node. Choose by test, not assumption. |
| Intra-node networking | NVLink/NVSwitch inside an 8x H200 or 4x B200 node carries tensor parallelism; NCCL uses it automatically. Needs host IPC/shared memory sized per model docs. | `UNVERIFIED:` the exact `/dev/shm` figure for GLM-5.2; the operator exposes a shared-memory size limit (2.0.1 notes) but I found no number. |
| Multi-node | Supported since 3.0.0 via LeaderWorkerSet. `spec.multiNode.parallelism` (pipeline, tensor) is required; `backendType` defaults to `lws` and "Currently only LWS is supported"; `ray` for NIM 2.0 and later, `mpi` for older. Needs the LWS CRD and controller installed. | Not needed for the stated profiles (8x H200 or 4x B200 fit one node). Only relevant if a profile spans nodes. Multi-node NIMs use Ray and vLLM (3.1.1 notes). |
| RBAC | The operator runs with a ClusterRole created by its Helm chart: it manages its CRDs, Deployments, Services, PVCs, Jobs, ConfigMaps, ServiceMonitors, HPAs, and, optionally, Ingress, Gateway API routes, KServe and LWS objects. | `UNVERIFIED:` the exact rule list; I did not read the chart. Review `helm template` output before approval in a locked-down cluster. Not namespace-scoped by default as far as I could tell. Validation webhooks are off by default outside OpenShift (3.0.2). |
| Secrets | (1) `docker-registry` secret for `nvcr.io` (image pull), (2) generic secret with `NGC_API_KEY` for model download. As of 3.1.3 the NGC key is optional on `NIMService` and `NIMCache`; if every model is pre-cached, leaving `authSecret` off means "the Operator does not inject the `NGC_API_KEY` environment variable into the NIM pod." | Pull secret still needed if images come from `nvcr.io`. With a Harbor mirror use a Harbor pull secret. |
| Database | None for NIM LLM serving. | The NeMo CRDs, now deprecated, needed Postgres and similar (Entity Store, Customizer). Helix has its own state needs, out of scope. |
| Tools | `kubectl` and Helm 3 or later. | |

## 4. Model lifecycle under the operator

*Plain gloss: download once into a cache object, name the exact profile you want, then run a service that reads from the cache.*

**Download and pre-staging (`NIMCache`).** One source per cache: `ngc` (with `modelPuller`, `pullSecret`, `authSecret`, and a `model` block with `engine` and `tensorParallelism`), `hf` (needs an HF token secret), or `dataStore` (NeMo Data Store, with `endpoint`, `modelName`, `namespace`, optional `revision`: a commit, branch or tag). A Job fetches into the PVC; wait for the cache `Ready` condition before creating the service. The pod mounts the volume at `/model-store`, and the pod fails if the artifacts are missing.

**Profile selection and pinning.** Cached profiles appear in `.status.profiles`, each with a hashed `name` and a `config` (`llm_engine`, `precision`, `tp`, `feat_lora`, `trtllm_buildable`). The NIM LLM operator page says: set `spec.storage.nimCache.profile` on the `NIMService` to a profile name (examples `vllm-fp8-tp1-pp1`, `sglang-fp8-tp1-pp1`), and list names with `list-model-profiles` in the image or `kubectl describe nimcache`. "Leave `engine` empty if you set `model.profiles` explicitly." The cache page documents `engine` and `tensorParallelism` as spec fields; it does not document a `precision` field in the spec (precision shows up only in status), so pin by explicit profile name or hash. Separately, the NIM container accepts `NIM_MODEL_PROFILE` as an environment variable, usable through `spec.env`. Profile auto-selection by hardware is the default when nothing is pinned, and 3.1.4 fixed a manifest parsing bug in it.

For the platform's two models, the GLM-5.2 docs (via search) describe an H200 profile at FP8 with tensor parallel size 8 and a B200 profile using NVFP4 at tensor parallel size 4. That is a flag: a "4x B200 FP8" profile was not seen. `UNVERIFIED:` that a 4x B200 FP8 profile exists; confirm from `nim-metadata` or the profile list.

**Image tag and digest pinning.** `spec.image` takes repository, tag, pull policy and pull secret. Doc examples set explicit tags such as `1.3.3`. The docs do not use the word "pinning" and do not document a digest field. `UNVERIFIED:` that `repository@sha256:` works in `spec.image.tag`; test it. Practical rule: set the tag to a version, mirror to Harbor, and record the digest in Git by also pinning `modelPuller` (which is an image reference too).

**Rollout and upgrade.** The NIMService page I read does not describe rolling-update strategy. Operator upgrades are decoupled from NIMService restarts (2.0.0 notes). Changing `spec.image` or the profile triggers a pod replacement. With one replica of an 8-GPU model, a default rolling update cannot schedule the second pod on the same GPUs; plan for `Recreate` semantics or spare GPU capacity. `UNVERIFIED:` which strategy the operator uses and whether it is configurable.

**Scaling.** `spec.replicas` (default 1) or `spec.scale.enabled` with `spec.scale.hpa` (`minReplicas`, `maxReplicas`, up to five `metrics`, `behavior`); you cannot define both. The Object-metric example targets `gpu_cache_usage_perc`. Scale to zero (3.1.3) needs an External or Object metric and the `HPAScaleToZero` feature gate. Each replica of these models is a full 8x H200 or 4x B200 node, so scaling is bounded by node count, and custom metrics need a metrics adapter (Prometheus Adapter or KEDA, `UNVERIFIED:` which NVIDIA documents).

**Health and readiness.** Defaults: liveness `/v1/health/live`, readiness `/v1/health/ready`, startup failure threshold 120 ("up to 20 minutes"); other probes wait for startup. The Helm chart's startup defaults allow about an hour (`periodSeconds: 30`, `failureThreshold: 120`) and the page says to increase for large models. The 20-minute operator default was raised in 2.0.2.

**Startup time for a large model.** `UNVERIFIED:` NVIDIA gives no figure for GLM-5.2. Loading ~750 GB from a network volume plus engine initialisation can plausibly exceed 20 minutes, so raise `startupProbe` to the Helm chart's hour, and test cold-start time on the real storage class. Pre-staging in a `NIMCache` removes the download, not the load.

## 5. Multi-environment (DEV, QA, PROD)

*Plain gloss: NVIDIA says nothing about environments; you promote the same pinned versions through Git, and ArgoCD needs a small health check for the new object types.*

**What NVIDIA documents.** I found no NVIDIA guidance on promotion between environments, for either the operator or Helix. `UNVERIFIED:` absence; I searched the operator and NIM LLM docs only.

**Standard pattern, applied to NIM CRDs.**

| Item | Same across environments | Per environment |
|---|---|---|
| NIM image tag (and digest, if usable) | yes, promoted by Git change | none |
| `NIMCache` source and `modelPuller` | yes | storage class, size, PVC name |
| Pinned profile name | yes | none, unless hardware differs |
| `NIMService` spec | yes (base) | replicas or HPA bounds, GPU count if DEV uses a smaller profile, node selector and tolerations, ingress host, ServiceMonitor labels |
| Secrets | names fixed | values (NGC key, pull secret); ideally external secrets or sealed |

Use a base plus overlays (Kustomize) or a Helm values file per environment, one Git branch or directory per environment, and promote by merging the version bump. If DEV has less GPU capacity, the profile differs, so the profile is a per-environment value, and QA should match PROD. That is the point at which QA stops being a faithful rehearsal, so it is worth stating.

**ArgoCD.** ArgoCD has no built-in health assessment for NIM CRDs; unknown kinds are considered Healthy once they exist. Add custom health checks in `argocd-cm` (`resource.customizations.health.apps.nvidia.com_NIMCache` and `..._NIMService`) that read `.status.state` or the `Ready` condition. The status conditions exist (the earlier file shows `Ready=True`, `Failed=False`, `State: Ready` for the NeMo kinds; `NIMService` and `NIMCache` expose conditions too). `UNVERIFIED:` exact field names on `NIMCache` and `NIMService`; read them from a live `kubectl get -o yaml` before writing the Lua. Also set sync waves: `NIMCache` before `NIMService`, and set `ignoreDifferences` for operator-managed fields. Mind that a large `NIMCache` PVC should not be pruned: use `Prune=false` or a PVC retention option, since "Deleting the cache then deletes the PVC and cached models" when `create: true`. With `create: false`, the PVC is yours to manage.

## 6. Air-gapped specifics

*Plain gloss: you carry the images and weights across the gap yourself; the operator then runs without internet or an NGC key.*

From the operator's air-gap page:

- Two options: NGC through a proxy, or a local model source. "Copy the model files into a persistent volume claim from a connected system."
- Pods run as non-root with defaults `spec.userID` 1000 and `spec.groupID` 2000. Match file ownership or set both fields on `NIMCache` and `NIMService`. Many NFS provisioners do not apply `fsGroup`, so set permissions yourself.
- With all models pre-cached, omit `spec.authSecret` (the key is optional since 3.1.3).
- Proxy and CA: `spec.proxy` with `httpProxy`, `httpsProxy`, `noProxy`, `certConfigMap`.
- NGC-mirrored local registries (S3, HTTPS, JFrog) are supported for LLM NIM; a Local File Data Store is supported for Multi-LLM NIM.

Not on that page: container image mirroring and `NIM_REPOSITORY_OVERRIDE`. The earlier file covers a Harbor mirroring procedure, labelled as mostly its own. `UNVERIFIED:` NVIDIA's official image mirroring recipe for the operator, including mirroring the operator's own images and the `modelPuller` image.

**NGC alternatives.** HF (needs HF reachability, so not true air-gap), a NeMo Data Store (deprecated product), an S3/HTTPS/JFrog mirror, or a hand-copied PVC. In practice the hand-copied PVC, or an object-store mirror inside the network, is the dependable path.

## 7. Model registry and model store options

*Plain gloss: only one of these is a store you can fill with your own approved weights, and none is a full lifecycle registry.*

| Option | What it is | Is it a model store? |
|---|---|---|
| NGC private registry | NVIDIA-hosted org space for containers, models, Helm charts, with access control | Yes for containers, charts and models you publish there, but it needs NGC connectivity, so it is not usable air-gapped. Use it as the connected-side staging. |
| `NIMCache` (source `ngc`, `hf`, `dataStore`) | A PVC filled by a Job from one source | No. It is a node-local-ish cache, not a registry. No versioning beyond what the source gives; `dataStore` has `revision`. |
| Local or mirrored registry (S3, HTTPS, JFrog) | A source the NIM can read from (LLM NIM) | Yes, if you operate it. This is the closest thing to an internal model store, and it fits the air-gapped case. |
| NeMo Data Store | Git-LFS-like store from the sunset NeMo Microservices | Was one; now deprecated with the product. Do not adopt. |
| Helix Files (filesets) and model entities | Platform storage of files, with model entities that reference a fileset; a deploy flow can point a deployment config at it; HF-backed storage configs exist | Partly. It tracks model entities and files, but I found no statement that it is a governed registry (approval stages, immutable versions). `UNVERIFIED:` registry semantics. |
| Harbor (OCI) | Image registry; can hold OCI artifacts | Not an NVIDIA option, but common to store weights as OCI artifacts. Out of NVIDIA's documented path. |

## 8. Observability

*Plain gloss: the NIM exposes Prometheus metrics itself, DCGM covers the GPUs, and the operator can create the ServiceMonitor.*

- **NIM metrics endpoint:** `/v1/metrics` (Prometheus format). Metric names named in the NIM docs include `gpu_cache_usage_perc`, `num_requests_running` and `time_to_first_token` (the page gave names only, with no descriptions). The first is the one the operator's HPA example uses.
- **Operator:** `spec.metrics.enabled` (default `false`) makes the operator create a `ServiceMonitor`, with `additionalLabels`, `interval` and `scrapeTimeout`. Label it to match the Prometheus selector. The operator's own metrics are on HTTP port 8080 (1.0.1 change).
- **Health:** `/v1/health/live` and `/v1/health/ready`.
- **DCGM exporter:** installed by the GPU Operator; gives GPU utilisation, memory, temperature, power, and XID errors per GPU. For 8-GPU nodes also watch NVLink and per-GPU skew.
- **OpenTelemetry:** the NIM docs list OpenTelemetry. `UNVERIFIED:` which spans and which version.

What to dashboard: per environment and per model, request rate and error rate at the gateway (Bifrost); time to first token and inter-token latency percentiles; running and waiting requests; KV cache usage (`gpu_cache_usage_perc`); GPU memory and utilisation per GPU; pod readiness and restart count; `NIMCache` and `NIMService` status; PVC usage; model load time at each restart. Alert on KV cache saturation, readiness flaps, XID errors and restarts, because a restart of a ~750 GB model is a long outage.

## Implications for a migration

What changes against an existing Helm or manifest NIM deployment:

1. **Packaging.** Replace the chart release (or manifests) with two CRs per model, plus a cluster-wide operator install. The operator becomes a new cluster-level dependency with a ClusterRole, a CRD set, and its own upgrade cycle, so it needs the same change control as the GPU Operator.
2. **Model download moves out of pod start-up.** Today, the pod or an init step likely fetches or mounts weights. With `NIMCache` it is a Job writing a PVC, and `NIMService` mounts it. Gain: separate failure domains, a visible status, and a pre-stage step before rollout. Cost: you must size and manage the PVC and storage access mode.
3. **Profile pinning becomes explicit.** Set the profile by name in `NIMService`, or accept hardware-based auto-selection. Pin it, and check the profile exists on both H200 and B200 hardware before assuming they match.
4. **GitOps.** Add ArgoCD custom health checks and sync waves. The existing Ansible plus GitLab branches flow can keep promoting a values or overlay file; only the rendered objects change. Ansible should stop at installing the GPU Operator and NIM Operator; per-environment model objects belong to ArgoCD.
5. **Rollout behaviour needs a test.** With 8-GPU or 4-GPU pods, an upgrade needs spare capacity or a planned outage. Test it in QA on the same hardware.
6. **Air-gap.** Mirror the operator's images, the NIM and `modelPuller` images and the model files to Harbor and the PVC, and omit the NGC key.
7. **Do not bundle Helix.** Helix is pre-1.0, with no GA statement, and does not replace the NIM half of the operator. Revisit it only if the platform actually needs the gateway, evaluation, or customisation functions, and then as a separate investigation.
8. **Keep the Helm path as the fallback.** It is supported, equal in the docs, and the rollback if the operator proves awkward on VKS.

Open checks before committing: VKS support for the operator and GPU Operator, RWX storage class performance with a ~750 GB model, cold-start time, rollout strategy on a single-node 8-GPU service, digest pinning, and the 4x B200 profile precision.

## References

All fetched 2026-11-19 unless noted. Release notes pages carry no dates in the text I could read.

- NIM Operator home: https://docs.nvidia.com/nim-operator/latest/index.html
- NIM Operator release notes (3.1.4 down to 1.0.0): https://docs.nvidia.com/nim-operator/latest/release-notes.html
- NIM Operator platform support: https://docs.nvidia.com/nim-operator/latest/platform-support.html
- NIMCache reference: https://docs.nvidia.com/nim-operator/latest/cache.html
- NIMService reference: https://docs.nvidia.com/nim-operator/latest/service.html
- NIM Operator air-gapped page: https://docs.nvidia.com/nim-operator/latest/air-gap.html
- NIM for LLMs Kubernetes deployment index: https://docs.nvidia.com/nim/large-language-models/latest/deployment/kubernetes-deployment/index.html
- NIM for LLMs Helm page: https://docs.nvidia.com/nim/large-language-models/latest/deployment/kubernetes-deployment/helm-k8s.html
- NIM for LLMs Operator page: https://docs.nvidia.com/nim/large-language-models/latest/deployment/kubernetes-deployment/nim-operator-deployment.html
- NIM for LLMs observability (topic list only): https://docs.nvidia.com/nim/large-language-models/latest/observability.html
- GLM-5.2 get-started (page text did not load; profile details from search summary): https://docs.nvidia.com/nim/large-language-models/latest/get-started/advanced/get-started-glm-5-2.html
- NeMo Microservices archive (sunset notice): https://archive.docs.nvidia.com/nemo/microservices/latest/index.html
- NeMo Helix home: https://docs.nvidia.com/nemo-helix
- NeMo Helix v0.10.0 notes (planned date 2026-11-18): https://docs.nvidia.com/nemo-helix/latest/documentation/reference/release-notes/release-0-10-0.md
- NeMo Helix 0.7.x notes (search-reported, 0.7.1 dated 2026-10-09): https://docs.nvidia.com/nemo-helix/v0.7.3/documentation/reference/release-notes/current-release.md
- NeMo Platform Helm install: https://docs.nvidia.com/nemo-platform/documentation/kubernetes-deployment/setup/helm
- Helix deploy models: https://docs.nvidia.com/nemo-helix/documentation/models-and-inference/deploy-models
- RAG Blueprint on the NIM Operator (inference for the "preferred in blueprints" remark): https://docs.nvidia.com/rag/2.3.0/deploy-nim-operator.html
- NGC chart page, `k8s-nim-operator` 3.1.3: https://catalog.ngc.nvidia.com/orgs/nvidia/-/helm-charts/k8s-nim-operator/3.1.3
