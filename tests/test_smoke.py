import json, os, socket, subprocess, sys, time
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SMOKE, MOCK = ROOT / "lab/smoke/smoke.py", ROOT / "lab/smoke/mock_llm.py"
# Fake keys are assembled at runtime so no literal matches the bifrost-virtual-key scanner rule.
VK, VK_PROBE = "sk-bf-" + "test", "sk-bf-" + "probe"

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

@pytest.fixture
def mock(tmp_path):
    procs = []
    def start(mode="good", rpm=1000, probe_rpm=2, log=None):
        port = free_port()
        p = subprocess.Popen([sys.executable, str(MOCK)], env={**os.environ, "MOCK_MODE": mode, "PORT": str(port),
                             "MOCK_RPM": str(rpm), "MOCK_VK": VK, "MOCK_VK_PROBE": VK_PROBE,
                             "MOCK_PROBE_RPM": str(probe_rpm),
                             **({"MOCK_LOG": str(log)} if log else {})})
        procs.append(p)
        for _ in range(50):
            try: socket.create_connection(("127.0.0.1", port), timeout=0.2).close(); break
            except OSError: time.sleep(0.1)
        return f"http://127.0.0.1:{port}/v1"
    yield start
    for p in procs: p.kill()

def models_file(tmp_path, tools=True, raw=None):
    f = tmp_path / "models.json"
    f.write_text(json.dumps(raw if raw is not None else
                 {"models": [{"id": "test-model", "capabilities": ["chat", "stream"] + (["tools"] if tools else [])}]}))
    return str(f)

def run(url, tmp_path, *extra, env_extra=None, tools=True, raw=None, revision="abc123"):
    env = {**os.environ, "BIFROST_VK": VK, "BIFROST_VK_PROBE": VK_PROBE, **(env_extra or {})}
    env.pop("SYNC_REVISION", None)
    if revision: env["SYNC_REVISION"] = revision
    return subprocess.run([sys.executable, str(SMOKE), "--base-url", url, "--models-file", models_file(tmp_path, tools, raw),
                           "--header-env", "x-bf-vk=BIFROST_VK", *extra], capture_output=True, text=True, env=env)

LIM = ("--limit-burst", "3", "--limit-header-env", "x-bf-vk=BIFROST_VK_PROBE", "--expect-limit", "rate limit")

def test_good_passes_and_key_not_in_argv(mock, tmp_path):
    r = run(mock(), tmp_path, "--expect-auth", "virtual key")
    assert r.returncode == 0, r.stdout
    assert VK not in r.stdout

def test_auth_negative_requires_bifrost_body(mock, tmp_path):
    r = run(mock(mode="generic401"), tmp_path, "--expect-auth", "virtual key")
    assert r.returncode == 1 and "auth-negative" in r.stdout

def test_limit_burst_expects_429_from_probe_key(mock, tmp_path):
    lim = LIM
    assert run(mock(probe_rpm=2), tmp_path, *lim).returncode == 0
    assert run(mock(probe_rpm=1000), tmp_path, *lim).returncode == 1

def test_skips_tools_when_capability_absent(mock, tmp_path):
    env = {**os.environ, "BIFROST_VK": VK}
    r = subprocess.run([sys.executable, str(SMOKE), "--base-url", mock(mode="notools"), "--models-file",
                        models_file(tmp_path, tools=False), "--header-env", "x-bf-vk=BIFROST_VK"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "[SKIP] tools" in r.stdout

def test_backoff_on_upstream_429(mock, tmp_path):
    assert run(mock(mode="flaky429"), tmp_path).returncode == 0

def test_id_preferred_over_alias(mock, tmp_path):
    f = tmp_path / "m.json"
    f.write_text(json.dumps({"models": [{"id": "test-model", "alias": "chat/x", "capabilities": ["chat"]}]}))
    env = {**os.environ, "BIFROST_VK": VK}
    r = subprocess.run([sys.executable, str(SMOKE), "--base-url", mock(), "--models-file", str(f),
                        "--header-env", "x-bf-vk=BIFROST_VK", "--json-report", str(tmp_path / "r.json")],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout
    assert "revision=" in r.stdout and "revision" in json.loads((tmp_path / "r.json").read_text())


def test_buffered_stream_fails(mock, tmp_path):
    r = run(mock(mode="buffered"), tmp_path)
    assert r.returncode == 1 and "[FAIL] stream" in r.stdout

def test_tools_failure_fails(mock, tmp_path):
    r = run(mock(mode="notools"), tmp_path)
    assert r.returncode == 1 and "[FAIL] tools" in r.stdout

def test_limit_fails_when_first_request_429(mock, tmp_path):
    r = run(mock(probe_rpm=0), tmp_path, *LIM)
    assert r.returncode == 1 and "[FAIL] limit-429" in r.stdout

def test_limit_fails_without_body_marker(mock, tmp_path):
    lim = [*LIM[:-1], "no-such-marker"]
    r = run(mock(probe_rpm=2), tmp_path, *lim)
    assert r.returncode == 1 and "[FAIL] limit-429" in r.stdout

def test_limit_records_retry_after_and_requires_expect_limit(mock, tmp_path):
    rep = tmp_path / "r.json"
    r = run(mock(probe_rpm=2), tmp_path, *LIM, "--json-report", str(rep))
    assert r.returncode == 0, r.stdout
    assert any(x["check"] == "limit-429" and "retry_after" in x for x in json.loads(rep.read_text())["results"])
    r = run(mock(), tmp_path, *LIM[:4])
    assert r.returncode == 2

def test_retry_after_honoured_and_flagged(mock, tmp_path):
    rep = tmp_path / "r.json"
    t = time.monotonic()
    r = run(mock(mode="flaky429"), tmp_path, "--json-report", str(rep))
    assert r.returncode == 0 and time.monotonic() - t >= 1.0
    assert "[PASS*]" in r.stdout and "retried" in r.stdout
    j = json.loads(rep.read_text())
    assert j["retried_calls"] >= 1 and j["retry_sleep"] >= 1

def test_max_retried_calls_fails_run(mock, tmp_path):
    r = run(mock(mode="flaky429"), tmp_path, "--max-retried-calls", "0")
    assert r.returncode == 1 and "retry-budget" in r.stdout

def test_retry_after_parsing():
    import importlib.util
    spec = importlib.util.spec_from_file_location("smoke_mod", SMOKE)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    f = m.parse_retry_after
    assert f("1") == 1 and f("999") == 30 and f("-5") == 2 and f("abc") == 2 and f("nan") == 2 and f(None) == 2 and f("inf") == 2

def test_negative_requests_carry_no_credentials(mock, tmp_path):
    log = tmp_path / "log.jsonl"
    r = run(mock(log=log, probe_rpm=2), tmp_path, "--expect-auth", "virtual key", *LIM, env_extra={"LLM_API_KEY": "bearer-secret"})
    assert r.returncode == 0, r.stdout
    reqs = [json.loads(l) for l in log.read_text().splitlines()]
    unauth = [q for q in reqs if "x-bf-vk" not in q]
    probe = [q for q in reqs if q.get("x-bf-vk") == VK_PROBE]
    assert unauth and all("authorization" not in q for q in unauth)
    assert len(probe) == 3 and all("authorization" not in q for q in probe)
    assert any(q.get("authorization") for q in reqs if q.get("x-bf-vk") == VK)

def test_expect_auth_empty_rejected(mock, tmp_path):
    assert run(mock(), tmp_path, "--expect-auth", "").returncode == 2

def test_require_negative_checks(mock, tmp_path):
    u = mock()
    r = run(u, tmp_path, "--require-negative-checks")
    assert r.returncode == 1 and "[FAIL] auth-negative" in r.stdout and "[FAIL] limit-429" in r.stdout
    r = run(u, tmp_path)
    assert r.returncode == 0 and "[SKIP] auth-negative" in r.stdout and "[SKIP] limit-429" in r.stdout

def test_models_validation(mock, tmp_path):
    u = mock()
    assert run(u, tmp_path, raw={"models": []}).returncode == 2
    assert run(u, tmp_path, raw={"models": [{"capabilities": []}]}).returncode == 2
    assert run(u, tmp_path, raw={"models": [{"id": "test-model"}]}).returncode == 2
    assert run(u, tmp_path, raw={"nope": 1}).returncode == 2

def test_summary_counts_skips_separately(mock, tmp_path):
    r = run(mock(), tmp_path, "--expect-auth", "virtual key", tools=False)
    assert r.returncode == 0 and "4 passed, 2 skipped, 0 failed" in r.stdout

def test_zero_passed_fails(mock, tmp_path):
    r = run(mock(), tmp_path, "--skip", "models", "--skip", "chat", "--skip", "stream", "--skip", "tools")
    assert r.returncode == 1

def test_revision_warning_and_require(mock, tmp_path):
    u = mock()
    r = run(u, tmp_path, revision=None)
    assert r.returncode == 0 and "SYNC_REVISION" in r.stderr
    r = run(u, tmp_path, "--require-revision", revision=None)
    assert r.returncode == 1 and "[FAIL] revision" in r.stdout
    assert run(u, tmp_path, "--require-revision").returncode == 0

def test_header_flag_warns(mock, tmp_path):
    r = run(mock(), tmp_path, "--header", "X-Foo: bar")
    assert "process list" in r.stderr and "--header-env" in r.stderr
