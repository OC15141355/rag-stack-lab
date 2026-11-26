"""Section 13 items 3, 4 and 6: every gate rejects its failure fixture and accepts the good tree; no check
without a failure fixture; the evidence rule; the speech service passes the same gates."""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import FIXTURES, TEMPLATE, apply_ops, copy_template, helm_ok, load_fixture, need_helm

pytest.importorskip("jsonschema")
import checks  # noqa: E402
import render  # noqa: E402

CASES = sorted(FIXTURES.glob("*/*.yaml"))
CASES = [c for c in CASES if c.parent.name in checks.CHECKS]


def run_one(root: Path, name: str, fx: dict, base: Path | None = None):
    ctx = checks.Ctx(root, base, frozenset(fx.get("labels") or []),
                     dt.date.fromisoformat(fx.get("today", "2026-11-26")))
    return checks.run(ctx, only={name})


def test_meta_every_check_has_a_failure_fixture_and_a_good_fixture():
    for name in checks.CHECKS:
        d = FIXTURES / name
        bad = [p for p in d.glob("bad*.yaml") if load_fixture(p)["expect"] in ("fail", "warn")]
        good = [p for p in d.glob("good*.yaml") if load_fixture(p)["expect"] == "pass"]
        assert bad, f"check {name} has no failure fixture under tests/reference/fixtures/{name}/"
        assert good, f"check {name} has no good fixture under tests/reference/fixtures/{name}/"
    stray = {p.name for p in FIXTURES.iterdir() if p.is_dir()} - set(checks.CHECKS) - {"drift"}
    assert not stray, f"fixture dirs for unknown checks: {stray}"


@pytest.mark.parametrize("case", CASES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_fixture(case: Path, tmp_path: Path):
    name, fx = case.parent.name, load_fixture(case)
    spec = checks.CHECKS[name]
    if spec["needs_helm"] or fx.get("rerender"):
        need_helm()
    head = copy_template(tmp_path / "head")
    apply_ops(head, fx["ops"])
    if fx.get("rerender"):
        render.write_tree(head / "clusters", render.render_all(head))
    base = TEMPLATE if fx.get("pair") else None
    findings = run_one(head, name, fx, base)
    fails = [f for f in findings if f.level == "FAIL"]
    warns = [f for f in findings if f.level == "WARN"]
    assert not [f for f in fails if "check crashed" in f.message], "a crash is not a rejection: " + str(fails)
    if fx["expect"] == "fail":
        assert fails, f"{case}: expected {name} to FAIL ({fx['description']}), it passed"
    elif fx["expect"] == "warn":
        assert not fails, [str(f) for f in fails]
        assert any(fx["match"] in f.message for f in warns), [str(f) for f in warns]
    else:
        assert not fails, [str(f) for f in fails]
    if fx.get("absent"):
        assert not any(fx["absent"] in f.message for f in findings), [str(f) for f in findings]


def test_the_committed_template_passes_every_tree_check():
    skip = set() if helm_ok() else {"render-check"}
    findings = checks.run(checks.Ctx(TEMPLATE, today=dt.date(2026, 11, 26)), skip=skip)
    fails = [str(f) for f in findings if f.level == "FAIL"]
    assert not fails, fails
    # the first real lifecycle warnings (design section 4): PB6 and the deprecated model-specific NIM
    warns = [f.message for f in findings if f.level == "WARN"]
    assert any("nim-production-branch: support ends 2027-01-31" in w for w in warns), warns
    assert any("chat/nemotron-super: support ends 2027-01-31" in w for w in warns), warns


def test_checks_cli_exit_codes(tmp_path):
    ok = subprocess.run([sys.executable, str(TEMPLATE / "tools/checks.py"), "--only", "evidence,digests-only"],
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    root = copy_template(tmp_path / "t")
    (root / "catalogue/evidence/qa/chat-glm-2026-11-21.yaml").unlink()
    bad = subprocess.run([sys.executable, str(root / "tools/checks.py"), "--root", str(root), "--only", "evidence"],
                         capture_output=True, text=True)
    assert bad.returncode == 1 and "has no qa smoke pass" in bad.stdout
    usage = subprocess.run([sys.executable, str(TEMPLATE / "tools/checks.py"), "--only", "no-such-check"],
                           capture_output=True, text=True)
    assert usage.returncode == 2


# ---- section 13 item 4: the evidence rule, both directions, on the PROD block specifically
def test_evidence_prod_block_without_qa_pass_is_rejected_and_with_one_accepted(tmp_path):
    root = copy_template(tmp_path / "t")
    ctx = checks.Ctx(root)
    assert not checks.c_evidence(ctx)
    qa = root / "catalogue/evidence/qa/chat-glm-2026-11-21.yaml"
    saved = qa.read_text()
    qa.unlink()
    msgs = checks.c_evidence(ctx)
    assert msgs and all("chat/glm: prod block" in m for m in msgs), msgs
    qa.write_text(saved)
    assert not checks.c_evidence(ctx)


def test_evidence_must_match_the_whole_triple(tmp_path):
    root = copy_template(tmp_path / "t")
    rec = root / "catalogue/evidence/qa/chat-glm-2026-11-21.yaml"
    rec.write_text(rec.read_text().replace("weights_revision: r2026-11", "weights_revision: r2026-10"))
    assert any("chat/glm: prod block" in m for m in checks.c_evidence(checks.Ctx(root)))


# ---- section 13 item 6: the speech service renders and passes the same gates
def test_speech_service_is_rendered_and_gated():
    for env in ("dev", "qa"):
        kinds = sorted(o["kind"] for o in checks.objs(TEMPLATE, env, folder="30-services")
                       if o["metadata"]["name"] == "speech-asr")
        assert kinds == ["Deployment", "NetworkPolicy", "Service"]
        smoke = [o for o in checks.objs(TEMPLATE, env, "Job", "40-gateway") if o["metadata"]["name"].startswith("smoke-speech-asr-")]
        assert len(smoke) == 1
    assert not [o for o in checks.objs(TEMPLATE, "prod") if o["metadata"]["name"].startswith(("speech-asr", "smoke-speech"))]
    assert not [m for m in checks.c_evidence(checks.Ctx(TEMPLATE)) if "speech" in m]


def test_speech_qa_block_needs_its_dev_pass_too(tmp_path):
    root = copy_template(tmp_path / "t")
    (root / "catalogue/evidence/dev/speech-asr-2026-11-12.yaml").unlink()
    assert any(m.startswith("speech/asr: qa block") for m in checks.c_evidence(checks.Ctx(root)))
