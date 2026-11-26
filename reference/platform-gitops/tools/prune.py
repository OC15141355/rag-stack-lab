#!/usr/bin/env python3
"""List what a merge REMOVED from one environment's render, for the explicit delete job. Stdlib + PyYAML.

    python3 tools/prune.py --base PREVIOUS_TREE --env prod [--allow-weights]

`kubectl apply` never deletes, so a retired service would keep running (and holding GPUs) after its blocks are
disabled. This prints one line per object present in PREVIOUS_TREE/clusters/<env>/{30-services,40-gateway} and
absent from this tree, as `<namespace> <Kind>[.<version>.<group>]/<name>`, ready for `kubectl delete`.
NIMCaches, PVCs and anything in 20-weights are listed ONLY with --allow-weights, which the person running the job
sets after the PR passed the delete-weights gate. Jobs are never listed (smoke Jobs expire by TTL).
Exit 0 always on success (an empty list is normal), 2 on usage error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render  # noqa: E402

FOLDERS = ("30-services", "40-gateway")
WEIGHTS_KINDS = ("NIMCache", "PersistentVolumeClaim")


def objects(root: Path, env: str, folders) -> dict[tuple, dict]:
    out = {}
    d = root / "clusters" / env
    for folder in folders:
        for f in sorted((d / folder).rglob("*.yaml")) if (d / folder).exists() else []:
            for o in render.load_yaml_docs(f):
                md = o.get("metadata", {})
                out[(o["apiVersion"], o["kind"], md.get("namespace", ""), md["name"])] = o
    return out


def removed(base: Path, head: Path, env: str, allow_weights: bool = False) -> list[str]:
    folders = FOLDERS + (("20-weights",) if allow_weights else ())
    gone = sorted(set(objects(base, env, folders)) - set(objects(head, env, folders)))
    lines = []
    for api, kind, ns, name in gone:
        if kind == "Job" or (kind in WEIGHTS_KINDS and not allow_weights):
            continue
        res = f"{kind}.{api.split('/')[1]}.{api.split('/')[0]}" if "/" in api else kind
        lines.append(f"{ns} {res}/{name}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", type=Path, required=True, help="the previous commit's template tree")
    ap.add_argument("--env", required=True, choices=render.ENVS)
    ap.add_argument("--root", type=Path, default=render.ROOT)
    ap.add_argument("--allow-weights", action="store_true")
    a = ap.parse_args(argv)
    for line in removed(a.base, a.root, a.env, a.allow_weights):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
