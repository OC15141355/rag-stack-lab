# 6. Smoke tests

> **[MACRO: Page Properties]** Status DRAFT · Owner <author> · Last updated <date>

**Purpose:** the automated checks that gate model promotion (QA → PROD) and confirm a cutover, and how to run them.

## What gets tested

| Check | Proves | A failure usually means |
|---|---|---|
| **models** | `/v1/models` lists the model under its served name (e.g. `chat/<model>`) | Wrong model ID or gateway mapping |
| **chat** | A plain completion returns content | Model not ready; reasoning used the whole output budget |
| **stream** | Tokens arrive as many SSE chunks, first token within a limit, ends with `[DONE]` | **Buffering** in a proxy; timeouts |
| **tools** | N attempts all return well-formed `tool_calls` with valid JSON arguments | Tool-call parser not enabled on the NIM |
| **context** (optional) | A ~N-token prompt is accepted | Configured max context lower than expected |
| **auth-negative** (optional) | A request without credentials is rejected (401/403) | Gateway enforcement off, or NIM reachable directly |
| **speech** (to add) | `POST /v1/audio/transcriptions` with a short WAV returns text | Speech NIM not ready or wrong port (9000) |

## How to run

A single dependency-free Python script (standard library only, so it runs in restricted CI runners), pointed at any
OpenAI-compatible endpoint: the gateway (for promotion) or a NIM Service directly (for diagnosis).

```sh
export LLM_API_KEY=<key>
python smoke.py --base-url https://<endpoint>/v1 --model chat/<model> \
  --max-ttft 60 --context-tokens 100000 --expect-auth --json-report smoke-report.json
# gateway key in a header instead of Bearer:   --header 'x-bf-vk: <virtual key>'
# private CA:                                   --ca-file /path/internal-ca.pem
```

Exit code 0 = pass. The JSON report is attached to the promotion MR / kept as a CI artifact (audit evidence).
The script has been tested against a mock endpoint (pass, buffered-stream fail, tool-call fail); **not yet against a
Project endpoint.**

## Where it runs (gates)

| Stage | Target | Blocking? | Thresholds |
|---|---|---|---|
| After DEV deploy | DEV gateway (or NIM direct until Bifrost exists) | Yes | Loose |
| After QA deploy | QA gateway | **Yes, gates the PROD MR** | PROD thresholds |
| After PROD cutover | PROD gateway | Yes (triggers rollback) | PROD thresholds |

> **[MACRO: Info panel]** Reasoning models (GLM 5.2 thinks by default) need generous `--max-ttft` and `--max-tokens`,
> or `chat` comes back with empty content.

## Results (fill in per run)

| Date | Env | Model | models | chat | stream (TTFT) | tools | context | auth | Report |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | |

## Not covered (follow-ups)

- Answer quality: add a small eval set as a separate, initially non-blocking job.
- Latency SLOs (p50/p95 over several requests).
- Embedding/rerank endpoints if added.
