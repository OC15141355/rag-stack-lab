"""Phase B: lab/gpu kustomizations build, match the vendored v3.1.4 CRDs, and agree with the catalogue."""
import shutil, subprocess
from pathlib import Path
from urllib.parse import urlparse
import pytest, yaml

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl needed")
jsonschema = pytest.importorskip("jsonschema")
NIM_IMAGE = ("nvcr.io/nim/meta/llama-3.1-8b-instruct:2.1.7"
             "@sha256:5ada92d1ca5c30069956e6e1322f0fbb250b4683b566aedb6547b10a64faf00b")
PRIVATE = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"}

def build(path):
    out = subprocess.run(["kubectl", "kustomize", str(ROOT / path)], capture_output=True, text=True, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]

def by(docs, kind, name=None):
    return [d for d in docs if d["kind"] == kind and (name is None or d["metadata"]["name"] == name)]

def crd_spec_schema(plural):
    crd = yaml.safe_load((ROOT / f"tests/fixtures/crds/apps.nvidia.com_{plural}.yaml").read_text())
    ver = next(v for v in crd["spec"]["versions"] if v["name"] == "v1alpha1")
    return ver["schema"]["openAPIV3Schema"]["properties"]["spec"]

def test_nim_kustomization_validates_against_both_crds():
    docs = build("lab/gpu/nim")
    assert sorted(d["kind"] for d in docs) == ["NIMCache", "NIMService", "NetworkPolicy", "NetworkPolicy", "NetworkPolicy"]
    for d in docs:
        assert d["metadata"]["namespace"] == "raglab-gpu"
    (cache,) = by(docs, "NIMCache"); (svc,) = by(docs, "NIMService")
    jsonschema.validate(cache["spec"], crd_spec_schema("nimcaches"))
    jsonschema.validate(svc["spec"], crd_spec_schema("nimservices"))

def test_cache_and_service_agree():
    docs = build("lab/gpu/nim")
    (cache,) = by(docs, "NIMCache"); (svc,) = by(docs, "NIMService")
    ngc = cache["spec"]["source"]["ngc"]
    assert ngc["modelPuller"] == NIM_IMAGE
    assert f'{svc["spec"]["image"]["repository"]}:{svc["spec"]["image"]["tag"]}' == NIM_IMAGE
    assert ngc["model"]["profiles"] == [svc["spec"]["storage"]["nimCache"]["profile"]], "profile pinned in BOTH places"
    assert svc["spec"]["storage"]["nimCache"]["name"] == cache["metadata"]["name"] == "llama-8b"
    assert ngc["pullSecret"] == "ngc-pull" and svc["spec"]["image"]["pullSecrets"] == ["ngc-pull"]
    assert ngc["authSecret"] == svc["spec"]["authSecret"] == "ngc-api-key"
    assert cache["metadata"]["annotations"]["argocd.argoproj.io/sync-options"] == "Prune=false,Delete=false"
    assert cache["spec"]["storage"]["pvc"]["storageClass"] == "local-path"
    for d in (cache, svc):
        assert "runtimeClassName" not in d["spec"], "NRI path: leave runtimeClassName unset"
    assert svc["spec"]["replicas"] in (0, 1)
    assert svc["spec"]["resources"]["limits"]["nvidia.com/gpu"] == 1

def test_nim_network_policies():
    docs = build("lab/gpu/nim")
    deny = by(docs, "NetworkPolicy", "default-deny-ingress")[0]["spec"]
    assert deny == {"podSelector": {}, "policyTypes": ["Ingress"]}
    allow = by(docs, "NetworkPolicy", "nim-from-bifrost")[0]["spec"]
    assert allow["podSelector"] == {"matchLabels": {"app.kubernetes.io/component": "nim-llm"}}
    assert allow["ingress"] == [{"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "raglab-dev-gpu"}},
                                           "podSelector": {"matchLabels": {"app": "bifrost"}}}],
                                 "ports": [{"port": 8000, "protocol": "TCP"}]}]
    eg = by(docs, "NetworkPolicy", "egress-dns-and-public-443")[0]["spec"]
    assert eg["podSelector"] == {} and eg["policyTypes"] == ["Egress"]
    blk = eg["egress"][1]["to"][0]["ipBlock"]
    assert blk["cidr"] == "0.0.0.0/0" and set(blk["except"]) == PRIVATE and eg["egress"][1]["ports"] == [{"port": 443}]
    (svc,) = by(docs, "NIMService")
    assert svc["spec"]["labels"]["app.kubernetes.io/component"] == "nim-llm"

def test_gonogo_job_uses_the_pinned_image_and_a_gpu():
    (job,) = [d for d in yaml.safe_load_all((ROOT / "lab/gpu/gonogo/list-profiles-job.yaml").read_text()) if d]
    assert job["kind"] == "Job" and job["metadata"]["namespace"] == "raglab-gpu"
    c = job["spec"]["template"]["spec"]["containers"][0]
    assert c["image"] == NIM_IMAGE and c["command"] == ["list-model-profiles"]
    assert c["resources"]["limits"]["nvidia.com/gpu"] == 1
    assert job["spec"]["template"]["spec"]["imagePullSecrets"] == [{"name": "ngc-pull"}]
    assert c["env"][0]["valueFrom"]["secretKeyRef"] == {"name": "ngc-api-key", "key": "NGC_API_KEY"}
    for k in (ROOT / "lab/gpu").rglob("kustomization.yaml"):
        assert "gonogo" not in k.read_text(), "the go/no-go Job is applied by hand only"

def test_gpu_check_job_pinned_and_unprivileged():
    (job,) = [d for d in yaml.safe_load_all((ROOT / "lab/gpu/gonogo/gpu-check-job.yaml").read_text()) if d]
    s = job["spec"]["template"]["spec"]; c = s["containers"][0]
    assert c["image"] == NIM_IMAGE and c["command"][0] == "nvidia-smi"
    assert c["resources"]["limits"]["nvidia.com/gpu"] == 1 and "runtimeClassName" not in s
    assert s["securityContext"]["runAsNonRoot"] is True and c["securityContext"]["allowPrivilegeEscalation"] is False
