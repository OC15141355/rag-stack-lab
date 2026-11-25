#!/usr/bin/env python3
"""Lambda Cloud helper for the raglab Phase B GPU session. Mac only; stdlib only. Prints no secrets.

  types [--all]                                  instance types, price, regions with capacity (A100 1x by default)
  launch --type T --region R [--name N] [--wait] rent ONE instance (refuses if any instance already exists)
  status [--id ID]                               raglab-gpu* instances (or one id): id, name, status, ip, type, region
  instances                                      every instance + file system on the account; exit 0 only if none
  terminate --yes [--id ID] [--wait]             terminate raglab-gpu* instances (or one id); billing stops here

The API key is read with `age -d` from ~/.sops/raglab-gpu-session/lambda-api-key.age (identity age-key.txt in
the same dir; override the dir with RAGLAB_GPU_DIR, the binary with RAGLAB_AGE_BIN) into this process only.
It is never printed, never put on argv, never written to disk, and never sent anywhere but the API base
(pinned to https://cloud.lambda.ai/api/v1/; only the explicit --test-base flag, used by the tests, overrides it,
and plain http is refused except for 127.0.0.1). Redirects are refused (the key must never follow one).
Exit: 0 ok, 1 condition not met (instances exist / wait timed out), 2 usage or local error, 3 API error.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BASE = "https://cloud.lambda.ai/api/v1/"
USER_AGENT = "raglab-lambda-helper/1.0"      # urllib's default UA is blocked by Cloudflare (error 1010)
ALLOWED_TYPES = ("gpu_1x_a100_sxm4", "gpu_1x_a100")   # spec D2: one A100 40GB, nothing bigger
SSH_KEY_NAME = "raglab-gpu-session"
NAME_PREFIX = "raglab-gpu"
LIVE_EXCLUDED = {"terminated"}
SHOWN_FIELDS = ("id", "name", "status", "ip", "instance_type", "region")   # never jupyter_token/url

_KEY: str | None = None


class ApiError(Exception):
    pass


def die(msg: str, code: int = 2):
    print(f"lambda: {msg}", file=sys.stderr); sys.exit(code)


def scrub(text: str) -> str:
    return text.replace(_KEY, "***") if _KEY else text


TEST_BASE: str | None = None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ApiError(f"refusing HTTP {code} redirect (the API key is never sent to a redirect target)")


OPENER = urllib.request.build_opener(NoRedirect)


def api_base() -> str:
    base = TEST_BASE or DEFAULT_BASE
    u = urllib.parse.urlparse(base)
    if not (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost"))):
        die("API base must be https (plain http only for 127.0.0.1)")
    return base if base.endswith("/") else base + "/"


def age_bin() -> str:
    b = os.environ.get("RAGLAB_AGE_BIN")
    if b is None:
        return "age"
    if not (os.path.isabs(b) and os.path.basename(b) == "age" and os.access(b, os.X_OK)):
        die("RAGLAB_AGE_BIN must be an absolute path to an executable named 'age'")
    return b


def api_key() -> str:
    global _KEY
    if _KEY is None:
        d = Path(os.environ.get("RAGLAB_GPU_DIR", str(Path.home() / ".sops" / "raglab-gpu-session")))
        ident, enc = d / "age-key.txt", d / "lambda-api-key.age"
        for f in (ident, enc):
            if not f.is_file():
                die(f"missing {f}")
        r = subprocess.run([age_bin(), "-d", "-i", str(ident), str(enc)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            die("age -d failed for the Lambda API key (output suppressed)")
        _KEY = r.stdout.strip()
    return _KEY


def api(method: str, path: str, body: dict | None = None):
    url = urllib.parse.urljoin(api_base(), path)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {api_key()}", "User-Agent": USER_AGENT,
        "Accept": "application/json", **({"Content-Type": "application/json"} if data else {})})
    try:
        with OPENER.open(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}").get("data")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode()).get("error", {})
            msg = f"{err.get('code', '?')}: {err.get('message', '')} {err.get('suggestion') or ''}".strip()
        except (ValueError, AttributeError):
            msg = "(no JSON error body)"
        raise ApiError(scrub(f"HTTP {e.code} {method} {path}: {msg}"[:400]))
    except urllib.error.URLError as e:
        raise ApiError(scrub(f"{method} {path}: {e.reason}"))


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def show(i: dict) -> str:
    t = (i.get("instance_type") or {}).get("name", "?")
    reg = (i.get("region") or {}).get("name", "?")
    return f"{i.get('id')}  name={i.get('name')}  status={i.get('status')}  ip={i.get('ip') or '-'}  type={t}  region={reg}"


def live(instances: list[dict]) -> list[dict]:
    return [i for i in instances if i.get("status") not in LIVE_EXCLUDED]


def ours(instances: list[dict]) -> list[dict]:
    return [i for i in live(instances) if str(i.get("name") or "").startswith(NAME_PREFIX)]


def poll() -> float:
    return float(os.environ.get("LAMBDA_POLL_SECONDS", "10"))


def cmd_types(a) -> int:
    for name, v in sorted((api("GET", "instance-types") or {}).items()):
        if not a.all and name not in ALLOWED_TYPES:
            continue
        it, regions = v.get("instance_type", {}), [r.get("name") for r in v.get("regions_with_capacity_available", [])]
        s = it.get("specs", {})
        print(f"{name}  ${it.get('price_cents_per_hour', 0) / 100:.2f}/h  gpus={s.get('gpus')}  vcpus={s.get('vcpus')}"
              f"  mem={s.get('memory_gib')}GiB  disk={s.get('storage_gib')}GiB"
              f"  capacity={','.join(regions) if regions else 'NONE'}  ({it.get('description', '')})")
    return 0


def cmd_launch(a) -> int:
    if a.type not in ALLOWED_TYPES:
        die(f"type {a.type} not allowed (spec D2: one of {', '.join(ALLOWED_TYPES)})")
    if not a.name.startswith(NAME_PREFIX):
        die(f"--name must start with {NAME_PREFIX} (terminate and status find instances by that prefix)")
    existing = live(api("GET", "instances") or [])
    if existing:
        for i in existing: print(show(i))
        die("refusing to launch: the account already has a live instance (one session = one instance)", 1)
    t = (api("GET", "instance-types") or {}).get(a.type)
    regions = [r.get("name") for r in (t or {}).get("regions_with_capacity_available", [])]
    if a.region not in regions:
        die(f"no capacity for {a.type} in {a.region} (capacity now: {','.join(regions) or 'NONE'})", 1)
    d = api("POST", "instance-operations/launch", {
        "region_name": a.region, "instance_type_name": a.type, "ssh_key_names": [SSH_KEY_NAME],
        "file_system_names": [], "quantity": 1, "name": a.name})
    ids = (d or {}).get("instance_ids") or []
    print(f"LAUNCHED {' '.join(ids)} at {now()}  -- BILLING HAS STARTED; terminate is the only stop")
    if not a.wait or not ids:
        return 0 if ids else 3
    deadline = time.time() + a.timeout
    while time.time() < deadline:
        i = api("GET", f"instances/{ids[0]}") or {}
        if i.get("status") == "active" and i.get("ip"):
            print(show(i)); return 0
        time.sleep(poll())
    print(f"TIMEOUT waiting for {ids[0]} to be active (it is still billing)", file=sys.stderr)
    return 1


def cmd_status(a) -> int:
    rows = [api("GET", f"instances/{a.id}") or {}] if a.id else ours(api("GET", "instances") or [])
    for i in rows: print(show(i))
    if not rows: print("no raglab-gpu instances")
    return 0


def cmd_instances(a) -> int:
    inst = live(api("GET", "instances") or [])
    fss = api("GET", "file-systems") or []
    print(f"{now()}  live instances: {len(inst)}  file systems: {len(fss)}")
    for i in inst: print("  instance " + show(i))
    for f in fss: print(f"  file-system {f.get('id')} name={f.get('name')} region={(f.get('region') or {}).get('name')}")
    return 0 if not inst and not fss else 1


def cmd_terminate(a) -> int:
    if not a.yes:
        die("terminate needs --yes")
    targets = [a.id] if a.id else [i["id"] for i in ours(api("GET", "instances") or [])]
    if not targets:
        print("nothing to terminate (no live raglab-gpu instances)"); return 0
    d = api("POST", "instance-operations/terminate", {"instance_ids": targets}) or {}
    done = [i.get("id") for i in d.get("terminated_instances", [])]
    print(f"TERMINATE requested at {now()}: {' '.join(done) or ' '.join(targets)}")
    if sorted(done) != sorted(targets):
        print(f"lambda: API confirmed {done} but {targets} were requested; check the console NOW", file=sys.stderr)
        return 1
    if not a.wait:
        return 0
    deadline = time.time() + a.timeout
    while time.time() < deadline:
        left = [i for i in live(api("GET", "instances") or []) if i.get("id") in targets]
        if not left:
            print(f"TERMINATED (no longer listed as live) at {now()}"); return 0
        time.sleep(poll())
    print("TIMEOUT: instance still listed as live; check the console NOW", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lambda.py", description=__doc__.splitlines()[0])
    ap.add_argument("--test-base", help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("types"); t.add_argument("--all", action="store_true")
    l = sub.add_parser("launch")
    l.add_argument("--type", required=True); l.add_argument("--region", required=True)
    l.add_argument("--name", default=f"{NAME_PREFIX}-session")
    l.add_argument("--wait", action="store_true"); l.add_argument("--timeout", type=float, default=1200)
    s = sub.add_parser("status"); s.add_argument("--id")
    sub.add_parser("instances")
    x = sub.add_parser("terminate")
    x.add_argument("--yes", action="store_true"); x.add_argument("--id")
    x.add_argument("--wait", action="store_true"); x.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args(argv)
    global TEST_BASE
    TEST_BASE = a.test_base
    try:
        return {"types": cmd_types, "launch": cmd_launch, "status": cmd_status,
                "instances": cmd_instances, "terminate": cmd_terminate}[a.cmd](a)
    except ApiError as e:
        print(f"lambda: API error: {e}", file=sys.stderr)
        return 3
    except SystemExit:
        raise
    except Exception as e:  # never a traceback that could echo a request: one clear line, exit 3
        print(scrub(f"lambda: unexpected {type(e).__name__}: {e}")[:300], file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
