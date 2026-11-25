"""scripts/key_probe.py against a local mock (hosted API + registry). No real endpoint is called."""
import base64, json, os, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "key_probe.py"
GOOD = "nvapi-" + "G" * 40
BAD = "nvapi-" + "B" * 40
DIGEST = "sha256:" + "ab" * 32

@pytest.fixture
def srv():
    state = {"rate_limited": False}
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def reply(self, code, obj=None, headers=()):
            data = json.dumps(obj).encode() if obj is not None else b""
            self.send_response(code)
            for k, v in headers: self.send_header(k, v)
            self.send_header("Content-Length", str(len(data))); self.end_headers()
            if self.command != "HEAD": self.wfile.write(data)
        def authed(self):
            return self.headers.get("Authorization") == f"Bearer {GOOD}"
        def route(self):
            p = self.path
            if state["rate_limited"]: return self.reply(429)
            if p == "/v1/models":
                return self.reply(200, {"data": [{"id": "meta/llama-3.1-8b-instruct"}]}) if self.authed() else self.reply(401)
            if p == "/v1/chat/completions":
                return self.reply(200, {"choices": []}) if self.authed() else self.reply(401)
            if p.startswith("/v2/nim/meta/x/manifests/"):
                if self.headers.get("Authorization") == "Bearer REGTOKEN":
                    return self.reply(200, headers=[("Docker-Content-Digest", DIGEST)])
                port = self.server.server_address[1]
                return self.reply(401, headers=[("WWW-Authenticate",
                    f'Bearer realm="http://127.0.0.1:{port}/token",scope="repository:nim/meta/x:pull"')])
            if p.startswith("/token"):
                want = "Basic " + base64.b64encode(f"$oauthtoken:{GOOD}".encode()).decode()
                return self.reply(200, {"token": "REGTOKEN"}) if self.headers.get("Authorization") == want else self.reply(401)
            return self.reply(404)
        do_GET = do_POST = do_HEAD = route
    s = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{s.server_address[1]}"
    yield {"env": {**os.environ, "KEY_PROBE_HOSTED": base, "KEY_PROBE_REGISTRY": base}, "state": state}
    s.shutdown()

def run(srv, key, *args):
    r = subprocess.run([sys.executable, str(SCRIPT), *args], input=key + "\n", env=srv["env"],
                       capture_output=True, text=True)
    assert key not in r.stdout + r.stderr
    return r

def test_hosted_accepted_with_chat(srv):
    r = run(srv, GOOD, "hosted", "--chat", "meta/llama-3.1-8b-instruct")
    assert r.returncode == 0 and "listed: True" in r.stdout and r.stdout.strip().endswith("ACCEPTED")

def test_hosted_rejected_is_exit_1(srv):
    r = run(srv, BAD, "hosted")
    assert r.returncode == 1 and "HTTP 401" in r.stdout and "REJECTED" in r.stdout

def test_rate_limit_is_inconclusive_not_rejected(srv):
    srv["state"]["rate_limited"] = True
    r = run(srv, BAD, "hosted")
    assert r.returncode == 2 and "INCONCLUSIVE" in r.stdout

def test_nvcr_accepted_prints_digest(srv):
    r = run(srv, GOOD, "nvcr", "--repo", "nim/meta/x", "--tag", "2.1.7")
    assert r.returncode == 0 and f"digest: {DIGEST}" in r.stdout

def test_nvcr_rejected(srv):
    r = run(srv, BAD, "nvcr", "--repo", "nim/meta/x", "--tag", "2.1.7")
    assert r.returncode == 1 and "registry token: HTTP 401" in r.stdout


def test_hosted_without_chat_is_inconclusive_even_when_models_ok(srv):
    r = run(srv, GOOD, "hosted")
    assert r.returncode == 2 and "INCONCLUSIVE" in r.stdout and "ACCEPTED" not in r.stdout

def test_non_json_body_is_inconclusive_not_rejected():
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            self.send_response(200); self.send_header("Content-Length", "6"); self.end_headers(); self.wfile.write(b"<html>")
        do_POST = do_GET
    s = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=s.serve_forever, daemon=True).start()
    env = {**os.environ, "KEY_PROBE_HOSTED": f"http://127.0.0.1:{s.server_address[1]}"}
    r = subprocess.run([sys.executable, str(SCRIPT), "hosted", "--chat", "m"], input=GOOD + "\n", env=env,
                       capture_output=True, text=True)
    s.shutdown()
    assert r.returncode == 2 and "crash" in r.stdout and GOOD not in r.stdout + r.stderr

def test_redirect_refused_and_no_auth_forwarded(srv):
    got = []
    class H2(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            got.append(self.headers.get("Authorization")); self.send_response(200)
            self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}")
    s2 = ThreadingHTTPServer(("127.0.0.1", 0), H2); threading.Thread(target=s2.serve_forever, daemon=True).start()
    target = f"http://127.0.0.1:{s2.server_address[1]}/v1/models"
    class H1(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            self.send_response(302); self.send_header("Location", target); self.send_header("Content-Length", "0"); self.end_headers()
    s1 = ThreadingHTTPServer(("127.0.0.1", 0), H1); threading.Thread(target=s1.serve_forever, daemon=True).start()
    env = {**os.environ, "KEY_PROBE_HOSTED": f"http://127.0.0.1:{s1.server_address[1]}"}
    r = subprocess.run([sys.executable, str(SCRIPT), "hosted", "--chat", "m"], input=GOOD + "\n", env=env,
                       capture_output=True, text=True)
    s1.shutdown(); s2.shutdown()
    assert r.returncode == 2 and "redirect" in r.stdout and got == []

def test_realm_must_be_https_nvcr():
    import importlib.util
    sp = importlib.util.spec_from_file_location("kp", SCRIPT); kp = importlib.util.module_from_spec(sp); sp.loader.exec_module(kp)
    assert kp.realm_ok("https://authn.nvidia.com/proxy_auth", False) is True
    assert kp.realm_ok("https://evil.example/token", False) is False
    assert kp.realm_ok("http://nvcr.io/proxy_auth", False) is False
    assert kp.realm_ok("https://evilnvcr.io/proxy_auth", False) is False
    assert kp.realm_ok("https://nvcr.io/proxy_auth", False) and kp.realm_ok("https://a.nvcr.io/x", False)
