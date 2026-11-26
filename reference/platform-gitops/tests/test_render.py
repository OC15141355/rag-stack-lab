"""Section 13 items 1-2: render.py renders clusters/{dev,qa,prod} offline from the catalogue, templates and vendored
charts; --check passes; golden tests: a bump in one env changes only that env; rendered NIM objects validate
against the vendored NIM Operator v3.1.4 CRDs (the chart's CRDs equal the repo's pinned copies)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import TEMPLATE, apply_ops, copy_template, need_helm

import render  # noqa: E402


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    need_helm()
    out = tmp_path_factory.mktemp("render")
    render.write_tree(out, render.render_all(TEMPLATE))
    return out


def changed(a: Path, b: Path) -> set[str]:
    return {d.split("/")[0] for d in render.diff_trees(a, b)}


def test_render_check_passes_on_the_committed_tree():
    need_helm()
    r = subprocess.run([sys.executable, str(TEMPLATE / "tools/render.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_render_is_deterministic(fresh, tmp_path):
    render.write_tree(tmp_path, render.render_all(TEMPLATE))
    assert render.diff_trees(fresh, tmp_path) == []
    assert render.diff_trees(fresh, TEMPLATE / "clusters") == []


def test_layout_is_the_five_folders_per_env(fresh):
    for env in render.ENVS:
        assert sorted(p.name for p in (fresh / env).iterdir()) == list(render.FOLDERS)


def test_golden_service_bump_in_dev_changes_only_dev(fresh, tmp_path):
    root = copy_template(tmp_path / "t")
    apply_ops(root, [{"file": "catalogue/services.yaml", "set": ["services", 1, "envs", "dev", "image"],
                      "value": "registry.internal.example/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:1.15.3@sha256:" + "a" * 64}])
    out = tmp_path / "out"
    render.write_tree(out, render.render_all(root))
    assert changed(fresh, out) == {"dev"}
    diffs = render.diff_trees(fresh / "dev", out / "dev")
    assert "30-services/chat-nemotron-super.yaml" in diffs
    assert "40-gateway/smoke.yaml" in diffs                     # new render hash -> new smoke Job
    assert "20-weights/chat-nemotron-super.yaml" not in diffs   # same weights revision: the PVC is untouched


def test_golden_glm_dev_bump_changes_only_dev(fresh, tmp_path):
    """The large model's three env blocks are written out in full (no YAML aliases): editing DEV's text changes
    DEV only. With the old shared anchor this edit silently moved QA and PROD too."""
    root = copy_template(tmp_path / "t")
    text = (root / "catalogue/services.yaml").read_text()
    old = "glm-5.3:2.2.1@sha256:c7953683fd32ad8139618e601834a972cb450d2f0d26242576ff7a37b4a7bb54"
    assert text.count(old) == 3
    (root / "catalogue/services.yaml").write_text(text.replace(old, "glm-5.3:2.2.2@sha256:" + "c" * 64, 1))
    out = tmp_path / "out"
    render.write_tree(out, render.render_all(root))
    assert changed(fresh, out) == {"dev"}


def test_service_hash_is_the_committed_file_hash():
    import hashlib
    for env, sid in (("prod", "chat/glm"), ("qa", "speech/asr")):
        f = TEMPLATE / "clusters" / env / "30-services" / f"{sid.replace('/', '-')}.yaml"
        assert render.service_hash(TEMPLATE, env, sid) == "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest()


def test_foundations_and_verify_layout():
    for env in render.ENVS:
        for f in ("10-platform/namespaces.yaml", "00-crds/nim-operator-crds.yaml"):
            for d in docs(env, f):
                assert d["metadata"]["annotations"]["argocd.argoproj.io/sync-options"] == "Prune=false,Delete=false"
        assert not by(docs(env, "20-weights/chat-glm.yaml"), "Job"), "verify Jobs live in 20-weights/verify/ only"
        (job,) = by(docs(env, "20-weights/verify/chat-glm.yaml"), "Job")
        assert job["metadata"]["labels"]["app"] == "weights-verify"
    for j in by(docs("prod", "40-gateway/smoke.yaml"), "Job"):
        assert j["spec"]["ttlSecondsAfterFinished"] == 604800


def test_golden_platform_bump_in_qa_changes_only_qa(fresh, tmp_path):
    root = copy_template(tmp_path / "t")
    apply_ops(root, [{"file": "catalogue/platform.yaml", "set": ["components", 2, "envs", "qa", "images", "operator.image"],
                      "value": "registry.internal.example/nvidia/cloud-native/k8s-nim-operator:v3.1.5@sha256:" + "b" * 64}])
    out = tmp_path / "out"
    render.write_tree(out, render.render_all(root))
    assert changed(fresh, out) == {"qa"}
    assert render.diff_trees(fresh / "qa", out / "qa") == ["10-platform/nim-operator.yaml"]


def test_golden_shared_template_change_shows_in_every_env(fresh, tmp_path):
    root = copy_template(tmp_path / "t")
    apply_ops(root, [{"file": "services/templates/nimservice.yaml", "replace": ["sharedMemorySizeLimit: 16Gi", "sharedMemorySizeLimit: 32Gi"]}])
    out = tmp_path / "out"
    render.write_tree(out, render.render_all(root))
    assert changed(fresh, out) == {"dev", "qa", "prod"}   # which is why one-env-per-pr gates it


def test_chart_version_not_vendored_is_an_error(tmp_path):
    need_helm()
    root = copy_template(tmp_path / "t")
    apply_ops(root, [{"file": "catalogue/platform.yaml", "set": ["components", 0, "envs", "prod", "version"], "value": "v25.10.0"}])
    with pytest.raises(render.RenderError, match="gpu-operator-v25.10.0.tgz is not vendored"):
        render.render_all(root)


def test_tampered_chart_archive_is_an_error(tmp_path):
    need_helm()
    root = copy_template(tmp_path / "t")
    p = root / "platform/charts/k8s-nim-operator-3.1.4.tgz"
    p.write_bytes(p.read_bytes() + b"\0")
    with pytest.raises(render.RenderError, match="does not match SHA256SUMS"):
        render.render_all(root)


def test_helm_version_is_pinned(tmp_path):
    need_helm()
    root = copy_template(tmp_path / "t")
    apply_ops(root, [{"file": "catalogue/platform.yaml", "set": ["tools", "helm"], "value": "v3.0.0"}])
    with pytest.raises(render.RenderError, match="pins tools.helm v3.0.0"):
        render.render_all(root)


def test_render_cli_check_detects_a_hand_edit(tmp_path):
    need_helm()
    root = copy_template(tmp_path / "t")
    f = root / "clusters/prod/30-services/chat-glm.yaml"
    f.write_text(f.read_text().replace("replicas: 1", "replicas: 2"))
    r = subprocess.run([sys.executable, str(root / "tools/render.py"), "--check", "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "clusters/prod/30-services/chat-glm.yaml" in r.stdout


def test_unknown_placeholder_is_an_error_not_an_empty_string(tmp_path):
    need_helm()
    root = copy_template(tmp_path / "t")
    apply_ops(root, [{"file": "services/templates/nimservice.yaml", "replace": ['name: "${name}"', 'name: "${nmae}"']}])
    with pytest.raises(render.RenderError, match=r"unknown placeholder \$\{nmae\}"):
        render.render_all(root)


# ---- what the rendered objects say (the lab defaults, section 11)
def docs(env, rel):
    return render.load_yaml_docs(TEMPLATE / "clusters" / env / rel)


def by(ds, kind):
    return [d for d in ds if d["kind"] == kind]


def test_every_object_is_labelled_managed_by():
    for env in render.ENVS:
        for f in (TEMPLATE / "clusters" / env).rglob("*.yaml"):
            for d in render.load_yaml_docs(f):
                assert d["metadata"]["labels"]["managed-by"] == "platform-gitops", (f, d["metadata"]["name"])


def test_nim_defaults_per_env():
    for env, airgapped in (("dev", False), ("qa", True), ("prod", True)):
        (svc,) = by(docs(env, "30-services/chat-glm.yaml"), "NIMService")
        (cache,) = by(docs(env, "30-services/chat-glm.yaml"), "NIMCache")
        assert svc["spec"]["storage"]["readOnly"] is False
        assert ("authSecret" in svc["spec"]) is (not airgapped)
        assert ("authSecret" in cache["spec"]["source"]["ngc"]) is (not airgapped)
        assert cache["spec"]["storage"]["pvc"] == {"create": False, "name": "glm-r2026-11"}
        envs = {e["name"]: e["value"] for e in svc["spec"]["env"]}
        assert envs["NIM_PASSTHROUGH_ARGS"] == "--enable-auto-tool-choice --tool-call-parser glm45"
        assert svc["spec"]["resources"]["limits"]["nvidia.com/gpu"] == 8
        # 2400 s measured cold start -> startup probe budget covers it (10 s period)
        assert svc["spec"]["startupProbe"]["probe"]["failureThreshold"] * 10 >= 2400


def test_weights_pvc_and_verify_job():
    (pvc,) = by(docs("prod", "20-weights/chat-glm.yaml"), "PersistentVolumeClaim")
    (job,) = by(docs("prod", "20-weights/verify/chat-glm.yaml"), "Job")
    assert pvc["spec"]["storageClassName"] == "weights-retain"
    assert pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-options"] == "Prune=false,Delete=false"
    assert job["spec"]["template"]["spec"]["volumes"][0]["persistentVolumeClaim"]["claimName"] == "glm-r2026-11"
    assert "2315582919fe093f5572208dbf73b6e63263920491504b8466442ebc8588eecf" in job["spec"]["template"]["spec"]["containers"][0]["command"]
    (sc,) = by(docs("prod", "10-platform/storage.yaml"), "StorageClass")
    assert sc["reclaimPolicy"] == "Retain"


def test_gateway_config_lessons():
    for env in render.ENVS:
        (cm,) = by(docs(env, "40-gateway/bifrost-config.yaml"), "ConfigMap")
        cfg = json.loads(cm["data"]["config.json"])
        assert cfg["client"]["disable_content_logging"] is True
        for p in cfg["providers"].values():
            assert p["network_config"]["allow_private_network"] is True       # in-cluster providers only
            assert p["network_config"]["base_url"].endswith(".models.svc.cluster.local:8000")
        for vk in cfg["governance"]["virtual_keys"]:
            assert all(pc["key_ids"] == ["*"] for pc in vk["provider_configs"])
        for section in render.GOVERNANCE_LISTS:
            assert section in cfg["governance"], section                     # always emitted, even empty
        (dep,) = by(docs(env, "40-gateway/bifrost.yaml"), "Deployment")
        c = dep["spec"]["template"]["spec"]["containers"][0]
        assert "args" not in c and c["image"].endswith(tuple("0123456789abcdef")) and "@sha256:" in c["image"]
        ann = dep["spec"]["template"]["metadata"]["annotations"]
        assert set(ann) == {"platform-gitops/config-hash", "platform-gitops/secret-hash.bifrost-env"}


def test_secret_hash_follows_the_sops_file(tmp_path):
    need_helm()
    root = copy_template(tmp_path / "t")
    f = root / "secrets/qa/bifrost-env.sops.yaml"
    f.write_text(f.read_text() + "\n")
    out = tmp_path / "out"
    render.write_tree(out, render.render_all(root))
    # the pod rolls (new secret-hash) and, because 40-gateway changed, the smoke Job is re-run under a new name
    assert render.diff_trees(TEMPLATE / "clusters", out) == ["qa/40-gateway/bifrost.yaml", "qa/40-gateway/smoke.yaml"]


def test_smoke_job_carries_the_render_hash_and_cold_start_deadline():
    (job,) = [j for j in by(docs("prod", "40-gateway/smoke.yaml"), "Job") if j["metadata"]["name"].startswith("smoke-")]
    c = job["spec"]["template"]["spec"]["containers"][0]
    rh = {e["name"]: e.get("value") for e in c["env"]}["SYNC_REVISION"]
    assert rh.startswith("sha256:") and job["metadata"]["name"] == f"smoke-{rh[7:19]}"
    assert job["spec"]["activeDeadlineSeconds"] >= 2400        # chat/glm's measured cold start
    assert job["spec"]["backoffLimit"] == 0
    texts = {str(p.relative_to(TEMPLATE / "clusters/prod")): p.read_text() for p in (TEMPLATE / "clusters/prod").rglob("*.yaml")}
    assert render.render_hash(texts) == rh
