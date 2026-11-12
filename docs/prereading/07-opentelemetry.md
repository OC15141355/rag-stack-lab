# OpenTelemetry for a multi-service LLM/RAG stack

Docs checked 2026-11-13 on opentelemetry.io (pages carry no single version number; versions are stated where a page gave one). GenAI conventions now live in the `open-telemetry/semantic-conventions-genai` repo, `main` branch, status Development.

## In one paragraph

OpenTelemetry (OTel) is a vendor-neutral standard and toolkit for producing and shipping telemetry: traces (the path of one request through many services), metrics (numbers over time) and logs. Your code, or auto-instrumentation attached to it, emits data in one wire format, OTLP (the OpenTelemetry Protocol). An OpenTelemetry Collector receives it, filters and batches it, and forwards it to backends. In your stack those backends are Tempo (traces), Prometheus (metrics) and Loki (logs). OTel is not a backend itself. The point for an LLM/RAG stack is one request ID that follows a user's question from the browser through the edge proxy, the API, the LLM gateway and the model.

## The plain version

Imagine posting a parcel that passes through five depots: your local post office, a sorting centre, a truck, a regional hub, and the delivery van. If the parcel is late, you want to know which depot held it up. So every depot stamps the parcel's label with a time and a note, and all stamps share one tracking number. Someone collects the stamps from every depot into a single page. That page is a "trace".

OpenTelemetry is the agreement on how to stamp, what the tracking number looks like, and how stamps get collected. Without it, each program keeps its own diary in its own format. When a user says "the answer took forever", you open five diaries in five formats and guess which one matches. With a shared tracking number you open one page and see that three seconds went to the model and 40 milliseconds to everything else.

For AI systems this matters more than usual, because a single question fans out into a search step, a prompt-building step and a slow model call, and the cost of each call (how many words went in and out) is part of what you want to see.

If you remember only five things:

- One tracking number (the trace ID) is passed along with every request, in a header called `traceparent`.
- Each step records a "span": what it did, when, how long, and whether it failed.
- A small relay program (the Collector) collects the records, tidies them and sends them to storage.
- You can switch recording on without editing code for many Python services, but the browser needs real code.
- Recording everything costs money, so you keep a sample and make sure the failures and slow ones are in it.

## Why it exists

Before OTel, every tracing or metrics product shipped its own libraries and wire format; switching backend meant re-instrumenting code. OTel (a CNCF project formed by merging OpenTracing and OpenCensus) separates "how you produce telemetry" from "where it goes".

What you already know that it resembles: Prometheus client libraries plus exporters, and Loki's promtail/Alloy shipping, but unified across three signals and with distributed tracing, which your Prometheus/Loki stack alone does not give you. You have Tempo already; OTel is how data gets into it.

## How it works

### Signals

- **Trace**: the record of one request across services. Made of spans.
- **Span**: one timed operation. Per the docs it has a name, parent span ID (empty for the root), start/end times, attributes, events, links and status.
- **Attributes**: key-value labels on a span (values are strings, booleans, numbers, or arrays of these).
- **Span kind**: Client (outgoing remote call), Server (incoming), Internal (in-process, the default), Producer/Consumer (async jobs).
- **Status**: Unset (default, no error), Error, Ok.
- **Metrics**: counters, histograms and gauges with attributes.
- **Logs**: log records, which can carry the current trace ID so you can jump from a log line to its trace.

Status of the signals: the Python instrumentation page says the "logs API & SDK are currently under development". The pages I opened do not state stability for traces or metrics. UNVERIFIED: that traces and metrics are stable in the spec and SDKs.

### Context propagation

In plain terms: to link spans from different programs, each program hands the tracking number to the next in an HTTP header.

Precisely: the sender serialises the span context (trace ID, span ID, flags, trace state) into headers ("inject"); the receiver reads them ("extract") and makes its spans children of the sender's span. The default propagator is W3C Trace Context, header `traceparent`, four dash-separated fields: version, trace ID, parent span ID, trace flags. Example from the docs: `00-a0892f3577b34da6a3ce929d0e0e4736-f03067aa0ba902b7-01`. A separate mechanism, baggage, carries arbitrary key-value pairs across services; do not put secrets in it.

### OTLP

In plain terms: the common language the stamps are written in. Precisely: OTLP can go over gRPC (default port 4317) or HTTP (4318). `OTEL_EXPORTER_OTLP_PROTOCOL` takes `grpc`, `http/protobuf` or `http/json`. With the base `OTEL_EXPORTER_OTLP_ENDPOINT` over HTTP, the SDK appends `/v1/traces`, `/v1/metrics`, `/v1/logs`; per-signal variables like `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` take the full URL. gRPC does not work from browsers.

### SDK vs auto-instrumentation

- **SDK + manual instrumentation**: you create a tracer provider, an exporter and spans in code (`tracer.start_as_current_span(...)`).
- **Auto-instrumentation**: libraries (FastAPI, HTTP clients, DB drivers) are wrapped so spans appear without code changes. Python: `opentelemetry-instrument <your command>`.
- **Kubernetes Operator injection**: an init container adds the Python agent to a pod via an annotation (below).

### The Collector

In plain terms: a relay station between your programs and your storage. Precisely: a standalone process with receivers (accept data, e.g. `otlp`), processors (modify: `memory_limiter`, `batch`, sampling), exporters (send to backends), connectors (join two pipelines) and extensions (health checks etc.). Configuring a component does not enable it; it must appear in a pipeline under `service`. Processors run in listed order, so `memory_limiter` goes first.

```
 browser SDK ----OTLP/HTTP----\                          /--> Tempo (traces)
 Traefik ---------OTLP--------->  Collector (gateway)  ---+--> Prometheus (metrics, OTLP receiver)
 FastAPI (SDK/auto) --OTLP---/   receivers->processors->  \--> Loki (logs, /otlp)
 LLM gateway ------OTLP------/        exporters
```

Deployment patterns (docs overview): **agent** (a Collector close to each workload, e.g. a DaemonSet or sidecar, which sends on) and **gateway** (signals go to a single OTLP endpoint, then to backends). The docs page I opened gave no pros/cons, so for a lab, one gateway Deployment is the simplest start; add agents only if you need per-node collection. UNVERIFIED: the DaemonSet/sidecar mapping and recommendations from my prior knowledge.

Distributions: UNVERIFIED which distribution (core vs contrib vs `opentelemetry-collector-k8s`) you need. The docs say the Tail Sampling Processor is in contrib, so check your distribution. The Operator page notes Helm-based installs use the `opentelemetry-collector-k8s` image.

## How you run it

### Collector config (gateway)

Components named here (`otlp` receiver, `memory_limiter`, `batch`) come from the Collector configuration page; endpoints and exporter wiring for the three backends are from each backend's docs. Exporter key names for your Collector version are UNVERIFIED: the Collector docs page I read used an exporter called `otlp_grpc`, while the Loki docs use `otlphttp`. I use `otlphttp` for all three; confirm it exists in your build with `otelcol-contrib components`.

```yaml
receivers:
  otlp:
    protocols:
      grpc: { endpoint: 0.0.0.0:4317 }   # 0.0.0.0 so other pods can reach it; default is localhost
      http:
        endpoint: 0.0.0.0:4318
        cors:                             # needed for browser export (see exporters docs)
          allowed_origins: ["https://app.example.com"]
          allowed_headers: ["*"]
processors:
  memory_limiter: { check_interval: 5s, limit_mib: 1500, spike_limit_mib: 300 }
  batch: {}
exporters:
  otlphttp/tempo:
    endpoint: http://tempo.monitoring.svc:4318        # Tempo distributor OTLP http receiver
  otlphttp/prom:
    metrics_endpoint: http://prometheus.monitoring.svc:9090/api/v1/otlp/v1/metrics   # UNVERIFIED key name
  otlphttp/loki:
    endpoint: http://loki.monitoring.svc:3100/otlp      # Loki native OTLP path /otlp
service:
  pipelines:
    traces:  { receivers: [otlp], processors: [memory_limiter, batch], exporters: [otlphttp/tempo] }
    metrics: { receivers: [otlp], processors: [memory_limiter, batch], exporters: [otlphttp/prom] }
    logs:    { receivers: [otlp], processors: [memory_limiter, batch], exporters: [otlphttp/loki] }
```

Backend requirements from their docs:
- **Tempo**: distributor `receivers.otlp.protocols.grpc/http`, default 4317/4318, both listening on localhost unless configured. Tempo version not stated on the page I read.
- **Prometheus**: the OTLP receiver is off by default; start with `--web.enable-otlp-receiver`; endpoint `/api/v1/otlp/v1/metrics`. By default no resource attributes become labels; list them under `otlp: promote_resource_attributes` (the page suggests `service.name`, `service.instance.id`, `k8s.pod.name`, `k8s.namespace.name`, ...). Delta temporality needs an experimental feature flag.
- **Loki**: endpoint `http://<loki>/otlp`; must use `otlphttp`; needs `allow_structured_metadata: true` (default on in Loki 3.0+). Listed resource attributes (17 defaults, e.g. `service.name`, `k8s.namespace.name`) become index labels, others become structured metadata. Entries above the structured-metadata limits (64KB, 128 entries per line) are rejected with HTTP 400, for example big `exception.stacktrace` values.

### Operator and the Instrumentation CRD

```bash
# prerequisite: cert-manager already installed (you have it)
kubectl apply -f https://github.com/open-telemetry/opentelemetry-operator/releases/latest/download/opentelemetry-operator.yaml
```
Installs the operator (the Operator page's command; it pins `latest`, so pin a version in GitOps; chart route UNVERIFIED).

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata: { name: demo-instrumentation, namespace: rag }
spec:
  exporter: { endpoint: http://otel-collector.observability.svc:4318 }   # Python uses http/protobuf, port 4318
  propagators: [tracecontext, baggage]
  sampler: { type: parentbased_traceidratio, argument: "0.1" }
```
Opt a workload in by adding to the pod template: `instrumentation.opentelemetry.io/inject-python: "true"` (value can also be an Instrumentation name or `namespace/name`; `"false"` disables). Create the Instrumentation before the app, or the `opentelemetry-auto-instrumentation` init container is not created. From operator v0.108.0 `OTEL_EXPORTER_OTLP_PROTOCOL` is set to `http/protobuf` for you. The Operator can also manage Collectors through an `OpenTelemetryCollector` resource (`opentelemetry.io/v1beta1` in the docs example); its `mode` values are UNVERIFIED.

### Instrument a FastAPI service

```bash
pip install opentelemetry-distro opentelemetry-exporter-otlp   # API, SDK, bootstrap/instrument tools + OTLP exporter
opentelemetry-bootstrap -a install                              # installs instrumentations for packages it detects
export OTEL_SERVICE_NAME=rag-api
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.observability.svc:4318
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_PYTHON_FASTAPI_EXCLUDED_URLS="healthz,metrics"      # regex list, skips noisy probes
opentelemetry-instrument uvicorn app:app --host 0.0.0.0 --port 8000
```
By default traces and metrics go OTLP/gRPC to `localhost:4317` (Python getting-started page). Whether `opentelemetry-bootstrap` picks up FastAPI: the docs page shows Flask; the FastAPI package is `opentelemetry-instrumentation-fastapi`. Code-level alternative: `FastAPIInstrumentor.instrument_app(app)` after creating the app, with optional `server_request_hook` to add attributes. UNVERIFIED: behaviour under `uvicorn --reload` or pre-fork gunicorn workers (the config page is silent); test with a single worker first.

Manual span with attributes (from the Python instrumentation page):
```python
with tracer.start_as_current_span("retrieve") as span:
    span.set_attribute("rag.top_k", 5)
```

### Instrument a React (browser) app

The browser page says client instrumentation is **experimental** and mostly unspecified. Packages: `@opentelemetry/api`, `core`, `sdk-trace`, `context-zone`, `instrumentation`, plus `instrumentation-document-load`, `instrumentation-user-interaction`, `instrumentation-xml-http-request`; meta package `@opentelemetry/auto-instrumentations-web`. The page's setup uses `TracerProvider` from `@opentelemetry/sdk-trace`, `ZoneContextManager`, and a composite of W3C trace-context and baggage propagators. For export, use an HTTP exporter (`@opentelemetry/exporter-trace-otlp-http` or `-proto`; gRPC does not work in browsers) with `url: '<endpoint>/v1/traces'`, and use `BatchSpanProcessor` instead of the console exporter. Constraints from the exporters page: the Collector must be reachable from users' browsers, CORS must allow your origin (Collector `cors.allowed_origins`), CSP `connect-src` must include the endpoint, and the page recommends a reverse proxy in front; Traefik can be that proxy with a route to the Collector's 4318 plus a rate limit. UNVERIFIED: the fetch instrumentation package (`@opentelemetry/instrumentation-fetch`) and its option to inject `traceparent` on cross-origin calls (`propagateTraceHeaderCorsUrls`); the pages I opened do not cover fetch. Your LLM calls from React are almost certainly `fetch`, so confirm this before relying on a browser-rooted trace.

### GenAI semantic conventions

Plain terms: an agreed vocabulary for labelling LLM calls, so every tool names "which model" and "how many tokens" the same way. Status: the old `opentelemetry.io/docs/specs/semconv/gen-ai/` pages now only say the conventions moved to `github.com/open-telemetry/semantic-conventions-genai`. The docs there carry status **Development** (not stable); only `error.type`, `server.address`, `server.port` are Stable. A third-party blog claimed stability; I did not verify it and the spec text above contradicts it. Expect renames.

Inference span (`docs/gen-ai/client-inference.md`, main branch):
- Span name `{gen_ai.operation.name} {gen_ai.request.model}`; kind CLIENT recommended (INTERNAL if the model runs in-process).
- Required: `gen_ai.operation.name` (e.g. `chat`, `embeddings`, `text_completion`, `generate_content`, `retrieval`, `execute_tool`, `invoke_agent`), `gen_ai.provider.name`.
- Conditionally required: `gen_ai.request.model`, `error.type`, `server.port`.
- Recommended: `gen_ai.request.temperature`, `gen_ai.request.max_tokens`, `gen_ai.response.id`, `gen_ai.response.model`, `gen_ai.response.finish_reasons`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`, `server.address`.
- Streaming: `gen_ai.request.stream` (only if streaming) and `gen_ai.response.time_to_first_chunk` (seconds).
- Opt-in (sensitive): `gen_ai.input.messages`, `gen_ai.output.messages`, system instructions, tool definitions. Content capture is controlled by `OTEL_INSTRUMENTATION_GENAI_CAPTURE_CONTENT` with `NO_CONTENT` (default), `SPAN_ONLY`, `EVENT_ONLY`, `SPAN_AND_EVENT`. This is the privacy switch; leave it off by default for any real data.

Metrics: `gen_ai.client.operation.duration`, `gen_ai.server.request.duration`, `gen_ai.server.time_to_first_token`, `gen_ai.server.time_per_output_token`; token counters `gen_ai.client.inference.usage.input_tokens` / `output_tokens` (plus cache and reasoning variants, with `gen_ai.token.modality`), and histograms `gen_ai.client.inference.operation.input_tokens` / `output_tokens`. The docs say to use the counters, not the histograms, for totals and cost. The older metric name `gen_ai.client.token.usage` is not on the current page (UNVERIFIED whether still emitted by older libraries).

Python helper: `opentelemetry-instrumentation-openai-v2` wraps the `openai` client (`OpenAIInstrumentor().instrument()`); docs show only `chat.completions.create`. By default it aligns with semantic conventions v1.30.0; `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` selects the latest, and `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` (`true` on the legacy path, else `span_only` / `event_only` / `span_and_event`) controls content. Pin that flag so dashboards survive spec churn. UNVERIFIED: that it works against an OpenAI-compatible NIM base URL (likely, since it wraps the client library, not the server); embeddings and streaming coverage are not documented on that page.

## How it fits the stack

A request "what does the policy say about leave?" end to end:

```
trace 4bf92f35...  (one trace ID)
 browser   [ui.ask  (click, fetch)                                      ] 2.9 s   <- root, if browser instrumentation works
   traefik   [router/service span                                     ]           (tracing.otlp, parent-based)
     fastapi   [POST /ask  (SERVER)                                 ]
        retrieve  [embeddings + vector search] 180 ms                   (gen_ai.operation.name=embeddings / retrieval)
        gateway   [chat {model}  (CLIENT)                         ] 2.5 s
           model     [inference service span, if instrumented]            (gen_ai.server.* metrics)
```
- Traefik exports its own spans with `tracing.otlp.*` (see 05-traefik.md) and, per its docs, inherits context from incoming requests; whether it forwards `traceparent` downstream is UNVERIFIED.
- FastAPI extracts `traceparent`, creates a SERVER span, and its outgoing HTTP client calls inject the header (requires the matching HTTP-client instrumentation, installed by `opentelemetry-bootstrap`).
- The LLM gateway and the model servers join the trace only if they themselves read `traceparent` and emit spans. UNVERIFIED for any specific gateway or NIM; if they do not, the trace shows a single long CLIENT span with gaps, and you fall back to their Prometheus metrics. Treat NIM/gateway tracing as a thing to test, not assume.
- Collector fans data to Tempo, Prometheus and Loki; in Grafana, link logs to traces via the trace ID (log records carry it when logging instrumentation is on; the logging path is the least stable signal).

## Sampling and cost

- **Head sampling**: decide at the start from the trace ID (e.g. keep 10%). Simple and cheap, but cannot guarantee error traces are kept. SDK sampler `parentbased_traceidratio` means: root spans sampled by ratio, children follow the parent, so a trace is whole or absent.
- **Tail sampling**: decide after seeing the whole trace (keep errors and slow ones). More useful, but stateful and resource-heavy; all spans of a trace must reach the same Collector instance. The Tail Sampling Processor is in contrib.
- They can combine: head-sample to protect the pipeline, tail-sample before export. The sampling page suggests sampling matters from roughly 1,000+ traces/second; below that, paying for storage is usually simpler.
- Cost drivers in an LLM stack: captured prompt/response content (large; off by default), high-cardinality metric attributes, Loki label cardinality (`k8s.pod.name` is called out as no longer recommended as a default index label), and 100% sampling from the browser.
- Practical lab setting: 100% in dev, `parentbased_traceidratio` at 0.1 in shared use, content capture off, probes excluded.

## What goes wrong

- **Nothing arrives in Tempo**: wrong protocol/port (Python operator injection needs HTTP 4318, not gRPC 4317); Collector bound to localhost (default) so other pods cannot reach it; the receiver/exporter configured but not listed in `service.pipelines`.
- **Broken traces (separate roots)**: a hop does not propagate `traceparent` (proxy stripping it, browser CORS, an uninstrumented gateway), or a service uses a different propagator.
- **Operator injection does nothing**: `Instrumentation` created after the app, annotation on the Deployment instead of the pod template, wrong language in annotation. Check `kubectl get events`.
- **Browser blocked**: CORS or CSP; or the Collector not reachable publicly.
- **Prometheus rejects OTLP**: receiver flag `--web.enable-otlp-receiver` missing, or labels you expected (`service_name`) missing because nothing is promoted.
- **Loki 400s or "malformed"**: `allow_structured_metadata` off, or oversized attributes.
- **Collector OOM / dropped data**: no `memory_limiter` first in the processor list, or tail sampling holding too many traces.
- **Sensitive data leaks**: GenAI content capture turned on; baggage carrying secrets; query strings in URL attributes.
- **Dashboards break after upgrade**: GenAI attribute names are Development status and change.
- **Health probes dominate trace volume**: exclude them with `OTEL_PYTHON_FASTAPI_EXCLUDED_URLS`.

## Check yourself

1. What are the four fields in a `traceparent` header, and what does a receiving service do with it?
2. What is the difference between a span's kind (Client/Server/Internal) and its status, and which would you look at to find a failing LLM call?
3. Why would the Operator's Python injection point at port 4318 rather than 4317, and what does it need to exist before the app is deployed?
4. Draw the Collector pipeline for traces, naming a receiver, two processors in the right order, and an exporter; what happens if the component is configured but not in `service.pipelines`?
5. What three settings must be right for OTLP metrics to land in Prometheus and OTLP logs to land in Loki?
6. Which GenAI attributes would you use to compute token cost per model, which metrics should you use for totals rather than histograms, and why is message content opt-in?
7. What is the status of the GenAI semantic conventions, and what do you do about that when building dashboards?
8. Explain head versus tail sampling, and what `parentbased_traceidratio` guarantees about a trace.
9. What would the trace look like if the LLM gateway does not propagate context, and how would you tell?

## References

All opened 2026-11-13.

- https://opentelemetry.io/docs/what-is-opentelemetry/
- https://opentelemetry.io/docs/concepts/signals/traces/
- https://opentelemetry.io/docs/concepts/context-propagation/
- https://opentelemetry.io/docs/concepts/sampling/
- https://opentelemetry.io/docs/languages/python/getting-started/
- https://opentelemetry.io/docs/languages/python/instrumentation/
- https://opentelemetry.io/docs/zero-code/python/ and /configuration/
- https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/
- https://opentelemetry.io/docs/languages/js/getting-started/browser/
- https://opentelemetry.io/docs/languages/js/exporters/
- https://opentelemetry.io/docs/languages/js/libraries/
- https://opentelemetry.io/docs/collector/, /configuration/, /deploy/
- https://opentelemetry.io/docs/platforms/kubernetes/operator/ and /operator/automatic/
- https://opentelemetry.io/docs/specs/semconv/gen-ai/ (redirect notice)
- https://github.com/open-telemetry/semantic-conventions-genai (and raw `docs/gen-ai/client-inference.md`, `gen-ai-spans.md`, `gen-ai-metrics.md`, `gen-ai-token-metrics.md`, `README.md`, `main` branch)
- https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html
- https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation-genai/openai.html
- https://grafana.com/docs/loki/latest/send-data/otel/
- https://grafana.com/docs/tempo/latest/configuration/ (first 100k characters only)
- https://prometheus.io/docs/guides/opentelemetry/
