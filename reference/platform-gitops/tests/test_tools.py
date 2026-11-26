"""Section 13 item 5 (orphan/drift lister on fixtures) and the small tools: weights verification, the smoke.py copy."""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from conftest import FIXTURES, REPO, TEMPLATE

import drift  # noqa: E402
import verify_weights  # noqa: E402

INV = FIXTURES / "drift"


def test_drift_clean_inventory_has_no_findings():
    assert drift.report(TEMPLATE, "prod", drift.load_inventory(INV / "clean.json")) == []


def test_drift_finds_the_planted_orphan_and_the_hand_applied_object():
    got = {(f["type"], f["kind"], f["name"]) for f in drift.report(TEMPLATE, "prod", drift.load_inventory(INV / "orphan.json"))}
    assert got == {("ORPHAN", "NIMService", "chat-retired-model"), ("UNMANAGED", "Deployment", "debug-shell")}


def test_drift_cli_exit_codes():
    def run(inv):
        return subprocess.run([sys.executable, str(TEMPLATE / "tools/drift.py"), "--env", "prod", "--inventory", str(inv)],
                              capture_output=True, text=True)
    assert run(INV / "clean.json").returncode == 0
    r = run(INV / "orphan.json")
    assert r.returncode == 1 and "ORPHAN" in r.stdout and "chat-retired-model" in r.stdout
    assert run(INV / "missing.json").returncode == 2


def test_drift_orphan_is_env_specific():
    # speech-asr is rendered for qa, so a labelled speech Deployment is fine there and an orphan in prod
    inv = [{"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": "speech-asr", "namespace": "models", "labels": {"managed-by": "platform-gitops"}}}]
    assert drift.report(TEMPLATE, "qa", inv) == []
    assert [f["type"] for f in drift.report(TEMPLATE, "prod", inv)] == ["ORPHAN"]


def _weights(tmp: Path) -> str:
    (tmp / "model").mkdir()
    (tmp / "model/a.safetensors").write_bytes(b"weights-a")
    (tmp / "config.json").write_text("{}")
    lines = [f"{hashlib.sha256((tmp / p).read_bytes()).hexdigest()}  {p}" for p in ("model/a.safetensors", "config.json")]
    (tmp / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
    return hashlib.sha256((tmp / "MANIFEST.sha256").read_bytes()).hexdigest()


def test_verify_weights_accepts_a_good_tree_and_writes_the_marker(tmp_path):
    sha = _weights(tmp_path)
    assert verify_weights.main(["--root", str(tmp_path), "--manifest-sha256", sha]) == 0
    assert (tmp_path / f".verified-{sha}").is_file()


def test_verify_weights_rejects_tampering(tmp_path):
    sha = _weights(tmp_path)
    (tmp_path / "model/a.safetensors").write_bytes(b"tampered")
    assert verify_weights.main(["--root", str(tmp_path), "--manifest-sha256", sha]) == 1
    assert not list(tmp_path.glob(".verified-*"))


def test_verify_weights_rejects_an_unreviewed_manifest_and_path_escape(tmp_path):
    _weights(tmp_path)
    assert verify_weights.main(["--root", str(tmp_path), "--manifest-sha256", "0" * 64]) == 1
    m = tmp_path / "MANIFEST.sha256"
    m.write_text(m.read_text() + f"{'0' * 64}  ../etc/passwd\n")
    sha2 = hashlib.sha256(m.read_bytes()).hexdigest()
    assert verify_weights.verify(tmp_path, sha2) == ["line 3: path ../etc/passwd escapes the weights root"]
    assert verify_weights.main(["--root", str(tmp_path), "--manifest-sha256", "XYZ"]) == 2


def test_rendered_verify_script_is_the_tool():
    import render
    (cm,) = render.load_yaml_docs(TEMPLATE / "clusters/prod/20-weights/verify-script.yaml")
    assert cm["data"]["verify_weights.py"] == (TEMPLATE / "tools/verify_weights.py").read_text()


def test_smoke_py_is_an_exact_copy_of_the_lab_smoke():
    src = (REPO / "lab/smoke/smoke.py").read_text().splitlines(keepends=True)
    dst = (TEMPLATE / "tools/smoke.py").read_text().splitlines(keepends=True)
    assert dst[1].startswith("# COPY of rag-stack-lab lab/smoke/smoke.py")
    assert [dst[0]] + dst[2:] == src, "run scripts/sync-reference-smoke.sh"
