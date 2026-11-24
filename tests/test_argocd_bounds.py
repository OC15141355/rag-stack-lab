"""Static bounds on what a merge to main can make Argo CD do. No cluster needed."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
ARGO = ROOT / "lab" / "argocd"
ENVS = {"raglab-dev", "raglab-qa", "raglab-prod"}

def load(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]

def apps():
    files = sorted((ARGO / "apps").glob("*.yaml"))
    assert files
    return [(f, d) for f in files for d in load(f)]

def test_apps_are_raglab_project_env_namespaces_only():
    for f, d in apps():
        assert d["kind"] == "Application", f
        assert d["spec"]["project"] == "raglab", f
        assert d["spec"]["destination"].get("namespace", "raglab-dev") in ENVS or f.name == "raglab-secrets.yaml", f
        opts = d["spec"].get("syncPolicy", {}).get("syncOptions", [])
        assert not any(o.startswith("CreateNamespace") for o in opts), f
        assert "managedNamespaceMetadata" not in d["spec"].get("syncPolicy", {}), f

def test_apps_dir_has_no_projects_or_privileged_targets():
    for f, d in apps():
        assert d["kind"] != "AppProject", f
        ns = d["spec"]["destination"].get("namespace")
        assert ns not in {"raglab-system", "argocd", "kube-system"}, f

def test_raglab_project_bounds():
    (p,) = load(ARGO / "hand-applied" / "appproject-raglab.yaml")
    s = p["spec"]
    assert s["clusterResourceWhitelist"] == []
    assert {d["namespace"] for d in s["destinations"]} == ENVS
    got = {(r["group"], r["kind"]) for r in s["namespaceResourceWhitelist"]}
    assert got == {("", "ConfigMap"), ("", "Secret"), ("", "Service"), ("", "PersistentVolumeClaim"),
                   ("apps", "Deployment"), ("batch", "Job"), ("networking.k8s.io", "NetworkPolicy"),
                   ("traefik.io", "IngressRoute"), ("apps.nvidia.com", "NIMService")}
    assert s["sourceRepos"] == ["https://github.com/OC15141355/rag-stack-lab.git"]

def test_default_project_locked():
    (p,) = load(ARGO / "hand-applied" / "appproject-default-locked.yaml")
    s = p["spec"]
    assert p["metadata"]["name"] == "default"
    assert s["sourceRepos"] == [] and s["destinations"] == [] and s["clusterResourceWhitelist"] == []
    assert s["namespaceResourceBlacklist"] == [{"group": "*", "kind": "*"}]

def test_platform_project_cluster_whitelist_name_restricted():
    (p,) = load(ARGO / "hand-applied" / "appproject-raglab-platform.yaml")
    s = p["spec"]
    assert s["clusterResourceWhitelist"] and all("name" in e for e in s["clusterResourceWhitelist"])
    assert [d["namespace"] for d in s["destinations"]] == ["raglab-system"]
    assert s["sourceRepos"] == ["https://helm.ngc.nvidia.com/nvidia"]

def test_raglab_system_uses_platform_project_with_inline_values():
    (a,) = load(ARGO / "hand-applied" / "raglab-system.yaml")
    assert a["spec"]["project"] == "raglab-platform"
    assert "source" in a["spec"] and "valuesObject" in a["spec"]["source"]["helm"]
    assert "CreateNamespace=true" not in a["spec"]["syncPolicy"].get("syncOptions", [])

def test_cmp_script_has_app_name_guard():
    (cm,) = load(ARGO / "hand-applied" / "cmp-plugin.yaml")
    script = cm["data"]["sops-kustomize.yaml"]
    assert '[ "$ARGOCD_APP_NAME" = raglab-secrets ]' in script
    assert '[ "$ARGOCD_APP_SOURCE_PATH" = lab/secrets ]' in script
    assert script.index("ARGOCD_APP_NAME") < script.index("sops --decrypt")

def test_nothing_hand_applied_under_apps():
    names = {f.name for f in (ARGO / "apps").glob("*.yaml")}
    for n in ["raglab-system.yaml", "root-app.yaml", "cmp-plugin.yaml", "namespaces.yaml"]:
        assert n not in names
