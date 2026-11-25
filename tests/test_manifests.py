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
    # TEMP (acceptance criterion 4): PVC removed from git for the prune test; reverted by the next PR.
    pvcs = [d for d in docs if d["kind"] == "PersistentVolumeClaim"]
    for pvc in pvcs:
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

# ---- fix round 1: stricter assertions ----
import json
IMAGE = "maximhq/bifrost:v2.6.0@sha256:5968d007ba4f74ee01bc4ceb071decb9927a0b7bb43dbb9072208f75e2d522e3"
CLUSTER_SCOPED = {"Namespace", "CustomResourceDefinition", "ClusterRole", "ClusterRoleBinding"}

def by(docs, kind, name=None):
    return [d for d in docs if d["kind"] == kind and (name is None or d["metadata"]["name"] == name)]

def pod_specs(docs):
    return [(d["kind"], d["spec"]["template"]["spec"]) for d in docs if d["kind"] in ("Deployment", "Job")]

@pytest.mark.parametrize("env", ["dev", "qa", "prod"])
@pytest.mark.parametrize("path", ["lab/envs", "lab/nim"])
def test_namespace_explicit(env, path):
    for d in build(f"{path}/{env}"):
        if d["kind"] not in CLUSTER_SCOPED:
            assert d["metadata"].get("namespace") == f"raglab-{env}", d["metadata"]["name"]

@pytest.mark.parametrize("env", ["dev", "qa", "prod"])
def test_bifrost_container(env):
    docs = build(f"lab/envs/{env}")
    c = by(docs, "Deployment", "bifrost")[0]["spec"]["template"]["spec"]["containers"][0]
    assert c["image"] == IMAGE
    assert "args" not in c and "command" not in c  # v2.6.0 entrypoint loops on unknown args
    e = {x["name"]: x.get("value") for x in c["env"]}
    assert e == {"APP_HOST": "0.0.0.0", "APP_PORT": "8080", "APP_DIR": "/app/data", "LOG_LEVEL": "info"}

@pytest.mark.parametrize("env", ["dev", "qa", "prod"])
def test_job_args_and_env(env):
    jc = by(build(f"lab/envs/{env}"), "Job", "smoke")[0]["spec"]["template"]["spec"]["containers"][0]
    cmd = jc["command"]
    assert cmd[cmd.index("--expect-limit") + 1] == "rate limit violated for vk"
    for e in jc["env"]:
        assert "value" not in e
        if e["name"] in ("BIFROST_VK", "BIFROST_VK_PROBE"):
            assert e["valueFrom"]["secretKeyRef"]["name"] == "bifrost-env"

@pytest.mark.parametrize("env", ["dev", "qa", "prod"])
def test_network_policies(env):
    docs = build(f"lab/envs/{env}")
    bif = by(docs, "NetworkPolicy", "bifrost")[0]["spec"]
    assert len(bif["ingress"]) == 1
    ing = bif["ingress"][0]
    assert ing["ports"] == [{"port": 8080}]
    assert ing["from"] == [
        {"podSelector": {"matchLabels": {"app": "smoke"}}},
        {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
         "podSelector": {"matchLabels": {"app.kubernetes.io/name": "traefik"}}}]
    dns, web = bif["egress"]
    assert {(p["port"], p["protocol"]) for p in dns["ports"]} == {(53, "UDP"), (53, "TCP")}
    assert web["ports"] == [{"port": 443}]
    blk = web["to"][0]["ipBlock"]
    assert blk["cidr"] == "0.0.0.0/0"
    assert set(blk["except"]) == {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"}
    sm = by(docs, "NetworkPolicy", "smoke")[0]["spec"]
    assert sm["policyTypes"] == ["Egress"]
    sdns = [r for r in sm["egress"] if any(p["port"] == 53 for p in r["ports"])][0]
    assert {(p["port"], p["protocol"]) for p in sdns["ports"]} == {(53, "UDP"), (53, "TCP")}

@pytest.mark.parametrize("env", ["dev", "qa", "prod"])
def test_ingressroute_only_v1(env):
    ir = by(build(f"lab/envs/{env}"), "IngressRoute")[0]
    assert len(ir["spec"]["routes"]) == 1
    m = ir["spec"]["routes"][0]["match"]
    assert m == f"Host(`raglab-{env}.lab`) && PathPrefix(`/v1`)"

@pytest.mark.parametrize("env", ["dev", "qa", "prod"])
def test_pss_fields(env):
    specs = pod_specs(build(f"lab/envs/{env}"))
    assert {k for k, _ in specs} == {"Deployment", "Job"}
    for _, s in specs:
        assert s["securityContext"]["runAsNonRoot"] is True
        assert s["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        for c in s["containers"]:
            assert c["securityContext"]["allowPrivilegeEscalation"] is False
            assert c["securityContext"]["capabilities"]["drop"] == ["ALL"]

@pytest.mark.parametrize("env", ["dev", "qa", "prod"])
def test_nim_crd_schema(env):
    jsonschema = pytest.importorskip("jsonschema")
    crd = yaml.safe_load((ROOT / "tests/fixtures/crds/apps.nvidia.com_nimservices.yaml").read_text())
    ver = next(v for v in crd["spec"]["versions"] if v["name"] == "v1alpha1")
    schema = ver["schema"]["openAPIV3Schema"]
    docs = build(f"lab/nim/{env}")
    assert {d["metadata"]["name"] for d in docs} == {"glm", "nemotron"}
    for d in docs:
        assert d["apiVersion"] == "apps.nvidia.com/v1alpha1"
        jsonschema.validate(d["spec"], schema["properties"]["spec"])
