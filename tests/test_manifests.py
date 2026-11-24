import shutil, subprocess, pytest, yaml
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl needed")

def build(path):
    out = subprocess.run(["kubectl", "kustomize", str(ROOT / path)], capture_output=True, text=True, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]

@pytest.mark.parametrize("env", ["dev", "qa", "prod"])
def test_env_overlay(env):
    docs = build(f"lab/envs/{env}")
    kinds = {(d["kind"], d["metadata"]["name"].split("-")[0]) for d in docs}
    assert ("Deployment", "bifrost") in kinds and ("Job", "smoke") in kinds
    for d in docs:
        assert d["metadata"].get("namespace", f"raglab-{env}") == f"raglab-{env}"
    dep = next(d for d in docs if d["kind"] == "Deployment")
    assert dep["spec"]["strategy"]["type"] == "Recreate"
    c = dep["spec"]["template"]["spec"]["containers"][0]
    assert "@sha256:" in c["image"] and c["resources"]["limits"]["memory"]
    cms = [d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"].startswith("bifrost-config-")]
    assert cms, "configMapGenerator must add a hash suffix (forces rollout on change)"
    pvc = next(d for d in docs if d["kind"] == "PersistentVolumeClaim")
    assert pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-options"] == "Prune=false,Delete=false"
    job = next(d for d in docs if d["kind"] == "Job")
    assert job["metadata"]["annotations"]["argocd.argoproj.io/hook"] == "PostSync"
    jc = job["spec"]["template"]["spec"]["containers"][0]
    assert "@sha256:" in jc["image"] and "REPLACE" not in jc["image"]
    cmd = jc["command"]
    assert "--require-negative-checks" in cmd and "--require-revision" in cmd
    envs = {e["name"] for e in jc["env"]}
    assert {"BIFROST_VK", "BIFROST_VK_PROBE", "SYNC_REVISION"} <= envs
    assert "sk-bf-" not in yaml.safe_dump_all(docs)

@pytest.mark.parametrize("env", ["dev", "qa", "prod"])
def test_nim_overlay(env):
    docs = build(f"lab/nim/{env}")
    assert len(docs) == 2
    for d in docs:
        assert d["kind"] == "NIMService" and d["spec"]["replicas"] == 0
        assert "emptyDir" in d["spec"]["storage"] and "nimCache" not in d["spec"]["storage"]
