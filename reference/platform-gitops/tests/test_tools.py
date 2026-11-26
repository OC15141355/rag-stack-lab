"""Section 13 item 5 (orphan/drift lister on fixtures) and the small tools (weights verification)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from conftest import FIXTURES, TEMPLATE

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


# ---- fix round 1: finished Jobs, Secret data, extra weights files, the delete list
def _job(name, status=None):
    o = {"apiVersion": "batch/v1", "kind": "Job",
         "metadata": {"name": name, "namespace": "gateway", "labels": {"managed-by": "platform-gitops"}}}
    if status:
        o["status"] = status
    return o


def test_drift_finished_smoke_jobs_are_not_orphans_but_running_ones_are():
    inv = [_job("smoke-0123456789ab", {"succeeded": 1}),
           _job("smoke-ba9876543210", {"failed": 1, "conditions": [{"type": "Failed", "status": "True"}]}),
           _job("smoke-running00000", {"active": 1})]
    got = [(f["type"], f["name"]) for f in drift.report(TEMPLATE, "prod", inv)]
    assert got == [("ORPHAN", "smoke-running00000")]


def test_drift_parses_metadata_only_secrets_and_strips_values(tmp_path):
    meta_only = {"apiVersion": "v1", "kind": "List", "items": [
        {"apiVersion": "v1", "kind": "Secret", "type": "Opaque", "metadata": {"name": "bifrost-env", "namespace": "gateway"}},
        {"apiVersion": "v1", "kind": "Secret", "type": "Opaque", "metadata": {"name": "hand-made", "namespace": "gateway"}}]}
    p = tmp_path / "inv.json"
    p.write_text(json.dumps(meta_only))
    got = [(f["type"], f["name"]) for f in drift.report(TEMPLATE, "prod", drift.load_inventory(p))]
    assert got == [("UNMANAGED", "hand-made")]
    with_data = {"items": [{"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "x"},
                            "data": {"K": "c2VjcmV0"}, "stringData": {"K": "secret"}}]}
    r = subprocess.run([sys.executable, str(TEMPLATE / "tools/drift.py"), "--strip-secret-data"],
                       input=json.dumps(with_data), capture_output=True, text=True)
    assert r.returncode == 0 and "c2VjcmV0" not in r.stdout and "secret\"" not in r.stdout
    assert json.loads(r.stdout)["items"][0]["metadata"]["name"] == "x"


def test_verify_weights_rejects_files_not_in_the_manifest(tmp_path):
    sha = _weights(tmp_path)
    (tmp_path / "model/extra.bin").write_bytes(b"unreviewed")
    assert verify_weights.verify(tmp_path, sha) == ["model/extra.bin: present but not in the manifest (an unreviewed file would be served)"]


def test_prune_lists_removed_services_and_guards_weights(tmp_path):
    from conftest import apply_ops, copy_template, need_helm
    import prune
    import render
    need_helm()
    head = copy_template(tmp_path / "head")
    apply_ops(head, [{"file": "catalogue/services.yaml", "set": ["services", 1, "envs", "dev", "enabled"], "value": False}])
    render.write_tree(head / "clusters", render.render_all(head))
    lines = prune.removed(TEMPLATE, head, "dev")
    assert "models NIMService.v1alpha1.apps.nvidia.com/chat-nemotron-super" in lines
    assert "models NetworkPolicy.v1.networking.k8s.io/chat-nemotron-super" in lines
    assert not [l for l in lines if "NIMCache" in l or "PersistentVolumeClaim" in l or "Job" in l]
    with_w = prune.removed(TEMPLATE, head, "dev", allow_weights=True)
    assert "models NIMCache.v1alpha1.apps.nvidia.com/nemotron-super-r2026-09" in with_w
    assert "models PersistentVolumeClaim/nemotron-super-r2026-09" in with_w
    assert prune.removed(TEMPLATE, head, "prod") == [] and prune.removed(TEMPLATE, TEMPLATE, "dev") == []


def test_wait_jobs_state_fails_fast_and_never_passes_empty():
    import wait_jobs
    ok = {"metadata": {"name": "a"}, "status": {"succeeded": 1}}
    run = {"metadata": {"name": "b"}, "status": {"active": 1}}
    bad = {"metadata": {"name": "c"}, "status": {"conditions": [{"type": "Failed", "status": "True"}]}}
    assert wait_jobs.state([ok])[0] == "succeeded"
    assert wait_jobs.state([ok, run])[0] == "running"
    assert wait_jobs.state([run, bad])[0] == "failed"     # fail fast: one failure ends the wait
    assert wait_jobs.state([])[0] == "none"
