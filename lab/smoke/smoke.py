#!/usr/bin/env python3
"""Smoke tests for an OpenAI-compatible LLM endpoint (NIM, gateway, inference service).

Stdlib only, so it runs in restricted CI runners without installing anything.

Usage:
  python smoke.py --base-url https://gw.example.internal/v1 (--model <id> | --models-file models.json)
                  [--api-key-env LLM_API_KEY] [--header 'Name: value'] [--header-env x-bf-vk=BIFROST_VK]
                  [--expect-auth BODY_SUBSTRING] [--limit-burst N --limit-header-env x-bf-vk=BIFROST_VK_PROBE]
                  [--context-tokens 32000] [--max-ttft 30] [--skip tools] [--ca-file ca.pem] [--json-report out.json]

Exit code 0 = all checks passed (skipped checks don't fail), 1 = a check failed, 2 = usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

RESULTS: list[dict] = []
HOLD = False  # while True, record() defers printing so run_check() can annotate retries first
MAX_RETRY_AFTER = 30.0
DEFAULT_RETRY_AFTER = 2.0


def parse_retry_after(value) -> float:
    """Seconds to wait for a Retry-After header: default 2s if absent/negative/non-numeric, capped at 30s."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER
    if v != v or v < 0 or v == float("inf"):  # NaN, negative, infinite
        return DEFAULT_RETRY_AFTER
    return min(v, MAX_RETRY_AFTER)


def emit(r: dict) -> None:
    print(f"[{r['status']}] {r['check']}: {r['detail']}", flush=True)


def record(name: str, ok: bool | None, detail: str, **extra) -> None:
    status = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
    RESULTS.append({"check": name, "status": status, "detail": detail, **extra})
    if not HOLD:
        emit(RESULTS[-1])


def run_check(c: "Client", name: str, fn) -> None:
    """Run one check; annotate its results with any 429 retries it needed (PASS becomes PASS*)."""
    global HOLD
    n0, snap = len(RESULTS), c.snapshot()
    HOLD = True
    try:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            record(name, False, f"error: {e}")
        calls, count, slept = c.since(snap)
        for r in RESULTS[n0:]:
            if calls:
                r.update(retried_calls=calls, retries=count, retry_sleep=round(slept, 2))
                r["detail"] += f" (retried {count}x across {calls} call(s), slept {slept:.1f}s)"
                if r["status"] == "PASS":
                    r["status"] = "PASS*"
            emit(r)
    finally:
        HOLD = False


class Client:
    def __init__(self, base_url: str, api_key: str | None, headers: dict[str, str], timeout: float, ca_file: str | None):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = headers
        self.timeout = timeout
        self.retries = 3
        self.no_retry = False
        self.retried_calls = self.retries_total = 0  # calls needing >=1 retry / total retries
        self.retry_sleep = 0.0
        self.last_retry_after: str | None = None  # Retry-After of the last un-retried 429
        self.ctx = ssl.create_default_context(cafile=ca_file)  # ca_file: private CA bundle (PEM); never disable verification

    def _req(self, method: str, path: str, body: dict | None, auth: bool = True) -> urllib.request.Request:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        h.update(self.headers if auth else {})
        if auth and self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(body).encode() if body is not None else None
        return urllib.request.Request(self.base + path, data=data, headers=h, method=method)

    def snapshot(self) -> tuple[int, int, float]:
        return self.retried_calls, self.retries_total, self.retry_sleep

    def since(self, snap: tuple[int, int, float]) -> tuple[int, int, float]:
        return (self.retried_calls - snap[0], self.retries_total - snap[1], self.retry_sleep - snap[2])

    def _backoff(self, e: urllib.error.HTTPError, attempt: int) -> None:
        delay = parse_retry_after(e.headers.get("Retry-After"))
        if attempt == 0:
            self.retried_calls += 1
        self.retries_total += 1
        self.retry_sleep += delay
        time.sleep(delay)

    def call(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> tuple[int, dict | str]:
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(self._req(method, path, body, auth), timeout=self.timeout, context=self.ctx) as r:
                    raw = r.read().decode()
                    try:
                        return r.status, json.loads(raw)
                    except json.JSONDecodeError:
                        return r.status, raw
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < self.retries and not self.no_retry:
                    self._backoff(e, attempt)
                    continue
                self.last_retry_after = e.headers.get("Retry-After")
                return e.code, e.read().decode(errors="replace")[:500]
        return 429, "retries exhausted"

    def stream(self, body: dict):
        """Yield (seconds_since_start, parsed_event_or_None_for_DONE)."""
        for attempt in range(self.retries + 1):  # retry 429 on connect, same policy as call()
            try:
                r = urllib.request.urlopen(self._req("POST", "/chat/completions", body), timeout=self.timeout, context=self.ctx)
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt >= self.retries or self.no_retry:
                    raise
                self._backoff(e, attempt)
        start = time.monotonic()  # after connect, so TTFT excludes retry sleeps
        with r:
            for line in r:
                line = line.decode().strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                t = time.monotonic() - start
                if payload == "[DONE]":
                    yield t, None
                    return
                yield t, json.loads(payload)


def message_text(msg: dict) -> tuple[str, str]:
    """Return (content, reasoning). Reasoning models may put text in reasoning_content/reasoning."""
    return (msg.get("content") or ""), (msg.get("reasoning_content") or msg.get("reasoning") or "")


def check_models(c: Client, model: str) -> None:
    code, body = c.call("GET", "/models")
    if code != 200 or not isinstance(body, dict):
        return record("models", False, f"HTTP {code}: {str(body)[:200]}")
    ids = [m.get("id") for m in body.get("data", [])]
    record("models", model in ids, f"{len(ids)} models listed; target {'present' if model in ids else 'MISSING'}", models=ids)


def check_chat(c: Client, model: str, max_tokens: int) -> None:
    t0 = time.monotonic()
    code, body = c.call("POST", "/chat/completions", {
        "model": model, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": "Reply with exactly the word: pong"}],
    })
    dt = time.monotonic() - t0
    if code != 200 or not isinstance(body, dict):
        return record("chat", False, f"HTTP {code}: {str(body)[:200]}")
    choice = body["choices"][0]
    content, reasoning = message_text(choice.get("message", {}))
    usage = body.get("usage", {})
    if not content and reasoning:
        return record("chat", False, f"empty content but reasoning present (finish={choice.get('finish_reason')}); "
                      "raise max_tokens or check reasoning parser", seconds=round(dt, 2))
    record("chat", bool(content), f"{dt:.1f}s, finish={choice.get('finish_reason')}, content={content[:40]!r}, usage={usage}",
           seconds=round(dt, 2))


def check_stream(c: Client, model: str, max_ttft: float) -> None:
    body = {"model": model, "stream": True, "max_tokens": 200,
            "messages": [{"role": "user", "content": "Count from 1 to 30, comma separated."}]}
    times, done = [], False
    try:
        for t, ev in c.stream(body):
            if ev is None:
                done = True
                break
            delta = (ev.get("choices") or [{}])[0].get("delta", {})
            if any(delta.get(k) for k in ("content", "reasoning_content", "reasoning")):
                times.append(t)
    except Exception as e:  # noqa: BLE001
        return record("stream", False, f"error: {e}")
    if not times:
        return record("stream", False, "no content chunks received")
    ttft, total = times[0], times[-1]
    spread = total - ttft
    # Buffering heuristic: many chunks that all arrive within a tiny window at the end.
    buffered = len(times) > 5 and spread < 0.05 * max(total, 0.001) and total > 1.0
    ok = done and ttft <= max_ttft and not buffered
    record("stream", ok, f"{len(times)} chunks, ttft={ttft:.2f}s, total={total:.2f}s, [DONE]={'yes' if done else 'no'}"
           + (", LOOKS BUFFERED (all chunks arrived together)" if buffered else ""),
           ttft=round(ttft, 3), chunks=len(times))


def check_tools(c: Client, model: str, attempts: int) -> None:
    tool = {"type": "function", "function": {
        "name": "get_weather", "description": "Get the weather for a city",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}
    good = 0
    last = ""
    for _ in range(attempts):
        code, body = c.call("POST", "/chat/completions", {
            "model": model, "tool_choice": "auto", "tools": [tool], "max_tokens": 512,
            "messages": [{"role": "user", "content": "What's the weather in Sydney? Use the tool."}]})
        if code != 200 or not isinstance(body, dict):
            last = f"HTTP {code}: {str(body)[:200]}"
            continue
        calls = body["choices"][0].get("message", {}).get("tool_calls") or []
        try:
            if calls and json.loads(calls[0]["function"]["arguments"]).get("city"):
                good += 1
            else:
                last = "no well-formed tool_calls (tool call may be in content as text: check tool-call parser)"
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            last = f"invalid tool arguments: {e}"
    record("tools", good == attempts, f"{good}/{attempts} well-formed tool calls" + (f"; last issue: {last}" if last and good < attempts else ""),
           good=good, attempts=attempts)


def check_context(c: Client, model: str, tokens: int) -> None:
    # ~1 token per "word " for most tokenizers; approximate on purpose.
    prompt = "word " * tokens + "\nReply with OK."
    t0 = time.monotonic()
    code, body = c.call("POST", "/chat/completions", {
        "model": model, "max_tokens": 16, "messages": [{"role": "user", "content": prompt}]})
    dt = time.monotonic() - t0
    if code == 200 and isinstance(body, dict):
        pt = body.get("usage", {}).get("prompt_tokens")
        return record("context", True, f"~{tokens} tokens accepted in {dt:.1f}s (prompt_tokens={pt})", seconds=round(dt, 2))
    record("context", False, f"~{tokens} tokens rejected: HTTP {code}: {str(body)[:200]}")


def check_auth(c: Client, model: str, body_substring: str) -> None:
    # _req sends no gateway headers or bearer key when auth=False
    code, body = c.call("POST", "/chat/completions", {"model": model, "max_tokens": 4,
                        "messages": [{"role": "user", "content": "hi"}]}, auth=False)
    text = json.dumps(body) if not isinstance(body, str) else body
    ok = code in (401, 403) and body_substring.lower() in text.lower()
    record("auth-negative", ok, f"unauthenticated -> HTTP {code}; gateway body {'matched' if ok else 'NOT matched'} ({body_substring!r})")


def check_limit(c: Client, model: str, n: int, probe_headers: dict, expect_body: str) -> None:
    """Burst n chats with the low-limit probe key (no bearer, no retry): 1-2 must be 200, a later one 429 w/ marker."""
    saved = (c.headers, c.api_key, c.no_retry)
    c.headers, c.api_key, c.no_retry = {**c.headers, **probe_headers}, None, True
    results, retry_after = [], None
    try:
        for _ in range(n):
            code, body = c.call("POST", "/chat/completions", {"model": model, "max_tokens": 1,
                                "messages": [{"role": "user", "content": "hi"}]})
            results.append((code, body))
            if code == 429 and retry_after is None:
                retry_after = c.last_retry_after
    finally:
        c.headers, c.api_key, c.no_retry = saved
    codes = [r[0] for r in results]
    first_ok = n >= 3 and codes[:2] == [200, 200]
    hit = next((b for code, b in results[2:] if code == 429), None)
    text = "" if hit is None else (hit if isinstance(hit, str) else json.dumps(hit))
    marker = expect_body.lower() in text.lower()
    ok = first_ok and hit is not None and marker
    why = ("" if ok else "; requests 1-2 must be 200" if not first_ok
           else "; no 429 after request 2" if hit is None else f"; 429 body lacks {expect_body!r}")
    record("limit-429", ok, f"{n} rapid probe-key requests -> codes {codes}, Retry-After={retry_after}{why}",
           codes=codes, retry_after=retry_after)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True, help="endpoint root including /v1")
    p.add_argument("--model", required=False, help="single model id (alternative to --models-file)")
    p.add_argument("--api-key-env", default="LLM_API_KEY", help="env var holding the bearer key (default LLM_API_KEY)")
    p.add_argument("--header", action="append", default=[], help="extra header 'Name: value' (repeatable)")
    p.add_argument("--timeout", type=float, default=300)
    p.add_argument("--max-ttft", type=float, default=60, help="max seconds to first streamed token")
    p.add_argument("--max-tokens", type=int, default=256)
    p.add_argument("--tool-attempts", type=int, default=3)
    p.add_argument("--context-tokens", type=int, default=0, help="also test a prompt of ~N tokens (0 = skip)")
    p.add_argument("--header-env", action="append", default=[],
                   help="header from env var: 'Header-Name=ENV_VAR' (value never on argv)")
    p.add_argument("--models-file", help="models.json from the catalogue; runs checks per model")
    p.add_argument("--expect-auth", metavar="BODY_SUBSTRING",
                   help="assert unauthenticated requests are rejected 401/403 with this substring in the body")
    p.add_argument("--expect-limit", metavar="BODY_SUBSTRING",
                   help="substring the gateway's 429 body must contain (required with --limit-burst)")
    p.add_argument("--require-negative-checks", action="store_true",
                   help="fail (not silently skip) when --expect-auth or --limit-burst is not given")
    p.add_argument("--max-retried-calls", type=int, default=3,
                   help="fail the run if more than K calls needed 429 retries (default 3)")
    p.add_argument("--require-revision", action="store_true", help="fail if SYNC_REVISION is not set")
    p.add_argument("--limit-burst", type=int, default=0,
                   help="send N quick 1-token chats without retry using --limit-header-env; pass only if one gets 429")
    p.add_argument("--limit-header-env", default="",
                   help="'Header-Name=ENV_VAR' for the low-limit probe key (separate from the main key)")
    p.add_argument("--skip", action="append", default=[], choices=["models", "chat", "stream", "tools"])
    p.add_argument("--ca-file", help="PEM bundle for a private CA (default: system trust store)")
    p.add_argument("--json-report", help="write results as JSON to this path")
    a = p.parse_args()
    if not a.model and not a.models_file:
        p.error("one of --model or --models-file is required")
    if a.expect_auth is not None and not a.expect_auth.strip():
        p.error("--expect-auth needs a non-empty body substring")
    if a.expect_limit is not None and not a.expect_limit.strip():
        p.error("--expect-limit needs a non-empty body substring")
    if a.limit_burst and "=" not in a.limit_header_env:
        p.error("--limit-burst requires --limit-header-env 'Header-Name=ENV_VAR'")
    if a.limit_burst and not a.expect_limit:
        p.error("--limit-burst requires --expect-limit BODY_SUBSTRING")

    headers = {}
    if a.header:
        print("warning: --header values appear in process lists (argv); use --header-env for anything secret", file=sys.stderr)
    for h in a.header:
        if ":" not in h:
            p.error(f"bad --header {h!r}")
        k, v = h.split(":", 1)
        headers[k.strip()] = v.strip()
    for h in a.header_env:
        if "=" not in h:
            p.error(f"bad --header-env {h!r}")
        k, var = h.split("=", 1)
        if var not in os.environ:
            p.error(f"--header-env: ${var} not set")
        headers[k.strip()] = os.environ[var]
    c = Client(a.base_url, os.environ.get(a.api_key_env), headers, a.timeout, a.ca_file)

    if a.model:
        models = [{"id": a.model, "capabilities": ["chat", "stream", "tools"]}]
    else:
        try:
            with open(a.models_file) as f:
                models = json.load(f)["models"]
            if not isinstance(models, list) or not models:
                raise ValueError("'models' must be a non-empty list")
            for i, m in enumerate(models):
                if not isinstance(m, dict) or not (m.get("id") or m.get("alias")):
                    raise ValueError(f"models[{i}] needs an 'id' or 'alias'")
                if not isinstance(m.get("capabilities"), list):
                    raise ValueError(f"models[{i}] needs a 'capabilities' list")
        except (OSError, ValueError, KeyError, TypeError) as e:  # JSONDecodeError is a ValueError
            print(f"error: bad --models-file {a.models_file}: {e!r}", file=sys.stderr)
            return 2
    first = models[0].get("id") or models[0]["alias"]
    for m in models:
        mid = m.get("id") or m["alias"]
        print(f"--- model {mid}")
        for name, fn in (("models", lambda: check_models(c, mid)), ("chat", lambda: check_chat(c, mid, a.max_tokens)),
                         ("stream", lambda: check_stream(c, mid, a.max_ttft)), ("tools", lambda: check_tools(c, mid, a.tool_attempts))):
            if name in a.skip or (name == "tools" and "tools" not in m["capabilities"] and not a.model):
                record(name, None, "skipped")
                continue
            run_check(c, name, fn)
        if a.context_tokens:
            run_check(c, "context", lambda: check_context(c, mid, a.context_tokens))
    if a.expect_auth:
        run_check(c, "auth-negative", lambda: check_auth(c, first, a.expect_auth))
    else:
        record("auth-negative", False if a.require_negative_checks else None,
               "required but --expect-auth not given" if a.require_negative_checks else "not requested (no --expect-auth)")
    if a.limit_burst:
        k, var = a.limit_header_env.split("=", 1)
        if var not in os.environ:
            p.error(f"--limit-header-env: ${var} not set")
        run_check(c, "limit-429", lambda: check_limit(c, first, a.limit_burst, {k.strip(): os.environ[var]}, a.expect_limit))
    else:
        record("limit-429", False if a.require_negative_checks else None,
               "required but --limit-burst not given" if a.require_negative_checks else "not requested (no --limit-burst)")
    if c.retried_calls > a.max_retried_calls:
        record("retry-budget", False, f"{c.retried_calls} calls needed 429 retries (max {a.max_retried_calls}); gateway is shedding load")
    revision = os.environ.get("SYNC_REVISION")
    if not revision:
        print("warning: SYNC_REVISION not set; this run is not tied to a synced revision", file=sys.stderr)
        if a.require_revision:
            record("revision", False, "SYNC_REVISION required but not set")
    revision = revision or "unknown"

    failed = [r for r in RESULTS if r["status"] == "FAIL"]
    passed = [r for r in RESULTS if r["status"] in ("PASS", "PASS*")]
    skipped = [r for r in RESULTS if r["status"] == "SKIP"]
    print(f"\n{len(passed)} passed, {len(skipped)} skipped, {len(failed)} failed")
    if not passed:
        print("FAIL: no check passed")
    print(f"revision={revision}")
    if a.json_report:
        with open(a.json_report, "w") as f:
            json.dump({"base_url": a.base_url, "model": a.model, "models": [m.get("id") or m["alias"] for m in models],
                       "revision": revision, "retried_calls": c.retried_calls, "retries": c.retries_total,
                       "retry_sleep": round(c.retry_sleep, 2), "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                       "results": RESULTS}, f, indent=2)
    return 1 if failed or not passed else 0


if __name__ == "__main__":
    sys.exit(main())
