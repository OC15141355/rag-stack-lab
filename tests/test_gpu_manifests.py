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

# ---- Task 5: dev-gpu overlay, catalogue agreement, NetworkPolicy probes ----
def test_service_name_and_port_match_catalogue():
    (svc,) = by(build("lab/gpu/nim"), "NIMService")
    cat = yaml.safe_load((ROOT / "lab/catalogue/catalogue.yaml").read_text())
    u = urlparse(cat["providers"]["nim-local"]["base_url"])
    e = svc["spec"]["expose"]["service"]
    assert u.hostname == f'{e["name"]}.raglab-gpu.svc.cluster.local' and u.port == e["port"] == 8000

def test_dev_gpu_overlay():
    docs = build("lab/gpu/envs/dev-gpu")
    for d in docs:
        assert d["metadata"]["namespace"] == "raglab-dev-gpu", d["metadata"]["name"]
    assert not by(docs, "IngressRoute"), "no Traefik on the rented cluster"
    assert [d for d in by(docs, "ConfigMap") if d["metadata"]["name"].startswith("bifrost-config-")]
    base = by(build("lab/envs/dev"), "NetworkPolicy", "bifrost")[0]["spec"]
    assert by(docs, "NetworkPolicy", "bifrost")[0]["spec"] == base, "Phase A base policy reused unchanged"
    nim = by(docs, "NetworkPolicy", "bifrost-to-nim")[0]["spec"]
    assert nim == {"podSelector": {"matchLabels": {"app": "bifrost"}}, "policyTypes": ["Egress"],
                   "egress": [{"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "raglab-gpu"}},
                                       "podSelector": {"matchLabels": {"app.kubernetes.io/component": "nim-llm"}}}],
                               "ports": [{"port": 8000, "protocol": "TCP"}]}]}
    for d in by(docs, "Deployment") + by(docs, "Job"):
        s = d["spec"]["template"]["spec"]
        assert s["securityContext"]["runAsNonRoot"] is True and s["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"

def test_netpol_probes():
    docs = [d for d in yaml.safe_load_all((ROOT / "lab/gpu/probes/netpol-probes.yaml").read_text()) if d]
    pods = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Pod"}
    assert {(n, p["metadata"]["namespace"], p["metadata"]["labels"]["app"]) for n, p in pods.items()} == {
        ("probe-as-bifrost", "raglab-dev-gpu", "bifrost"), ("probe-unlabelled", "raglab-dev-gpu", "probe"),
        ("probe-other-ns", "default", "bifrost")}
    for p in pods.values():
        c = p["spec"]["containers"][0]
        assert "@sha256:" in c["image"] and p["spec"]["securityContext"]["runAsNonRoot"] is True
        assert c["securityContext"]["capabilities"]["drop"] == ["ALL"]
    cms = [d for d in docs if d["kind"] == "ConfigMap"]
    assert {d["metadata"]["namespace"] for d in cms} == {"raglab-dev-gpu", "default"}
    assert all("llama-8b.raglab-gpu.svc.cluster.local:8000/v1/health/ready" in d["data"]["probe.py"] for d in cms)


def _probe_script():
    docs = [d for d in yaml.safe_load_all((ROOT / "lab/gpu/probes/netpol-probes.yaml").read_text()) if d]
    return [d for d in docs if d["kind"] == "ConfigMap"][0]["data"]["probe.py"]

def _run_probe(url, tmp_path):
    import subprocess, sys
    src = _probe_script().replace("http://llama-8b.raglab-gpu.svc.cluster.local:8000/v1/health/ready", url)
    f = tmp_path / "probe.py"; f.write_text(src)
    return subprocess.run([sys.executable, str(f)], env={"PROBE": "p", "PATH": "/usr/bin"}, capture_output=True, text=True).stdout.strip()

def test_probe_reports_http_codes_and_blocks_only_on_network_failure(tmp_path):
    import threading, socket
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            code = 503 if self.path == "/503" else 200
            self.send_response(code); self.send_header("Content-Length", "0"); self.end_headers()
    s = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=s.serve_forever, daemon=True).start()
    port = s.server_address[1]
    assert _run_probe(f"http://127.0.0.1:{port}/ok", tmp_path) == "PROBE p status=200"
    assert _run_probe(f"http://127.0.0.1:{port}/503", tmp_path) == "PROBE p status=503"
    s.shutdown(); s.server_close()
    assert _run_probe(f"http://127.0.0.1:{port}/ok", tmp_path).startswith("PROBE p BLOCKED (ConnectionRefusedError")
    assert "ERROR" in _run_probe("http://no-such-host.invalid/", tmp_path)


def test_runbook_never_pairs_tee_with_exit_code_echo():
    text = (ROOT / "lab/gpu/README.md").read_text()
    for line in text.splitlines():
        assert not ("| tee" in line and "$?" in line), line   # `cmd | tee f; echo exit=$?` reports tee's status
    assert "key_probe.py hosted --chat meta/llama-3.1-8b-instruct; echo exit=$?" in text
    assert text.count("scripts/gpu-ansible.sh playbooks/") == 4 and "ansible-playbook -i" not in text
    assert "mkdir -p -m 700 \"$RG\" \"$RG/evidence\"" in text and "--core" in text and "password" in text
