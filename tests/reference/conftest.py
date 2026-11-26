"""Shared helpers for the reference/platform-gitops template tests (design section 13)."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "reference/platform-gitops"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(TEMPLATE / "tools"))

import render  # noqa: E402


def helm_ok() -> bool:
    if not shutil.which("helm"):
        return False
    pinned = render.load_yaml(TEMPLATE / "catalogue/platform.yaml")["tools"]["helm"]
    got = subprocess.run(["helm", "version", "--template", "{{.Version}}"], capture_output=True, text=True).stdout.strip()
    return got == pinned


def need_helm():
    """Skip without the pinned helm locally; in CI (REQUIRE_HELM=1) a missing helm is a failure, never a skip."""
    if helm_ok():
        return
    if os.environ.get("REQUIRE_HELM") == "1":
        pytest.fail("REQUIRE_HELM=1 but the pinned helm is not on PATH")
    pytest.skip("pinned helm not available")


def copy_template(dst: Path) -> Path:
    shutil.copytree(TEMPLATE, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return dst


# ---------------------------------------------------------------- fixture ops
def _walk_set(node, path, value, unset=False):
    for k in path[:-1]:
        node = node[k] if not isinstance(node, dict) else node.setdefault(k, {})
    last = path[-1]
    if unset:
        del node[last]
    elif isinstance(node, list) and last == len(node):
        node.append(value)
    else:
        node[last] = value


def _match(doc, sel):
    return all(doc.get("kind") == sel["kind"] if k == "kind" else doc.get("metadata", {}).get("name") == v
               for k, v in sel.items())


def apply_ops(root: Path, ops: list[dict]):
    for op in ops:
        f = root / op["file"]
        if op.get("delete"):
            f.unlink(); continue
        if "write" in op:
            f.parent.mkdir(parents=True, exist_ok=True); f.write_text(op["write"]); continue
        if "copy" in op:
            f.parent.mkdir(parents=True, exist_ok=True); f.write_text((root / op["copy"]).read_text()); continue
        if "append" in op:
            f.write_text(f.read_text() + op["append"]); continue
        if "replace" in op:
            old, new = op["replace"]
            text = f.read_text()
            assert old in text, f"fixture replace target not found in {op['file']}: {old!r}"
            f.write_text(text.replace(old, new)); continue
        docs = json.loads(json.dumps(render.load_yaml_docs(f)))   # break YAML-alias sharing: edit ONE block only
        if "append_doc" in op:
            docs.append(op["append_doc"])
        else:
            if "doc" in op:
                hits = [d for d in docs if _match(d, op["doc"])]
                assert len(hits) == 1, f"fixture doc selector {op['doc']} matched {len(hits)} docs in {op['file']}"
                target = hits[0]
            else:
                assert len(docs) == 1
                target = docs[0]
            if "json" in op:
                holder = target
                for k in op["json"][:-1]:
                    holder = holder[k]
                data = json.loads(holder[op["json"][-1]])
                _walk_set(data, op.get("set") or op.get("unset"), op.get("value"), unset="unset" in op)
                holder[op["json"][-1]] = json.dumps(data, indent=2, sort_keys=True) + "\n"
            else:
                _walk_set(target, op.get("set") or op.get("unset"), op.get("value"), unset="unset" in op)
        f.write_text(yaml.safe_dump_all(docs, sort_keys=False, explicit_start=True))


def load_fixture(path: Path) -> dict:
    return copy.deepcopy(yaml.safe_load(path.read_text()))
