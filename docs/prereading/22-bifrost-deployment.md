# Deploying Bifrost on Kubernetes

Checked 2026-11-18 against the `maximhq/bifrost` repo (`helm-charts/bifrost/Chart.yaml` and `values.yaml` on `main`) and docs.getbifrost.ai. The chart read as version 2.1.48 with appVersion 2.4.0. Doc 06 recorded gateway v2.5.1, so the chart lags the gateway. Items I could not confirm are marked `UNVERIFIED:`. Replace the placeholder names (`registry.example.internal`, `bifrost.example.internal`, `nim-chat-a`) with your own.

For what Bifrost is, virtual keys, headers and logging, read [06-bifrost-llm-gateway.md](06-bifrost-llm-gateway.md). This doc covers only getting it running. Related: [05-traefik.md](05-traefik.md), [07-opentelemetry.md](07-opentelemetry.md), [10-vmware-tanzu-kubernetes.md](10-vmware-tanzu-kubernetes.md), [12-harbor-podman-images.md](12-harbor-podman-images.md).

## In one paragraph

Run Bifrost as one Helm release in its own namespace, with PostgreSQL for its config and log stores, its image mirrored into your private registry and pinned by tag, its secrets created beforehand and referenced by name, and Traefik terminating TLS in front. Point two custom providers (type `openai`) at the in-cluster NIM Services, turn on governance enforcement so every call needs a virtual key, and expose `/metrics` for Prometheus and an OTel plugin for traces. Then prove it with positive and negative curl probes before any client is told the address.

## The plain version

Picture a building's front desk. Visitors (the chat portal, Cline, Claude Code) never walk straight to the workshops (the model servers). They check in at the desk, show a badge, and the desk sends them to the right workshop. Deploying Bifrost is setting up that desk: choosing where it keeps its visitor book, who holds the master keys, and what the front door looks like.

Most of the work is boring and that is good. You make a space for it, bring its container image inside your own network because the cluster cannot reach the internet, store its passwords in Kubernetes secrets, and describe the two model servers it should know about. The one tricky part is the front door. The model answers arrive a few words at a time, and anything in the doorway that waits for the whole answer, or hangs up after a minute, will make chat feel broken.

After installing, you test like a security guard would: confirm a visitor with a badge gets in, and confirm a visitor with no badge or a fake one is turned away. A desk that lets everyone in is worse than no desk, because it looks like control.

Five things to remember:

- Pin the image tag yourself. The chart will not start without one, and its default lags the gateway.
- Use PostgreSQL if you want more than one replica or want state to survive a rescheduled pod.
- Pick one owner for configuration: the Helm values or the web UI, not both.
- Turn governance enforcement on, then prove it with a no-key probe that must fail.
- Streaming needs no buffering and long timeouts at Traefik and at Bifrost.

## Before you start

### Decisions

| Decision | Recommendation | Why |
|---|---|---|
| Config and log store | PostgreSQL (`storage.mode: postgres`) | The chart default is `sqlite` on a 10Gi `ReadWriteOnce` volume. That ties you to one replica and one node's volume. PostgreSQL must be 16 or later, UTF8 encoded (doc 06, docs). |
| Replicas | Start at `1`, move to `2` only after Postgres works | `replicaCount` defaults to 1. UNVERIFIED: whether governance counters (budgets, rate limits) are shared correctly across replicas without the enterprise clustering feature. Test before relying on it. |
| Source of truth | Helm values own it; UI read-mostly | Chart option `bifrost.sourceOfTruth` is `split` (default) or `config.json`. See doc 06. `config.json` makes the file win on restart. The chart documents it only as a commented example. |
| Secrets | Pre-created Kubernetes Secrets, referenced by name | Keeps values out of Git and out of `helm get values`. |
| Image | Mirror and pin | See below. |
| Dashboard auth | Enable `bifrost.authConfig` | Otherwise the UI is open to whoever reaches the Service. |

### Prerequisites

- `kubectl` and `helm` 3.x on a machine that can reach both the cluster and your registry. The chart repo is `https://maximhq.github.io/bifrost/helm-charts`. If the cluster is restricted, pull the chart on a connected machine with `helm pull`, then carry the `.tgz` in, or push it to a Harbor OCI project (`helm push`).
- A PostgreSQL 16+ instance reachable from the namespace, with an empty UTF8 database and a user that owns it. How it is provided (operator, managed service) is out of scope here.
- Traefik with a TLS certificate for the hostname (a cert-manager `Certificate` or a pre-made Secret).
- The in-cluster NIM Service names, namespace and port. NIM listens on 8000 by default.
- Prometheus Operator CRDs if you want a `ServiceMonitor`.

### Image mirroring facts

The chart's `image.repository` default is `docker.io/maximhq/bifrost`, and `image.tag` defaults to empty and is required ("the chart will not start without it"). Choose a tag from the GitHub releases page and record it. Doc 06 saw gateway v2.5.1 on 2026-11-15. UNVERIFIED: that Docker Hub tags carry a `v` prefix such as `v2.5.1`; the Helm docs example shows `v1.4.11`, and the chart's appVersion is written without one. Run `podman search` or check the Docker Hub tags page first, and use the exact string you see.

### Chart version vs app version

Chart 2.1.48 declares appVersion 2.4.0, but the gateway had moved on to 2.5.1. Because you set `image.tag` yourself you get the newer gateway, but the chart templates were written for the older one. Read the chart's release notes for the gap before you upgrade, and expect the occasional value key that exists in the gateway but not yet in the chart.

## Step by step

### 1. Create the namespace

```bash
kubectl create namespace bifrost
kubectl label namespace bifrost app.kubernetes.io/part-of=llm-gateway
```

Expected:

```
namespace/bifrost created
namespace/bifrost labeled
```

On a cluster with Pod Security Admission, add `pod-security.kubernetes.io/enforce=restricted` and check the chart's `podSecurityContext` and `securityContext` values satisfy it. The Terraform guide runs the container as UID 1000, non-root. UNVERIFIED: whether the chart defaults pass `restricted` unchanged.

### 2. Mirror the image

On a machine with internet access and registry credentials:

```bash
TAG=2.5.1   # use the exact tag string verified above
podman pull docker.io/maximhq/bifrost:${TAG}
podman tag  docker.io/maximhq/bifrost:${TAG} registry.example.internal/llm/bifrost:${TAG}
podman login registry.example.internal
podman push registry.example.internal/llm/bifrost:${TAG}
```

Expected (abridged): `Copying blob ...`, then `Writing manifest to image destination`. Record the digest:

```bash
skopeo inspect docker://registry.example.internal/llm/bifrost:${TAG} | grep Digest
```

Expected: `"Digest": "sha256:..."`. Prefer pinning by digest in `image.tag` if your policy requires it. UNVERIFIED: that the chart accepts `sha256:` in `image.tag` (it likely builds `repo:tag`, which would break; test with `helm template`).

For a private registry create a pull secret:

```bash
kubectl -n bifrost create secret docker-registry harbor-pull \
  --docker-server=registry.example.internal \
  --docker-username='<robot-account>' --docker-password='<token>'
```

Expected: `secret/harbor-pull created`.

### 3. Create secrets

```bash
kubectl -n bifrost create secret generic bifrost-encryption \
  --from-literal=encryption-key="$(openssl rand -base64 32)"

kubectl -n bifrost create secret generic bifrost-postgres \
  --from-literal=password='<db-password>'

kubectl -n bifrost create secret generic bifrost-admin \
  --from-literal=username=admin \
  --from-literal=password="$(openssl rand -base64 24)"
```

Expected: three `secret/... created` lines. The encryption key protects stored provider keys in the database. UNVERIFIED: the exact required key length; the chart only names the secret `key` as `encryption-key` by default. Back it up now. Losing it makes encrypted DB values unreadable, so store it where your normal secret backup covers it.

The NIM Services need no client auth, so there is no provider API key. UNVERIFIED: whether Bifrost insists on a non-empty key entry for a custom provider. If it does, create a dummy secret (`nim-dummy-key`) and reference it under `providerSecrets`. Doc 06 raised the same open question.

### 4. Write values.yaml

Key names below were read from the chart's `values.yaml`. Anything marked `UNVERIFIED` is a gateway config shape that the chart passes through but does not show an example for.

```yaml
image:
  repository: registry.example.internal/llm/bifrost
  tag: "2.5.1"
  pullPolicy: IfNotPresent
imagePullSecrets:
  - name: harbor-pull

replicaCount: 1

resources:
  requests: { cpu: 500m, memory: 512Mi }
  limits:   { cpu: "2",  memory: 2Gi }

service:
  type: ClusterIP
  port: 8080

storage:
  mode: postgres

postgresql:
  enabled: false          # do not deploy the bundled Postgres
  external:
    enabled: true
    host: pg.db.svc.cluster.local
    port: 5432
    user: bifrost
    database: bifrost
    sslMode: require      # chart default is "disable"
    existingSecret: bifrost-postgres
    passwordKey: password

bifrost:
  logLevel: info
  logStyle: json
  encryptionKeySecret:
    name: bifrost-encryption
    key: encryption-key
  authConfig:
    isEnabled: true
    existingSecret: bifrost-admin
    usernameKey: username
    passwordKey: password
  client:
    enableLogging: true
    disableContentLogging: true     # metadata only; see below
    logRetentionDays: 30
    enforceAuthOnInference: true    # chart default is already true
    allowedOrigins: []
  providers:
    nim-chat-a:
      keys:
        - name: nim-chat-a-key
          value: "env.NIM_DUMMY_KEY"
          models: ["*"]
          weight: 1
      network_config:
        base_url: "http://nim-chat-a.nim.svc:8000/v1"
        default_request_timeout_in_seconds: 600
        stream_idle_timeout_in_seconds: 300
        max_retries: 1
      custom_provider_config:
        base_provider_type: openai
    nim-chat-b:
      keys:
        - name: nim-chat-b-key
          value: "env.NIM_DUMMY_KEY"
          models: ["*"]
          weight: 1
      network_config:
        base_url: "http://nim-chat-b.nim.svc:8000/v1"
        default_request_timeout_in_seconds: 600
        stream_idle_timeout_in_seconds: 300
        max_retries: 1
      custom_provider_config:
        base_provider_type: openai
  providerSecrets:
    NIM_DUMMY_KEY:
      existingSecret: nim-dummy-key
      envVar: NIM_DUMMY_KEY
  plugins:
    telemetry:
      enabled: true
    logging:
      enabled: true
      config:
        disable_content_logging: true
    governance:
      enabled: true
      config:
        is_vk_mandatory: true
    otel:
      enabled: true
      config:
        service_name: bifrost
        collector_url: "http://otel-collector.observability.svc:4318/v1/traces"
        protocol: http
        trace_type: genai_extension

startupProbe:   { httpGet: { path: /health, port: http }, periodSeconds: 30, failureThreshold: 60 }
livenessProbe:  { httpGet: { path: /health, port: http }, initialDelaySeconds: 30, periodSeconds: 30 }
readinessProbe: { httpGet: { path: /health, port: http }, initialDelaySeconds: 10, periodSeconds: 10 }
```

Notes on what is and is not verified:

- Confirmed in the chart: `image.*`, `imagePullSecrets`, `replicaCount`, `resources`, `service`, `storage.mode`, `postgresql.external.{host,port,user,database,sslMode,existingSecret,passwordKey}`, `bifrost.encryptionKeySecret`, `bifrost.authConfig.*`, `bifrost.client.{enableLogging,disableContentLogging,logRetentionDays,enforceAuthOnInference,allowedOrigins}`, `bifrost.providerSecrets`, `plugins.{telemetry,logging,governance,otel}`, and the three probes on `/health` (already the defaults, shown here only to make them explicit).
- UNVERIFIED: the chart's own `providers` examples show `keys` and `network_config.base_url` but no `custom_provider_config`. The key is taken from the gateway docs (doc 06). Run `helm template` and look for it in the rendered `config.json` ConfigMap or Secret before installing.
- UNVERIFIED: whether `base_url` should end in `/v1`. Doc 06 flagged this. Probe `http://<svc>:8000/v1/models` from a debug pod, then check a Bifrost chat call reaches `/v1/chat/completions` and not `/v1/v1/chat/completions`. If it doubles, drop `/v1` from `base_url`.
- UNVERIFIED: whether in-cluster addresses need `allow_private_network: true` under `network_config` (doc 06 saw the key). Set it if the first call fails with a blocked-address error.
- `plugins.governance.config.is_vk_mandatory: true` appears in the chart; `bifrost.client.enforceAuthOnInference: true` also does. Setting both is intentional. The docs contradict each other on defaults, so check the stored value in the UI after install (Settings).
- Content logging: `disableContentLogging: true` keeps request metadata (model, tokens, latency, key) and drops prompts and completions. Turn it on only with an explicit decision, because logs then hold whatever users type.
- Cline and some clients may send `/chat/completions` through the OpenAI-compatible route; no extra config is needed on the Bifrost side.

Dry-run it:

```bash
helm repo add bifrost https://maximhq.github.io/bifrost/helm-charts && helm repo update
helm template bifrost bifrost/bifrost -n bifrost -f values.yaml | grep -n -A12 'base_url'
```

Expected: both `base_url` lines appear in a rendered config, with `custom_provider_config` next to them.

### 5. Install

```bash
helm upgrade --install bifrost bifrost/bifrost -n bifrost -f values.yaml --wait --timeout 10m
kubectl -n bifrost get pods
```

Expected:

```
Release "bifrost" does not exist. Installing it now.
NAME: bifrost ... STATUS: deployed
NAME                      READY   STATUS    RESTARTS
bifrost-xxxxxxxxxx-yyyyy  1/1     Running   0
```

The startup probe allows up to 30 minutes (30 s x 60) for first boot, which covers database migrations. If the pod restarts, read `kubectl -n bifrost logs deploy/bifrost` first.

### 6. Expose through Traefik

Prefer your own manifest over the chart's `ingress` block so Traefik-specific options are explicit. Disable the chart ingress (`ingress.enabled: false`, the default).

```yaml
apiVersion: traefik.io/v1alpha1
kind: ServersTransport
metadata: { name: bifrost-st, namespace: bifrost }
spec:
  forwardingTimeouts:
    dialTimeout: 10s
    responseHeaderTimeout: 0s     # 0 = wait forever for the first byte
    idleConnTimeout: 600s
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata: { name: bifrost, namespace: bifrost }
spec:
  entryPoints: [websecure]
  routes:
    - match: Host(`bifrost.example.internal`)
      kind: Rule
      services:
        - name: bifrost
          port: 8080
          serversTransport: bifrost-st
          responseForwarding:
            flushInterval: 1ms
  tls:
    secretName: bifrost-tls
```

Apply and check:

```bash
kubectl apply -f ingressroute.yaml
curl -sS -o /dev/null -w '%{http_code}\n' https://bifrost.example.internal/health
```

Expected: `200`.

Streaming-safe rules:

- Do not attach `buffering`, `compress` or retry middlewares to this route. Compression and buffering both hold back SSE frames.
- Entrypoint `respondingTimeouts.readTimeout`/`writeTimeout` are static Traefik config. If long generations are cut at a fixed time (often 60 s), raise or zero them in the Traefik deployment args, not here. UNVERIFIED: your Traefik version's defaults; check [05-traefik.md](05-traefik.md) and your static config.
- Any L4 or L7 load balancer in front of Traefik (VKS often provisions one) has its own idle timeout. Find it.
- The service name `bifrost` assumes the chart's default fullname for release `bifrost`. Confirm with `kubectl -n bifrost get svc`.

### 7. Create a virtual key

With enforcement on, the first key must come from the admin side. Log in to `https://bifrost.example.internal` with the admin secret, open Virtual Keys, create one per client (portal backend, Cline, Claude Code), restrict `provider_configs` to the two NIM providers, and set a budget and rate limit. Copy the `sk-bf-...` value once.

Or via the API (basic auth with the admin credentials):

```bash
curl -sS -u admin:"$ADMIN_PW" https://bifrost.example.internal/api/governance/virtual-keys \
  -H 'Content-Type: application/json' -d '{
    "name": "portal-backend",
    "provider_configs": [
      {"provider": "nim-chat-a", "allowed_models": ["*"]},
      {"provider": "nim-chat-b", "allowed_models": ["*"]}
    ],
    "budget": {"max_limit": 50, "reset_duration": "1M"},
    "rate_limit": {"request_max_limit": 60, "request_reset_duration": "1m"}
  }'
```

Expected: a JSON object containing an `id` and a `value` starting `sk-bf-`. UNVERIFIED: the exact route path and field names. They come from my reading of the governance docs and chart `governance.virtualKeys` shape. Open the UI's network tab, or the API reference at docs.getbifrost.ai, and match them. Alternatively declare keys under `bifrost.governance.virtualKeys` in values (the chart supports `id`, `value`, `provider_configs`), which fits the config-as-code route.

Remember from doc 06: if dashboard auth is on, `Authorization: Bearer` is consumed by admin auth, so the key goes in `x-bf-vk` unless `disable_auth_on_inference` is set. Clients that only send a Bearer token (Cline, many SDKs) need that setting; decide it deliberately.

### 8. Metrics scrape

Bifrost serves `/metrics` on port 8080 (telemetry plugin). The chart did not show a `serviceMonitor` key in the part I read. UNVERIFIED: whether one exists in the unread tail of `values.yaml`; run `helm show values bifrost/bifrost | grep -i servicemonitor`. If absent, add your own:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: bifrost
  namespace: bifrost
  labels: { release: prometheus }   # match your Prometheus selector
spec:
  selector:
    matchLabels: { app.kubernetes.io/name: bifrost }
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

Check the Service's port name (`kubectl -n bifrost get svc bifrost -o yaml`) and labels, then fix the selector and `port`. If dashboard auth is on, the docs say to add `basicAuth` with the admin credentials. Useful metric names: `bifrost_upstream_requests_total`, `bifrost_error_requests_total`, `bifrost_stream_first_token_latency_seconds`, `bifrost_input_tokens_total`, `bifrost_cost_total`, `bifrost_active_requests`. Labels include `provider`, `model`, `virtual_key_name`.

## Prove it works

Set variables:

```bash
export BF=https://bifrost.example.internal
export VK=sk-bf-...        # the virtual key
export MODEL=nim-chat-a/<model-id>
```

1. Health and models list (key via `x-bf-vk`):
   ```bash
   curl -sS $BF/v1/models -H "x-bf-vk: $VK" | head -c 400
   ```
   Expected: JSON `{"data":[{"id":"nim-chat-a/...`. Both providers' models should appear.

2. Chat:
   ```bash
   curl -sS $BF/v1/chat/completions -H "x-bf-vk: $VK" -H 'Content-Type: application/json' \
     -d '{"model":"'$MODEL'","messages":[{"role":"user","content":"Say hi in five words."}]}'
   ```
   Expected: `choices[0].message.content` and a `usage` block. Repeat with the second model.

3. Streaming, which must be gradual:
   ```bash
   curl -sSN $BF/v1/chat/completions -H "x-bf-vk: $VK" -H 'Content-Type: application/json' \
     -d '{"model":"'$MODEL'","stream":true,"messages":[{"role":"user","content":"Count from 1 to 30 slowly."}]}' \
     | while IFS= read -r l; do printf '%s %s\n' "$(date +%S.%N)" "$l"; done
   ```
   Expected: many `data: {...}` lines with timestamps spread across seconds, ending `data: [DONE]`. If everything lands in one burst at the end, something is buffering (Traefik middleware, an external load balancer, or compression).

4. Tool call:
   ```bash
   curl -sS $BF/v1/chat/completions -H "x-bf-vk: $VK" -H 'Content-Type: application/json' -d '{
     "model":"'$MODEL'","tool_choice":"auto",
     "messages":[{"role":"user","content":"What is the weather in Paris?"}],
     "tools":[{"type":"function","function":{"name":"get_weather","description":"Get weather","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}]}'
   ```
   Expected: `choices[0].message.tool_calls[0].function.name` equal to `get_weather`. Run once with `"stream":true` too, since streamed tool-call deltas are the usual failure (doc 06). UNVERIFIED: whether the NIM model needs tool-calling enabled on the NIM side.

5. The `/anthropic` route (what Claude Code uses). Point Claude Code at `ANTHROPIC_BASE_URL=$BF/anthropic` with the virtual key as its token:
   ```bash
   curl -sS $BF/anthropic/v1/messages -H "x-api-key: $VK" -H 'anthropic-version: 2023-06-01' \
     -H 'Content-Type: application/json' \
     -d '{"model":"'$MODEL'","max_tokens":64,"messages":[{"role":"user","content":"Say hi."}]}'
   ```
   Expected: an Anthropic-shaped body (`"type":"message"`, `content[0].text`). UNVERIFIED: that a non-Anthropic NIM model name is accepted on this route and that Claude Code's own request features (tool use, token counting, extended thinking fields) work against these models. Test with the real client, not only curl.

6. Negative probes, which are mandatory:
   ```bash
   curl -sS -o /dev/null -w 'no key:  %{http_code}\n' $BF/v1/chat/completions -H 'Content-Type: application/json' \
     -d '{"model":"'$MODEL'","messages":[{"role":"user","content":"x"}]}'
   curl -sS -o /dev/null -w 'bad key: %{http_code}\n' $BF/v1/chat/completions -H 'x-bf-vk: sk-bf-not-real' \
     -H 'Content-Type: application/json' -d '{"model":"'$MODEL'","messages":[{"role":"user","content":"x"}]}'
   ```
   Expected: `no key: 401` and a `virtual_key_required` error (doc 06); `bad key: 401` or `403`. The docs do not say which for an unknown key, so record what you get. A `200` on either means enforcement is off. Fix before anything else. Also probe the NIM Service directly from outside the namespace to see whether network policy blocks bypass; NIM has no auth, so only the network stops a client skipping Bifrost.

7. Budget and rate limit exceed. Create a throwaway key with `request_max_limit: 2` per minute and send four requests:
   ```bash
   for i in 1 2 3 4; do curl -sS -o /dev/null -w '%{http_code}\n' $BF/v1/chat/completions \
     -H "x-bf-vk: $LIMITED" -H 'Content-Type: application/json' \
     -d '{"model":"'$MODEL'","messages":[{"role":"user","content":"x"}]}'; done
   ```
   Expected: `200 200 429 429`. For a budget, set a tiny `max_limit` (for example 0.0001) on another throwaway key; expect `402` `budget_exceeded` after the first calls. UNVERIFIED: that self-hosted NIM models carry a price, so spend may stay at zero. Without pricing data, budgets will never trip. Check the logs UI cost column, and set a pricing override if it shows 0.

8. Logs UI: open the dashboard, Logs. Expect your probe requests with provider, model, tokens, latency and key name; with `disableContentLogging` true the prompt text should not appear. Confirm that, since it is the privacy promise.

9. Prometheus:
   ```bash
   curl -sS $BF/metrics -u admin:"$ADMIN_PW" | grep -E '^bifrost_(upstream_requests_total|input_tokens_total)' | head
   ```
   Expected: counters with `provider="nim-chat-a"` and your virtual key name. Then in Prometheus, check the target is `UP` and `rate(bifrost_upstream_requests_total[5m])` returns series. If `/metrics` requires no auth in your setup, drop `-u`.

10. Traces: find a trace for service `bifrost` in your trace backend. Expected: spans for the probe request with GenAI attributes (`genai_extension` format).

## Upgrades, backup, rollback

Upgrade:

1. Mirror the new tag (step 2) and read the gateway release notes for config or schema changes.
2. Back up first: `pg_dump` the Bifrost database, and note `helm get values bifrost -n bifrost -o yaml > values.backup.yaml`.
3. Change `image.tag` (and chart version if wanted) and run `helm upgrade bifrost bifrost/bifrost -n bifrost -f values.yaml --wait`. Avoid `--reuse-values`; it can hide newly required keys. Docs mention it, but an explicit values file is easier to audit.
4. Re-run the Prove-it-works probes.

Backup:

- PostgreSQL is the state: virtual keys, budgets, config and logs. Back it up on your normal database schedule, and test a restore.
- The encryption key secret. Without it the database cannot be decrypted. Back it up separately from the database.
- With SQLite the files are `config.db` and `logs.db` under `/app/data`; snapshot the PVC.
- `helm uninstall` keeps PVCs by default. Deleting them destroys SQLite state.

Rollback:

```bash
helm history bifrost -n bifrost
helm rollback bifrost <revision> -n bifrost --wait
```

Helm only reverts Kubernetes objects. UNVERIFIED: whether a newer gateway runs forward-only database migrations that the older image cannot read. Assume yes: restore the pre-upgrade database dump if a rollback to an older image fails to start.

## What goes wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `helm install` fails: image tag required | `image.tag` empty | Set `image.tag`. |
| `ImagePullBackOff` | Registry path wrong or no pull secret | Check `kubectl describe pod`; add `imagePullSecrets`; confirm mirror path and tag exist. |
| Pod restarts, never ready | Postgres unreachable, wrong password, non-UTF8 DB, or `sslMode` mismatch | Read pod logs; test with `psql` from a debug pod; recreate DB as UTF8. |
| `no key` probe returns 200 | Enforcement off | Set `enforceAuthOnInference` and governance `is_vk_mandatory`; restart; check stored value in UI. |
| 401 with a valid key from Cline | Key sent as Bearer while dashboard auth consumes `Authorization` | Use `x-bf-vk` where possible, or set `disable_auth_on_inference` deliberately (doc 06). |
| `404` from a provider | `base_url` duplicates or lacks `/v1` | Test `curl http://<svc>:8000/v1/models` from a pod; toggle the suffix. |
| Connection blocked to a cluster address | Private-network guard | UNVERIFIED: try `allow_private_network: true`. Also check NetworkPolicy and namespace egress rules. |
| Stream arrives in one burst | Buffering or compression middleware, or an external load balancer | Remove middlewares, set `flushInterval`, check the balancer. |
| Stream cut at 60 s or 120 s | Traefik entrypoint timeout, balancer idle timeout, or `stream_idle_timeout_in_seconds` (docs default 120) | Raise all three. |
| UI edits vanish after upgrade | Values own the config (`split` or `config.json`) | Pick one owner; move the change into values. |
| Budget never trips | Self-hosted models have no price | Add pricing override or use request and token limits. |
| `/metrics` missing series | Telemetry plugin off, or no traffic yet | `plugins.telemetry.enabled: true`; send a request. |
| ServiceMonitor target not found | Label or port name mismatch | Compare Service labels and port names with the monitor. |
| Clients bypass the gateway | NIM has no auth and a flat network | NetworkPolicy: allow NIM ingress only from `bifrost`. |

## Questions to ask whoever owns the deployment

- Which PostgreSQL serves it, who backs it up, and when was a restore last tested?
- Where is the encryption key stored, and is it in the secret backup?
- Is the image pinned by tag or digest, and who decides when to move it?
- Does the source of truth live in Git values or in the UI? Who may edit the UI?
- Is content logging on? Who can read the logs, and for how long are they kept?
- What do the load balancer and Traefik idle and write timeouts say?
- Is there a NetworkPolicy forcing NIM traffic through Bifrost?
- Which virtual keys exist, who owns each, and what are their limits?
- How many replicas run, and have counters (budgets, rate limits) been tested across them?
- What does the on-call person do when the gateway is down? Is there a direct fallback path?

## Check yourself

1. Why is SQLite a poor choice if you want two replicas?
2. What two settings make an unauthenticated request fail, and what status do you expect?
3. A streamed answer arrives all at once. Name three places to look.
4. Why can a budget stay at zero spend for a self-hosted model?
5. What must you back up besides the database, and why?
6. Which file wins on restart if `sourceOfTruth` is `config.json` and someone edited the UI?
7. Why mirror the image and pin the tag, when the chart's appVersion is behind?

## References

Checked 2026-11-18 unless noted.

- Helm chart `values.yaml`: https://github.com/maximhq/bifrost/blob/main/helm-charts/bifrost/values.yaml
- Helm chart `Chart.yaml` (2.1.48, appVersion 2.4.0): https://github.com/maximhq/bifrost/blob/main/helm-charts/bifrost/Chart.yaml
- Helm deployment docs (repo URL, install, upgrade): https://docs.getbifrost.ai/deployment-guides/helm
- Kubernetes/Terraform deployment guide (port, `/health`, data dir, UID 1000): https://docs.getbifrost.ai/deployment-guides/k8s
- Gateway setup (image `maximhq/bifrost`, env vars, data dir): https://docs.getbifrost.ai/quickstart/gateway/setting-up
- Telemetry and metrics: https://docs.getbifrost.ai/features/telemetry
- OpenTelemetry plugin: https://docs.getbifrost.ai/features/observability/otel
- Config schema: https://www.getbifrost.ai/schema
- Releases: https://github.com/maximhq/bifrost/releases (checked 2026-11-15 in doc 06)
