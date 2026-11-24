#!/usr/bin/env python3
"""Structural secrets checks for this repo (stdlib + PyYAML).

Rules:
  R1 every file under lab/secrets/ is named *.sops.yaml
  R2 every lab/secrets file has a top-level `sops:` block
  R3 every leaf under data/stringData of those files is ENC[...]; there must be at least one such leaf
  R4 generated Bifrost files (lab/envs/*/generated/*) contain no literal nvapi-/sk-bf- values
  R5 no age private key or PEM private-key header anywhere in scanned text files
Exit 0 clean, 1 findings, 2 usage.
"""
from __future__ import annotations
import argparse, re, subprocess, sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("check_secrets: PyYAML required (uv run --with pyyaml ...)", file=sys.stderr); sys.exit(2)

AGE_PRIV = re.compile(r"(?i)AGE-SECRET-KE[Y]-[A-Z0-9-]*1[A-Z0-9]{20,}")
PEM_PRIV = re.compile(r"-{4,5} ?BEGIN [A-Z0-9 _-]*PRIVATE KEY")
LITERAL = re.compile(r"(nvapi-[A-Za-z0-9_-]{20,}|sk-bf-[A-Za-z0-9_-]{8,})")
ENC = re.compile(r"^ENC\[[A-Z0-9_]+,data:.*\]$")

def leaves(node):
    if isinstance(node, dict):
        for v in node.values(): yield from leaves(v)
    elif isinstance(node, list):
        for v in node: yield from leaves(v)
    else:
        yield node

def check_secret_file(rel: str, text: str) -> list[str]:
    out = []
    if not rel.endswith(".sops.yaml"):
        out.append(f"{rel}: files under lab/secrets must be *.sops.yaml")
    try:
        docs = [d for d in yaml.safe_load_all(text) if d is not None]
    except yaml.YAMLError as e:
        return out + [f"{rel}: unparseable YAML ({e.__class__.__name__})"]
    for d in docs:
        if not isinstance(d, dict) or "sops" not in d:
            out.append(f"{rel}: no sops metadata block"); continue
        vals = [v for k in ("data", "stringData") for v in leaves(d.get(k) or {})]
        if not vals:
            out.append(f"{rel}: sops block present but no data/stringData values (nothing encrypted)")
        for v in vals:
            if not (isinstance(v, str) and ENC.match(v)):
                out.append(f"{rel}: value under data/stringData is not ENC[...]")
                break
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
    return [l for l in r.stdout.splitlines() if l]

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args()
    root = Path(a.root)
    paths = a.paths or tracked_files(root)
    findings = []
    for rel in paths:
        p = root / rel
        if not p.is_file(): continue
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            continue
        if rel.startswith("lab/secrets/"):
            findings += check_secret_file(rel, text)
        findings += check_text(rel, text)
    for f in findings: print(f"FINDING {f}")
    return 1 if findings else 0

if __name__ == "__main__":
    sys.exit(main())
