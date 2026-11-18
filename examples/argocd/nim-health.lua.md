# ArgoCD health checks for `NIMCache` and `NIMService`

ArgoCD ships no health check for `apps.nvidia.com` resources (I looked in `argoproj/argo-cd` `resource_customizations` on 2026-11-19 and found no `apps.nvidia.com` or `nim` directory). Without one, ArgoCD reports an unknown CRD as Healthy as soon as it exists, so sync waves would not wait for the model cache to finish. These checks make the wave order real.

Status values below come from `k8s-nim-operator` **v3.1.4**:

| Kind | Field | Values | Source |
|---|---|---|---|
| `NIMCache` | `status.state` | `Ready`, `Failed`, `NotReady`, `PVC-Created`, `Started`, `InProgress`, `Pending` | [nimcache_types.go L209-L222](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimcache_types.go#L209-L222) |
| `NIMCache` | `status.conditions[].type` | `NIM_CACHE_JOB_CREATED`, `NIM_CACHE_JOB_COMPLETED`, `NIM_CACHE_JOB_PENDING`, `NIM_CACHE_PVC_CREATED`, `NIM_CACHE_RECONCILE_FAILED` | [nimcache_types.go L197-L207](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimcache_types.go#L197-L207) |
| `NIMService` | `status.state` | `Ready`, `NotReady`, `Pending`, `Failed` | [nimservice_types.go L58-L66](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/api/apps/v1alpha1/nimservice_types.go#L58-L66) |
| `NIMService` | `status.conditions[].type` | `Ready`, `Failed` | [internal/conditions/conditions.go](https://github.com/NVIDIA/k8s-nim-operator/blob/v3.1.4/internal/conditions/conditions.go) (`SetConditionsReadyNIMService`, `...NotReady...`, `...Failed...`) |

Gotcha: `nimservice_types.go` declares `NIM_SERVICE_READY` and `NIM_SERVICE_FAILED`, but in v3.1.4 nothing uses them. The condition types the controller actually writes on a `NIMService` are plain `Ready` and `Failed`. A health check keyed on `NIM_SERVICE_READY` would never fire. The `status.state` field is the safest signal for both kinds, and the checks below use it first.

## argocd-cm snippet

Key format is `resource.customizations.health.<group>_<kind>` ([ArgoCD health docs](https://argo-cd.readthedocs.io/en/stable/operator-manual/health/)).

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
  labels:
    app.kubernetes.io/name: argocd-cm
    app.kubernetes.io/part-of: argocd
data:
  resource.customizations.health.apps.nvidia.com_NIMCache: |
    local hs = {}
    hs.status = "Progressing"
    hs.message = "Waiting for status"
    if obj.status == nil then
      return hs
    end

    -- A reconcile error is reported as a condition even while state looks normal.
    if obj.status.conditions ~= nil then
      for _, c in ipairs(obj.status.conditions) do
        if c.type == "NIM_CACHE_RECONCILE_FAILED" and c.status == "True" then
          hs.status = "Degraded"
          hs.message = c.message or "NIMCache reconcile failed"
          return hs
        end
      end
    end

    local state = obj.status.state
    if state == "Ready" then
      hs.status = "Healthy"
      hs.message = "Cache ready, pvc " .. (obj.status.pvc or "?")
    elseif state == "Failed" then
      hs.status = "Degraded"
      hs.message = "Caching job failed. Check the job pod logs."
    else
      -- NotReady, PVC-Created, Started, InProgress, Pending, or empty
      hs.status = "Progressing"
      hs.message = "Cache state: " .. (state or "unset")
    end
    return hs

  resource.customizations.health.apps.nvidia.com_NIMService: |
    local hs = {}
    hs.status = "Progressing"
    hs.message = "Waiting for status"
    if obj.status == nil then
      return hs
    end

    local state = obj.status.state
    local msg = nil
    if obj.status.conditions ~= nil then
      for _, c in ipairs(obj.status.conditions) do
        -- The controller writes condition types "Ready" and "Failed" (not NIM_SERVICE_*).
        if c.type == "Failed" and c.status == "True" then
          msg = c.message
        elseif c.type == "Ready" and msg == nil then
          msg = c.message
        end
      end
    end

    if state == "Ready" then
      hs.status = "Healthy"
      hs.message = msg or "NIMService ready"
    elseif state == "Failed" then
      hs.status = "Degraded"
      hs.message = msg or "NIMService failed"
    else
      -- NotReady, Pending, or empty. A cold start of a large model sits here for a long time.
      hs.status = "Progressing"
      hs.message = msg or ("NIMService state: " .. (state or "unset"))
    end
    return hs
```

Notes on behaviour:

- `NIMService` goes `NotReady` (reason `NIMCacheNotReady`) while its `NIMCache` is not `Ready`, and `Failed` (reason `NIMCacheNotFound` or `NIMCacheFailed`) if the cache is missing or failed (`internal/controller/platform/standalone/nimservice.go` L355-L395 in v3.1.4). With the wave order below that should not happen on first sync, but it is the signal to look at when it does.
- A `Degraded` NIMService fails the wave, so the sync reports an error rather than hanging.
- `Progressing` for a long download is correct. ArgoCD keeps waiting. Give the Application a generous sync timeout in your pipeline, since a ~750 GB download can take hours.
- I could not run these scripts against a real cluster, and no `lua` interpreter was available when I wrote them. UNVERIFIED: they parse and behave as intended. Test with `argocd admin settings resource-overrides health -f nimcache.yaml` (listed in the ArgoCD CLI reference) against sample objects before rolling out.

## Sync waves: cache before service

Annotate each resource. ArgoCD applies lower waves first and waits for them to be Healthy before starting the next (default delay between waves is 2 seconds; [sync waves docs](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/)).

| Wave | Resources | Why |
|---|---|---|
| `-1` | Pre-staged PVCs (QA/PROD overlays) | The cache must have its volume first. |
| `0` | `NIMCache`, `NetworkPolicy` | Download or verify the model before anything tries to serve it. |
| `1` | `NIMService` | Starts only once the cache check above reports Healthy. |

```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "0"   # NIMCache
```

The operator already holds the `NIMService` in `NotReady` until the cache is `Ready`, so the wave is a clean-reporting measure, not the only safety.

## Protecting caches from prune and delete

```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-options: Prune=false,Delete=false
```

Verified in the ArgoCD sync options doc: `Prune=false` ("No Prune Resources") stops a sync from pruning the object, `Delete=false` ("No Resource Deletion") keeps it when the Application is deleted, and several options can share the annotation separated by commas ([sync-options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)).

Why the NIMCache needs it: with `spec.storage.pvc.create: true` the operator creates the PVC and sets the NIMCache as its owner (`controllerutil.SetControllerReference` in `nimcache_controller.go`), so deleting the NIMCache garbage-collects the PVC and the weights with it. A re-download of ~750 GB, or an unrecoverable loss in an air gap, is the cost of a stray prune.

Caveat: `Delete=false` keeps the object only if ArgoCD is the one deleting it. It does not stop `kubectl delete nimcache`. For that, use a PVC reclaim policy of `Retain` on the storage class or an admission policy.
