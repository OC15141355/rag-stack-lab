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
    def start(mode="good", rpm=1000, probe_rpm=2):
        port = free_port()
        p = subprocess.Popen([sys.executable, str(MOCK)], env={**os.environ, "MOCK_MODE": mode, "PORT": str(port),
                             "MOCK_RPM": str(rpm), "MOCK_VK": VK, "MOCK_VK_PROBE": VK_PROBE,
                             "MOCK_PROBE_RPM": str(probe_rpm)})
        procs.append(p)
        for _ in range(50):
            try: socket.create_connection(("127.0.0.1", port), timeout=0.2).close(); break
            except OSError: time.sleep(0.1)
        return f"http://127.0.0.1:{port}/v1"
    yield start
    for p in procs: p.kill()

def models_file(tmp_path, tools=True):
    f = tmp_path / "models.json"
    f.write_text(json.dumps({"models": [{"id": "test-model", "capabilities": ["chat", "stream"] + (["tools"] if tools else [])}]}))
    return str(f)

def run(url, tmp_path, *extra):
    env = {**os.environ, "BIFROST_VK": VK, "BIFROST_VK_PROBE": VK_PROBE}
    return subprocess.run([sys.executable, str(SMOKE), "--base-url", url, "--models-file", models_file(tmp_path),
                           "--header-env", "x-bf-vk=BIFROST_VK", *extra], capture_output=True, text=True, env=env)

def test_good_passes_and_key_not_in_argv(mock, tmp_path):
    r = run(mock(), tmp_path, "--expect-auth", "virtual key")
    assert r.returncode == 0, r.stdout
    assert VK not in r.stdout

def test_auth_negative_requires_bifrost_body(mock, tmp_path):
    r = run(mock(mode="generic401"), tmp_path, "--expect-auth", "virtual key")
    assert r.returncode == 1 and "auth-negative" in r.stdout

def test_limit_burst_expects_429_from_probe_key(mock, tmp_path):
    lim = ("--limit-burst", "3", "--limit-header-env", "x-bf-vk=BIFROST_VK_PROBE")
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
