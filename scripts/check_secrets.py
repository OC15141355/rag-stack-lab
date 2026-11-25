#!/usr/bin/env python3
"""Structural secrets checks for this repo (stdlib + PyYAML).

Rules:
  R1 every file under a secrets dir (lab/secrets/, lab/gpu/secrets/) is named *.sops.yaml
     (paths are normalised first); the only exception is that dir's kustomization.yaml index
  R2 every file has >=1 YAML document, each with a top-level `sops:` block whose `mac` is ENC[...]
     and whose keys are all known sops keys
  R3 every leaf outside `sops:` is ENC[...], except apiVersion, kind, type,
     metadata.name and metadata.namespace; at least one ENC leaf must exist
  R4 generated Bifrost files (lab/envs/*/generated/*) contain no literal nvapi-/sk-bf- values
  R5 no age private key or PEM private-key header anywhere in scanned text files
  R6 undecodable files under a secrets dir and explicit paths that do not exist are findings
  R7 the age recipients of every secrets file equal those of the FIRST .sops.yaml creation rule whose
     path_regex matches it (sops semantics), so a GPU-session file can never carry the Phase A key
     and vice versa and carry no pgp/kms/gcp_kms/azure_kv/hc_vault/key_groups entries; a missing .sops.yaml
     under --root is itself a finding (fails closed)
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
NON_AGE = ("pgp", "kms", "gcp_kms", "azure_kv", "hc_vault", "key_groups")
SECRET_DIRS = ("lab/secrets/", "lab/gpu/secrets/")

def secrets_dir(rel: str) -> str | None:
    return next((d for d in SECRET_DIRS if rel.startswith(d)), None)

def sops_rules(root: Path) -> list[tuple[re.Pattern, set[str]]] | None:
    f = root / ".sops.yaml"
    if not f.is_file():
        return None
    rules = []
    for r in (yaml.safe_load(f.read_text()) or {}).get("creation_rules") or []:
        ages = r.get("age") or ""
        ages = ages if isinstance(ages, list) else [a.strip() for a in ages.split(",")]
        rules.append((re.compile(r.get("path_regex", "")), {a for a in ages if a}))
    return rules

def check_recipients(rel: str, text: str, rules) -> list[str]:
    want = next((ages for rx, ages in rules if rx.search(rel)), None)
    if want is None:
        return [f"{rel}: no .sops.yaml creation rule matches this path"]
    try:
        docs = [d for d in yaml.safe_load_all(text) if isinstance(d, dict) and isinstance(d.get("sops"), dict)]
    except yaml.YAMLError:
        return []   # already reported by check_secret_file
    out = []
    for d in docs:
        extra = [k for k in NON_AGE if d["sops"].get(k)]
        if extra:
            out.append(f"{rel}: sops block has non-age key types ({', '.join(extra)})")
        got = {a.get("recipient") for a in d["sops"].get("age") or [] if isinstance(a, dict)}
        if got != want:
            out.append(f"{rel}: sops age recipients do not match the first matching .sops.yaml rule")
    return out

def leaves(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items(): yield from leaves(v, path + (str(k),))
    elif isinstance(node, list):
        for v in node: yield from leaves(v, path)
    else:
        yield path, node

def is_secrets_kustomization(rel: str, text: str) -> list[str] | None:
    """The one non-sops file allowed under lab/secrets: a pure index of *.sops.yaml names.
    Returns None if rel isn't that file, else a (possibly empty) list of findings."""
    if rel not in {d + "kustomization.yaml" for d in SECRET_DIRS}:
        return None
    class Strict(yaml.SafeLoader):
        pass
    def no_dups(loader, node, deep=False):
        keys = [loader.construct_object(k, deep=True) for k, _ in node.value]
        if len(keys) != len(set(keys)):
            raise yaml.YAMLError("duplicate key")
        return yaml.SafeLoader.construct_mapping(loader, node, deep)
    Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, no_dups)
    try:
        d = yaml.load(text, Loader=Strict)
    except yaml.YAMLError:
        return [f"{rel}: unparseable YAML or duplicate keys"]
    ok = (isinstance(d, dict) and set(d) == {"apiVersion", "kind", "resources"}
          and d["apiVersion"] == "kustomize.config.k8s.io/v1beta1"
          and d["kind"] == "Kustomization" and isinstance(d["resources"], list)
          and all(isinstance(r, str) and re.fullmatch(r"[A-Za-z0-9_-]+\.sops\.yaml", r) for r in d["resources"]))
    return [] if ok else [f"{rel}: must contain only apiVersion, kind and a resources list of bare *.sops.yaml names"]

def check_secret_file(rel: str, text: str) -> list[str]:
    k = is_secrets_kustomization(rel, text)
    if k is not None:
        return k
    out = []
    if not rel.endswith(".sops.yaml"):
        out.append(f"{rel}: files under {secrets_dir(rel) or 'lab/secrets/'} must be *.sops.yaml")
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
    rules = sops_rules(root)
    paths = a.paths or tracked_files(root)
    findings = []
    for raw in paths:
        rel = posixpath.normpath(raw)
        p = root / rel
        in_secrets = secrets_dir(rel) is not None
        if not p.is_file():
            findings.append(f"{rel}: path does not exist or is not a file")
            continue
        data = p.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            if in_secrets:
                findings.append(f"{rel}: undecodable (non-UTF-8) file under {secrets_dir(rel)}")
                continue
            text = data.decode("utf-8", errors="replace")
        if in_secrets:
            findings += check_secret_file(rel, text)
            if not rel.endswith("/kustomization.yaml"):
                if rules is None:
                    findings.append(f"{rel}: no .sops.yaml: cannot verify recipients")
                else:
                    findings += check_recipients(rel, text, rules)
        findings += check_text(rel, text)
    for f in findings: print(f"FINDING {f}")
    return 1 if findings else 0

if __name__ == "__main__":
    sys.exit(main())
