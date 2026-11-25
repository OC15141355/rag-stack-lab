#!/usr/bin/env python3
"""Build (emit) or check (verify) the plaintext for lab/gpu/secrets/gpu.sops.yaml. Never prints a value.

  emit    reads the session nvapi- key with `age -d` (into this process only), generates fresh Bifrost
          values, and writes three Secret manifests to stdout. Refuses to write to a terminal: stdout
          must be a pipe into `sops encrypt`.
  verify  reads the DECRYPTED file on stdin (from `sops decrypt`), checks its structure and that the
          key inside equals the session key on disk; prints only OK/FAIL lines.

Session files (override the directory with RAGLAB_GPU_DIR, the age binary with RAGLAB_AGE_BIN):
  age-key.txt              session age identity (decrypts the .age file)
  session-nvapi-key.age    the session nvapi- key (hosted API + nvcr.io pull), age-encrypted
Exit 0 ok, 1 verify failure, 2 usage/input error.
"""
from __future__ import annotations
import argparse, base64, json, os, re, secrets, stat, subprocess, sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("make_gpu_sops: PyYAML required (uv run --with pyyaml ...)", file=sys.stderr); sys.exit(2)

GPU_NS, DEV_GPU_NS = "raglab-gpu", "raglab-dev-gpu"
NIM_LOCAL_PLACEHOLDER = "not-a-secret-nim-local"   # the NIM ignores the bearer; Bifrost needs a value
KEY_RE = re.compile(r"^nvapi-[A-Za-z0-9_-]{20,}$")
BIFROST_KEYS = {"NVIDIA_API_KEY", "NIM_LOCAL_API_KEY", "BIFROST_ENCRYPTION_KEY", "BIFROST_ADMIN_USER",
                "BIFROST_ADMIN_PASSWORD", "BIFROST_VK", "BIFROST_VK_PROBE"}


def die(msg: str, code: int = 2):
    print(f"make_gpu_sops: {msg}", file=sys.stderr); sys.exit(code)


def session_dir() -> Path:
    return Path(os.environ.get("RAGLAB_GPU_DIR", str(Path.home() / ".sops" / "raglab-gpu-session")))


def read_session_key() -> str:
    d = session_dir()
    ident, enc = d / "age-key.txt", d / "session-nvapi-key.age"
    for f in (ident, enc):
        if not f.is_file():
            die(f"missing {f}")
    r = subprocess.run([os.environ.get("RAGLAB_AGE_BIN", "age"), "-d", "-i", str(ident), str(enc)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die("age -d failed (output suppressed)")
    key = r.stdout.strip()
    if not KEY_RE.match(key):
        die("decrypted session key does not look like an nvapi- key (value not shown)")
    return key


def dockerconfig(key: str) -> str:
    auth = base64.b64encode(f"$oauthtoken:{key}".encode()).decode()
    return json.dumps({"auths": {"nvcr.io": {"username": "$oauthtoken", "password": key, "auth": auth}}},
                      sort_keys=True)


def secret(name: str, ns: str, data: dict, typ: str = "Opaque") -> dict:
    return {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name, "namespace": ns},
            "type": typ, "stringData": data}


def build(key: str) -> list[dict]:
    return [
        secret("ngc-pull", GPU_NS, {".dockerconfigjson": dockerconfig(key)}, "kubernetes.io/dockerconfigjson"),
        secret("ngc-api-key", GPU_NS, {"NGC_API_KEY": key}),
        secret("bifrost-env", DEV_GPU_NS, {
            "NVIDIA_API_KEY": key,
            "NIM_LOCAL_API_KEY": NIM_LOCAL_PLACEHOLDER,
            "BIFROST_ENCRYPTION_KEY": secrets.token_urlsafe(32),
            "BIFROST_ADMIN_USER": "raglab-admin",
            "BIFROST_ADMIN_PASSWORD": secrets.token_urlsafe(24),
            "BIFROST_VK": "sk-bf-" + secrets.token_urlsafe(24),
            "BIFROST_VK_PROBE": "sk-bf-" + secrets.token_urlsafe(24),
        }),
    ]


def emit() -> int:
    if sys.stdout.isatty() or stat.S_ISREG(os.fstat(1).st_mode):
        die("refusing to write secrets to a terminal or a file; pipe into `sops encrypt`")
    sys.stdout.write(yaml.safe_dump_all(build(read_session_key()), sort_keys=False, default_flow_style=False))
    return 0


def verify(text: str, source_key: str | None) -> int:
    ok = True

    def check(name: str, cond: bool):
        nonlocal ok
        print(f"{'OK  ' if cond else 'FAIL'} {name}")
        ok = ok and cond

    try:
        docs = [d for d in yaml.safe_load_all(text) if d]
    except yaml.YAMLError:
        print("FAIL parse"); return 1
    by = {(d.get("metadata", {}).get("namespace"), d.get("metadata", {}).get("name")): d
          for d in docs if isinstance(d, dict)}
    check("three documents", len(docs) == 3)
    check("no sops block (input must be decrypted)", all("sops" not in d for d in docs if isinstance(d, dict)))
    pull = by.get((GPU_NS, "ngc-pull"), {})
    api = by.get((GPU_NS, "ngc-api-key"), {})
    bif = by.get((DEV_GPU_NS, "bifrost-env"), {})
    check("ngc-pull type dockerconfigjson", pull.get("type") == "kubernetes.io/dockerconfigjson")
    check("ngc-api-key type Opaque", api.get("type") == "Opaque")
    check("bifrost-env type Opaque", bif.get("type") == "Opaque")
    key = (api.get("stringData") or {}).get("NGC_API_KEY", "")
    check("NGC_API_KEY is an nvapi- key", bool(KEY_RE.match(key)))
    try:
        auths = json.loads((pull.get("stringData") or {}).get(".dockerconfigjson", "{}"))["auths"]
        ent = auths.get("nvcr.io", {})
        check("dockerconfigjson has only nvcr.io", set(auths) == {"nvcr.io"})
        check("nvcr.io username is $oauthtoken", ent.get("username") == "$oauthtoken")
        check("nvcr.io password equals NGC_API_KEY", ent.get("password") == key)
        check("nvcr.io auth decodes to $oauthtoken:<key>",
              base64.b64decode(ent.get("auth", "")).decode() == f"$oauthtoken:{key}")
    except (ValueError, KeyError, TypeError, AttributeError):
        check("dockerconfigjson parses", False)
    sd = bif.get("stringData") or {}
    check("bifrost-env has exactly the expected keys", set(sd) == BIFROST_KEYS)
    check("bifrost NVIDIA_API_KEY equals NGC_API_KEY", sd.get("NVIDIA_API_KEY") == key)
    check("NIM_LOCAL_API_KEY is the placeholder", sd.get("NIM_LOCAL_API_KEY") == NIM_LOCAL_PLACEHOLDER)
    check("virtual keys are sk-bf- and distinct",
          all(str(sd.get(k, "")).startswith("sk-bf-") for k in ("BIFROST_VK", "BIFROST_VK_PROBE"))
          and sd.get("BIFROST_VK") != sd.get("BIFROST_VK_PROBE"))
    check("generated values are long enough",
          all(len(str(sd.get(k, ""))) >= 30 for k in ("BIFROST_ENCRYPTION_KEY", "BIFROST_ADMIN_PASSWORD")))
    if source_key is not None:
        check("key equals the session key on disk (decode probe)", key == source_key)
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("emit")
    v = sub.add_parser("verify")
    v.add_argument("--no-source", action="store_true", help="skip the comparison with the key on disk")
    a = ap.parse_args()
    if a.cmd == "emit":
        return emit()
    return verify(sys.stdin.read(), None if a.no_source else read_session_key())


if __name__ == "__main__":
    sys.exit(main())
