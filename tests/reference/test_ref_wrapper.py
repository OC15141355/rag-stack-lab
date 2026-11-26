"""Thin wrapper: reference/platform-gitops/ ships its own tests (its CI runs them in GitLab). This repo runs that
suite as-is, plus the checks that only make sense inside rag-stack-lab (the pinned CRD copies, the lab smoke.py
source, this repo's .gitignore)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "reference/platform-gitops"


def test_template_suite_passes():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=TEMPLATE,
                       capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    tail = "\n".join((r.stdout + r.stderr).splitlines()[-40:])
    assert r.returncode == 0, tail
    assert " passed" in tail, tail
    if os.environ.get("REQUIRE_HELM") == "1":
        assert " skipped" not in tail, tail


def test_chart_crds_are_the_pinned_v3_1_4_crds():
    """00-crds comes from the vendored chart; it must equal the CRDs this repo pins in tests/fixtures/crds."""
    docs = [d for d in yaml.safe_load_all((TEMPLATE / "clusters/prod/00-crds/nim-operator-crds.yaml").read_text()) if d]
    rendered = {d["metadata"]["name"]: d for d in docs}
    for plural in ("nimcaches", "nimservices"):
        pinned = yaml.safe_load((REPO / f"tests/fixtures/crds/apps.nvidia.com_{plural}.yaml").read_text())
        assert rendered[f"{plural}.apps.nvidia.com"]["spec"] == pinned["spec"]


def test_smoke_py_is_an_exact_copy_of_the_lab_smoke():
    src = (REPO / "lab/smoke/smoke.py").read_text().splitlines(keepends=True)
    dst = (TEMPLATE / "tools/smoke.py").read_text().splitlines(keepends=True)
    assert dst[1].startswith("# COPY of rag-stack-lab lab/smoke/smoke.py")
    assert [dst[0]] + dst[2:] == src, "run scripts/sync-reference-smoke.sh"


def test_no_template_file_is_gitignored():
    """This repo ignores *secret* paths; a template file it silently drops would vanish from the PR."""
    if not shutil.which("git"):
        return
    files = [str(p.relative_to(REPO)) for p in TEMPLATE.rglob("*")
             if p.is_file() and not {"__pycache__", ".pytest_cache", ".ruff_cache"} & set(p.parts)]
    r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "--no-index", "--stdin"], input="\n".join(files),
                       capture_output=True, text=True)
    assert r.stdout.strip() == "", f"gitignored: {r.stdout}"
