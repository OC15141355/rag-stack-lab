"""make_gpu_sops.py with a fake `age` binary: no real key is ever used in tests."""
import os, pty, subprocess, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_gpu_sops.py"
FAKE_KEY = "nvapi-" + "T" * 40          # built at runtime so gitleaks never sees a literal

def setup(tmp_path, key=FAKE_KEY, age_rc=0):
    d = tmp_path / "session"; d.mkdir()
    (d / "age-key.txt").write_text("identity-placeholder\n")
    (d / "session-nvapi-key.age").write_text("ciphertext-placeholder\n")
    fake = tmp_path / "fake-age"
    fake.write_text(f"#!/bin/sh\nprintf '%s\\n' '{key}'\nexit {age_rc}\n"); fake.chmod(0o755)
    return {**os.environ, "RAGLAB_GPU_DIR": str(d), "RAGLAB_AGE_BIN": str(fake)}

def run(env, *args, stdin=None, stdout=subprocess.PIPE):
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, input=stdin,
                          stdout=stdout, stderr=subprocess.PIPE, text=True)

def test_emit_builds_three_secrets(tmp_path):
    r = run(setup(tmp_path), "emit")
    assert r.returncode == 0, r.stderr
    docs = list(yaml.safe_load_all(r.stdout))
    assert [(d["metadata"]["namespace"], d["metadata"]["name"], d["type"]) for d in docs] == [
        ("raglab-gpu", "ngc-pull", "kubernetes.io/dockerconfigjson"),
        ("raglab-gpu", "ngc-api-key", "Opaque"),
        ("raglab-dev-gpu", "bifrost-env", "Opaque")]
    assert FAKE_KEY not in r.stderr

def test_emit_then_verify_passes(tmp_path):
    env = setup(tmp_path)
    out = run(env, "emit").stdout
    v = run(env, "verify", stdin=out)
    assert v.returncode == 0, v.stdout
    assert "FAIL" not in v.stdout and FAKE_KEY not in v.stdout + v.stderr
    assert "OK   key equals the session key on disk (decode probe)" in v.stdout

def test_two_emits_generate_fresh_bifrost_values(tmp_path):
    env = setup(tmp_path)
    a, b = (list(yaml.safe_load_all(run(env, "emit").stdout))[2]["stringData"] for _ in range(2))
    assert a["BIFROST_VK"] != b["BIFROST_VK"] and a["BIFROST_ENCRYPTION_KEY"] != b["BIFROST_ENCRYPTION_KEY"]

def test_verify_detects_tampering(tmp_path):
    env = setup(tmp_path)
    docs = list(yaml.safe_load_all(run(env, "emit").stdout))
    docs[2]["stringData"]["NVIDIA_API_KEY"] = "nvapi-" + "X" * 40
    v = run(env, "verify", stdin=yaml.safe_dump_all(docs))
    assert v.returncode == 1 and "FAIL bifrost NVIDIA_API_KEY equals NGC_API_KEY" in v.stdout
    assert "X" * 40 not in v.stdout

def test_verify_detects_wrong_source_key(tmp_path):
    out = run(setup(tmp_path), "emit").stdout
    o = tmp_path / "o"; o.mkdir()
    other = setup(o, key="nvapi-" + "Z" * 40)
    v = run(other, "verify", stdin=out)
    assert v.returncode == 1 and "FAIL key equals the session key on disk" in v.stdout

def test_verify_rejects_still_encrypted_input(tmp_path):
    env = setup(tmp_path)
    docs = list(yaml.safe_load_all(run(env, "emit").stdout))
    for d in docs: d["sops"] = {"version": "3.13.3"}
    v = run(env, "verify", "--no-source", stdin=yaml.safe_dump_all(docs))
    assert v.returncode == 1 and "FAIL no sops block" in v.stdout

def test_age_failure_is_reported_without_output(tmp_path):
    r = run(setup(tmp_path, age_rc=1), "emit")
    assert r.returncode == 2 and r.stdout == "" and FAKE_KEY not in r.stderr

def test_non_nvapi_key_rejected_without_echo(tmp_path):
    r = run(setup(tmp_path, key="sk-not-a-nvidia-key-1234567890"), "emit")
    assert r.returncode == 2 and r.stdout == "" and "sk-not-a-nvidia" not in r.stderr

def test_emit_refuses_a_terminal(tmp_path):
    master, slave = pty.openpty()
    try:
        r = subprocess.run([sys.executable, str(SCRIPT), "emit"], env=setup(tmp_path),
                           stdout=slave, stderr=subprocess.PIPE, text=True)
    finally:
        os.close(slave)
        os.close(master)
    assert r.returncode == 2 and "refusing to write secrets to a terminal" in r.stderr


def test_gpu_secrets_kustomization_lists_only_gpu_file():
    k = yaml.safe_load((ROOT / "lab/gpu/secrets/kustomization.yaml").read_text())
    assert k == {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": ["gpu.sops.yaml"]}
