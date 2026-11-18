# Deploying the NIM Operator and NeMo microservices

## In one paragraph

The NVIDIA NIM Operator is a Kubernetes controller that turns two small YAML objects into a running model server: a `NIMCache` downloads a model to shared storage once, and a `NIMService` starts the NIM container that reads from that cache and serves an OpenAI-compatible API. It also ships custom resources for the NeMo microservices (`NemoDatastore`, `NemoEntitystore`, `NemoCustomizer`, `NemoEvaluator`, `NemoGuardrail`). That second half is on its way out. The operator's own docs (checked 2026-11-18) say "Support for managing NeMo Microservices CRDs and deployments is deprecated" (3.1.3 release-notes notice), and NVIDIA's archived NeMo Microservices docs say the product was sunset on 2026-10-01 with all new development moved to the NeMo Platform, whose docs hub is now NeMo Helix. So: the NIM half of the operator is the stable part to learn; the NeMo half is something to understand for existing deployments and to plan an exit from. This file assumes you have read files 01 (NIM) and 02 (NeMo microservices) and does not repeat what those services are.

## The plain version

Think of a restaurant group opening a new kitchen. The head chef (the model) is hired once, and his recipes, knives and notebooks (the model files) have to be carried in from head office. Carrying them in takes hours and you do not want to repeat it every time a cook calls in sick.

The NIM Operator is the facilities manager. You hand it two forms. Form one says "bring the chef's equipment from head office to the shared storeroom, once." Form two says "open a kitchen using that storeroom, with one stove (a GPU) and a front counter on port 8000." The manager does the carrying, checks the storeroom, opens the kitchen, and reopens it if it burns down. The NeMo forms are extra forms for the back-office departments (records, testing, safety checks, training). Head office has announced that this particular set of back-office forms is being retired and replaced by a different system with different paperwork.

Without the manager, someone runs a long chain of manual steps: pull a large image, download the model on every pod start, mount the right volumes, and remember the right flags. Each restart can mean another large download.

If you remember only five things:

- Install order matters: GPU Operator first, then the NIM Operator, then secrets, then `NIMCache`, then `NIMService`.
- Two different secrets are needed: one so the cluster can pull images from `nvcr.io`, one holding the NGC API key so the model puller can download weights.
- A `NIMCache` must reach `Ready` before the `NIMService` can start; the model lives on a volume, not in the image.
- The NeMo custom resources are deprecated in the operator, and the NeMo Microservices product itself is sunset. Do not start new work on them.
- Air-gapped installs mean mirroring images and pre-filling the cache volume; the operator docs cover the cache part well and the image-mirroring part barely at all.

## Section 1. Install the NIM Operator with Helm

*Gloss: the operator is one Deployment plus some CRDs, and it only works once the cluster can already hand out GPUs.*

### Prerequisites, from the install page (latest, checked 2026-11-18)

1. Hardware that meets the requirements for the NIMs or NeMo services you plan to run.
2. A Kubernetes cluster with cluster-admin access. The GitHub README lists Kubernetes v1.28 or higher.
3. An NVIDIA AI Enterprise subscription or NVIDIA Developer Program membership ("Access to NIM containers and models is restricted").
4. The NVIDIA GPU Operator. The page says the NIM Operator "requires that the GPU Operator be installed on your cluster."

### Step 1: GPU Operator

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && helm repo update

helm install --wait --generate-name \
   -n gpu-operator --create-namespace \
   nvidia/gpu-operator
```

Check that nodes advertise GPUs. This output is illustrative; the docs do not show it for this step.

```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia\\.com/gpu
# NAME        GPU
# gpu-node-1  1
# cpu-node-1  <none>
```

### Step 2: the operator itself

```bash
kubectl create namespace nim-operator

helm upgrade --install nim-operator nvidia/k8s-nim-operator \
   -n nim-operator --version=3.1.2

kubectl get pods -n nim-operator
```

Expected output, as printed on the install page:

```
NAME                                            READY   STATUS    RESTARTS   AGE
nim-operator-k8s-nim-operator-6b546f57d5-g4zgg  1/1     Running   0          35h
```

Version note: the install page pins chart `3.1.2`. The operator release notes list v3.1.4 as the latest (a single bug fix for automatic profile selection in NIM caches), and the GitHub releases API showed v3.1.3 dated 2026-10-28 at the top when I queried it. Pin deliberately, and read the release notes before choosing. The same page covers OpenShift (OperatorHub) separately.

Confirm the CRDs exist:

```bash
kubectl get crd | grep apps.nvidia.com
# expected (names from the docs' resource list; exact set depends on version):
# nimbuilds.apps.nvidia.com   nimcaches.apps.nvidia.com   nimpipelines.apps.nvidia.com
# nimservices.apps.nvidia.com  nemocustomizers... nemoevaluators... nemoguardrails...
```

UNVERIFIED: the exact CRD list printed by 3.1.x. The docs name `nimcaches`, `nimservices`, `nimpipelines` and `nimbuild` and the NeMo kinds, but I did not see a `kubectl get crd` output.

### Step 3: the secrets

Two secrets, created in the namespace where the NIM will live. The install page's Helm path does not create them; the NeMo prerequisites page gives these commands, which apply equally to a NIM namespace.

```bash
kubectl create namespace nim-service

# 1. Image pull secret: lets the kubelet pull from nvcr.io
kubectl create secret -n nim-service docker-registry ngc-secret \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password=<ngc-api-key>

# 2. API key secret: used by the model-puller job and by the NIM container
kubectl create secret -n nim-service generic ngc-api-secret \
  --from-literal=NGC_API_KEY=<ngc-api-key>
```

The username is the literal string `$oauthtoken`; keep the single quotes so the shell does not expand it. The secret names `ngc-secret` and `ngc-api-secret` are the names used in every sample manifest.

### Step 4: storage class

The `NIMCache` creates a PVC. The docs say: omit `storageClass` or set it to `""` to use the cluster default; use `ReadWriteMany` when several pods share one cache; local-path provisioners are fine for research and development, and a network-backed provisioner is recommended for production.

```bash
kubectl get storageclass
# NAME                   PROVISIONER            RECLAIMPOLICY   VOLUMEBINDINGMODE
# nfs-client (default)   cluster.local/nfs...   Delete          Immediate
```

A trap straight from the docs: the sample `NIMCache` asks for `ReadWriteMany`, yet the page's example `kubectl get pvc` output shows `RWO` on an `nfs-client` class. Always read the access mode off the real PVC.

## Section 2. NIMCache and NIMService for an LLM

*Gloss: the cache is a one-off download job that fills a volume; the service is a Deployment that mounts that volume and asks for a GPU.*

### The NIMCache

Fields below are the ones in the operator docs' LLM sample. The image tag and model are the docs' example, not a recommendation; substitute a current model from the NGC catalogue.

```yaml
apiVersion: apps.nvidia.com/v1alpha1
kind: NIMCache
metadata:
  name: meta-llama3-8b-instruct
  namespace: nim-service
spec:
  source:
    ngc:
      modelPuller: nvcr.io/nim/meta/llama-3.1-8b-instruct:1.3.3
      pullSecret: ngc-secret          # image pull secret
      authSecret: ngc-api-secret      # secret with NGC_API_KEY
      model:
        engine: tensorrt_llm
        tensorParallelism: "1"
  storage:
    pvc:
      create: true
      storageClass: <storage-class-name>   # omit for cluster default
      size: "50Gi"
      volumeAccessMode: ReadWriteMany
  resources: {}
```

Notes on fields:

- `spec.source` has three documented variants: `ngc` (NGC catalogue), `dataStore` (a NeMo Data Store, which is a NeMo-side dependency and therefore on the deprecated path) and `hf` (Hugging Face; the docs show only `authSecret` for it, so UNVERIFIED: the remaining `hf` fields, check the CRD with `kubectl explain nimcache.spec.source.hf`).
- `create: false` plus `name:` reuses an existing PVC.
- If the operator created the PVC (`create: true`), deleting the `NIMCache` also deletes the PVC and the cached profiles. For a 100 GB+ cache, that is a decision, not a default.
- Optional `profiles` and `subPath` fields exist on the page; I did not exercise them.

```bash
kubectl apply -f nimcache.yaml
kubectl get nimcaches.apps.nvidia.com -n nim-service
```

Expected output from the docs (the timestamp in the AGE column is how the page prints it):

```
NAME                      STATUS   PVC                           AGE
meta-llama3-8b-instruct   Ready    meta-llama3-8b-instruct-pvc   2024-09-19T13:20:53Z
```

The cache is filled by a Kubernetes Job. Watch it:

```bash
kubectl get jobs -n nim-service
# NAME                          COMPLETIONS   DURATION   AGE
# meta-llama3-8b-instruct-job   1/1           8s         2m57s
```

The 8 seconds in the docs' example is not realistic for a first download of a multi-gigabyte model; expect minutes to hours depending on size and bandwidth.

Status values on the page: `Pending`, `PVC-Created`, `Started`, `InProgress`, `NotReady` (often just the puller image still downloading), `Ready`, `Failed`. See which profiles were cached:

```bash
kubectl get nimcaches.apps.nvidia.com -n nim-service meta-llama3-8b-instruct \
  -o jsonpath="{.status.profiles}" | jq .
```

The docs say each entry has a `name` hash and a `config` object with fields such as `llm_engine: tensorrt_llm`, `precision: bf16`, `tp: 1`.

### The NIMService

```yaml
apiVersion: apps.nvidia.com/v1alpha1
kind: NIMService
metadata:
  name: meta-llama3-8b-instruct
  namespace: nim-service
spec:
  image:
    repository: nvcr.io/nim/meta/llama-3.1-8b-instruct
    tag: "1.3.3"
    pullPolicy: IfNotPresent
    pullSecrets:
      - ngc-secret
  authSecret: ngc-api-secret
  replicas: 1                     # omit if you use spec.scale (autoscaling)
  storage:
    nimCache:
      name: meta-llama3-8b-instruct
      profile: ''                 # empty = operator picks a profile
  resources:
    limits:
      nvidia.com/gpu: 1
  expose:
    service:
      type: ClusterIP
      port: 8000
```

The docs also describe `spec.expose.router` (Ingress or Gateway API, host `<name>.<namespace>.<hostDomainName>`), `spec.metrics` plus `spec.scale` for an HPA (do not set `replicas` as well), and `spec.storage.pvc` with `create: true` if you skip the `NIMCache` and let the service download for itself. Skipping the cache is easy but means each fresh PVC re-downloads.

```bash
kubectl apply -f service.yaml
kubectl get nimservices.apps.nvidia.com -A
```

```
NAMESPACE     NAME                      STATUS   AGE
nim-service   meta-llama3-8b-instruct   Ready    2024-08-12T17:16:05Z
```

`kubectl describe` shows (from the docs) a `Ready` condition with message "Deployment is ready", a `Failed` condition of `False`, and `State: Ready`. Ask the operator what model name the server reports:

```bash
kubectl get nimservice.apps.nvidia.com -n nim-service meta-llama3-8b-instruct \
  -o jsonpath="{.status.model}" | jq .
# { "clusterEndpoint": "", "externalEndpoint": "", "name": "meta/llama-3.1-8b-instruct" }
```

Then call it from inside the cluster, using the `name` value as the model:

```bash
kubectl run --rm -it -n default curl --image=curlimages/curl:latest -- ash
# inside the pod:
curl -X POST 'http://meta-llama3-8b-instruct.nim-service:8000/v1/chat/completions' \
  -H 'Content-Type: application/json' \
  -d '{"model":"meta/llama-3.1-8b-instruct","messages":[{"role":"user","content":"Say hello"}],"max_tokens":32}'
```

Remember from file 01 that a NIM may have no built-in client authentication (UNVERIFIED there too). Keep `type: ClusterIP`, put a gateway in front, and add a NetworkPolicy.

Other operator resources worth knowing exist: `NIMPipeline` (several `NIMService`s as a group) and `NIMBuild` (prebuilds TensorRT-LLM engines for specific GPUs; the docs list "Local NIM Engine Builds" under advanced configuration).

## Section 3. The NeMo microservices through the operator's NeMo CRDs

*Gloss: each NeMo service has its own custom resource, and most of the work is standing up the databases and storage each one expects.*

**Read this first.** Every NeMo page in the operator's 3.1.2 docs carries this banner: "The NIM Operator is deprecating support for the NeMo Microservices CRDs and deployments in the next release. NeMo Microservices are transitioning to the NeMo Platform." The 3.1.3 release notes then say support "is deprecated"; no removal date is given. Treat everything in this section as maintenance knowledge for an existing install, not a starting point. Section 4 covers the way forward.

### What each resource does and what it needs

From the operator's NeMo prerequisites page (3.1.2), dependencies per service:

| Resource | Purpose | Dependencies |
|---|---|---|
| `NemoDatastore` | File and model storage with a Hugging Face Hub compatible API | PostgreSQL, MinIO (object storage), storage provisioner, database and object-store secrets |
| `NemoEntitystore` | Metadata for namespaces, projects, datasets, models | PostgreSQL, storage provisioner, DB user secret; requires Data Store |
| `NemoEvaluator` | Benchmarks and LLM-as-a-judge runs | PostgreSQL, DB user secret, Argo Workflows, Milvus; requires Data Store and Entity Store |
| `NemoCustomizer` | Fine-tuning jobs | PostgreSQL, storage provisioner, secrets (DB user, W&B API key), a ConfigMap for training and model downloads, OpenTelemetry, Volcano scheduler; requires Data Store, Entity Store and the separate NeMo Operator |
| `NemoGuardrail` | Safety checks in front of a model | PostgreSQL, OpenTelemetry, storage provisioner, and a NIM endpoint (for example a `NIMPipeline`) |

The separate **NeMo Operator** is only for Customizer training jobs and is installed from its own chart (example version 25.6.0 on that page):

```bash
helm fetch https://helm.ngc.nvidia.com/nvidia/nemo-microservices/charts/nemo-operator-${VERSION}.tgz \
  --username='$oauthtoken' --password=<NGC API key>
helm upgrade --install nemo-operator nemo-operator-${VERSION}.tgz -n nemo \
  --set controllerManager.manager.scheduler=volcano \
  --set imagePullSecrets[0].name=ngc-secret
```

The page's quick-start minimum is a single-node Linux cluster, cluster-admin, at least 200 GB free disk, and at least one A100 or H100 80 GB GPU. Dependencies are installed by an Ansible playbook in the operator repo (`test/e2e/nemo-dependencies`, check out the matching tag, edit `values.yaml`, run `ansible-playbook -c local -i localhost install.yaml`). NVIDIA labels these playbooks as for testing; they "may not suit production". Production means your own managed PostgreSQL, object storage, and so on. The same two secrets as Section 1 are needed in the `nemo` namespace.

### Example: NemoGuardrail

The docs page has no single complete manifest; the YAML below is assembled from its field reference (3.1.2), with a hosted endpoint as the model. Field names are the page's. Treat values as placeholders.

```yaml
apiVersion: apps.nvidia.com/v1alpha1
kind: NemoGuardrail
metadata:
  name: nemoguardrails-sample
  namespace: nemo
spec:
  configStore:
    pvc:
      name: pvc-guardrail-config
      create: true
      storageClass: <storage-class>
      volumeAccessMode: ReadWriteMany
      size: 1Gi
      subPath: guardrails-config-store
  nimEndpoint:
    baseURL: http://meta-llama3-8b-instruct.nim-service:8000/v1   # in-cluster NIM
    # for hosted models or NIM Proxy:
    # apiKeySecret: <nim-api-key-secret>
    # apiKeyKey: NIM_ENDPOINT_API_KEY
  expose:
    service:
      type: ClusterIP
      port: 8000
  image:
    repository: nvcr.io/nvidia/nemo-microservices/guardrails
    tag: "25.10"
    pullPolicy: IfNotPresent
    pullSecrets:
      - ngc-secret
  replicas: 1
  resources:
    limits:
      cpu: "1"
      ephemeral-storage: 10Gi
  userID: 1000
  groupID: 2000
```

Points worth knowing: the NIM endpoint must be OpenAI-compatible; the NIM Proxy is supported as an endpoint, but only one endpoint is supported. The page includes a PostgreSQL secret example (`guardrail-pg-existing-secret`) but never references it from the custom resource and documents no database field for Guardrails, so how Guardrails reaches PostgreSQL is UNVERIFIED. The docs say PostgreSQL stores guardrail configurations while the sample shows a PVC config store. Do not assume which one holds your configs without inspecting the pod.

```bash
kubectl apply -n nemo -f nemo-guardrail.yaml
kubectl describe nemoguardrails.apps.nvidia.com -n nemo
# Conditions: Ready=True ("Deployment is ready"), Failed=False;  State: Ready
```

Verify from a curl pod:

```bash
curl -X GET "http://nemoguardrails-sample.nemo:8000/v1/guardrail/configs"
# a fresh install returns an empty list: "data":[]
```

### Example: NemoEvaluator

The Evaluator page's sample is long; its documented required pieces, from the field reference, are below. The page itself warns of naming inconsistencies between sample and table (`argoWorkflows` versus `argoWorkFlows`, `entitystore` versus `entity`), so confirm with `kubectl explain nemoevaluator.spec` against your installed version.

```yaml
apiVersion: apps.nvidia.com/v1alpha1
kind: NemoEvaluator
metadata:
  name: nemoevaluator-sample
  namespace: nemo
spec:
  image:
    repository: nvcr.io/nvidia/nemo-microservices/evaluator
    tag: "<tag>"                      # UNVERIFIED: exact repository/tag, copy from the sample
    pullSecrets: [ngc-secret]
  evaluationImages:                   # required; harness images (lmEvalHarness, llmAsJudge, ...)
    lmEvalHarness: "<harness-image>"
  argoWorkflows:
    endpoint: http://argo-workflows-server.nemo.svc.cluster.local:2746
    serviceAccount: argo-workflows-executor
  vectorDB:
    endpoint: http://milvus.nemo.svc.cluster.local:19530
  datastore:
    endpoint: http://nemodatastore-sample.nemo.svc.cluster.local:8000
  entitystore:
    endpoint: http://nemoentitystore-sample.nemo.svc.cluster.local:8000
  databaseConfig:
    host: <postgres-host>
    port: 5432
    databaseName: <db>
    credentials:
      user: <user>
      secretName: evaluator-pg-existing-secret
      passwordKey: password
  expose:
    service:
      type: ClusterIP
      port: 8000
```

The endpoint addresses, service account name and harness image keys above are my placeholders; only the field names come from the page. The secret `evaluator-pg-existing-secret` with a password key is as the docs describe.

```bash
kubectl apply -n nemo -f nemo-evaluator.yaml
kubectl describe nemoevaluator.apps.nvidia.com -n nemo
# Ready=True, Failed=False, State: Ready
curl http://nemoevaluator-sample.nemo:8000/v1/evaluation/configs
# fresh install returns an empty list
```

`NemoCustomizer` and `NemoDatastore`/`NemoEntitystore` have their own pages (`customizer.html`, `data-store.html`, `entity-store.html`); I did not read them in full. UNVERIFIED: their field-level YAML.

## Section 4. What the sunset means, and the NeMo Platform / Helix path

*Gloss: the old product gets no new releases, the operator is dropping support for managing it, and the replacement is a different system with a different install.*

### What is confirmed

- NVIDIA's archived NeMo Microservices docs say it "will be sunset on October 1, 2026" with all new development moved to NeMo Platform. A search result for the NGC Helm chart page repeats the date and says there will be no new releases. The same sources say to contact your NVIDIA account team to discuss next steps; they give no technical migration recipe.
- The NIM Operator docs: deprecation announced in 3.1.1 notes, restated in 3.1.3 ("Support for managing NeMo Microservices CRDs and deployments is deprecated"). Removal date: not given. I could not find the text of any release that has removed the CRDs.
- Existing deployments keep running; nothing in the sources says they stop. But there are no new microservices releases, and the operator's NeMo support is deprecated, so you carry the security-patch and upgrade burden yourself. UNVERIFIED: whether NVIDIA will publish security fixes for the archived 25.x/26.3 images.

### What an existing deployment should do

1. Inventory: `kubectl get nemoguardrails,nemoevaluators,nemocustomizers,nemodatastores,nemoentitystores -A` and note versions and what depends on each.
2. Pin the NIM Operator at the version you run now, and read release notes before bumping. Upgrading may remove the NeMo reconcilers (UNVERIFIED that any release does).
3. Mirror the images you run now into your own registry (Section 5) before the NGC tags become hard to reach.
4. Decide per service: guardrails and evaluation are the likely candidates to move; the NIM serving layer is unaffected.

### The replacement: NeMo Platform / NeMo Helix

Facts from the Helix docs (docs.nvidia.com/nemo-helix, versions 0.5 to 0.10 listed, "latest" default):

- It is described as "an open source control plane for improving and hardening production agents", reached via REST API, CLI (`nemo`), Python SDK, plus a browser UI called NeMo Studio (alpha).
- A separate docs site, docs.nvidia.com/nemo-platform, has release notes including v0.5.0 dated 2026-09-04 and the operator docs link to it as the home for NeMo Platform. UNVERIFIED: the official statement that "NeMo Platform" was renamed "NeMo Helix". The sites overlap, one third-party page claims a rename, and the Helix home page I fetched does not use the phrase "NeMo Platform". Treat the two names as the same lineage until NVIDIA says so.
- It is a different architecture, not a CRD-for-CRD port. For example the Evaluator became "NeMo Helix Evals" with renamed config blocks (`evaluator:` to `evals:`) and no automatic migration of job history.

Install with Helm, from the Helix docs:

```bash
export NHX_NAMESPACE=nemo-helix
export NHX_HELM_RELEASE=nemo-helix
export NHX_HELM_CHART_VERSION=<chart-version>      # you must pin; no default given
export NGC_API_KEY=<your-ngc-api-key>

kubectl create namespace "$NHX_NAMESPACE"

kubectl create secret docker-registry nvcrimagepullsecret \
  --docker-server=nvcr.io --docker-username='$oauthtoken' \
  --docker-password="$NGC_API_KEY" --namespace "$NHX_NAMESPACE"
kubectl create secret generic ngc-api \
  --from-literal=NGC_API_KEY="$NGC_API_KEY" --namespace "$NHX_NAMESPACE"

helm repo add nemo-helix https://helm.ngc.nvidia.com/nvidia/nemo-helix \
  --username '$oauthtoken' --password "$NGC_API_KEY"
helm repo update nemo-helix
helm show values nemo-helix/nemo-helix --version "$NHX_HELM_CHART_VERSION" > values.yaml
# values.yaml: existingSecret: ngc-api ; imagePullSecrets: [{name: nvcrimagepullsecret}]

helm upgrade --install "$NHX_HELM_RELEASE" nemo-helix/nemo-helix \
  --version "$NHX_HELM_CHART_VERSION" -n "$NHX_NAMESPACE" --create-namespace \
  -f values.yaml --wait --timeout 20m
```

The chart is `nemo-helix/nemo-helix`; a release-candidate chart is at `oci://ghcr.io/nvidia-nemo/nemo-helix/nemo-helix`. The docs say install takes about 10 minutes and do not print sample output. Verify:

```bash
kubectl get pods -n nemo-helix
kubectl rollout status deployment/nemo-helix-api -n nemo-helix --timeout=10m
kubectl -n nemo-helix port-forward svc/nemo-helix-api 8080:8080 &
curl -sf http://localhost:8080/health/ready
nemo config set --base-url http://localhost:8080
nemo workspaces list
```

Prerequisites on the Helix pages: `kubectl`, Helm 3, permission to create cluster-scoped resources, ReadWriteMany storage for shared jobs storage, ingress or Gateway API, images from `nvcr.io/nvidia/nemo-helix/...` (for example `nhx-api`). Separate pages cover database setup, Milvus, Volcano, OpenShift and backup. The Kubernetes minimum version is not stated on the prerequisites page.

### Which parts still need a GPU

The Helix system-requirements page says GPU requirements "apply only when you run local model or GPU-accelerated workloads", and that local provider workflows (hosted OpenRouter, OpenAI, Anthropic, Gemini, NVIDIA Build, Ollama, or any OpenAI-compatible endpoint) need no local GPU. For local GPU work it asks for a data-centre GPU with at least 40 GB VRAM (80 GB recommended; A100 80GB, H100 80GB and B200 meet it), CUDA 13 or later, an R580-branch or newer driver, Linux x86_64 only. It does not name which Helix components need a GPU, so which pods in the chart request `nvidia.com/gpu` is UNVERIFIED; read your rendered `values.yaml`. In the older microservices (file 02) the same split held: Customizer and local model serving need GPUs; Data Store, Entity Store, Guardrails and Evaluator do not, because the models they call run as separate NIMs.

## Section 5. Disconnected and air-gapped installs

*Gloss: three things have to be inside the fence before it works: the container images, the model files, and the Helm charts.*

### What the operator docs actually say

The operator's air-gapped page covers the model cache and proxying. It does not give image-mirroring steps (I read it for that purpose). Documented there:

- Copying model files onto a PVC yourself: NIM containers run as non-root, defaults `spec.userID: 1000` and `spec.groupID: 2000`. Make files readable by those IDs, or set matching `spec.userID` and `spec.groupID` on both the `NIMCache` and `NIMService`. Many NFS provisioners do not honour `fsGroup`, so set ownership by hand. Permission errors surface in the NIM Service status and pod events.
- `spec.authSecret` on a `NIMService` is optional if every model is pre-cached and the NIM never contacts NGC or a credentialed mirror; the operator then does not inject `NGC_API_KEY`.
- Proxy support via `spec.proxy` on both cache job and service: `httpsProxy`, `httpProxy`, `noProxy`, and `certConfigMap` (a ConfigMap of CA certificates in the namespace, created with `kubectl create configmap -n nim-service ca-certs --from-file=<cert-file>`).
- The page also mentions mirrored local model registries as an option and points to the caching pages. UNVERIFIED: the details of that option.

### Mirroring images to Harbor (a procedure, mostly mine)

The commands are standard tooling, not operator-specific; the list of images is what you must assemble.

```bash
# on a connected machine
echo "$NGC_API_KEY" | skopeo login nvcr.io -u '$oauthtoken' --password-stdin
skopeo copy --all docker://nvcr.io/nim/meta/llama-3.1-8b-instruct:1.3.3 \
  dir:./mirror/llama-3.1-8b-instruct-1.3.3
# carry ./mirror across the gap, then on the inside:
skopeo copy --dest-tls-verify=true \
  dir:./mirror/llama-3.1-8b-instruct-1.3.3 \
  docker://harbor.example.internal/nvidia/nim/meta/llama-3.1-8b-instruct:1.3.3
```

Images to mirror, at minimum: the GPU Operator and its operand images (listed in its chart values), the NIM Operator image (from the chart; `helm template` then grep `image:`), the NIM image, and the `modelPuller` image (in the NIMCache sample it is the NIM image itself). For NeMo: the service images and the Data Store HuggingFace-CLI puller image shown in the cache sample (`nds-v2-huggingface-cli`). Charts: `helm pull nvidia/k8s-nim-operator --version 3.1.2` and push to Harbor's OCI registry. Then override image repositories in chart values and set `spec.image.repository` and `pullSecrets` to the Harbor path.

### Pre-staging the model cache

The two routes that need no NGC access from inside:

1. Fill the cache once on a connected cluster (a normal `NIMCache`), then copy the PVC contents (`tar` over a pod, or the storage array's replication) to the disconnected cluster, and create the `NIMCache` there pointing at a pre-created PVC (`create: false`, `name:`). UNVERIFIED: whether the operator then marks that cache `Ready` without running its job; test it, and check how the status behaves.
2. Use the NIM's own tools, described in file 01: `download-to-cache` and `create-model-store` produce a transferable directory. How these tie to a `NIMCache` object is UNVERIFIED.

### NGC access

Downloading is the only phase that needs NGC. Image pulls need the NGC API key as the `$oauthtoken` password. Model downloads need the same key as `NGC_API_KEY`. Helix's `helm repo add` also needs the key. Inside the fence, replace them with Harbor robot credentials, and use `authSecret` only where something still reaches out. The Helix docs say they do not cover air-gapped or private registries, so UNVERIFIED: Helix air-gap support beyond "override image registries in values".

## Section 6. VMware VKS / Tanzu

*Gloss: the GPU must first be presented to the worker VM by vSphere before any of the above can see it.*

Little of this is NVIDIA-documented for the NIM Operator specifically; my searches found nothing on "NIM Operator on VKS" and the NIM Operator install page lists TKG among platforms covered by the generic Helm install ("Any Kubernetes Platform: TKG, EKS, AKS, OKE, GKE"). From VMware and partner sources, which are older (vSphere 7/8 era, TKGS naming) and should be rechecked against current VCF documentation:

- A vSphere admin creates a custom VM class carrying a vGPU profile (or, alternatively, uses Dynamic DirectPath I/O passthrough, which dedicates the whole GPU to one worker VM; vGPU lets several VMs share one).
- The class must be added to the vSphere Namespace (VM Service tile, Manage VM Classes) before a cluster spec can use it.
- The NVIDIA vGPU host driver must be installed on the ESXi host first; the guest driver and the GPU Operator then run inside the worker nodes.
- Caveats from the same sources: a three-zone Supervisor does not support VMs with vGPU; VMs with vGPU managed by VM Service are powered off when the host enters maintenance mode (so a drain is not enough; plan capacity).
- vGPU needs an NVIDIA licence server, and the GPU Operator has vGPU-specific settings. UNVERIFIED here: the exact GPU Operator values for vGPU guests (consult NVIDIA's GPU Operator vGPU documentation and the AI Enterprise support matrix).
- Implication for `NIMService`: `nvidia.com/gpu: 1` then means one vGPU slice. An LLM that needs the whole 80 GB card needs a profile that exposes it; a small slice will fail with out-of-memory at profile load.

## Prove it works

Positive checks, in order:

```bash
kubectl get pods -n gpu-operator                      # all Running/Completed
kubectl get pods -n nim-operator                      # controller 1/1 Running
kubectl get nimcaches.apps.nvidia.com -n nim-service  # STATUS Ready
kubectl get nimservices.apps.nvidia.com -n nim-service # STATUS Ready
kubectl exec -n nim-service deploy/meta-llama3-8b-instruct -- nvidia-smi   # UNVERIFIED output format; shows model process on GPU
curl -s http://meta-llama3-8b-instruct.nim-service:8000/v1/health/ready    # from a curl pod
curl -s http://meta-llama3-8b-instruct.nim-service:8000/v1/models          # lists the model
```

(`/v1/health/ready` and `/v1/models` are NIM paths from file 01.)

Negative checks, which are the ones that catch silent failures:

1. **Wrong model name**: request `"model": "does-not-exist"`; expect an error response, not a completion. A success means you are not talking to the server you think.
2. **Cache reuse, not re-download**: delete the NIM pod (`kubectl delete pod -n nim-service -l app=<name>`; label UNVERIFIED, use `kubectl get pods --show-labels`). It should return to `Ready` in minutes without a fresh download; check pod logs for no "downloading" lines.
3. **Image pull secret really works**: temporarily point the service at a name that does not exist in your mirror; expect `ImagePullBackOff`, proving pulls go through the registry you intend (in an air-gapped cluster, also confirm there is no route to `nvcr.io`: `kubectl run -it --rm t --image=curlimages/curl -- curl -m 5 -sI https://nvcr.io` should time out).
4. **No GPU, no start**: scale a deployment requesting `nvidia.com/gpu: 1` onto a cluster with none; expect a Pending pod with an "Insufficient nvidia.com/gpu" event, not a CPU fallback.
5. **Not exposed**: from outside the cluster network, the service address must not respond. The NIM may accept unauthenticated requests.
6. **Auth-less air gap**: remove `authSecret`, delete the pod, and confirm it still starts. If it fails, something is still reaching NGC.
7. **Guardrails block something**: with a configured guardrail, send a request your policy must refuse and one it must allow. An empty config list (`"data":[]`) means guardrails are installed but enforcing nothing.

## What goes wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `NIMCache` stuck `NotReady` or `InProgress` | Puller image still downloading, or slow model download | `kubectl describe nimcache`, `kubectl get jobs`, check job pod logs; wait before intervening (the docs say this can resolve on its own) |
| `NIMCache` `Failed` | Wrong or missing `ngc-api-secret`, key lacking entitlement, or no egress | Re-create secret with a key that can access the model; test the key with a manual pull |
| Pod `ImagePullBackOff` on `nvcr.io` | `ngc-secret` missing in that namespace, or username not literally `$oauthtoken` | Re-create in the correct namespace; keep single quotes |
| PVC is `RWO` when you asked for `RWX` | Storage class cannot do RWX (the docs' own example shows this) | Use an RWX-capable class, or accept one pod per cache |
| Pod `Pending`, `Insufficient nvidia.com/gpu` | GPU Operator not ready, or all GPUs allocated | Check `gpu-operator` pods and node allocatable |
| NIM starts, then exits with permission errors on cache | Files owned by a different UID than `userID: 1000` / `groupID: 2000`; NFS ignoring `fsGroup` | `chown` on the share, or set matching IDs on both cache and service |
| Profile load fails or out-of-memory | Auto-selected profile needs more VRAM than the GPU (or vGPU slice) offers | Check `.status.profiles`; choose a smaller profile or more GPUs per replica |
| Deleting the `NIMCache` wiped the model | `create: true` means the operator owns and deletes the PVC | Pre-create the PVC and use `create: false` for long-lived caches |
| NeMo CR stays not ready | Missing PostgreSQL secret, Data/Entity Store not up, Argo or Milvus missing for Evaluator | Deploy dependencies in the order of the table; check events |
| Evaluator spec rejected on apply | Field-name inconsistency in docs (`argoWorkflows` vs `argoWorkFlows`) | `kubectl explain nemoevaluator.spec` against the installed CRD |
| Helix pods pending after install | Install takes about 10 minutes; RWX storage or database not ready | Wait, then check PVC binding and the database setup page |
| Air-gapped pod tries to contact NGC | Image or model reference points to NGC; `authSecret` set but cache not complete | Rewrite image paths to Harbor; verify cache `Ready` before enabling |

## Questions to ask whoever owns the deployment

1. Which operator chart version is installed, and was it chosen with the NeMo deprecation in mind?
2. Are any `Nemo*` custom resources in use today? Which services depend on them?
3. Where do the PostgreSQL, object storage, Argo and Milvus dependencies live, and who backs them up? Were they created by the test Ansible playbooks?
4. What is the storage class, can it do ReadWriteMany, and who owns the cache PVC lifecycle?
5. Is the NGC key a personal key or a service key? Who rotates it, and which namespaces hold copies?
6. Is there a mirror of every image in use, including the model puller and operand images, and how is it refreshed?
7. How are caches pre-staged, and what is the process for adding a model to a disconnected cluster?
8. How is client access to the NIM controlled, given the NIM itself may not authenticate callers?
9. On VKS: are GPUs vGPU or passthrough, what profile sizes are in the VM classes, and who holds the vGPU licence server?
10. What is the plan, and the date, for moving off the NeMo Microservices images toward NeMo Helix (or dropping the dependency)?

## Check yourself

1. Which two secrets are needed to get a model from NGC onto a node, and what is each for?
2. Why does a `NIMService` wait for a `NIMCache`, and what happens to the cache if the operator created the PVC and you delete the `NIMCache`?
3. A `NIMCache` is `Ready` but the pod fails with permission errors. What is the first thing you check?
4. Which NeMo resources depend on both Data Store and Entity Store?
5. What does "deprecated" mean in the operator, compared with "sunset" for the NeMo Microservices product?
6. Name one NeMo Helix workload that does not need a local GPU, and the minimum VRAM it asks for when it does.
7. For an air-gapped cluster, list the three kinds of artefact you must move inside.
8. Why can a vGPU-backed `nvidia.com/gpu: 1` still fail to load a large model?

## References

Fetched or searched 2026-11-18 unless noted.

- NIM Operator documentation home: https://docs.nvidia.com/nim-operator/latest/index.html
- Install (chart 3.1.2, GPU Operator commands): https://docs.nvidia.com/nim-operator/latest/install.html
- NIMCache reference: https://docs.nvidia.com/nim-operator/latest/cache.html
- NIMService reference: https://docs.nvidia.com/nim-operator/latest/service.html
- Air-gapped environments: https://docs.nvidia.com/nim-operator/latest/air-gap.html
- Release notes (v3.1.4 latest, deprecation notice): https://docs.nvidia.com/nim-operator/latest/release-notes.html
- GitHub repository and releases API (v3.1.3 dated 2026-10-28): https://github.com/NVIDIA/k8s-nim-operator
- NeMo quick start (3.1.2, deprecation banner): https://docs.nvidia.com/nim-operator/3.1.2/deploy-nemo-microservices.html
- NeMo prerequisites (3.1.2): https://docs.nvidia.com/nim-operator/3.1.2/nemo-prerequisites.html
- NemoGuardrail (3.1.2): https://docs.nvidia.com/nim-operator/3.1.2/guardrail.html
- NemoEvaluator (3.1.2): https://docs.nvidia.com/nim-operator/3.1.2/evaluator.html
- NeMo Helix docs index: https://docs.nvidia.com/nemo-helix/latest/llms.txt
- Helix Helm install: https://docs.nvidia.com/nemo-helix/latest/documentation/kubernetes-deployment/setup/helm/install.md
- Helix prerequisites: https://docs.nvidia.com/nemo-helix/latest/documentation/kubernetes-deployment/setup/helm/prerequisites.md
- Helix system requirements: https://docs.nvidia.com/nemo-helix/latest/documentation/reference/system-requirements.md
- Helix Evals upgrade page: https://docs.nvidia.com/nemo-helix/latest/documentation/evaluate-models/upgrading-from-evaluator.md
- NeMo Platform release notes (v0.5.0, 2026-09-04): https://docs.nvidia.com/nemo-platform/latest/documentation/reference/release-notes/current-release
- Archived NeMo Microservices docs (sunset notice): https://docs.nvidia.com/nemo/microservices/latest/about/release-notes/index.html
- VMware and partner GPU-on-Tanzu material (older, recheck): https://williamlam.com/2023/10/nvidia-gpu-with-dynamic-directpath-io-passthrough-to-tanzu-kubernetes-grid-tkg-cluster-using-vsphere-with-tanzu.html and https://docs.vmware.com/en/VMware-vSphere/8.0/vsphere-with-tanzu-tkg/GUID-4FF388B6-CE4C-433C-AD0A-E74890E9CA58.html
- Related files in this repo: 01-nvidia-nim.md, 02-nemo-microservices.md, 10-vmware-tanzu-kubernetes.md, 12-harbor-podman-images.md
