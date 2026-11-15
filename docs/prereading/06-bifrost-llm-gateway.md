# Bifrost — the LLM gateway

Version described: Bifrost HTTP gateway v2.5.1, released 10 Nov 2026 (GitHub releases page, checked 2026-11-15; core v1.15.2, framework v1.12.2). The Helm chart in `helm-charts/bifrost/Chart.yaml` on `main` read as chart 2.1.48 with appVersion 2.4.0, so the chart lags the gateway: pin `image.tag` yourself. Docs are at docs.getbifrost.ai. Items I could not confirm are marked `UNVERIFIED:`.

## In one paragraph

Bifrost is an open-source (Apache 2.0) LLM gateway written in Go by Maxim AI. It exposes one OpenAI-compatible API (plus Anthropic- and Gemini-style routes) in front of many model providers, and handles keys, retries, fallbacks, budgets, rate limits, caching, logging, metrics and MCP tool servers in one process. For a stack with a chat portal and coding agents (Cline) calling GLM 5.2 and Nemotron 3 Super on NVIDIA NIM endpoints, it would sit between the clients and the NIM services as the single place that holds provider keys, issues "virtual keys" to callers, and emits OpenTelemetry and Prometheus data. It plays the same role as LiteLLM, with a different design: Go instead of Python, a built-in web UI, and a config store in SQLite or PostgreSQL.

## The plain version

Think of a company switchboard. Staff do not memorise the direct number of every supplier. They ring one number, say who they are and what they need, and the operator connects them. The operator also knows each person's spending limit, can try a second supplier if the first is engaged, and writes every call in a log.

Bifrost is that operator for AI models. The chat portal and the coding assistant both talk to Bifrost in one common language. Bifrost decides which model server really answers, uses the right password for it, and counts what was used.

Without it, every app would hold its own copy of every model password and address. Changing a model would mean editing every app. Nobody could say who used how much, and one runaway coding agent could eat the whole budget. If a model server went down, each app would break in its own way.

Two things deserve care. First, the operator hears every conversation, so decide what the log is allowed to keep. Second, the operator must pass replies along as they arrive, a few words at a time. If anything in the middle waits for the full answer, chat feels frozen.

Five things to remember:

- Bifrost is a single front desk for model servers; apps never hold provider passwords.
- Callers get their own "virtual keys" with budgets and limits, so you can see and cap usage per person or app.
- Models are named `provider/model`, and the provider part is your own label.
- Settings can live in a file or in a database edited through the web UI; know which one wins.
- Logging can store full prompts. Decide that on purpose.

## Why it exists

A gateway solves the problems that appear once more than one app calls more than one model: provider credentials scattered across clients, no per-caller budget, no common retry or failover behaviour, no single place to measure latency and tokens, and every client needing a different SDK flavour. You already run LiteLLM for this, so the useful question is how Bifrost differs.

| Aspect | Bifrost | LiteLLM (your reference point) |
|---|---|---|
| Language | Go | Python |
| Licence | Apache 2.0 (repo README) | MIT core with enterprise-licensed parts (UNVERIFIED: re-check current LiteLLM licence text) |
| Config | `config.json` and/or DB-backed web UI | `config.yaml` and/or DB-backed admin UI |
| Auth | Virtual keys, `x-bf-vk` or Bearer | Virtual keys, Bearer |
| Governance | Budgets, rate limits, teams, customers (VK-level in OSS per the docs) | Keys, teams, budgets |
| Provider breadth | README says 23+ providers, "10,000+ models" | Broader long tail (UNVERIFIED: no count checked) |

Performance claims, with their source. All are vendor numbers; none is an independent test:

- README "Performance" section: sustained 5,000 RPS on AWS t3 instances, added latency 59 µs on t3.medium and 11 µs on t3.xlarge, 100% success. The README body also says "less than 15 µs"; the repo About text says "under 200 µs". The figures disagree with each other, so quote a range, not a number.
- Maxim blog and affiliated Dev.to posts: "40x", "50x" and "80x faster than LiteLLM" in different titles; one comparison at 500 RPS on t3.medium quotes p99 of 1.68 s against 90.72 s. The benchmark code is said to be public at `github.com/maximhq/bifrost-benchmarking` (UNVERIFIED: I did not read it).
- One third-party post measured roughly 0.08 ms overhead and noted it disappears into noise next to a real model call (UNVERIFIED: single anecdotal source).

For GPU-served reasoning models that take seconds per token burst, gateway overhead of microseconds versus hundreds of microseconds is not the deciding factor. Concurrency behaviour under many long streams and operational fit matter more. Test with your own load.

Enterprise versus open source: the README lists hierarchical budgets across teams and customers, OIDC login with directory sync, clustering, adaptive load balancing, guardrails and secrets management as enterprise features, though the docs do not always label each one cleanly (the virtual-key page describes team and customer budgets while another passage says rate limits are VK-level only). Check each feature against the plan before you design around it. UNVERIFIED: the exact OSS/enterprise boundary for each feature.

## How it works

### Request flow

In plain terms: a request arrives, is checked, routed to a provider key, sent upstream, and the answer is passed back and recorded.

1. Client calls an inference route such as `POST /v1/chat/completions`.
2. HTTP auth and governance run: the virtual key is looked up, budget and rate limits are checked, allowed providers and models are enforced.
3. Plugins run pre-hooks (cache lookup, routing rules, logging setup).
4. A provider key is picked by weight; the request goes upstream with retries.
5. On failure, fallbacks are tried in order.
6. Post-hooks record logs, metrics and traces; the response (or SSE stream) goes to the client.

### Provider/model naming

In plain terms: the model name says which supplier to use, then which product.

Models are written `provider/model`, for example `openai/gpt-4o-mini`. The prefix is the name of a provider entry in your Bifrost config, so for a custom provider called `nim` you send `nim/<model-id>`. The quickstart also says a bare model name works when Bifrost can resolve it through its Model Catalog. For predictability, always send the prefixed form. Only the first slash separates provider from model; model IDs that themselves contain slashes (NIM IDs often look like `org/model-name`) should still work as `nim/org/model-name`. UNVERIFIED: I did not test a model ID with an embedded slash.

### Configuration

In plain terms: settings can sit in a file, in a database edited by the web UI, or both, and the rules for who wins matter.

- Two modes (docs quickstart). DB-backed: config is stored in SQLite or PostgreSQL and edited through the UI or API; a present `config.json` seeds or reconciles it at startup. File-only: set `config_store.enabled` to `false`; the UI cannot edit config and changes need a restart. Omitting `config_store` does not give file-only; if `config.json` exists, a default SQLite config store is created.
- Reconciliation: each entity loaded from the file gets a content hash. Later UI edits persist in the DB, and re-applying an unchanged file does not overwrite them. Change an entity in the file and its new hash overwrites the DB copy. `source_of_truth: "config.json"` makes sections present in the file replace the matching DB state, and a present-but-empty section can prune rows. In the Helm chart this is `bifrost.sourceOfTruth` (`split` by default, or `config.json`).
- Practical rule for GitOps on Kubernetes: choose one owner. Either the file is authoritative (set source of truth to the file, treat the UI as read-only) or the UI is, with the file only seeding. Mixed use produces "I changed it and it came back" surprises.
- Secrets in the file use `env.VAR_NAME` references so values stay out of Git.
- Stores: config store (required for UI), logs store (optional), vector store (optional, for semantic cache). PostgreSQL must be 16 or later with UTF8 encoding.

### Providers and keys

In plain terms: a provider entry is a named supplier with an address and one or more keys.

Each provider has `keys` (each with a unique `name`, a `value` or `env.` reference, a `models` allow-list and a `weight`), a `network_config` (`base_url`, `default_request_timeout_in_seconds`, `max_retries`, backoff, `extra_headers`, TLS options, `stream_idle_timeout_in_seconds`) and concurrency settings.

For an OpenAI-compatible or NIM endpoint, use a custom provider whose `base_provider_type` is `openai`. NIM exposes an OpenAI-style API, so this is the natural fit. UNVERIFIED: whether Bifrost also ships a first-party `nvidia` provider; the docs I read list custom bases as `openai`, `anthropic`, `bedrock`, `cohere`, `gemini`, `replicate`, `typesafe`.

```json
{
  "providers": {
    "nim": {
      "keys": [
        { "name": "nim-key-1", "value": "env.NIM_API_KEY", "models": ["*"], "weight": 1.0 }
      ],
      "network_config": {
        "base_url": "http://nim-glm.llm.svc.cluster.local:8000",
        "default_request_timeout_in_seconds": 600,
        "max_retries": 1,
        "stream_idle_timeout_in_seconds": 300
      },
      "custom_provider_config": {
        "base_provider_type": "openai",
        "allowed_requests": {
          "chat_completion": true,
          "chat_completion_stream": true
        },
        "request_path_overrides": { "chat_completion": "/v1/chat/completions" }
      }
    }
  }
}
```

This sketch is assembled from the custom-provider page; the hostname, timeouts and the exact `base_url` convention (with or without `/v1`) are placeholders to verify, since `request_path_overrides` is joined to `base_url`. UNVERIFIED: whether an in-cluster NIM that needs no key still requires a dummy key value. A self-hosted NIM usually needs no auth; Bifrost key entries may still be required. Also note `allow_private_network` appears in `network_config`; UNVERIFIED: whether it must be enabled to reach cluster-internal or RFC1918 addresses. Test early.

If GLM 5.2 and Nemotron 3 Super are served by separate NIM deployments, create two providers (for example `nim-glm`, `nim-nemotron`), each with its own `base_url`. Model names then become `nim-glm/<id>`.

### Virtual keys and governance

In plain terms: a virtual key is a Bifrost-issued pass that carries its own limits, so callers never see provider keys.

- Header: `x-bf-vk` works for every key. Also accepted: `Authorization: Bearer sk-bf-...` (OpenAI style), `x-api-key` (Anthropic style), `x-goog-api-key`, `api-key` (Azure style).
- Interaction with HTTP auth: if Bifrost's own admin/HTTP auth is enabled, `Authorization` is consumed by that, so the virtual key must go in `x-bf-vk`. A virtual key in `Authorization` works only when `disable_auth_on_inference` is `true`. This is the key gotcha for clients that can only send a Bearer token.
- Budgets: a dollar `max_limit` with a `reset_duration` (1 minute to 1 year). Rate limits: token and request limits per period.
- Provider access is deny-by-default: only providers listed in the key's `provider_configs` are allowed, unless `allow_all_providers` is set. Within a provider, `key_ids` selects which provider keys the virtual key may use.
- Enforcement: governance is optional by default per the docs. Without `client.enforce_auth_on_inference: true` a request with no virtual key is allowed and gets no governance. One passage of the docs suggests new deployments have enforcement on by default; the docs contradict themselves, so read the stored value in the UI.
- Errors: missing key with enforcement on is 401 `virtual_key_required`; inactive or expired key 403 `access_blocked`; budget exceeded 402 `budget_exceeded`; rate limit 429; model or provider not allowed 403. The response for a wholly unknown key is not documented. UNVERIFIED: verify with the negative probe below.

### Fallbacks and load balancing

In plain terms: if one supplier fails, try the next; if you have several keys for one supplier, spread the load.

- Fallbacks go in the request body as a `fallbacks` array of `provider/model` strings. After the primary exhausts its retries, each fallback is tried in order. Each fallback gets its own retry budget.
- Retries: `max_retries` defaults to `0`. Network and 5xx errors retry on the same key with exponential backoff (defaults 500 ms initial, 5 s max). Per-key failures (429, rejected credentials) rotate to another key, only when more than one key exists.
- Key load balancing is by `weight`. Adaptive load balancing is described as enterprise.
- Whether fallbacks apply to streams generally is not stated. The docs describe buffering of startup metadata for Azure so early errors can fall back; once output has started, errors surface as stream errors. Assume no mid-stream failover. UNVERIFIED for non-Azure providers.
- Fallbacks are chosen by the caller (or by routing rules), not by a global config list. UNVERIFIED: whether a provider-level default fallback list exists. Cline cannot send a `fallbacks` body field, so a routing rule or governance setting would be needed for coding agents.

### Streaming and SSE

In plain terms: tokens are passed through as they arrive.

Streaming uses standard SSE (`stream: true`). Metrics exist for first-token and inter-token latency. `stream_idle_timeout_in_seconds` has a documented 120 s default; a reasoning model that thinks silently longer than that before its first token can be cut off, so raise it. v2.5.1 release notes say a panic during streaming no longer crashes the gateway and the client gets a terminal error frame.

### Tool calling passthrough

In plain terms: the model's request to run a tool is passed through untouched; Bifrost does not run it.

For ordinary chat completions, `tools` and `tool_calls` are part of the OpenAI schema and are forwarded to the provider. The MCP section describes a manual-approval default in which the model only suggests calls. UNVERIFIED: whether every field of a streamed tool-call delta survives translation for a custom `openai`-type provider; probe with the tool-call curl below on both models.

### Plugins and middleware

In plain terms: small modules hook in before and after each request.

Released plugin packages seen on the releases page: `telemetry`, `semanticcache`, `routing`, `prompts`, `otel`, `modelcatalogresolver`, `mocker`. Plugins are listed in the `plugins` array of `config.json`. Custom plugins and the hook interface (Go-based pre/post hooks) are mentioned in the README feature list, but I could not confirm the loading mechanism or execution order from the docs. UNVERIFIED: custom plugin loading and ordering.

### Semantic cache

In plain terms: if someone asks nearly the same question again, replay the old answer without calling the model.

Needs a vector store (Redis/Valkey, Weaviate, Qdrant or Pinecone) enabled in config. Two modes: semantic (needs an embedding provider and a matching `dimension`) and direct hash (`dimension: 1`, identical requests only). Caching engages only when the request sends `x-bf-cache-key` or a `default_cache_key` is set, which means Cline would not use it unless a default key is configured. Entries are scoped per virtual key and user by default. TTL defaults to 5 minutes, threshold 0.8. It is not provider prompt caching. For coding agents, whose prompts rarely repeat, expect little benefit and some privacy risk; for FAQ-style chat it can help.

### Logging

In plain terms: Bifrost can keep a record of every request, and that record may contain the full prompt.

- Request logs go to the logs store (SQLite `logs.db` in the app dir by default, or PostgreSQL). The Helm chart supports a separate PostgreSQL logs store and object storage.
- `client.enable_logging` turns logging on (default not stated in the docs). `client.disable_content_logging` (default `false`) strips message content from the log store and keeps metadata. `log_retention_days` defaults to 365. `logging_headers` lists request headers copied into log metadata.
- Content flags are separate per sink. The client flag does not stop OTLP export or other connectors; set `disable_content_logging` on the OTel plugin as well. Spans export full chat history and tool results by default.
- `allow_per_request_content_storage_override` (default `false`) lets a request send `x-bf-disable-content-logging` or `x-bf-store-raw-request-response` to override. Leave it off unless needed.
- To stop storing prompts: set `disable_content_logging: true` on the client and on the OTel plugin, set provider `store_raw_request_response` to false, keep the per-request override off, and shorten `log_retention_days`.

### Observability

In plain terms: Prometheus can scrape it, and it can push traces and metrics to an OpenTelemetry collector.

Prometheus: `/metrics` on the main port. Names include `http_requests_total`, `http_request_duration_seconds`, `bifrost_upstream_requests_total`, `bifrost_success_requests_total`, `bifrost_error_requests_total`, `bifrost_upstream_latency_seconds`, `bifrost_overhead_latency_microseconds`, `bifrost_input_tokens_total`, `bifrost_output_tokens_total`, `bifrost_cache_hits_total`, `bifrost_cost_total`, `bifrost_active_requests`, `bifrost_provider_key_up`, `bifrost_key_rotation_events_total`, `bifrost_request_retries`, `bifrost_stream_first_token_latency_seconds`, `bifrost_stream_inter_token_latency_seconds`, `bifrost_mcp_client_operation_duration_seconds`. Labels include `provider`, `model`, `virtual_key_id`, `virtual_key_name`, `team_id`, `fallback_index`, `selected_key_name`. Custom labels come from `client.prometheus_labels` or `x-bf-dim-*` request headers. Watch cardinality if you label per user (`user_labels_enabled` is opt-in).

OpenTelemetry: the `otel` plugin takes `collector_url` (OTLP; HTTP example `http://localhost:4318/v1/traces`, gRPC `host:4317`), `protocol` (`http` or `grpc`), `trace_type` (`genai_extension` is the released choice), `service_name` (default `bifrost`), `headers`, and optional metrics push (`metrics_enabled`, `metrics_endpoint`, 15 s default interval). Values accept `env.VAR_NAME`. This lines up with the GenAI conventions you read about in the OpenTelemetry primer.

### MCP gateway

In plain terms: Bifrost can also be the single doorway to tool servers, not just models.

It acts as an MCP client to upstream tool servers (STDIO, HTTP, SSE) and as an MCP server at `/mcp` for tools such as Cline, authenticated with a virtual key. Virtual keys carry tool allow-lists; headers `x-bf-mcp-include-tools` and `x-bf-mcp-include-clients` narrow a single request. Execution modes: manual approval (default), agent mode, and a code mode (gateway only). If Bifrost also serves MCP, the docs recommend disabling automatic tool injection to avoid duplicate tools. Whether you need this at all depends on whether tool access should be centrally governed; it can be left off.

## How you run it

- NPX: `npx -y @maximhq/bifrost`, optionally `--transport-version v2.4.0`; flags `-port`, `-host 0.0.0.0`, `-app-dir`.
- Docker: `docker run -p 8080:8080 -v $(pwd)/data:/app/data maximhq/bifrost`. Env vars `APP_PORT` and `APP_HOST`. Tags are versioned, for example `v2.4.0`; pin one.
- Default port 8080. The web UI is served at `http://localhost:8080`. `/health` is used for probes.
- Persistent storage: the app dir holds optional `config.json`, `config.db` (SQLite config) and `logs.db`. With PostgreSQL for config and logs you need no disk. A fresh instance has no admin password; set `BIFROST_SETUP_TOKEN` before exposing it.
- Helm:

```bash
helm repo add bifrost https://maximhq.github.io/bifrost/helm-charts
helm repo update
helm install bifrost bifrost/bifrost --set image.tag=<pinned-tag> -f my-values.yaml
```

  `image.tag` is required. `storage.mode` defaults to `sqlite` with a 10Gi PVC, deployed as a StatefulSet with one PVC per pod; the chart recommends PostgreSQL for production HA. Other values seen: `bifrost.sourceOfTruth`, `postgresql.external.*` (with `existingSecret`), `bifrost.providerSecrets`, and an `ingress` map. UNVERIFIED: the exact `replicaCount` key and the ingress example (README truncated in my read).
- Plain Kubernetes example (docs Terraform page): Service ClusterIP 80 to container 8080, HTTP probes on `/health` (liveness 30 s delay, readiness 10 s), container user 1000, `config.json` mounted from a Secret at `/app/data/config.json`, requests 250m CPU and 512Mi memory.
- Behind Traefik: it is a plain HTTP service. Route to it normally, and apply the streaming and timeout cautions from the Traefik primer.

## Pointing Cline at Bifrost

Settings in Cline's OpenAI Compatible provider:

- Base URL: Bifrost's docs for a comparable agent (Roo Code) use `http://<host>/openai`, i.e. the OpenAI-integration prefix, without a trailing `/v1`. A plain `http://<host>/v1` route also exists for inference. Cline appends paths itself, so test both `https://bifrost.example/openai` and `https://bifrost.example/v1`. UNVERIFIED: which form Cline needs; the docs I read have no Cline page.
- API key: put the virtual key here. Cline sends it as `Authorization: Bearer <key>`.
- Model ID: `provider/model` as Bifrost names it, for example `nim-glm/<model-id>`. Copy it from `GET /v1/models`.

The header risk: Cline's OpenAI Compatible provider has a custom headers option in recent versions (UNVERIFIED: I did not check Cline's current docs here; see the Cline primer). If it cannot send `x-bf-vk`, the Bearer route must work. Per the virtual-key docs, a virtual key with the `sk-bf-` prefix works in `Authorization: Bearer`, but only if HTTP auth on Bifrost is off for inference (`disable_auth_on_inference: true`). Older keys without the prefix need `x-bf-vk`. So decide: either keep Bifrost's admin auth off the inference path and use Bearer virtual keys, or set `x-bf-vk` in Cline's custom headers.

Probes (replace host and key):

```bash
H=https://bifrost.example; K=sk-bf-xxxx

# 1. models list
curl -s $H/v1/models -H "Authorization: Bearer $K" | head -c 600

# 2. chat
curl -s $H/v1/chat/completions -H "Authorization: Bearer $K" \
  -H 'Content-Type: application/json' \
  -d '{"model":"nim-glm/MODEL_ID","messages":[{"role":"user","content":"Say hi"}]}'

# 3. streaming: output must arrive in pieces, not at the end
curl -sN $H/v1/chat/completions -H "Authorization: Bearer $K" \
  -H 'Content-Type: application/json' \
  -d '{"model":"nim-glm/MODEL_ID","stream":true,"messages":[{"role":"user","content":"Count to 20"}]}'

# 4. tool call
curl -s $H/v1/chat/completions -H "Authorization: Bearer $K" \
  -H 'Content-Type: application/json' \
  -d '{"model":"nim-glm/MODEL_ID","messages":[{"role":"user","content":"Weather in Paris?"}],
       "tools":[{"type":"function","function":{"name":"get_weather","description":"Get weather",
       "parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}],
       "tool_choice":"auto"}'

# 5. negative probes: expect 401/403, never 200
curl -s -o /dev/null -w '%{http_code}\n' $H/v1/chat/completions \
  -H 'Content-Type: application/json' -d '{"model":"nim-glm/MODEL_ID","messages":[{"role":"user","content":"x"}]}'
curl -s -o /dev/null -w '%{http_code}\n' $H/v1/chat/completions -H "Authorization: Bearer sk-bf-wrong" \
  -H 'Content-Type: application/json' -d '{"model":"nim-glm/MODEL_ID","messages":[{"role":"user","content":"x"}]}'
```

If the no-key probe returns 200, enforcement is off and governance is not protecting anything. Also repeat probe 5 with a key whose provider list excludes the model; expect 403.

## Reading an existing Bifrost deployment

Questions to answer, and where to look:

- Which version runs? The image tag in the Deployment or values file; the UI footer or `/health` (UNVERIFIED: whether `/health` shows a version).
- Where does config live: file, DB, or both? Look for `config_store`, `bifrost.sourceOfTruth` / `source_of_truth`, and the mounted `config.json`.
- Which database? SQLite on a PVC or PostgreSQL (`storage.mode`, `postgresql.external`)? Single replica or several?
- What providers exist, and their `base_url`, timeouts, `max_retries`, `stream_idle_timeout_in_seconds`? UI Providers page.
- Which keys are real, and how are secrets injected (`env.` references, `bifrost.providerSecrets`, an external secrets operator)?
- Is `enforce_auth_on_inference` on? Is `disable_auth_on_inference` set? Is admin auth enabled and was `BIFROST_SETUP_TOKEN` used?
- What virtual keys exist, with which budgets, rate limits, and allowed providers (`provider_configs`, `allow_all_providers`)?
- Are fallbacks or routing rules configured, and who sets them?
- Is `enable_logging` on? Is `disable_content_logging` set, on the client and on the OTel plugin? What is `log_retention_days`, and which `logging_headers` are captured?
- Which plugins are enabled (semantic cache, otel, routing)? Is a vector store configured?
- Where do metrics go: a `ServiceMonitor` scraping `/metrics`, and an OTLP collector URL?
- How does Traefik route to it: timeouts, buffering, and any middleware that touches headers?

## What goes wrong

- Buffering behind ingress: a proxy or middleware that buffers responses turns streaming into one late burst. Disable response buffering on the route and check with the streaming probe through the real ingress, not just in-cluster.
- Model-name mismatch: the prefix is Bifrost's provider name, not the upstream vendor. A name that works against NIM directly fails against Bifrost until it is prefixed, and the reverse for models with slashes in the ID. Use `/v1/models` output.
- Key and header confusion: a virtual key in `Authorization` fails if admin auth owns that header; `x-bf-vk` is safe everywhere. A missing key succeeds if enforcement is off. Always run the negative probes.
- Timeouts on reasoning models: the default request timeout (the Go example uses 60 s) and 120 s stream-idle default can cut off long silent thinking. Raise both in Bifrost, and the ingress read timeout to match.
- Logging stores sensitive prompts: by default, content goes to the log DB for up to 365 days, and spans carry full chat history to the collector. Coding agents send source files. Turn off content logging at both sinks or accept it explicitly.
- SQLite with several replicas: each pod gets its own database, so UI changes made on one pod are not seen by another. Use PostgreSQL if running more than one replica.
- Config drift: UI edits persist over an unchanged file; changed file entries overwrite UI edits. Pick one owner.

## Check yourself

1. What does the prefix in `nim-glm/model-x` refer to, and where is it defined?
2. Which header works for every virtual key, and why might `Authorization: Bearer` fail on a given deployment?
3. A request with no key returns 200. Which setting do you check first?
4. You change a provider in the UI, then redeploy with an unchanged `config.json`. What happens to your change? What if you edit that provider in the file?
5. Name two places where full prompts can end up, and the flag that controls each.
6. Why is SQLite a poor fit for three replicas?
7. Cline's streamed answers arrive all at once. List three places to look.
8. Which published performance claim would you not rely on for a GPU-bound stack, and why?

## References

All checked 2026-11-15.

- GitHub repo and README: https://github.com/maximhq/bifrost
- Releases: https://github.com/maximhq/bifrost/releases
- Helm chart metadata and README: https://github.com/maximhq/bifrost/tree/main/helm-charts/bifrost
- Setting up the gateway: https://docs.getbifrost.ai/quickstart/gateway/setting-up
- Provider configuration: https://docs.getbifrost.ai/quickstart/gateway/provider-configuration
- Custom providers: https://docs.getbifrost.ai/providers/custom-providers
- Virtual keys: https://docs.getbifrost.ai/features/governance/virtual-keys
- Fallbacks: https://docs.getbifrost.ai/features/fallbacks
- Telemetry (Prometheus): https://docs.getbifrost.ai/features/telemetry
- OpenTelemetry plugin: https://docs.getbifrost.ai/features/observability/otel
- Semantic caching: https://docs.getbifrost.ai/features/semantic-caching
- MCP overview: https://docs.getbifrost.ai/mcp/overview
- Client settings: https://docs.getbifrost.ai/deployment-guides/config-json/client.md
- Kubernetes deployment: https://docs.getbifrost.ai/deployment-guides/k8s
- Roo Code integration (closest to Cline): https://docs.getbifrost.ai/cli-agents/roo-code.md
- Vendor benchmark write-ups: https://getmaxim.ai/blog/bifrost-a-drop-in-llm-proxy-40x-faster-than-litellm
