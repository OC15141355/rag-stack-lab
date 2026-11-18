# Smoke tests as promotion gates

## The plain version

Before a model goes up a level (DEV → QA → PROD), a short automated test
checks that it answers, streams, uses tools and accepts long inputs. That
turns "the QA → PROD promotion is gated by smoke tests" into something real:
a pipeline job that either passes or blocks the merge. The script is
deliberately boring. It needs nothing but Python, so it runs in a locked-down
CI runner.

## The script

[`examples/smoke/smoke.py`](../../examples/smoke/smoke.py): stdlib only, any
OpenAI-compatible endpoint (a NIM directly, the gateway, or an inference
service).

| Check | What it proves | Failure usually means |
|---|---|---|
| `models` | `/v1/models` lists the target model | Wrong model ID, gateway mapping missing |
| `chat` | A plain completion returns content | Model not ready; reasoning ate the output budget (reported specifically) |
| `stream` | SSE arrives in many chunks, time-to-first-token under a limit, ends with `[DONE]` | **Buffering** somewhere (detected heuristically), timeouts |
| `tools` | N attempts all return well-formed `tool_calls` with valid JSON arguments | Tool-call parser not enabled or wrong on the NIM |
| `context` (opt-in) | A ~N-token prompt is accepted | Configured max context lower than expected |
| `auth-negative` (opt-in) | A request without credentials gets 401/403 | Gateway enforcement off, or NIM reachable directly |

```sh
export LLM_API_KEY=<key>
python examples/smoke/smoke.py --base-url https://<endpoint>/v1 --model <id> \
  --max-ttft 60 --context-tokens 100000 --expect-auth --json-report smoke-report.json
# gateway that wants a header instead of Bearer:
python examples/smoke/smoke.py ... --header 'x-bf-vk: <virtual key>'
# private CA:
python examples/smoke/smoke.py ... --ca-file /etc/ssl/certs/internal-ca.pem
```

Exit code 0 = no failures. The JSON report is the artifact to attach to the
promotion MR or keep in CI as the audit evidence.

## Verified against a fake endpoint

[`examples/smoke/mock_llm.py`](../../examples/smoke/mock_llm.py) is a tiny fake
server with three modes. Output from a run on 2026-11-19:

```
=== mode=good
[PASS] models: 1 models listed; target present
[PASS] chat: 0.0s, finish=stop, content='pong', usage={'prompt_tokens': 6, 'completion_tokens': 1}
[PASS] stream: 30 chunks, ttft=0.00s, total=1.65s, [DONE]=yes
[PASS] tools: 3/3 well-formed tool calls
[PASS] context: ~1000 tokens accepted in 0.0s (prompt_tokens=1003)
[PASS] auth-negative: request without credentials returned HTTP 401 (expected 401/403)
exit=0
=== mode=buffered
[FAIL] stream: 30 chunks, ttft=1.51s, total=1.51s, [DONE]=yes, LOOKS BUFFERED (all chunks arrived together)
exit=1
=== mode=notools
[FAIL] tools: 0/2 well-formed tool calls; last issue: no well-formed tool_calls (tool call may be in content as text: check tool-call parser)
[FAIL] context: ~60000 tokens rejected: HTTP 400: {"error": "context length 60003 exceeds 50000"}
exit=1
```

Run the self-test yourself:

```sh
MOCK_MODE=good PORT=18080 python3 examples/smoke/mock_llm.py &
LLM_API_KEY=test-key python3 examples/smoke/smoke.py --base-url http://127.0.0.1:18080/v1 --model test-model --expect-auth
kill %1
```

It has not been run against a real NIM or gateway yet. Expect to tune
`--max-ttft` and `--max-tokens` for reasoning models (GLM 5.2 thinks by
default, so first tokens can be slow and short budgets can come back empty).

## Using it as a gate

- **Where to point it:** gate on what consumers use. Test **through the
  gateway** for promotion. Also test the NIM service directly during
  diagnosis, to tell gateway problems from model problems.
- **Per environment thresholds:** QA should use PROD's thresholds; DEV can be
  looser.
- **Per model:** run once per model in the catalogue (doc 09's pipeline loops
  over them).
- **Flakiness:** tool calling is probabilistic. Use `--tool-attempts 3–5` and
  require all of them to pass for agentic-coding models. Record the rate over
  time.
- **What it doesn't test:** answer quality. Add a small eval set (fixed prompts
  with expected properties) as a separate, non-blocking job at first.

## Extending it

- Latency SLOs: add p50/p95 over several requests.
- Embeddings/rerank NIMs: add `/v1/embeddings` checks.
- JUnit output for GitLab test reports: convert the JSON report.
