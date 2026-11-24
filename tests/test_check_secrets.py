import subprocess, sys, textwrap
from pathlib import Path

CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"

def run(root: Path, *paths: str):
    return subprocess.run([sys.executable, str(CHECK), "--root", str(root), *paths],
                          capture_output=True, text=True)

def w(root: Path, rel: str, body: str):
    p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(textwrap.dedent(body)); return rel

ENC_OK = """\
apiVersion: v1
kind: Secret
metadata: {name: s}
stringData:
  NVIDIA_API_KEY: ENC[AES256_GCM,data:abc,iv:x,tag:y,type:str]
sops:
  age: [{recipient: age1xyz}]
  version: 3.13.3
"""

def test_encrypted_secret_passes(tmp_path):
    assert run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", ENC_OK)).returncode == 0

def test_plaintext_value_under_secrets_fails(tmp_path):
    body = ENC_OK.replace("ENC[AES256_GCM,data:abc,iv:x,tag:y,type:str]", "hunter2")
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
    assert r.returncode == 1 and "not ENC[" in r.stdout

def test_missing_sops_block_fails(tmp_path):
    body = ENC_OK.split("sops:")[0]
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
    assert r.returncode == 1 and "no sops metadata" in r.stdout

def test_sops_block_but_nothing_encrypted_fails(tmp_path):
    # FC 9: sops writes a sops: block even when encrypted_regex matched nothing
    body = "apiVersion: v1\nkind: ConfigMap\ndata:\n  x: hunter2\nsops:\n  version: 3.13.3\n"
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
    assert r.returncode == 1

def test_wrong_filename_under_secrets_fails(tmp_path):
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.yaml", ENC_OK))
    assert r.returncode == 1 and "must be *.sops.yaml" in r.stdout

def test_generated_config_with_literal_key_fails(tmp_path):
    r = run(tmp_path, w(tmp_path, "lab/envs/dev/generated/config.json",
                        '{"providers": {"x": {"keys": [{"value": "nvapi-' + "A"*50 + '"}]}}}'))
    assert r.returncode == 1 and "literal secret" in r.stdout

def test_generated_config_with_env_ref_passes(tmp_path):
    r = run(tmp_path, w(tmp_path, "lab/envs/dev/generated/config.json",
                        '{"providers": {"x": {"keys": [{"value": "env.NVIDIA_API_KEY"}]}}}'))
    assert r.returncode == 0

def test_private_age_key_anywhere_fails(tmp_path):
    r = run(tmp_path, w(tmp_path, "lab/notes.txt", "AGE-SECRET-KE" + "Y-1" + "Q"*58 + "\n"))
    assert r.returncode == 1
