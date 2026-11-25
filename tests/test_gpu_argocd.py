"""Phase B: static bounds for the rented-GPU-cluster Argo CD files, and Phase A isolation. No cluster needed."""
from pathlib import Path
import pytest, yaml

ROOT = Path(__file__).resolve().parents[1]
GPU = ROOT / "lab" / "gpu" / "argocd"
HA = GPU / "hand-applied"
GPU_NS = {"raglab-gpu", "raglab-dev-gpu"}
REPO = "https://github.com/OC15141355/rag-stack-lab.git"
PLACEHOLDER = "PENDING-GO-NO-GO"

def load(p):
    return [d for d in yaml.safe_load_all(Path(p).read_text()) if d]

def one(p):
    (d,) = load(p); return d

def gpu_apps():
    files = sorted((GPU / "apps").glob("*.yaml"))
    assert files
    return [(f, d) for f in files for d in load(f)]

def rendered(name):
    lines = (GPU / "rendered" / name).read_text().splitlines()
    cluster = {tuple(l.split(None, 1)[1].split("/", 2)) for l in lines if l.startswith("CLUSTER ")}
    ns = {tuple(l.split(None, 1)[1].split("/", 1)) for l in lines if l.startswith("NS ")}
    assert not [l for l in lines if l.startswith("UNKNOWN ")], f"{name}: unknown-scope kinds need a decision"
    return cluster, ns

def test_gpu_apps_bounded():
    for f, d in gpu_apps():
        s = d["spec"]
        assert d["kind"] == "Application" and d["metadata"]["namespace"] == "raglab-apps", f
        assert s["project"] == "raglab-gpu", f
        assert s["destination"]["namespace"] in GPU_NS, f
        assert s["source"]["repoURL"] == REPO and s["source"]["targetRevision"] == "main", f
        assert s["source"]["path"].startswith("lab/gpu/"), f
        opts = s.get("syncPolicy", {}).get("syncOptions", [])
        assert not any(o.startswith("CreateNamespace") for o in opts), f

def test_only_secrets_app_uses_the_cmp():
    users = [d["metadata"]["name"] for _, d in gpu_apps() if "plugin" in d["spec"]["source"]]
    assert users == ["raglab-gpu-secrets"]
    (app,) = [d for _, d in gpu_apps() if d["metadata"]["name"] == "raglab-gpu-secrets"]
    assert app["spec"]["source"]["path"] == "lab/gpu/secrets"
    assert "ServerSideApply=true" in app["spec"]["syncPolicy"]["syncOptions"]

def test_gpu_cmp_guard():
    script = one(HA / "cmp-plugin.yaml")["data"]["sops-kustomize.yaml"]
    assert '[ "$ARGOCD_APP_NAME" = raglab-apps_raglab-gpu-secrets ]' in script
    assert '[ "$ARGOCD_APP_SOURCE_PATH" = lab/gpu/secrets ]' in script
    assert script.index("ARGOCD_APP_NAME") < script.index("sops --decrypt")

def test_raglab_gpu_project_bounds():
    s = one(HA / "appproject-raglab-gpu.yaml")["spec"]
    assert s["sourceNamespaces"] == ["raglab-apps"] and s["sourceRepos"] == [REPO]
    assert {d["namespace"] for d in s["destinations"]} == GPU_NS
    assert s["clusterResourceWhitelist"] == []
    assert {(r["group"], r["kind"]) for r in s["namespaceResourceWhitelist"]} == {
        ("", "ConfigMap"), ("", "Secret"), ("", "Service"), ("", "PersistentVolumeClaim"), ("apps", "Deployment"),
        ("batch", "Job"), ("networking.k8s.io", "NetworkPolicy"), ("apps.nvidia.com", "NIMService"),
        ("apps.nvidia.com", "NIMCache")}

def test_platform_project_matches_rendered_charts_exactly():
    s = one(HA / "appproject-raglab-gpu-platform.yaml")["spec"]
    assert s["sourceRepos"] == ["https://helm.ngc.nvidia.com/nvidia"]
    assert not s.get("sourceNamespaces")
    assert {d["namespace"] for d in s["destinations"]} == {"gpu-operator", "raglab-system"}
    gc, gn = rendered("gpu-operator-v26.7.3.txt")
    nc, nn = rendered("k8s-nim-operator-3.1.4.txt")
    want = set(gc) | {t for t in nc if not (t[1] == "CustomResourceDefinition" and t[2].endswith(".apps.nvidia.com"))}
    want.add(("apiextensions.k8s.io", "CustomResourceDefinition", "*.apps.nvidia.com"))
    got = {(e["group"], e["kind"], e["name"]) for e in s["clusterResourceWhitelist"]}
    assert got == want
    assert {(e["group"], e["kind"]) for e in s["namespaceResourceWhitelist"]} == gn | nn
    assert not any(k == "RuntimeClass" for _, k, _ in got), "NRI path: no RuntimeClass (spec section 6)"

def test_gpu_operator_app():
    a = one(HA / "raglab-gpu-operator.yaml"); s = a["spec"]; src = s["source"]
    assert s["project"] == "raglab-gpu-platform" and a["metadata"]["namespace"] == "argocd"
    assert (src["repoURL"], src["chart"], src["targetRevision"]) == ("https://helm.ngc.nvidia.com/nvidia", "gpu-operator", "v26.7.3")
    v = src["helm"]["valuesObject"]
    assert v["driver"]["enabled"] is False
    assert v["cdi"] == {"enabled": True, "nriPluginEnabled": True}
    assert v["dcgmExporter"]["enabled"] is False and v["migManager"]["enabled"] is False
    flat = yaml.safe_dump(v)
    assert "CONTAINERD_CONFIG" not in flat and "CONTAINERD_SOCKET" not in flat, "NRI path: no k3s containerd vars"
    assert s["destination"]["namespace"] == "gpu-operator"
    assert {"ServerSideApply=true", "RespectIgnoreDifferences=true"} <= set(s["syncPolicy"]["syncOptions"])
    assert [(i["group"], i["kind"]) for i in s["ignoreDifferences"]] == [("nvidia.com", "ClusterPolicy")]

def test_nim_operator_app_equals_phase_a_values():
    a = one(HA / "raglab-nim-operator.yaml")["spec"]
    p = one(ROOT / "lab/argocd/hand-applied/raglab-system.yaml")["spec"]
    assert a["project"] == "raglab-gpu-platform" and a["destination"]["namespace"] == "raglab-system"
    for k in ("repoURL", "chart", "targetRevision"):
        assert a["source"][k] == p["source"][k]
    assert a["source"]["helm"]["valuesObject"] == p["source"]["helm"]["valuesObject"]

def test_gpu_root_only_creates_applications():
    docs = load(HA / "root-app.yaml")
    (proj,) = [d for d in docs if d["kind"] == "AppProject"]
    (app,) = [d for d in docs if d["kind"] == "Application"]
    assert app["metadata"]["name"] == "raglab-gpu-root" and app["spec"]["project"] == "raglab-gpu-root"
    assert app["spec"]["source"]["path"] == "lab/gpu/argocd/apps"
    assert proj["spec"]["namespaceResourceWhitelist"] == [{"group": "argoproj.io", "kind": "Application"}]
    assert proj["spec"]["clusterResourceWhitelist"] == []
    assert [d["namespace"] for d in proj["spec"]["destinations"]] == ["raglab-apps"]

def test_gpu_namespaces_pod_security():
    ns = {d["metadata"]["name"]: d["metadata"]["labels"] for d in load(HA / "namespaces.yaml")}
    enforce = {k: v["pod-security.kubernetes.io/enforce"] for k, v in ns.items()}
    assert enforce == {"argocd": "restricted", "raglab-apps": "restricted", "raglab-system": "baseline",
                       "gpu-operator": "privileged", "raglab-gpu": "baseline", "raglab-dev-gpu": "restricted"}
    assert ns["raglab-gpu"]["pod-security.kubernetes.io/warn"] == "restricted"

def test_copied_hand_applied_files_identical_to_phase_a():
    for n in ("appproject-default-locked.yaml", "repo-server-egress.yaml"):
        assert (HA / n).read_text() == (ROOT / "lab/argocd/hand-applied" / n).read_text(), n

def test_phase_a_never_sees_gpu_paths():
    (root,) = [d for d in load(ROOT / "lab/argocd/hand-applied/root-app.yaml") if d["kind"] == "Application"]
    assert root["spec"]["source"]["path"] == "lab/argocd/apps"
    for f in (ROOT / "lab/argocd").rglob("*.yaml"):
        assert "lab/gpu" not in f.read_text(), f
    for f, d in gpu_apps():
        p = d["spec"]["source"]["path"]
        assert p != "lab/secrets" and not p.startswith("lab/envs/") and not p.startswith("lab/nim/"), f

def test_nim_app_only_after_go_no_go():
    """raglab-gpu-nim is added by the go/no-go PR; from then on no placeholder may remain."""
    nim_app = GPU / "apps" / "raglab-gpu-nim.yaml"
    texts = [(ROOT / "lab/gpu/nim" / f).read_text() for f in ("nimcache.yaml", "nimservice.yaml")]
    if nim_app.exists():
        assert all(PLACEHOLDER not in t for t in texts), "go/no-go PR must fill the profile"
        d = one(nim_app)
        assert d["spec"]["source"]["path"] == "lab/gpu/nim" and d["spec"]["destination"]["namespace"] == "raglab-gpu"
    else:
        assert all(PLACEHOLDER in t for t in texts)
