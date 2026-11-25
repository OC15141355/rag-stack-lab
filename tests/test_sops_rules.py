"""The .sops.yaml rule order is a security boundary: the first matching rule wins."""
import re
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
PHASE_A = "age14c2r6yt9qlvj2mdl7k4hdg2rfpcga8ehpt4dnahfx2l8dvkdm50syjrs65"
SESSION = "age1lsw2ne59z5y02s074k2kmrqfda5tc363hvacn24v0g60x6n0hyqs5sd89v"
RULES = yaml.safe_load((ROOT / ".sops.yaml").read_text())["creation_rules"]

def first_match(path):
    return next((r for r in RULES if re.search(r["path_regex"], path)), None)

def test_gpu_secrets_go_to_session_key_only():
    r = first_match("lab/gpu/secrets/gpu.sops.yaml")
    assert r is RULES[0], "GPU rule must be placed before the Phase A rule"
    assert r["age"] == SESSION and PHASE_A not in r["age"]
    assert r["encrypted_regex"] == "^(data|stringData)$"

def test_phase_a_secrets_unchanged():
    for env in ("dev", "qa", "prod"):
        r = first_match(f"lab/secrets/{env}.sops.yaml")
        assert r["age"] == PHASE_A and SESSION not in r["age"]
        assert r["path_regex"] == r"^lab/secrets/[a-z0-9-]+\.sops\.yaml$"

def test_no_rule_matches_outside_secret_dirs():
    for p in ["lab/gpu/nim/nimcache.yaml", "lab/gpu/secrets/kustomization.yaml",
              "lab/secrets/kustomization.yaml", "lab/gpu/secrets/sub/x.sops.yaml", "x/lab/secrets/a.sops.yaml"]:
        assert first_match(p) is None, p

def test_exactly_two_rules():
    assert len(RULES) == 2
