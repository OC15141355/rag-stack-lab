import json, subprocess, sys
from pathlib import Path
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "lab/catalogue/generate.py"
SCHEMA = json.loads((ROOT / "lab/catalogue/bifrost-config.schema.json").read_text())

def gen(*args):
    return subprocess.run([sys.executable, str(GEN), *args], capture_output=True, text=True, cwd=ROOT)

def cfg(env):
    return json.loads((ROOT / f"lab/envs/{env}/generated/config.json").read_text())

def test_generate_writes_all_envs():
    r = gen(); assert r.returncode == 0, r.stderr
    for env in ("dev", "qa", "prod"):
        assert (ROOT / f"lab/envs/{env}/generated/config.json").exists()
        assert (ROOT / f"lab/envs/{env}/generated/models.json").exists()

def test_config_is_valid_against_bifrost_schema():
    gen()
    for env in ("dev", "qa", "prod"):
        jsonschema.validate(cfg(env), SCHEMA)

def test_security_settings():
    gen(); c = cfg("prod")
    assert c["source_of_truth"] == "config.json"
    assert c["client"]["enforce_auth_on_inference"] is True
    assert c["client"]["disable_content_logging"] is True
    assert c["governance"]["auth_config"]["is_enabled"] is True
    assert c["encryption_key"] == "env.BIFROST_ENCRYPTION_KEY"

def test_no_literal_secrets_only_env_refs():
    gen(); text = json.dumps(cfg("dev"))
    assert "nvapi-" not in text and "sk-bf-" not in text
    assert '"env.NVIDIA_API_KEY"' in text and '"env.BIFROST_VK"' in text

def test_limits_are_per_env_and_probe_key_exists():
    gen(); g = cfg("dev")["governance"]
    rl = {r["id"]: r for r in g["rate_limits"]}
    assert rl["rl-dev"]["request_max_limit"] == 30 and rl["rl-dev-probe"]["request_max_limit"] == 2
    vks = {v["id"]: v for v in g["virtual_keys"]}
    assert vks["vk-dev"]["value"] == "env.BIFROST_VK" and vks["vk-dev-probe"]["value"] == "env.BIFROST_VK_PROBE"
    assert vks["vk-dev-probe"]["rate_limit_id"] == "rl-dev-probe"

def test_aliases_map_to_upstream():
    gen(); key = cfg("dev")["providers"]["nvidia-hosted"]["keys"][0]
    assert key["aliases"]["chat/glm"] == "z-ai/glm-5.3-flash"
    assert set(key["models"]) == {"chat/glm", "chat/nemotron"}

def test_check_mode_detects_drift(tmp_path):
    gen()
    p = ROOT / "lab/envs/qa/generated/config.json"; orig = p.read_text()
    try:
        p.write_text(orig.replace('"request_max_limit": 30', '"request_max_limit": 99'))
        assert gen("--check").returncode == 1
    finally:
        p.write_text(orig)
    assert gen("--check").returncode == 0
