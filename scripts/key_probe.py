#!/usr/bin/env python3
"""Probe whether an NVIDIA key works, reading the key from STDIN only. Prints status codes, never the key.

  hosted [--chat MODEL]          GET <hosted>/v1/models (and one 4-token chat call if --chat)
  nvcr --repo R --tag T          registry token for R (Basic $oauthtoken:<key>), then the manifest of R:T;
                                 prints the manifest digest
A 200 from /v1/models proves nothing about the key (it is served without auth), so `hosted` without --chat
reports INCONCLUSIVE, never ACCEPTED: always pass --chat for a verdict. Redirects are refused.
Exit: 0 = key accepted (all calls 200), 1 = key REJECTED (a 401/403 anywhere), 2 = anything else
(network error, 404, 429, 5xx): proves nothing about the key.
Usage:  age -d -i <identity> <key.age> | python3 scripts/key_probe.py hosted --chat meta/llama-3.1-8b-instruct
Endpoints can be overridden for tests: KEY_PROBE_HOSTED (default https://integrate.api.nvidia.com),
KEY_PROBE_REGISTRY (default https://nvcr.io).
"""
from __future__ import annotations
import argparse, base64, json, os, re, sys, urllib.error, urllib.parse, urllib.request

UA = "raglab-key-probe/1.0"
MANIFEST_TYPES = ", ".join([
    "application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"])


class Rejected(Exception):
    pass


class Inconclusive(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Inconclusive(f"refusing HTTP {code} redirect (credentials are never sent to a redirect target)")


OPENER = urllib.request.build_opener(NoRedirect)


def call(url: str, headers: dict, body: dict | None = None, method: str | None = None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, method=method,
                                 headers={"User-Agent": UA, **headers,
                                          **({"Content-Type": "application/json"} if body else {})})
    try:
        with OPENER.open(req, timeout=60) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), b""
    except urllib.error.URLError as e:
        raise Inconclusive(f"network error: {e.reason}")


def expect_ok(what: str, code: int):
    print(f"{what}: HTTP {code}")
    if code in (401, 403):
        raise Rejected(what)
    if code != 200:
        raise Inconclusive(what)


def hosted(key: str, chat: str | None):
    base = os.environ.get("KEY_PROBE_HOSTED", "https://integrate.api.nvidia.com").rstrip("/")
    auth = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    code, _, body = call(f"{base}/v1/models", auth)
    expect_ok("GET /v1/models", code)
    if not chat:
        raise Inconclusive("/v1/models alone proves nothing about the key; rerun with --chat MODEL")
    if chat:
        ids = {m.get("id") for m in json.loads(body or b"{}").get("data", [])}
        print(f"model {chat} listed: {chat in ids}")
        code, _, _ = call(f"{base}/v1/chat/completions", auth, {
            "model": chat, "max_tokens": 4, "messages": [{"role": "user", "content": "Reply with OK."}]})
        expect_ok(f"POST /v1/chat/completions ({chat})", code)


def realm_ok(realm: str, overridden: bool) -> bool:
    if overridden:      # tests point the registry at a local mock explicitly
        return True
    u = urllib.parse.urlparse(realm)
    # nvcr.io's real challenge points at https://authn.nvidia.com/proxy_auth, so nvidia.com is allowed too
    h = u.hostname or ""
    return u.scheme == "https" and any(h == d or h.endswith("." + d) for d in ("nvcr.io", "nvidia.com"))


def nvcr(key: str, repo: str, tag: str):
    reg = os.environ.get("KEY_PROBE_REGISTRY", "https://nvcr.io").rstrip("/")
    murl = f"{reg}/v2/{repo}/manifests/{tag}"
    code, hdrs, _ = call(murl, {"Accept": MANIFEST_TYPES})
    chal = next((v for k, v in hdrs.items() if k.lower() == "www-authenticate"), "")
    params = dict(re.findall(r'(\w+)="([^"]*)"', chal))
    if code != 401 or "realm" not in params:
        raise Inconclusive(f"unexpected anonymous response HTTP {code}")
    if not realm_ok(params["realm"], bool(os.environ.get("KEY_PROBE_REGISTRY"))):
        raise Inconclusive("token realm is not https on nvcr.io/nvidia.com: refusing to send the key")
    q = {k: v for k, v in params.items() if k in ("service", "scope")}
    q.setdefault("scope", f"repository:{repo}:pull")
    basic = base64.b64encode(f"$oauthtoken:{key}".encode()).decode()
    code, _, body = call(f"{params['realm']}?{urllib.parse.urlencode(q)}", {"Authorization": f"Basic {basic}"})
    expect_ok("registry token", code)
    token = json.loads(body).get("token") or json.loads(body).get("access_token")
    code, hdrs, _ = call(murl, {"Authorization": f"Bearer {token}", "Accept": MANIFEST_TYPES}, method="HEAD")
    expect_ok(f"manifest {repo}:{tag}", code)
    print("digest:", next((v for k, v in hdrs.items() if k.lower() == "docker-content-digest"), "(none)"))


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hosted"); h.add_argument("--chat")
    n = sub.add_parser("nvcr"); n.add_argument("--repo", required=True); n.add_argument("--tag", required=True)
    a = ap.parse_args()
    if sys.stdin.isatty():
        print("key_probe: pipe the key on stdin (never type or paste it)", file=sys.stderr); return 2
    key = sys.stdin.read().strip()
    if not key:
        print("key_probe: empty key on stdin", file=sys.stderr); return 2
    try:
        hosted(key, a.chat) if a.cmd == "hosted" else nvcr(key, a.repo, a.tag)
    except Rejected as e:
        print(f"REJECTED ({e})"); return 1
    except Inconclusive as e:
        print(f"INCONCLUSIVE ({e}): proves nothing about the key"); return 2
    except Exception as e:
        print(f"INCONCLUSIVE (crash: {type(e).__name__}): proves nothing about the key"); return 2
    print("ACCEPTED"); return 0


if __name__ == "__main__":
    sys.exit(main())
