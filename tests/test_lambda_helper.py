"""scripts/lambda.py against a local mock of the Lambda Cloud API. No real API call is ever made."""
import json, os, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "lambda.py"
FAKE_KEY = "secret_" + "lambdakey" * 4          # built at runtime

TYPES = {
    "gpu_1x_a100_sxm4": {"instance_type": {"name": "gpu_1x_a100_sxm4", "description": "1x A100 (40 GB SXM4)",
                                           "price_cents_per_hour": 199,
                                           "specs": {"vcpus": 30, "memory_gib": 200, "storage_gib": 512, "gpus": 1}},
                         "regions_with_capacity_available": [{"name": "us-east-1"}]},
    "gpu_8x_h100_sxm5": {"instance_type": {"name": "gpu_8x_h100_sxm5", "price_cents_per_hour": 2392, "specs": {}},
                         "regions_with_capacity_available": [{"name": "us-east-1"}]},
}

def inst(i, name="raglab-gpu-session", status="active"):
    return {"id": i, "name": name, "status": status, "ip": "198.51.100.7", "jupyter_token": "JUPYTERTOKEN",
            "jupyter_url": "https://jupyter.example", "instance_type": {"name": "gpu_1x_a100_sxm4"},
            "region": {"name": "us-east-1"}}

class Mock:
    def __init__(self):
        self.instances, self.fss, self.calls, self.error = [], [], [], None

    def handle(self, h, method):
        n = int(h.headers.get("Content-Length") or 0)
        body = json.loads(h.rfile.read(n)) if n else None
        self.calls.append({"method": method, "path": h.path, "headers": dict(h.headers), "body": body})
        if self.error:
            return 400, {"error": {"code": "global/invalid-parameters", "message": "bad " + FAKE_KEY}}
        p = h.path.split("/api/v1/", 1)[-1]
        if method == "GET" and p == "instance-types": return 200, {"data": TYPES}
        if method == "GET" and p == "instances": return 200, {"data": self.instances}
        if method == "GET" and p.startswith("instances/"):
            return 200, {"data": next(i for i in self.instances if i["id"] == p.split("/")[1])}
        if method == "GET" and p == "file-systems": return 200, {"data": self.fss}
        if method == "POST" and p == "instance-operations/launch":
            self.instances.append(inst("i-new")); return 200, {"data": {"instance_ids": ["i-new"]}}
        if method == "POST" and p == "instance-operations/terminate":
            ids = body["instance_ids"]
            self.instances = [i for i in self.instances if i["id"] not in ids]
            return 200, {"data": {"terminated_instances": [{"id": i} for i in ids]}}
        return 404, {"error": {"code": "not-found", "message": p}}

@pytest.fixture
def api(tmp_path):
    m = Mock()
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _do(self, method):
            code, obj = m.handle(self, method)
            if code is None: return
            data = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        def do_GET(self): self._do("GET")
        def do_POST(self): self._do("POST")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = tmp_path / "session"; d.mkdir()
    (d / "age-key.txt").write_text("identity\n"); (d / "lambda-api-key.age").write_text("ct\n")
    (tmp_path / "bin").mkdir(); fake = tmp_path / "bin" / "age"; fake.write_text(f"#!/bin/sh\nprintf '%s\\n' '{FAKE_KEY}'\n"); fake.chmod(0o755)
    m.env = {**os.environ, "RAGLAB_GPU_DIR": str(d), "RAGLAB_AGE_BIN": str(fake), "LAMBDA_POLL_SECONDS": "0.05"}
    m.base = f"http://127.0.0.1:{srv.server_address[1]}/api/v1/"; m.srv = srv
    yield m
    srv.shutdown()

def run(m, *args, env=None):
    base = ["--test-base", m.base] if env is None or "BASE" not in env else ["--test-base", env["BASE"]]
    r = subprocess.run([sys.executable, str(SCRIPT), *base, *args], env=m.env, capture_output=True, text=True)
    assert FAKE_KEY not in r.stdout + r.stderr, "API key leaked to output"
    return r

def test_auth_and_user_agent(api):
    assert run(api, "types").returncode == 0
    h = api.calls[0]["headers"]
    assert h["Authorization"] == f"Bearer {FAKE_KEY}"
    assert "python" not in h["User-Agent"].lower() and h["User-Agent"].startswith("raglab-lambda-helper/")

def test_types_shows_a100_only_by_default(api):
    out = run(api, "types").stdout
    assert "gpu_1x_a100_sxm4  $1.99/h" in out and "capacity=us-east-1" in out and "h100" not in out
    assert "gpu_8x_h100_sxm5" in run(api, "types", "--all").stdout

def test_launch_posts_exact_body_and_waits(api):
    r = run(api, "launch", "--type", "gpu_1x_a100_sxm4", "--region", "us-east-1", "--wait")
    assert r.returncode == 0, r.stderr
    post = [c for c in api.calls if c["method"] == "POST"]
    assert len(post) == 1 and post[0]["body"] == {
        "region_name": "us-east-1", "instance_type_name": "gpu_1x_a100_sxm4",
        "ssh_key_names": ["raglab-gpu-session"], "file_system_names": [], "quantity": 1,
        "name": "raglab-gpu-session"}
    assert "LAUNCHED i-new" in r.stdout and "status=active" in r.stdout and "198.51.100.7" in r.stdout

def test_launch_refuses_other_types_without_calling_api(api):
    r = run(api, "launch", "--type", "gpu_8x_h100_sxm5", "--region", "us-east-1")
    assert r.returncode == 2 and not api.calls

def test_launch_refuses_when_an_instance_exists(api):
    api.instances.append(inst("i-old", name="something-else"))
    r = run(api, "launch", "--type", "gpu_1x_a100_sxm4", "--region", "us-east-1")
    assert r.returncode == 1 and "already has a live instance" in r.stderr
    assert not [c for c in api.calls if c["method"] == "POST"]

def test_launch_refuses_region_without_capacity(api):
    r = run(api, "launch", "--type", "gpu_1x_a100_sxm4", "--region", "us-west-2")
    assert r.returncode == 1 and "no capacity" in r.stderr
    assert not [c for c in api.calls if c["method"] == "POST"]

def test_status_never_prints_jupyter_fields(api):
    api.instances.append(inst("i-1"))
    out = run(api, "status").stdout
    assert "i-1" in out and "JUPYTERTOKEN" not in out and "jupyter" not in out

def test_terminate_requires_yes(api):
    api.instances.append(inst("i-1"))
    r = run(api, "terminate")
    assert r.returncode == 2 and not api.calls

def test_terminate_only_raglab_instances_and_waits(api):
    api.instances += [inst("i-1"), inst("i-2", name="not-ours")]
    r = run(api, "terminate", "--yes", "--wait")
    assert r.returncode == 0 and "TERMINATED" in r.stdout
    post = [c for c in api.calls if c["method"] == "POST"]
    assert post[0]["body"] == {"instance_ids": ["i-1"]}
    assert [i["id"] for i in api.instances] == ["i-2"]

def test_instances_exit_code_is_teardown_evidence(api):
    assert run(api, "instances").returncode == 0
    api.fss.append({"id": "fs-1", "name": "x", "region": {"name": "us-east-1"}})
    r = run(api, "instances")
    assert r.returncode == 1 and "file systems: 1" in r.stdout
    api.fss.clear(); api.instances.append(inst("i-1", status="booting"))
    assert run(api, "instances").returncode == 1

def test_api_error_is_reported_and_scrubbed(api):
    api.error = True
    r = run(api, "types")
    assert r.returncode == 3 and "global/invalid-parameters" in r.stderr and "***" in r.stderr

def test_plain_http_to_remote_refused(api):
    r = run(api, "types", env={"BASE": "http://example.com/api/v1/"})
    assert r.returncode == 2 and "must be https" in r.stderr


def test_env_base_override_is_ignored_and_age_bin_must_be_age(api, tmp_path):
    # the old env var no longer redirects the key anywhere; without --test-base the real https base is used,
    # so only check the local refusal paths here (no network)
    bad = tmp_path / "evil"; bad.write_text("#!/bin/sh\necho x\n"); bad.chmod(0o755)
    r = subprocess.run([sys.executable, str(SCRIPT), "--test-base", api.base, "types"],
                       env={**api.env, "RAGLAB_AGE_BIN": str(bad)}, capture_output=True, text=True)
    assert r.returncode == 2 and "executable named 'age'" in r.stderr and not api.calls

def test_redirects_are_refused_and_key_not_forwarded(api):
    got = []
    class H2(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            got.append(self.headers.get("Authorization")); self.send_response(200)
            self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}")
    s2 = ThreadingHTTPServer(("127.0.0.1", 0), H2); threading.Thread(target=s2.serve_forever, daemon=True).start()
    api.redirect_to = f"http://127.0.0.1:{s2.server_address[1]}/x"
    orig = api.handle
    def handle(h, method):
        if h.path.endswith("instance-types"):
            h.send_response(302); h.send_header("Location", api.redirect_to); h.send_header("Content-Length", "0")
            h.end_headers(); return None, None
        return orig(h, method)
    api.handle = handle
    r = run(api, "types")
    s2.shutdown()
    assert r.returncode == 3 and "redirect" in r.stderr and got == []

def test_terminate_nonzero_when_api_confirms_fewer(api):
    api.instances += [inst("i-1")]
    orig = api.handle
    def handle(h, method):
        if method == "POST":
            n = int(h.headers.get("Content-Length") or 0); h.rfile.read(n)
            return 200, {"data": {"terminated_instances": []}}
        return orig(h, method)
    api.handle = handle
    r = run(api, "terminate", "--yes")
    assert r.returncode == 1 and "check the console" in r.stderr

def test_unexpected_exception_is_exit_3(api):
    orig = api.handle
    api.handle = lambda h, m: (200, {"data": "not-a-dict"}) if h.path.endswith("instance-types") else orig(h, m)
    r = run(api, "types")
    assert r.returncode == 3 and "unexpected" in r.stderr
