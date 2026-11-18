# Target-state reference: NIM LLMs with the NIM Operator

Date: 2026-11-19. This is a reference implementation, not a deployed system. Nothing here was applied to a cluster. The examples build with `kubectl kustomize` (client-side, no cluster), and the rendered output of all three overlays validates against the operator's own CRD schemas with unknown fields rejected (a throwaway check; zero errors, and a deliberately misspelt field was caught). Background: [03-nvidia-recommended-deployment](03-nvidia-recommended-deployment.md), [05-gap-analysis](05-gap-analysis.md), [23-nemo-nim-operator-deployment](../prereading/23-nemo-nim-operator-deployment.md).

**Source tag used: `NVIDIA/k8s-nim-operator` v3.1.4** (latest release on 2026-11-19; v3.1.3 precedes it). Every field in the examples exists in `api/apps/v1alpha1/*_types.go` and in the CRDs under `config/crd/bases/` at that tag. Links below are pinned to the tag.

## The plain version

Two big language models need to run on GPU servers in three places: a development area, a test area and the real one. None of them can reach the internet.

Think of a hospital pharmacy. The drugs (model files) arrive in bulk, are checked, and go on a shelf (a storage volume). Wards (the running models) never fetch drugs themselves. They only read from the shelf, and only one named door (the gateway) may send them requests.

The operator needs two order forms per model. The first says "stock this shelf with exactly this version and this variant". The second says "run this model from that shelf on these GPUs, and tell me when it is ready". The git repository holds those forms. ArgoCD, the clerk, files them and watches the status. Stocking can take hours and fills a shelf worth a terabyte or more, so the clerk is told to file the shelf forms first, wait until the shelf reports "ready", and never throw a shelf away by accident.

All three areas get the same version. A change is made once, tried in development, then test, then production, each by a reviewed merge request. The only differences between areas are sizes, storage names and, in development only, possibly a different model variant because the hardware is smaller. That last difference is the weak spot: development cannot show how the production variant behaves, so test must be a faithful copy of production.

The surprises from reading the operator's code, such as the fixed rollout strategy and the health-condition names, are in "Key findings" near the end.

## File map

| File | Purpose |
|---|---|
| `examples/nim-operator/base/nimcache-glm-5-2.yaml` | Cache for the ~750B FP8 model |
| `examples/nim-operator/base/nimcache-nemotron-3-super.yaml` | Cache for Nemotron 3 Super 120B-A12B |
| `examples/nim-operator/base/nimservice-glm-5-2.yaml` | Service, 8 GPUs, TP8, one node |
| `examples/nim-operator/base/nimservice-nemotron-3-super.yaml` | Service for Nemotron |
| `examples/nim-operator/base/networkpolicy.yaml` | Gateway-only ingress, Prometheus scrape, DNS-only egress |
| `examples/nim-operator/base/kustomization.yaml` | Ties the base together, sets namespace `nim-service` |
| `examples/nim-operator/overlays/{dev,qa,prod}/` | Per-environment patches |
| `examples/argocd/nim-health.lua.md` | Health checks, sync waves, prune/delete protection |
| `examples/argocd/applicationset.yaml` | One Application per environment |

All image repositories, tags and profile ids in the examples are placeholders (see "What I could not verify"). Do not apply them as they are.

## Walkthrough: the base

### NIMCache ([`nimcache_types.go`](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimcache_types.go))

| Field | Value and why |
|---|---|
| `spec.source.ngc.modelPuller` | The mirrored NIM image in Harbor. Immutable (CEL rule, [L123-L124](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimcache_types.go#L123-L124)), so an image change means a new `NIMCache`, not an edit. The tag matches the service tag. |
| `spec.source.ngc.pullSecret` | Harbor pull credentials for the puller image ([L126](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimcache_types.go#L126)). |
| `spec.source.ngc.authSecret` | NGC key, optional ([L121](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimcache_types.go#L121)). Present in base so DEV can download; QA and PROD remove it by patch. |
| `spec.source.ngc.model.profiles` | The pinned profile id. When set, the other selectors (`engine`, `precision`, `tensorParallelism`, `gpus`) are ignored ([ModelSpec L134-L137](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimcache_types.go#L134-L137)). The job is run with `--profiles <ids>` ([nimcache_controller.go L1440](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/internal/controller/nimcache_controller.go#L1440)). |
| `spec.storage.pvc.{create,storageClass,size,volumeAccessMode}` | The operator-made PVC ([common_types.go L494-L511](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/common_types.go#L494-L511)). ReadWriteMany so the cache job and the serving pod can both mount it. 1536Gi for the large model (weights ~750 GB plus headroom), 512Gi for Nemotron. Both are my estimates. |
| `spec.resources.{cpu,memory}` | Caching job only ([L40](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimcache_types.go#L40)). The job asks for no GPU. |
| `spec.nodeSelector`, `spec.tolerations` | The job lands on GPU-pool nodes. If `nodeSelector` is empty the operator defaults to the NFD label `feature.node.kubernetes.io/pci-10de.present=true` ([GetNodeSelectors L321](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimcache_types.go#L321)). |
| `spec.userID` / `spec.groupID` | 1000 / 2000, the operator defaults, written down so a pre-staged copy can be given the right ownership. |
| annotations | `sync-wave: "0"` and `sync-options: Prune=false,Delete=false`; see the ArgoCD file. |

### NIMService ([`nimservice_types.go`](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimservice_types.go))

| Field | Value and why |
|---|---|
| `spec.image.{repository,tag,pullPolicy,pullSecrets}` | Harbor path, pinned tag, `IfNotPresent` ([Image, common_types.go L219-L224](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/common_types.go#L219-L224)). `repository` and `tag` are required. |
| `spec.storage.nimCache.{name,profile}` | Links to the cache and pins the profile ([NIMCacheVolSpec L197-L200](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimservice_types.go#L197-L200)). The controller turns it into `NIM_MODEL_PROFILE` ([nimservice.go L406-L441](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/internal/controller/platform/standalone/nimservice.go#L406-L441)). |
| `spec.storage.readOnly` | The serving pod must not write to the cache. |
| `spec.storage.sharedMemorySizeLimit` | Size of the `/dev/shm` emptyDir ([L261](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimservice_types.go#L261)). 64Gi and 32Gi are guesses. |
| `spec.resources` | `nvidia.com/gpu: 8` set explicitly. If left out and the cache is an optimized NIM, the operator reads TP from the cached profile and assigns that many GPUs ([addGPUResources L1326](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/internal/controller/platform/standalone/nimservice.go#L1326)). Setting it explicitly makes the manifest self-describing, but the number must match the profile. |
| `spec.nodeSelector`, `spec.tolerations` | Pin to H200 nodes (`nvidia.com/gpu.product`, a GPU Feature Discovery label; check the exact value) and tolerate the GPU taint. |
| `spec.labels` | Merged into the pod and Service labels ([GetServiceLabels L568-L575](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimservice_types.go#L568-L575)); the NetworkPolicy selects on it. Do not set `app.kubernetes.io/part-of` here; the operator sets it. |
| `spec.startupProbe` | A wrapper `{enabled, probe}` ([common_types.go L450-L453](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/common_types.go#L450-L453)). The default is a 30 s delay, 10 s period and 120 failures, about 21 minutes ([L734-L748](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimservice_types.go#L734-L748)). Raised to 60 s + 360 x 10 s (about 61 minutes) for the large model and about 31 minutes for Nemotron. Starting points; measure the real cold start. |
| `spec.expose.service.{type,port}` | ClusterIP on 8000; the gateway is the only caller, so no ingress ([Service L149-L173](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/common_types.go#L149-L173)). |
| `spec.metrics.{enabled,serviceMonitor}` | The operator renders a `ServiceMonitor` scraping `/v1/metrics` on the `api` port ([GetServiceMonitorParams L1765-L1799](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimservice_types.go#L1765-L1799)). Needs the Prometheus Operator CRDs. `additionalLabels` must match what your Prometheus selects on. |
| `spec.replicas` | 1 in base. One replica of the large model is a whole 8-GPU node. |
| `spec.authSecret` | Omitted: with a warm cache the NIM does not contact NGC. |

`multiNode` is not set: the large model is single-node by the stated profile, so no LeaderWorkerSet is needed.

### NetworkPolicy (`base/networkpolicy.yaml`)

- Ingress to port 8000 on pods labelled `app.kubernetes.io/component: nim-llm`, from pods labelled `app.kubernetes.io/name: llm-gateway` in namespace `llm-gateway`, and from Prometheus in `monitoring`. In each rule `namespaceSelector` and `podSelector` sit in the same `from` entry, so they are ANDed. Splitting them into two entries would admit the whole namespace. The labels are placeholders for local conventions.
- Metrics and API share port 8000 (`/v1/metrics`), so one port is enough. The separate `metricsPort` applies only to Triton-based NIMs ([common_types.go L165-L170](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/common_types.go#L165-L170)) and is not set.
- A second policy allows egress to CoreDNS only. In the air gap a warm NIM needs nothing else. The cache job pod does not carry the `nim-llm` label, so it is not covered by these policies; if you add a namespace default-deny, the DEV cache job needs its own egress rule to NGC.

### Kustomization

`namespace: nim-service` and the five resources. Image tags live only in the base manifests, never in overlays. Promotion changes the base.

## Walkthrough: overlays

| | DEV | QA | PROD |
|---|---|---|---|
| Large-model replicas | 1 | 1 | 1 |
| Nemotron replicas | 1 | 1 | 2 (`patch-replicas-nemotron.yaml`) |
| Cache | operator-made PVC, NGC allowed (`authSecret` kept) | pre-staged PVC, no `authSecret` | same as QA |
| Storage class | `dev-rwx-fast` | `qa-rwx-fast` | `prod-rwx-fast` |
| Sizes (large / Nemotron) | 1536Gi / 512Gi | same | same |
| Profile | DEV override (optional, below) | base | base |
| Image tag | base | base | base |

Keep QA's storage class, size and hardware the same as PROD's. The base is the only place a tag or profile id lives.

**DEV profile override and its risk.** The DEV overlay includes `patch-profile-glm-cache.yaml` and `patch-profile-glm-service.yaml`. They swap in a profile for different GPUs (example: 4x B200 NVFP4 TP4) and change the GPU count and node selector. Delete them if DEV has 8x H200. The risk: DEV then runs a different engine configuration and precision from PROD. It proves manifests, probes, policies, Harbor pulls and the gateway path. It does not prove memory fit, throughput, cold-start time or output quality for the PROD profile. Rules I would hold to: QA runs the exact PROD profile on PROD-class hardware; no model sign-off from DEV results; the DEV profile id is recorded in the MR so reviewers see the divergence.

**QA and PROD cache patches.** Each patch sets `create: false` and `name`, and removes `storageClass`, `size` and `authSecret`. `pvc-prestaged.yaml` declares the PVCs with sync-wave `-1` and `Prune=false,Delete=false`. Declaring the volume in git and filling it out of band is how pre-staging fits GitOps. UNVERIFIED: whether the operator then reaches `Ready` (see below). The patch file headers state the fallback.

**JSON6902 patches** are used because the kinds are CRDs with no Kustomize schema, so strategic merge would replace lists wholesale and could not target list items.

## How a model upgrade flows

1. **Mirror first.** On the connected side, pull the new NIM image and stage the new weights. Push the image to Harbor and put the weights on a new PVC in each environment. Do this before any MR; production never downloads.
2. **MR 1 to `main` (DEV).** In `base/`, change the image tag in the `NIMService`, the `modelPuller` tag in the `NIMCache`, and the profile id in both (cache `model.profiles`, service `storage.nimCache.profile`). Because `modelPuller` is immutable, the safe pattern is a new cache name (for example `glm-5-2-v2`) with the service pointing at it, not an edit in place. Include any DEV profile patch change. DEV auto-syncs.
3. **Verify in DEV.** `NIMCache` and `NIMService` both Healthy (Lua checks), a request through the gateway, metrics visible.
4. **MR 2, fast-forward `qa`.** The ApplicationSet tracks `main` for DEV, `qa` for QA and `prod` for PROD, so a merge to `main` cannot reach QA or PROD by itself. QA syncs manually.
5. **QA soak.** Same hardware and profile as PROD. Run acceptance prompts, measure cold start, force a restart to confirm the startup probe holds.
6. **MR 3, fast-forward `prod`.** Sync in a change window.
7. **Outage plan.** The operator's Deployment template uses `maxSurge: 0` (key finding 3), so a single-replica 8-GPU service has an outage while the pod is replaced. Plan the window, or run two replicas on two 8-GPU nodes.
8. **Rollback.** Revert the MR and sync. The old cache PVC survives because of `Prune=false,Delete=false`, and the old image is still in Harbor. Keep both until the new version has soaked.

## Air-gap prep checklist

- [ ] Operator chart `k8s-nim-operator` pulled to Harbor OCI at a pinned version; operator image and dependency images mirrored (`helm template`, grep `image:`).
- [ ] GPU Operator and its operand images mirrored (GPUs must be exposed before the NIM Operator is useful).
- [ ] Prometheus Operator CRDs present (the operator renders a `ServiceMonitor` when `metrics.enabled: true`).
- [ ] LeaderWorkerSet only if a multi-node profile is ever used; not needed here.
- [ ] Both NIM images copied with `skopeo copy --all` to `harbor.example.internal/nim/...`; digests recorded.
- [ ] Pull secret `harbor-pull` (robot account, pull-only) in the `nim-service` namespace of each cluster. No NGC key in QA or PROD.
- [ ] Weights staged: fill one connected cache with the exact pinned profile, then copy it to each environment's PVC. Check the size against the PVC request. Set ownership to 1000:2000 by hand if the NFS provisioner ignores `fsGroup`.
- [ ] Record the profile id and a cache listing with checksums in the MR so QA and PROD can be compared with DEV.
- [ ] Storage class: RWX, read performance tested with a ~750 GB model, reclaim policy `Retain` for cache volumes.
- [ ] GPU node label values and taint key confirmed (`nvidia.com/gpu.product`, `nvidia.com/gpu`).
- [ ] File-descriptor limits on GPU nodes raised (03 notes a "Too many open files" issue for models over ~49B parameters).
- [ ] ArgoCD: health checks in `argocd-cm`, the ApplicationSet, a project that permits `apps.nvidia.com` kinds, GitLab repo credentials, and the `qa` and `prod` branches protected. Ansible stops at the GPU Operator and NIM Operator installs.
- [ ] Gateway namespace and pod labels match the NetworkPolicy; Prometheus labels match both the NetworkPolicy and the `ServiceMonitor` `additionalLabels`.

## What I could not verify

- UNVERIFIED: real NIM image repositories and tags for GLM 5.2 and Nemotron 3 Super. The values (`.../zai-org/glm-5.2:1.0.0`, `.../nvidia/nemotron-3-super-120b-a12b:1.0.0`) are placeholders.
- UNVERIFIED: the real profile ids (the `REPLACE_WITH_...` strings). Get them from `list-model-profiles` in the image, or `kubectl describe nimcache` after a first cache run.
- UNVERIFIED: that a pre-filled PVC with `create: false` and no NGC key lets the operator reach `NIMCache` state `Ready`. The code renders a caching Job whose command is `download-to-cache` ([nimcache_controller.go L1377](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/internal/controller/nimcache_controller.go#L1377)); I did not trace whether that succeeds offline on a populated store. Fallback: skip `NIMCache` and set `NIMService` `spec.storage.pvc.name` to the PVC (the controller supports an existing PVC, [nimservice.go L418-L420](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/internal/controller/platform/standalone/nimservice.go#L418-L420)), pinning the profile with `NIM_MODEL_PROFILE` in `spec.env`.
- UNVERIFIED: PVC sizes (1536Gi, 512Gi), shared-memory sizes (64Gi, 32Gi), CPU and memory requests, and the GPU count for Nemotron 3 Super (2 assumed; it must equal the pinned profile's TP).
- UNVERIFIED: that the H200 FP8 TP8 and 4x B200 profiles exist with the precision assumed (carried over from 03).
- UNVERIFIED: the Lua health scripts. No Lua interpreter was available, and I did not run `argocd admin settings resource-overrides health` on sample objects.
- UNVERIFIED: `templatePatch` in the ApplicationSet on the installed ArgoCD version (documented, but the minimum version is not confirmed here).
- UNVERIFIED: whether VKS supports the operator, RWX storage at this size, and the NetworkPolicy semantics assumed (including kubelet probes passing under the policy).
- UNVERIFIED: whether digest pinning (`tag: sha256:...` or a digest in `repository`) renders correctly. Both fields are plain strings; I did not trace how the operator joins them.
- UNVERIFIED: the exact rollout behaviour with `maxUnavailable: 25%` and `maxSurge: 0` on one replica. I infer an in-place replacement with an outage; test in QA.

## Key findings

1. **`NIMService` conditions are `Ready` and `Failed`, not `NIM_SERVICE_READY`.** The constants at [nimservice_types.go L54-L57](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimservice_types.go#L54-L57) are not used by the controller in v3.1.4; use `status.state` plus those two types. `NIMCache` does use `NIM_CACHE_*` types, but `status.state` is the cleaner signal.
2. **Profile pinning has two places**: `spec.source.ngc.model.profiles` on the cache and `spec.storage.nimCache.profile` on the service (which becomes `NIM_MODEL_PROFILE`). They must carry the same id.
3. **The rollout strategy is fixed.** The Deployment template hard-codes `RollingUpdate`, `maxSurge: 0`, `maxUnavailable: 25%` ([manifests/deployment.yaml L18-L22](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/manifests/deployment.yaml#L18-L22)) and `NIMServiceSpec` has no field to change it. This answers the question 03 left open: no spare 8 GPUs are needed, but an upgrade is an outage for a single replica.
4. **The operator-created PVC is owned by the `NIMCache`** (`SetControllerReference` in [nimcache_controller.go L569](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/internal/controller/nimcache_controller.go#L569)), so deleting the cache deletes the weights. That is why `Prune=false,Delete=false` goes on the cache, and why QA and PROD declare their PVCs separately.
5. **Defaults to override:** the startup probe allows only about 21 minutes, and the cache job always runs even for a pre-filled PVC (not yet shown to succeed offline). Both matter more for a ~750 GB model than for the small models in NVIDIA's examples.

## References

- Operator source, tag v3.1.4: https://github.com/NVIDIA/k8s-nim-operator/tree/v3.1.4
- API types: https://github.com/NVIDIA/k8s-nim-operator/tree/v3.1.4/api/apps/v1alpha1
- CRDs: https://github.com/NVIDIA/k8s-nim-operator/tree/v3.1.4/config/crd/bases
- Rendered manifest templates (deployment, service, servicemonitor): https://github.com/NVIDIA/k8s-nim-operator/tree/v3.1.4/manifests
- Controllers: https://github.com/NVIDIA/k8s-nim-operator/tree/v3.1.4/internal/controller
- Operator releases: https://github.com/NVIDIA/k8s-nim-operator/releases
- ArgoCD sync options (Prune=false, Delete=false): https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/
- ArgoCD sync waves: https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/
- ArgoCD resource health customization: https://argo-cd.readthedocs.io/en/stable/operator-manual/health/
- ArgoCD ApplicationSet `templatePatch`: https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Template/
- `argocd admin settings resource-overrides health`: https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd_admin_settings_resource-overrides_health/
- Local: [03](03-nvidia-recommended-deployment.md), [05](05-gap-analysis.md), [23](../prereading/23-nemo-nim-operator-deployment.md)
