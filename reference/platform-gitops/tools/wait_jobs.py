#!/usr/bin/env python3
"""Wait for Kubernetes Jobs to finish, failing FAST on the first failed one. Stdlib only (shells out to kubectl).

    python3 tools/wait_jobs.py -f clusters/prod/20-weights/verify/ --timeout 21600
    python3 tools/wait_jobs.py -l app=weights-verify -n models --timeout 60

`kubectl wait --for=condition=complete` waits out its whole timeout on a Job that already failed; this returns
as soon as any Job has failed. Exit 0 = every Job succeeded, 1 = a Job failed or the timeout passed, 2 = usage or
no Jobs found (an empty selection is never a pass).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time


def state(items: list[dict]) -> tuple[str, list[str]]:
    """('succeeded' | 'failed' | 'running' | 'none', per-Job lines)."""
    if not items:
        return "none", []
    lines, failed, done = [], False, True
    for j in items:
        st = j.get("status") or {}
        conds = {c.get("type") for c in st.get("conditions") or [] if c.get("status") == "True"}
        name = j.get("metadata", {}).get("name")
        if st.get("failed") or "Failed" in conds:
            failed = True
            lines.append(f"FAILED    {name}")
        elif st.get("succeeded") or "Complete" in conds:
            lines.append(f"succeeded {name}")
        else:
            done = False
            lines.append(f"running   {name}")
    return ("failed" if failed else "succeeded" if done else "running"), lines


def get(args) -> list[dict]:
    cmd = ["kubectl", "get", "-o", "json"]
    cmd += ["-f", args.file] if args.file else ["job", "-l", args.selector, "-n", args.namespace]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    data = json.loads(r.stdout)
    items = data.get("items", [data]) if isinstance(data, dict) else data
    return [i for i in items if i.get("kind", "Job") == "Job"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("-f", "--file")
    g.add_argument("-l", "--selector")
    ap.add_argument("-n", "--namespace", default="default")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--interval", type=int, default=15)
    a = ap.parse_args(argv)
    deadline = time.monotonic() + a.timeout
    while True:
        try:
            st, lines = state(get(a))
        except (RuntimeError, ValueError) as e:
            print(f"wait_jobs: {e}", file=sys.stderr)
            return 2
        print("\n".join(lines), flush=True)
        if st == "none":
            print("wait_jobs: no Jobs selected (never a pass)", file=sys.stderr)
            return 2
        if st in ("succeeded", "failed"):
            return 0 if st == "succeeded" else 1
        if time.monotonic() >= deadline:
            print(f"wait_jobs: timeout after {a.timeout}s", file=sys.stderr)
            return 1
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
