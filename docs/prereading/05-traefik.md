# Traefik as a Kubernetes ingress / edge proxy

Docs version described: Traefik v3.7 (the doc pages' edit links point at the `v3.7` branch; checked 2026-11-13). Helm chart version: UNVERIFIED (the values file I read does not show its own chart version).

## In one paragraph

Traefik is a reverse proxy that learns its routes from "providers" (Kubernetes, Docker, files) instead of from a config file you reload by hand. You describe traffic in four layers: entrypoints (ports Traefik listens on), routers (match rules), middlewares (request/response transforms such as auth or rate limits) and services (where traffic goes). On Kubernetes it reads standard `Ingress` objects, its own CRDs (`IngressRoute`, `Middleware`, ...), and Gateway API objects. For an LLM stack it is the edge: it terminates TLS, runs auth and rate limits, and forwards long-lived streaming responses to the inference service / LLM gateway. It can run beside ingress-nginx using a separate IngressClass.

## Why it exists

Classic reverse proxies (nginx, HAProxy) are configured from a file; in Kubernetes a controller renders that file from `Ingress` objects and reloads. Traefik was built around the idea that routing config is dynamic data: the proxy watches the orchestrator and updates its routing table in memory, with no template-and-reload step.

What you already know that it resembles: ingress-nginx. Both watch `Ingress` objects, terminate TLS, and apply per-route policy. The differences you will feel:

- Per-route policy is expressed as separate reusable objects (`Middleware`) chained on a route, not as annotations on one Ingress.
- Traefik has its own CRDs (richer match rules, middleware chains) in addition to `Ingress`; ingress-nginx is Ingress-plus-annotations.
- Traefik has Gateway API support in the same binary.
- It ships a built-in dashboard, Prometheus metrics and OTLP tracing/metrics export.

A note on timing: Traefik's own ingress-nginx provider page and the cert-manager docs both state that the ingress-nginx project announced retirement for March 2026 (no further updates or security patches). That is the practical reason to learn a second ingress controller now.

## How it works

Request path inside Traefik (the vocabulary the docs use):

```
client --> EntryPoint (:80 / :443)
              |
              v
          Router  (rule: Host(`api.example.com`) && PathPrefix(`/v1`))
              |  (optional TLS settings on the router)
              v
        Middleware chain  (forwardAuth -> rateLimit -> headers ...)
              |
              v
          Service  (load balancer over Kubernetes Service endpoints)
              |
              v
          backend pods

Providers (Kubernetes Ingress / CRD / Gateway API) --> generate routers, middlewares, services
```

Definitions (from the v3.7 docs overview):

- **EntryPoint**: a port and protocol (TCP/UDP) Traefik listens on. Defined in static config (startup config), not by providers.
- **Router**: matches requests (host, path, headers) and sends them to a service, optionally through middlewares.
- **Service**: how to reach backends. In Kubernetes this is a Kubernetes `Service`; Traefik load-balances across the endpoints.
- **Middleware**: modifies the request or acts before forwarding.
- **Provider**: an infrastructure system Traefik queries for routing data and watches for changes.

Static vs dynamic configuration: static config (entrypoints, providers, metrics, tracing, API/dashboard) is set at startup via flags, a file, or Helm values. Dynamic config (routers, services, middlewares) comes from providers and updates live.

### Ingress vs IngressRoute CRD vs Gateway API

| | Kubernetes `Ingress` | Traefik CRDs (`IngressRoute`, `Middleware`, ...) | Gateway API |
|---|---|---|---|
| API group / version | `networking.k8s.io/v1` | `traefik.io/v1alpha1` (seen in the docs' manifests) | `gateway.networking.k8s.io/v1` (seen in docs' HTTPRoute sample) |
| Portable to other controllers | Yes | No | Yes |
| Per-route policy | Annotations: Traefik documents `traefik.ingress.kubernetes.io/router.middlewares`, `router.tls.options`, `service.middlewares`, `service.serverstransport` | Native fields (`middlewares:`, `tls:`, `services[].responseForwarding`, ...) | Filters; Traefik middlewares attach as `ExtensionRef` filters, which requires the CRD provider enabled |
| Traefik provider key | `providers.kubernetesIngress` | `providers.kubernetesCRD` (CRD kinds: IngressRoute, Middleware, TraefikService, ServersTransport, TLSOption, TLSStore, plus TCP/UDP variants) | `providers.kubernetesGateway` |
| Maturity note | Stable API | Group version is `v1alpha1` in manifests | Traefik docs: Gateway API spec v1.6.3; standard channel covers HTTPRoute, GRPCRoute, TLSRoute, BackendTLSPolicy; TCPRoute needs `experimentalChannel` |

Practical guidance for this stack: use `IngressRoute` + `Middleware` where you need per-route policy (auth, streaming tweaks); the docs' Helm quickstart enables the CRD provider by default. Gateway API CRDs are not installed by the chart; you apply them separately (the getting-started page uses `standard-install.yaml` from Gateway API v1.6.3).

## How you run it

### Install with Helm

```bash
helm repo add traefik https://traefik.github.io/charts   # chart repository
helm repo update
```

Minimal `values.yaml`. Key names are from the chart's `values.yaml` and the getting-started page; the choices (class name, second class) are mine:

```yaml
# values.yaml
ingressClass:
  enabled: true
  isDefaultClass: false        # chart default is true; set false when ingress-nginx already is the default
  name: traefik                # UNVERIFIED: chart default is "" and I did not confirm what name that renders
providers:
  kubernetesIngress:
    enabled: true
    ingressClass: traefik      # only handle Ingresses of this class (chart default: null)
  kubernetesCRD:
    enabled: true              # chart default true
    ingressClass: traefik      # docs: empty = also handle resources with no class
    allowCrossNamespace: false
ports:
  web:
    port: 8000                 # container port; exposedPort 80 on the Service
  websecure:
    port: 8443                 # exposedPort 443
  metrics:
    port: 9100                 # chart default; not exposed on the Service by default
service:
  spec:
    type: LoadBalancer         # chart default
metrics:
  prometheus:
    entryPoint: metrics
    serviceMonitor:
      enabled: true            # needs Prometheus Operator CRDs
ingressRoute:
  dashboard:
    enabled: false             # chart default; see dashboard section
```

```bash
helm install traefik traefik/traefik -n traefik --create-namespace -f values.yaml --wait
```

What it does: installs the controller, its RBAC and CRDs, creates a `LoadBalancer` Service on 80/443. (The upstream quickstart installs with no namespace flag; `-n traefik --create-namespace` is my choice.) If you run GitOps, put the same values in an ArgoCD Helm source rather than running `helm install` by hand.

### Running alongside ingress-nginx

Mechanism, confirmed from the provider docs: with `ingressClass` set, Traefik processes only Ingresses whose IngressClass name (or `kubernetes.io/ingress.class` value) matches. With it empty, Traefik also takes Ingresses that have no class. So:

1. Give Traefik its own IngressClass (`traefik`) and set `providers.kubernetesIngress.ingressClass: traefik` and `providers.kubernetesCRD.ingressClass: traefik`.
2. Do not make it the default class while ingress-nginx is (`ingressClass.isDefaultClass: false`), otherwise class-less Ingresses are ambiguous.
3. Give it its own `LoadBalancer` IP / port-forward; the two controllers must not bind the same external IP and ports.
4. Migrate one hostname at a time by changing `spec.ingressClassName` on that Ingress.

UNVERIFIED: that existing ingress-nginx ignores Ingresses with `ingressClassName: traefik` is standard IngressClass behaviour but I did not open ingress-nginx docs for this. Traefik also has an `ingressNGINX` provider (`providers.kubernetesIngressNGINX`, default `ingressClass: nginx`, `controllerClass: k8s.io/ingress-nginx`) that reads ingress-nginx annotations; its docs warn that running it next to the standard Ingress provider can create duplicate routers. Leave it off unless you are migrating annotations.

### Routes and middlewares (CRDs)

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: api-ratelimit
  namespace: llm
spec:
  rateLimit:
    average: 100        # requests per `period`
    period: 1s
    burst: 200          # token-bucket size
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: api-auth
  namespace: llm
spec:
  forwardAuth:
    address: http://auth.llm.svc:9000/verify     # your auth service
    authResponseHeaders: ["X-User", "X-Team"]    # copied onto the forwarded request
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: llm-api
  namespace: llm
spec:
  ingressClassName: traefik
  entryPoints: [websecure]
  routes:
    - kind: Rule
      match: Host(`llm.example.com`) && PathPrefix(`/v1`)
      middlewares:
        - name: api-auth
        - name: api-ratelimit
      services:
        - name: inference-gateway      # the inference service / LLM gateway
          port: 4000
          responseForwarding:
            flushInterval: 1ms         # appears in the docs' example manifest
  tls:
    secretName: llm-example-com-tls    # Secret created by cert-manager
```

What it does: matches host+path on the HTTPS entrypoint, runs forwardAuth, then rate-limits, then proxies to the gateway Service with TLS terminated by the named Secret. The `Middleware` objects are in the same namespace as the route (cross-namespace references need `allowCrossNamespace`). Port 4000 is a placeholder.

### TLS with cert-manager

Traefik reads certificates from Kubernetes Secrets (docs: in Kubernetes certificates "can and must be provided by secrets"). It also has its own ACME `certResolver`, but with an existing cert-manager you can keep cert-manager as the single issuer.

- For `Ingress` objects: cert-manager's ingress-shim watches Ingresses; the annotation `cert-manager.io/cluster-issuer: <name>` plus `spec.tls[].hosts` and `secretName` makes it create a Certificate (cert-manager docs, "latest", menu shows 1.21).
- For `IngressRoute`: the cert-manager ingress page covers only `networking.k8s.io/v1` Ingress, so UNVERIFIED whether the annotation works on IngressRoute. Safe pattern: create a cert-manager `Certificate` resource explicitly and reference its `secretName` in `tls.secretName`.
- HTTP-01 challenges: set the solver's `ingressClassName` (cert-manager 1.12+) to `traefik` so challenge Ingresses are routed by Traefik:

```yaml
solvers:
- http01:
    ingress:
      ingressClassName: traefik
```

- A `tls: {}` block with no secret makes Traefik serve a self-signed or default certificate.
- A router-level `tls` section replaces the entrypoint-level TLS settings entirely rather than merging.

### The dashboard

```yaml
# values.yaml fragment
ingressRoute:
  dashboard:
    enabled: true
    matchRule: Host(`traefik.internal.example.com`)
    entryPoints: [websecure]
    middlewares:
      - name: dashboard-allowlist   # a Middleware you define, e.g. ipAllowList
```

The docs say enabling API/dashboard in production is not recommended without authentication, because it exposes all configuration including sensitive data. The dashboard lives at `/dashboard/` (the trailing slash is mandatory). The chart's default `matchRule` is ``PathPrefix(`/dashboard`) || PathPrefix(`/api`)`` on the `traefik` entrypoint (port 8080), which is not exposed on the Service by default. For a quick look: `kubectl -n traefik port-forward deploy/traefik 8080:8080` then open `http://localhost:8080/dashboard/` (UNVERIFIED: depends on `api.insecure` or the IngressRoute being active; the chart's port-forward pattern was not confirmed in a source I opened).

### Middlewares that matter for an LLM stack

| Middleware | Key options (v3.7 docs) | LLM-stack note |
|---|---|---|
| `forwardAuth` | `address`, `authResponseHeaders`, `authRequestHeaders`, `forwardBody` (default false; docs: "Breaks streaming"), `maxBodySize`, `authSigninURL` | 2xx from the auth service = allow; anything else is returned to the client. Keep `forwardBody` false. Sends `X-Forwarded-Method/Proto/Host/Uri/For` to the auth server. |
| `rateLimit` | `average`, `period`, `burst`, `sourceCriterion` (ip strategy, `requestHeaderName`), optional `redis` | Counts requests, not tokens. Without Redis, limits are per Traefik instance. Rate by a header (e.g. an API-key header) with `requestHeaderName`. |
| `headers` | `customRequestHeaders`, `customResponseHeaders`, `accessControlAllowOriginList` etc. | CORS for the React frontend: the middleware answers preflight itself and does not pass it to the backend. Overwrites same-name headers. |
| `buffering` | `maxRequestBodyBytes`, `memRequestBodyBytes` (1 MiB), `maxResponseBodyBytes`, `retryExpression` | Attaching it buffers the request body and sends a fixed `Content-Length` upstream. The page says nothing about streaming responses, so do not attach it to streaming routes. |

### Streaming (SSE) and timeouts

LLM chat responses stream token by token over HTTP (server-sent events, SSE: a long-lived response of `data:` lines). What the docs state:

- Service `responseForwarding.flushInterval` defaults to 100ms; it is ignored when Traefik recognises the response as streaming, in which case writes flush immediately; a negative value flushes after each write. The page does not name `text/event-stream`. UNVERIFIED: that SSE is auto-detected as streaming; setting `flushInterval` to a small value or negative is the explicit safeguard.
- Entrypoint timeouts (`entryPoints.<name>.transport.respondingTimeouts`): `readTimeout` 60s (covers reading the whole request including body), `writeTimeout` 0s (no limit), `idleTimeout` 180s. Defaults do not cut off long streams.
- Backend connection (`ServersTransport`, attached via the service's `serversTransport`): `dialTimeout` 30s, `responseHeaderTimeout` 0s (no limit), `idleConnTimeout` 90s. A slow first token is not cut off by default. I did not see the CRD manifest for `ServersTransport`; UNVERIFIED: exact CRD field layout.
- Upstream of Traefik, a cloud load balancer or another proxy may have its own idle timeout; that is outside Traefik.

### Metrics and tracing

Prometheus (static config `metrics.prometheus`): `entryPoint` (chart default `metrics`, port 9100, not exposed on the Service), `addEntryPointsLabels` (true), `addServicesLabels` (true), `addRoutersLabels` (false), `buckets`. Metric names from the docs: `traefik_entrypoint_requests_total`, `traefik_entrypoint_request_duration_seconds`, `traefik_service_requests_total`, `traefik_service_request_duration_seconds`, `traefik_service_server_up`, `traefik_open_connections`, `traefik_tls_certs_not_after`, and router equivalents. It can also push metrics over OTLP (`metrics.otlp.*`).

Tracing (static config `tracing`): export via `tracing.otlp.http.endpoint` (default `https://localhost:4318`) or `tracing.otlp.grpc.endpoint` (default `localhost:4317`), `sampleRate` (default 1.0), `serviceName` (default `traefik`), `capturedRequestHeaders`. Sampling is parent-based with a ratio for root spans, so a trace already sampled upstream stays sampled. Helm: `tracing.otlp.enabled: true`. Per-route tracing: `observability.tracing: true` on an `IngressRoute` route, with `traceVerbosity` minimal or detailed (the field appears in the v3.7 CRD page; UNVERIFIED whether it is required when global tracing is on).

```yaml
tracing:
  otlp:
    enabled: true
    grpc:
      enabled: true
      endpoint: otel-collector.observability.svc:4317
      insecure: true
  sampleRate: 0.1
```

UNVERIFIED: the docs do not explicitly say Traefik reads and injects W3C `traceparent`; they say it inherits "the tracing context from incoming requests."

## How it fits the stack

```
browser (React) --HTTPS--> Traefik (edge) --> FastAPI app --> inference service / LLM gateway --> model servers
                              |                                                   
                              +--> forwardAuth service (auth decision)
                              +--> OTLP --> OpenTelemetry Collector --> Tempo
                              +--> /metrics --> Prometheus
```

- Calls it: browsers and API clients. cert-manager (HTTP-01 challenge Ingresses). Prometheus (scrape).
- It calls: the frontend and API Services, the forwardAuth service, the inference service / LLM gateway, and the OTLP collector.
- Keep Traefik as the only public entry; internal services call each other via cluster Services, not through the edge.

## What goes wrong

- 404 from Traefik for every request: no router matched. Check the dashboard Routers tab, the Host rule, the entrypoint name, and `ingressClass` on both the provider and the object.
- Route works from one controller and not the other / duplicate routers: both controllers or both Traefik providers claim the same Ingress. Check IngressClass settings; do not enable the `ingressNGINX` provider alongside `kubernetesIngress` without class scoping.
- `middleware ... not found`: referenced `Middleware` is in another namespace (needs `allowCrossNamespace` or explicit `namespace:`), or the name contains `@` (not allowed in the CRD field).
- 503 with `allowEmptyServices`: that option (chart default true for CRD and Ingress providers) routes to endpoint-less Services and returns 503 after middlewares run.
- Streams arrive in one lump at the end: a buffering middleware, an upstream proxy buffering, or a large `flushInterval`. Test with `curl -N`.
- 401 loops with forwardAuth: the auth service sees `X-Forwarded-*` headers, not the original request; make it decide on `X-Forwarded-Uri`/`Host`. A non-2xx auth response is passed straight to the client.
- Large uploads fail at 60s: `readTimeout` covers reading the full request body.
- Rate limit looks too loose with replicas: without Redis the limit is per instance.
- Rate limit by client IP behind another proxy limits the proxy: set `sourceCriterion.ipStrategy.depth` or use a header.
- Certificate stays pending: HTTP-01 solver Ingress created with a different class than the one Traefik handles (set the solver `ingressClassName`).
- Dashboard exposed publicly: it shows full configuration; protect it.

## Traefik vs ingress-nginx

| Topic | Traefik v3.7 | ingress-nginx |
|---|---|---|
| Project status | Active (docs v3.7) | Retirement announced for March 2026 per Traefik and cert-manager docs; I did not open the upstream announcement (UNVERIFIED primary source) |
| Config model | Providers; dynamic, no reload; Ingress, own CRDs, Gateway API | Ingress + annotations + ConfigMap (UNVERIFIED; from prior knowledge, not re-read) |
| Per-route policy | Reusable `Middleware` objects chained per route | Annotations on each Ingress (UNVERIFIED, prior knowledge) |
| Gateway API | Built in (`providers.kubernetesGateway`, spec v1.6.3) | UNVERIFIED |
| Reads nginx annotations | Optional `kubernetesIngressNGINX` provider translates many | n/a |
| Dashboard | Built in | None built in (UNVERIFIED) |
| Metrics | Prometheus built in; OTLP push | Prometheus (UNVERIFIED) |
| Tracing | OTLP built in (`tracing.otlp`) | UNVERIFIED |
| Rate limit scope | Per instance unless Redis configured | UNVERIFIED |
| Streaming defaults | `writeTimeout` 0, `flushInterval` 100ms | UNVERIFIED (known to need `proxy-buffering off` for SSE from memory; unchecked) |

Rows marked UNVERIFIED on the ingress-nginx side are deliberate: I only opened Traefik and cert-manager docs. Check the ingress-nginx docs before relying on them.

## Check yourself

1. What are the four layers of a Traefik request path, and which of them are defined in static versus dynamic configuration?
2. Which three Kubernetes-facing providers can feed Traefik routes, and which one makes Traefik middlewares usable as Gateway API filters?
3. How do you stop Traefik and ingress-nginx from both claiming the same Ingress, and why should Traefik not be the default IngressClass during migration?
4. Why would `forwardBody: true` on `forwardAuth` or a `buffering` middleware be a problem for a chat-completions route?
5. Which timeouts could cut off a long streamed LLM response or a slow first token, and what are their defaults?
6. How would you get a cert-manager certificate onto an `IngressRoute`, and what must the HTTP-01 solver's `ingressClassName` be set to?
7. Why does a Traefik rate limit behave differently with three replicas than with one, and what fixes it?
8. Name three things you must do before exposing the dashboard, and the URL path (with its quirk) where it is served.

## References

All opened and read on 2026-11-13. Traefik docs describe v3.7 (inferred from the pages' edit links).

- https://doc.traefik.io/traefik/ (concepts overview)
- https://doc.traefik.io/traefik/getting-started/kubernetes/ (Helm install, Gateway API v1.6.3)
- https://doc.traefik.io/traefik/reference/install-configuration/providers/kubernetes/kubernetes-crd/
- https://doc.traefik.io/traefik/reference/install-configuration/providers/kubernetes/kubernetes-ingress/
- https://doc.traefik.io/traefik/reference/install-configuration/providers/kubernetes/kubernetes-ingress-nginx/
- https://doc.traefik.io/traefik/reference/routing-configuration/kubernetes/gateway-api/
- https://doc.traefik.io/traefik/reference/routing-configuration/kubernetes/crd/http/ingressroute/
- https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/forwardauth/
- https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/ratelimit/
- https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/buffering/
- https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/headers/
- https://doc.traefik.io/traefik/reference/routing-configuration/http/load-balancing/service/
- https://doc.traefik.io/traefik/reference/routing-configuration/http/load-balancing/serverstransport/
- https://doc.traefik.io/traefik/reference/routing-configuration/http/tls/tls-certificates/
- https://doc.traefik.io/traefik/reference/install-configuration/entrypoints/
- https://doc.traefik.io/traefik/reference/install-configuration/api-dashboard/
- https://doc.traefik.io/traefik/reference/install-configuration/observability/metrics/
- https://doc.traefik.io/traefik/reference/install-configuration/observability/tracing/
- https://raw.githubusercontent.com/traefik/traefik-helm-chart/master/traefik/values.yaml (master branch, chart version not shown)
- https://cert-manager.io/docs/usage/ingress/ (docs "latest", menu shows 1.21)
- https://cert-manager.io/docs/configuration/acme/http01/ ("latest")
