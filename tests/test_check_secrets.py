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
  mac: ENC[AES256_GCM,data:mac,iv:i,tag:t,type:str]
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
    body = "apiVersion: v1\nkind: ConfigMap\ndata:\n  x: hunter2\nsops:\n  mac: ENC[AES256_GCM,data:m,iv:i,tag:t,type:str]\n  version: 3.13.3\n"
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
    assert r.returncode == 1 and "not ENC[" in r.stdout

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
    assert r.returncode == 1 and "age private key" in r.stdout

def test_pem_header_fails(tmp_path):
    r = run(tmp_path, w(tmp_path, "docs/x.txt", "-----BEGIN " + "RSA PRIVATE KEY-----\n"))
    assert r.returncode == 1 and "PEM private key" in r.stdout

def test_invalid_yaml_fails(tmp_path):
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", "a: [unclosed\n"))
    assert r.returncode == 1 and "unparseable YAML" in r.stdout

def test_non_utf8_under_secrets_fails(tmp_path):
    p = tmp_path / "lab/secrets/dev.sops.yaml"; p.parent.mkdir(parents=True)
    p.write_bytes(b"\xff\xfe\x00bad")
    r = run(tmp_path, "lab/secrets/dev.sops.yaml")
    assert r.returncode == 1 and "undecodable" in r.stdout

def test_non_utf8_elsewhere_still_scanned(tmp_path):
    p = tmp_path / "notes.bin"
    p.write_bytes(b"\xff" + ("AGE-SECRET-KE" + "Y-1" + "Q"*58).encode())
    r = run(tmp_path, "notes.bin")
    assert r.returncode == 1 and "age private key" in r.stdout

def test_multi_document_second_doc_plaintext_fails(tmp_path):
    body = ENC_OK + "---\n" + ENC_OK.replace("ENC[AES256_GCM,data:abc,iv:x,tag:y,type:str]", "hunter2")
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
    assert r.returncode == 1 and "not ENC[" in r.stdout

def test_plaintext_top_level_key_fails(tmp_path):
    body = ENC_OK.replace("stringData:", "password: hunter2\nstringData:")
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
    assert r.returncode == 1 and "not ENC[" in r.stdout

def test_plaintext_annotation_fails(tmp_path):
    body = ENC_OK.replace("metadata: {name: s}", "metadata: {name: s, annotations: {note: hunter2}}")
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
    assert r.returncode == 1 and "not ENC[" in r.stdout

def test_missing_sops_mac_fails(tmp_path):
    body = ENC_OK.replace("  mac: ENC[AES256_GCM,data:mac,iv:i,tag:t,type:str]\n", "")
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
    assert r.returncode == 1 and "sops.mac" in r.stdout

def test_path_normalisation(tmp_path):
    w(tmp_path, "lab/secrets/dev.yaml", ENC_OK)
    for rel in ("./lab/secrets/dev.yaml", "lab//secrets/dev.yaml", "lab/x/../secrets/dev.yaml"):
        r = run(tmp_path, rel)
        assert r.returncode == 1 and "must be *.sops.yaml" in r.stdout, rel

def test_git_failure_exits_2(tmp_path):
    r = run(tmp_path)  # not a git repo, no explicit paths
    assert r.returncode == 2

def test_missing_explicit_path_is_finding(tmp_path):
    r = run(tmp_path, "lab/secrets/nope.sops.yaml")
    assert r.returncode == 1 and "does not exist" in r.stdout

def test_empty_file_under_secrets_fails(tmp_path):
    for body in ("", "# just a comment\n"):
        r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
        assert r.returncode == 1 and "no YAML documents" in r.stdout

def test_sops_mac_must_be_enc(tmp_path):
    body = ENC_OK.replace("mac: ENC[AES256_GCM,data:mac,iv:i,tag:t,type:str]", "mac: plaintext")
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
    assert r.returncode == 1 and "sops.mac" in r.stdout

def test_unknown_sops_key_fails(tmp_path):
    body = ENC_OK.replace("  version: 3.13.3\n", "  version: 3.13.3\n  hunter2: leaked\n")
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
    assert r.returncode == 1 and "unknown key" in r.stdout


def test_secrets_kustomization_index_passes(tmp_path):
    body = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: [dev.sops.yaml]\n"
    assert run(tmp_path, w(tmp_path, "lab/secrets/kustomization.yaml", body)).returncode == 0

def test_secrets_kustomization_with_extra_key_fails(tmp_path):
    body = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: [dev.sops.yaml]\nsecretGenerator: [{name: x, literals: [a=b]}]\n"
    assert run(tmp_path, w(tmp_path, "lab/secrets/kustomization.yaml", body)).returncode != 0

def test_secrets_kustomization_non_sops_resource_fails(tmp_path):
    body = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: [plain.yaml]\n"
    assert run(tmp_path, w(tmp_path, "lab/secrets/kustomization.yaml", body)).returncode != 0

def test_other_non_sops_file_under_secrets_still_fails(tmp_path):
    body = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: [dev.sops.yaml]\n"
    assert run(tmp_path, w(tmp_path, "lab/secrets/other.yaml", body)).returncode != 0
