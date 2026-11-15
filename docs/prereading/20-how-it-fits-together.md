# How it fits together — the engineer's version

## In one paragraph

[The map](../00-map/README.md) names the parts and walks one request through
them. This document goes one level down. It covers what actually travels
between the parts, which part owns which job, and why the GPU end behaves the
way it does. It also covers how code reaches production, how you see inside a
running request, and where each kind of failure shows up. The last section is
about where a platform engineer adds value on a stack like this. Read it after
the map and before you open any repo: it gives you the questions the code
answers.

## The plain version

Think of the system as a restaurant.

The dining room (the chat portal) takes orders and remembers who ordered what.
The pass (the gateway, Bifrost) is where every order is checked: is this table
allowed to order, have they hit their limit, and which kitchen gets it. The
kitchens (the NIMs on GPUs) are expensive, have limited burners, and cook
several orders at once. A busy kitchen does not refuse an order. It makes you
wait, so the first sign of trouble is a slow first bite (time to first token),
not an error. The dish comes out a spoonful at a time (streaming), and every
hand it passes through must pass each spoonful on immediately rather than
waiting for the whole plate (buffering).

Behind the scenes there is a supply chain. Recipes are tested in a practice
kitchen (dev containers and Tilt), approved ingredients come only through the
loading dock (Harbor), and a manager decides which kitchen gets which burners
(Kubernetes and Volcano). Each order carries a ticket number (the trace ID)
that every station stamps, so when a meal is late you can find which station
held it.

Most "it's broken" reports come from three places: the pass rejects or
misroutes the order (key, model name), a hand in the chain holds the spoonfuls
(buffering or timeouts), or the kitchen is full (queueing, context length).

**Five things to remember**

1. There are three paths through the system: requests, delivery (code to
   production), and observation. Most confusion comes from mixing them up.
2. Every job has one owner: authentication, budgets, prompt building,
   retrieval, model routing. Learn who owns what and the code makes sense.
3. GPUs fail slowly, not loudly. Watch the queue and time to first token, not
   error rates.
4. Streaming is only as good as the worst hop in the chain.
5. The trace ID is your best friend. Learn to follow one request end to end
   before you need to.

## 1. Three paths, not one

The diagram in the map draws everything at once. Engineers think in three
separate paths:

| Path | What travels | Starts | Ends | You care when |
|---|---|---|---|---|
| **Request path** | HTTP requests and streamed tokens | A browser or Cline | A NIM on a GPU, then back | Something is slow, wrong or refused |
| **Delivery path** | Code, images, manifests, model weights | Your editor | A running pod | You change something, or a deploy breaks |
| **Observation path** | Traces, metrics, logs, conversation data | Every component | Dashboards, trace search, insights reports | You need to know *why* |

When you open a repo, first decide which path it belongs to. An inference
service is request path. A Helm chart, Tiltfile or `devcontainer.json` is
delivery path. A Collector config or insights pipeline is observation path.

## 2. The request path, at the level of actual bytes

### 2.0 One open question first: gateway, inference service, or both?

A stack like this can have two layers between the portal and the NIMs. One is
an **LLM gateway** (Bifrost): keys, budgets, routing. The other is an in-house
**inference service** (a Python/uv service exposing OpenAI-compatible routes).
The inference service might *be* the thing in front of Bifrost, sit behind it,
or be a separate path, for example for embeddings or RAG. This document writes
"gateway" for the hop that holds keys and routes models. Find out early which
layers actually exist and in what order. The `*_URL` settings in each repo
answer it: whoever points at the NIMs is the last hop.

### 2.1 What each hop receives and sends

Plain gloss: every hop gets an HTTP request, may add or remove something, and
passes it on. Knowing exactly what changes at each hop is most of debugging.

**Browser → Traefik.** An HTTPS POST to the portal hostname, with a session
cookie or an OIDC bearer token. The body is the portal's own format, not
OpenAI's. Typically it carries a conversation ID plus the new message.

**Traefik → portal backend.** Traefik terminates TLS, matches the host and path
to a route, and runs any middlewares, for example forward-auth to an identity
provider, headers, or rate limits. It also creates or continues a trace by
adding a `traceparent` header. Then it forwards plain HTTP to the portal
Service. The body is unchanged.

**Portal backend → gateway.** This is where the request becomes an
OpenAI-shaped call. The backend:
- authenticates the user and loads the conversation history from its database
- builds the `messages` array: system prompt, history (possibly trimmed to fit
  the context window), the new message, and retrieved documents once RAG
  exists
- chooses a model name and calls the gateway with a key the portal itself
  holds, not the user's.

```http
POST /v1/chat/completions
Authorization: Bearer <portal's gateway key>
traceparent: 00-<trace-id>-<span-id>-01
Content-Type: application/json

{"model": "<gateway's name for GLM>", "stream": true,
 "messages": [{"role":"system","content":"..."},
              {"role":"user","content":"..."}]}
```

**Gateway (Bifrost) → NIM.** The gateway checks the key, applies budgets and
rate limits, maps the public model name to a provider and its real model ID,
and forwards to the NIM's `/v1/chat/completions`. It may retry or fall back to
another model. It records usage (token counts, cost) and, depending on
configuration, the prompt and response. See
[06 Bifrost](06-bifrost-llm-gateway.md).

**NIM → back up the chain.** The NIM streams Server-Sent Events:

```
data: {"choices":[{"delta":{"content":"Hel"}}]}
data: {"choices":[{"delta":{"content":"lo"}}]}
data: {"choices":[{"delta":{}, "finish_reason":"stop"}], "usage":{...}}
data: [DONE]
```

Reasoning models may put their thinking in a separate field (often
`reasoning_content`) before the answer. Each hop must forward each `data:` line
as it arrives. The portal backend usually re-wraps them into its own event
format for the React app. Cline, talking to the gateway directly, consumes them
as they are.

**Cline's path is shorter.** Cline → (Traefik, if the gateway is exposed
through it) → gateway → NIM. There is no portal, conversation database or
retrieval in between. Cline builds its own enormous prompt (system prompt,
tools, file contents) and sends a `tools` array. That makes it the hardest
client the platform has to serve: the longest contexts, tool calling, long
streams, and many calls per task.

### 2.2 Who owns which job

Plain gloss: before reading code, know which component is *supposed* to do each
job; then check whether it actually does.

| Job | Usual owner | Questions to answer in the real system |
|---|---|---|
| TLS termination | Traefik | Which certs, from where (cert-manager? internal CA)? |
| User authentication | Traefik forward-auth or portal backend (OIDC) | Which IdP? Does the portal trust a header Traefik sets? |
| Service-to-service auth | Gateway keys (Bifrost virtual keys) | One key per client (portal, each developer, Cline)? |
| Budgets, rate limits | Gateway | Per user or per app? What happens on exceed: 429 or queue? |
| Conversation storage | Portal backend + its DB | Which DB? Retention? |
| Prompt construction | Portal backend | Where's the system prompt? How is history trimmed? |
| Retrieval (RAG) | Portal backend or a separate RAG server | Does the portal call retrieval itself, or a RAG service that calls the model? |
| Model routing, fallback | Gateway | Model name → which NIM? Any fallbacks? |
| Token generation | NIM (vLLM / SGLang / TensorRT-LLM inside) | Which engine, which profile, what max context? |
| Usage accounting | Gateway | Where do token counts go? Who reads them? |
| Prompt and response logging | Gateway and/or portal | Stored where, for how long, who can read it? |
| Conversation insights | Insights pipeline reading stored conversations | Reads from which store, how is privacy handled? |
| Trace propagation | Every hop | Does each hop forward `traceparent`? |

You'll often find a job done twice, for example auth in both Traefik and the
portal, or done nowhere, for example nobody trimming history. Both are
legitimate, useful findings.

### 2.3 Where the time goes

Plain gloss: a chat reply has two speeds, how long until the first word, and
how fast words come after that. They have different causes.

- **TTFT (time to first token)** = network hops + gateway overhead + **queue
  wait** + **prefill**. Prefill is the GPU reading the entire prompt. It grows
  with prompt length, so a Cline request carrying 80k tokens of files has a
  much longer TTFT than a chat "hi". Queue wait grows when the NIM is at its
  concurrency limit.
- **Decode speed (tokens/second per request)** depends on the model size, the
  GPU and how many other requests share the batch. More concurrent users gives
  more total throughput but slower per-user output.
- **Reasoning models** spend tokens thinking before the visible answer. To the
  user that looks like a long TTFT, even though tokens are flowing.

This is why timeouts belong at specific hops:

| Hop | Timeout to know | Failure if too short |
|---|---|---|
| Traefik entrypoint/transport | read/idle timeouts, `responseHeaderTimeout` | Long-prompt or reasoning requests cut off before the first token |
| Any nginx-style proxy | `proxy_read_timeout` (default 60s between reads), `proxy_buffering` | Streams cut, or delivered in one burst |
| Portal backend HTTP client | httpx/OpenAI client timeout | Portal shows an error while the model is still thinking |
| Gateway | per-provider request timeout | 504 from the gateway, with the NIM still generating |
| Cline | retries (3) | Repeated failures surface fast |

### 2.4 What happens at the GPU end

Plain gloss: a GPU's memory holds two things, the model itself and a scratchpad
for every conversation in progress. When the scratchpad fills, new requests
wait.

- **Weights.** The model's parameters, loaded once. Size ≈ parameters × bytes
  per parameter (FP8 = 1 byte, BF16 = 2, FP4 ≈ 0.5). A ~750B-parameter model at
  FP8 needs ~750 GB for weights alone. That's why it spans 8 large GPUs with
  **tensor parallelism**: each layer is split across GPUs, which talk over
  NVLink on every token.
- **KV cache.** For each request, the engine stores keys and values for every
  token so far, so it doesn't recompute them. It grows linearly with context
  length. Per token it costs roughly
  `2 × layers × kv_heads × head_dim × bytes`. For an illustrative model with 60
  layers, 8 KV heads, head_dim 128 and FP8, that's ~120 KB per token, so one
  128k-token conversation needs ~15 GB. Newer architectures compress this
  (latent attention, sparse attention, hybrid Mamba layers in Nemotron 3), so
  check the real model.
- **The trade.** GPU memory left after weights = KV cache pool. Pool ÷
  (context per request) = how many requests fit at once. A deployment can
  advertise a 1M-token window only by accepting very few concurrent long
  requests. This is why the configured max context is usually far below the
  model card's figure, and why it's a *platform* decision, not a model fact.
- **Continuous batching and paged attention.** Modern engines (vLLM, SGLang)
  add and remove requests from the running batch every step and allocate KV
  cache in pages. When the pool is full, new requests queue (`waiting`) and
  running ones may be preempted.
- **Prefix caching.** Requests sharing a prefix, such as the same system prompt
  or the same Cline system prompt and tools, can reuse cached KV, which
  shortens TTFT. Whether it's enabled is a profile/engine flag worth knowing.
- **NIM profiles.** A NIM picks an optimised profile (engine, precision, tensor
  parallelism, GPU type) at startup. `list-model-profiles` inside the container
  shows the options. The chosen profile is in the startup logs. Read them.

The metrics that tell you all of this come from the engine through the NIM's
`/v1/metrics`. Names vary by engine and version
(`UNVERIFIED: exact names for your engine version`). For vLLM they look like
`vllm:num_requests_running`, `vllm:num_requests_waiting` (UNVERIFIED: not on the metrics design page),
`vllm:kv_cache_usage_perc`, `vllm:time_to_first_token_seconds`,
`vllm:e2e_request_latency_seconds` (UNVERIFIED, as above),
`vllm:prompt_tokens_total` and `vllm:generation_tokens_total`. SGLang exposes
similar `sglang:` metrics. The four to graph first are **requests waiting, KV
cache usage, TTFT p95 and generation tokens/sec**.

### 2.5 What RAG changes

Plain gloss: RAG adds a lookup before the model call. It makes prompts bigger
and adds three more services that can be slow or wrong.

With RAG, between "build messages" and "call the gateway", something:
1. embeds the question (an embedding NIM, through the gateway or directly)
2. runs a hybrid query against OpenSearch (vectors plus keywords), and maybe a
   graph expansion in Neo4j
3. reranks the candidates (a reranking NIM)
4. puts the top chunks into the prompt, with citations.

Effects: the prompt is longer (higher TTFT, more KV cache), there are three
extra network calls (each needs a span), and a new class of failure appears
where the system works fine but answers wrongly because it retrieved the wrong
text. That last kind needs **evaluation**, not monitoring. See
[03](03-nvidia-rag-blueprint.md), [08](08-opensearch-elasticsearch-vector-search.md)
and [09](09-neo4j-graph.md).

## 3. The delivery path

Plain gloss: how a line of code you write ends up running on the cluster, and
how a multi-hundred-gigabyte model ends up on a GPU.

```
editor (dev container) → Tilt → image build (Podman/Buildah) → Harbor
   → manifests (Helm values / Kustomize) → Kubernetes on Tanzu/VKS
   → scheduler (default or Volcano) → pod on a node → image pulled from Harbor
```

- **Inner loop (minutes):** dev container + Tilt against a dev namespace. Tilt
  rebuilds and live-updates on save. See [13](13-dev-containers.md) and
  [14](14-tilt.md).
- **Outer loop (hours/days):** CI builds tagged images, pushes them to Harbor,
  and deployment manifests are updated, by GitOps (ArgoCD/Flux) or by
  pipeline-run Helm. Find out which; it decides where "the truth" of a
  deployment lives.
- **Disconnected or restricted environments:** nothing pulls from the
  internet. Images are mirrored into Harbor, and model weights are mirrored
  *separately* and pre-staged into a cache (a PVC, or NIM Operator `NIMCache`).
  A NIM pod that starts but sits for an hour is often downloading or loading
  weights. See [12](12-harbor-podman-images.md) and [01](01-nvidia-nim.md).
- **GPU placement:** NIM pods request `nvidia.com/gpu: N`. Volcano adds queues
  and gang scheduling, so an 8-GPU job either gets all 8 or waits instead of
  holding 5 and deadlocking. See [11](11-volcano-gpu-scheduling.md).
- **Tanzu/VKS specifics:** clusters are created through the vSphere supervisor;
  your kubeconfig is usually namespace-scoped. `kubectl auth can-i --list`
  tells you what you're allowed to do. See [10](10-vmware-tanzu-kubernetes.md).

When "my change isn't showing up", walk this chain. Did the image build? Did
the tag change? Was it pushed? Did the manifest reference it? Did the pod
restart? Is the pod pulling the tag you think it is?

## 4. The observation path

Plain gloss: three kinds of evidence (traces, metrics, logs) plus one special
kind (conversation insights), each answering different questions.

| Signal | Answers | Comes from | Lands in (typical) |
|---|---|---|---|
| Traces | "Where did *this* request spend its time?" | Traefik, FastAPI and httpx instrumentation, the gateway, the RAG server | Tempo/Jaeger/Zipkin via the OTel Collector |
| Metrics | "Is the system healthy *overall*?" | NIM `/v1/metrics`, gateway, Traefik, app | Prometheus → Grafana |
| Logs | "What exactly happened at this moment?" | Every pod | Loki/Elastic/OpenSearch |
| Gateway usage logs | "Who used how many tokens on which model?" | Bifrost | Its DB/log store |
| Conversation insights | "What are people using this for?" | Stored conversations → summarise → embed → cluster | An insights report ([17](17-clio-conversation-insights.md)) |

The thread that ties them together is the **W3C `traceparent` header**. If any
hop drops it, the trace breaks into two unrelated pieces. Checking that every
hop propagates it is a concrete, valuable early task. To correlate signals,
log lines should include the trace ID, and exemplars should link metrics to
traces. See [07](07-opentelemetry.md).

The GenAI semantic conventions (`gen_ai.*` attributes for model, token counts
and so on) are still at Development status, so attribute names shift between
library versions. Pin versions and expect churn.

## 5. Failure map: symptom → hop → where to look

| Symptom | Most likely hop | First thing to check |
|---|---|---|
| 401/403 immediately | Gateway or Traefik auth | Which key/header, and which component returned it (response headers, gateway logs) |
| 404 or "model not found" | Gateway | The model name the client sends vs the gateway's mapping (`/v1/models`) |
| 400 on tool requests | NIM | Tool-call parser / auto tool choice not enabled for that model |
| 400 "context length exceeded" | NIM | Configured max context vs prompt size; history trimming in the portal |
| Long wait, then the reply arrives all at once | Any proxy | Buffering: Traefik buffering middleware or forward-auth `forwardBody`, nginx `proxy_buffering`, the portal re-wrapping the stream |
| Cut off after ~60s | A proxy or client timeout | The timeout table in 2.3 |
| Slow first token, normal speed after | NIM queue or prefill | `requests_waiting`, KV cache usage, prompt size |
| Slow tokens throughout | NIM under load, or the wrong profile | Running request count, profile in the startup logs |
| 429 | Gateway | Budget or rate limit on that key |
| Empty answer from a reasoning model | NIM/gateway/client | Reasoning in `reasoning_content` while the client reads only `content`; output token limit hit during thinking |
| Correct-looking but wrong answer (RAG) | Retrieval | What was retrieved: log the chunks, run an eval set |
| Pod Pending | Scheduler | GPU requests vs free GPUs, Volcano queue, node taints |
| Pod running but NIM not ready for a long time | NIM startup | Weight download/cache, profile selection logs |
| Change not deployed | Delivery path | Image tag, pull policy, which manifest is the source of truth |

## 6. Where a platform engineer adds value here

Plain gloss: you don't need to know the codebase to contribute. You need to own
a cross-cutting concern that the application developers are too busy to own.

Concerns on a stack like this that usually have no owner, and that map
directly onto running a production LLM gateway:

1. **The gateway itself.** Model naming, keys per client, budgets, fallbacks,
   logging policy (what's stored, for how long), and a written "how to get a
   key and point a tool at it" page. This is the LiteLLM skill set, transferred.
2. **A streaming and timeout audit.** Walk every hop in 2.3 and record its
   buffering and timeout settings. Test with a long reasoning request and a
   100k-token prompt. This finds real bugs quickly.
3. **End-to-end tracing.** Prove a single trace spans Traefik → portal →
   gateway → NIM. Fix the hops that drop `traceparent`.
4. **The LLM serving dashboard.** Requests running/waiting, KV cache use, TTFT
   p50/p95, tokens/sec, and gateway errors by code and model. Add one alert:
   requests waiting > 0 for 5 minutes.
5. **Capacity notes.** For each model: profile, GPUs, configured max context,
   and measured concurrent users at acceptable TTFT. Use the arithmetic in 2.4
   to explain the trade-offs to non-specialists.
6. **An eval harness.** A small fixed set of prompts (chat, coding/tool calls,
   later RAG questions with known answers) run against each model and version
   change. This turns "the new version feels worse" into a number.
7. **Developer experience.** Make "Cline in the dev container against the
   gateway" a documented, tested path. Every developer benefits, and you need
   it anyway.
8. **Runbooks.** For each failure-map row: how to confirm, how to fix.

Pick one, ask whether anyone already owns it, and offer it as a scoped task
with a visible output (a doc, a dashboard, a test). That's how you become
useful before you understand all the code.

### Questions that show you understand the system

- "What max context does each NIM actually serve, and how did we pick it?"
- "Does the portal trim history, and what happens when a conversation exceeds
  the window?"
- "Is prefix caching on? Our system prompts and Cline's are long and shared."
- "Which hop owns user auth, and does the gateway know which user made a
  request, or only which app?"
- "Where are prompts and responses stored, and who can read them?"
- "Do traces currently connect from Traefik through to the NIM?"
- "Is deployment GitOps or pipeline-driven? Where's the source of truth for
  what's running?"
- "How are model weights staged, and how long does a cold NIM start take?"

## Check yourself

1. Name the three paths, and say which one a Tiltfile, a Bifrost config and a
   Collector config belong to.
2. A user waits 40 seconds, then the whole answer appears at once. Which two
   kinds of hop do you suspect, and what settings do you check?
3. Why does Cline stress the platform more than the chat portal does? Give
   three reasons.
4. Explain to a non-engineer why the model card says 1M tokens but the
   deployment allows far fewer.
5. Which four engine metrics do you graph first, and what does each one rising
   mean?
6. Where in the request path would you look for: a 429, a 400 on a tool call,
   an empty answer from a reasoning model?
7. A new image was pushed, but the old behaviour persists. Walk the delivery
   chain.
8. What breaks if one hop does not forward `traceparent`?

## References

The component docs in this folder carry the primary references. Extra sources
for this document (checked 2026-11-15):

- W3C Trace Context: https://www.w3.org/TR/trace-context/
- vLLM production metrics: https://docs.vllm.ai/en/latest/design/metrics/
- vLLM paged attention / automatic prefix caching: https://docs.vllm.ai/en/latest/design/prefix_caching/
- SGLang: https://docs.sglang.io/
- OpenAI chat completions streaming format: https://platform.openai.com/docs/api-reference/chat-streaming
- OpenTelemetry GenAI semantic conventions: https://github.com/open-telemetry/semantic-conventions-genai
