#!/usr/bin/env python3
"""Structural secrets checks for this repo (stdlib + PyYAML).

Rules:
  R1 every file under lab/secrets/ is named *.sops.yaml (paths are normalised first)
  R2 every file has >=1 YAML document, each with a top-level `sops:` block whose `mac` is ENC[...]
     and whose keys are all known sops keys
  R3 every leaf outside `sops:` is ENC[...], except apiVersion, kind, type,
     metadata.name and metadata.namespace; at least one ENC leaf must exist
  R4 generated Bifrost files (lab/envs/*/generated/*) contain no literal nvapi-/sk-bf- values
  R5 no age private key or PEM private-key header anywhere in scanned text files
  R6 undecodable files under lab/secrets and explicit paths that do not exist are findings
Exit 0 clean, 1 findings, 2 usage.
"""
from __future__ import annotations
import argparse, posixpath, re, subprocess, sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("check_secrets: PyYAML required (uv run --with pyyaml ...)", file=sys.stderr); sys.exit(2)

AGE_PRIV = re.compile(r"(?i)AGE-SECRET-KE[Y]-[A-Z0-9-]*1[A-Z0-9]{20,}")
PEM_PRIV = re.compile(r"-{4,5} ?BEGIN [A-Z0-9 _-]*PRIVATE KEY")
LITERAL = re.compile(r"(nvapi-[A-Za-z0-9_-]{20,}|sk-bf-[A-Za-z0-9_-]{8,})")
ENC = re.compile(r"^ENC\[[A-Z0-9_]+,data:.*\]$")

SOPS_KEYS = {"kms", "gcp_kms", "azure_kv", "hc_vault", "age", "pgp", "lastmodified", "mac",
             "unencrypted_suffix", "encrypted_suffix", "unencrypted_regex", "encrypted_regex",
             "unencrypted_comment_regex", "encrypted_comment_regex", "mac_only_encrypted",
             "version", "shamir_threshold", "key_groups"}
PLAIN_OK = {("apiVersion",), ("kind",), ("type",), ("metadata", "name"), ("metadata", "namespace")}

def leaves(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items(): yield from leaves(v, path + (str(k),))
    elif isinstance(node, list):
        for v in node: yield from leaves(v, path)
    else:
        yield path, node

def check_secret_file(rel: str, text: str) -> list[str]:
    out = []
    if not rel.endswith(".sops.yaml"):
        out.append(f"{rel}: files under lab/secrets must be *.sops.yaml")
    try:
        docs = [d for d in yaml.safe_load_all(text) if d is not None]
    except yaml.YAMLError as e:
        return out + [f"{rel}: unparseable YAML ({e.__class__.__name__})"]
    if not docs:
        out.append(f"{rel}: no YAML documents (empty or comment-only)")
    for d in docs:
        if not isinstance(d, dict) or not isinstance(d.get("sops"), dict):
            out.append(f"{rel}: no sops metadata block"); continue
        mac = d["sops"].get("mac")
        if not (isinstance(mac, str) and ENC.match(mac)):
            out.append(f"{rel}: sops.mac missing or not ENC[...] (file not produced by sops?)")
        for k in d["sops"]:
            if k not in SOPS_KEYS:
                out.append(f"{rel}: unknown key in sops block: {k}")
        body = {k: v for k, v in d.items() if k != "sops"}
        enc = 0
        bad = False
        for path, v in leaves(body):
            if isinstance(v, str) and ENC.match(v):
                enc += 1
            elif path not in PLAIN_OK:
                bad = True
        if bad:
            out.append(f"{rel}: value outside sops block is not ENC[...]")
        if enc == 0:
            out.append(f"{rel}: sops block present but nothing encrypted")
    return out

def check_text(rel: str, text: str) -> list[str]:
    out = []
    if AGE_PRIV.search(text): out.append(f"{rel}: age private key material")
    if PEM_PRIV.search(text): out.append(f"{rel}: PEM private key header")
    if "/generated/" in rel and LITERAL.search(text):
        out.append(f"{rel}: literal secret value in generated config (use env.VAR)")
    return out

def tracked_files(root: Path) -> list[str]:
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"check_secrets: git ls-files failed: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return [l for l in r.stdout.splitlines() if l]

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args()
    root = Path(a.root)
    paths = a.paths or tracked_files(root)
    findings = []
    for raw in paths:
        rel = posixpath.normpath(raw)
        p = root / rel
        in_secrets = rel.startswith("lab/secrets/")
        if not p.is_file():
            findings.append(f"{rel}: path does not exist or is not a file")
            continue
        data = p.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            if in_secrets:
                findings.append(f"{rel}: undecodable (non-UTF-8) file under lab/secrets")
                continue
            text = data.decode("utf-8", errors="replace")
        if in_secrets:
            findings += check_secret_file(rel, text)
        findings += check_text(rel, text)
    for f in findings: print(f"FINDING {f}")
    return 1 if findings else 0

if __name__ == "__main__":
    sys.exit(main())
