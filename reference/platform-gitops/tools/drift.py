#!/usr/bin/env python3
"""Nightly drift report for one environment: what is live but not in git. Stdlib + PyYAML.

    kubectl get <kinds> -A -o json > inventory.json     # on that environment's runner, read-only credentials
    python3 tools/drift.py --env prod --inventory inventory.json [--json]

Reports:
  ORPHAN     a live object labelled managed-by=platform-gitops that is NOT in clusters/<env>/ (e.g. a retired
             NIMService still holding 8 GPUs, or a weights PVC whose catalogue entry was removed)
             Finished Jobs are not orphans: smoke Jobs expire by ttlSecondsAfterFinished.
  UNMANAGED  a live object WITHOUT that label in a managed namespace (a hand-applied change), unless it is owned by
             another object (operator children, ReplicaSets, Pods) or is a Kubernetes default
Secrets applied from secrets/<env>/*.sops.yaml count as known (their metadata is readable without decryption).
Secret values never reach this tool: the CI job pipes `kubectl get secrets -o json` through
`drift.py --strip-secret-data` before anything is written (and load_inventory strips again).
The other half of drift, live objects that differ from git, is `kubectl diff --server-side -f clusters/<env>/...`
in the same nightly job. Exit 0 clean, 1 findings, 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render  # noqa: E402

# Created by Kubernetes itself in every namespace, or ephemeral by nature.
DEFAULTS = {("ConfigMap", "kube-root-ca.crt"), ("ServiceAccount", "default")}
EPHEMERAL_KINDS = {"Event", "Pod", "ReplicaSet", "Endpoints", "EndpointSlice", "Lease", "ControllerRevision"}


def group(api_version: str) -> str:
    return api_version.split("/")[0] if "/" in api_version else ""


def ident(o: dict) -> tuple[str, str, str, str]:
    md = o.get("metadata", {})
    return (group(o.get("apiVersion", "")), o.get("kind", ""), md.get("namespace", "") or "", md.get("name", ""))


def desired(root: Path, env: str) -> tuple[set, set]:
    """(identities rendered or SOPS-managed for env, managed namespaces)."""
    ids, managed_ns = set(), set()
    d = root / "clusters" / env
    if not d.is_dir():
        raise FileNotFoundError(f"{d} does not exist")
    for f in sorted(d.rglob("*.yaml")):
        folder = f.relative_to(d).parts[0]
        for o in render.load_yaml_docs(f):
            ids.add(ident(o))
            ns = o.get("metadata", {}).get("namespace")
            if ns and folder in ("20-weights", "30-services", "40-gateway"):
                managed_ns.add(ns)
    for f in sorted((root / "secrets" / env).glob("*.sops.yaml")):
        o = render.load_yaml(f) or {}
        ids.add(ident(o))
    return ids, managed_ns


def strip_secret_data(data):
    """Drop every Secret value (data, stringData) from a kubectl List or object: the drift job needs metadata only,
    and Secret values must never be written to a CI workspace or log."""
    items = data["items"] if isinstance(data, dict) and "items" in data else data if isinstance(data, list) else [data]
    for o in items:
        if isinstance(o, dict):
            o.pop("data", None)
            o.pop("stringData", None)
            ((o.get("metadata") or {}).get("annotations") or {}).pop("kubectl.kubernetes.io/last-applied-configuration", None)
    return data


def load_inventory(path: Path) -> list[dict]:
    data = strip_secret_data(json.loads(path.read_text()))   # defensive: never hold Secret values in memory longer
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    raise ValueError("inventory must be a kubectl List ({'items': [...]}) or a JSON array of objects")


def finished_job(o: dict) -> bool:
    st = o.get("status") or {}
    conds = {c.get("type") for c in st.get("conditions") or [] if c.get("status") == "True"}
    return o.get("kind") == "Job" and bool(st.get("succeeded") or st.get("failed") or conds & {"Complete", "Failed"})


def report(root: Path, env: str, inventory: list[dict], extra_managed_ns: set | None = None) -> list[dict]:
    ids, managed_ns = desired(root, env)
    managed_ns |= extra_managed_ns or set()
    out = []
    for o in inventory:
        g, kind, ns, name = i = ident(o)
        md = o.get("metadata", {})
        labelled = (md.get("labels") or {}).get(render.MANAGED_BY[0]) == render.MANAGED_BY[1]
        if labelled and i not in ids and not finished_job(o):   # finished smoke Jobs expire by TTL
            out.append({"type": "ORPHAN", "kind": kind, "namespace": ns, "name": name,
                        "why": "labelled managed-by=platform-gitops but not rendered for this env"})
        elif (not labelled and ns in managed_ns and i not in ids and not md.get("ownerReferences")
              and kind not in EPHEMERAL_KINDS and (kind, name) not in DEFAULTS
              and not (kind == "Secret" and o.get("type") == "kubernetes.io/service-account-token")):
            out.append({"type": "UNMANAGED", "kind": kind, "namespace": ns, "name": name,
                        "why": "in a managed namespace without the managed-by label (applied by hand?)"})
    return sorted(out, key=lambda r: (r["type"], r["namespace"], r["kind"], r["name"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strip-secret-data", action="store_true",
                    help="filter: read kubectl JSON on stdin, write it without Secret values to stdout, exit")
    ap.add_argument("--env", choices=render.ENVS)
    ap.add_argument("--inventory", type=Path)
    ap.add_argument("--root", type=Path, default=render.ROOT)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.strip_secret_data:
        json.dump(strip_secret_data(json.load(sys.stdin)), sys.stdout)
        return 0
    if not a.env or not a.inventory:
        ap.error("--env and --inventory are required")
    try:
        findings = report(a.root, a.env, load_inventory(a.inventory))
    except (OSError, ValueError) as e:
        print(f"drift: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(findings, indent=2))
    else:
        for f in findings:
            print(f"{f['type']:9} {f['namespace'] or '-'}/{f['kind']}/{f['name']}: {f['why']}")
        print(f"drift {a.env}: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
