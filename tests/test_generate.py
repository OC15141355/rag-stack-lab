import json, shutil, subprocess, sys
from pathlib import Path
import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "lab/catalogue/generate.py"
CAT = yaml.safe_load((ROOT / "lab/catalogue/catalogue.yaml").read_text())
SCHEMA = json.loads((ROOT / "lab/catalogue/bifrost-config.schema.json").read_text())
PROVIDER_SCHEMA = {"$ref": "#/$defs/provider", "$defs": SCHEMA["$defs"]}
ENVS = ("dev", "qa", "prod")

def gen(out, *args):
    return subprocess.run([sys.executable, str(GEN), "--out", str(out), *args],
                          capture_output=True, text=True, cwd=ROOT)

def gen_ok(out, *args):
    r = gen(out, *args)
    assert r.returncode == 0, r.stdout + r.stderr
    return r

@pytest.fixture
def out(tmp_path):
    gen_ok(tmp_path)
    return tmp_path

def cfg(out, env):
    return json.loads((out / env / "generated/config.json").read_text())

def test_generate_writes_all_envs(out):
    for env in ENVS:
        assert (out / env / "generated/config.json").exists()
        assert (out / env / "generated/models.json").exists()

def test_config_is_valid_against_bifrost_schema(out):
    for env in ENVS:
        jsonschema.validate(cfg(out, env), SCHEMA)

def test_providers_validate_against_provider_def(out):
    for env in ENVS:
        for name, prov in cfg(out, env)["providers"].items():
            jsonschema.validate(prov, PROVIDER_SCHEMA)

def test_broken_provider_block_fails_provider_validation(out):
    prov = dict(cfg(out, "dev")["providers"]["nvidia-hosted"]); prov["keys"] = "garbage"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(prov, PROVIDER_SCHEMA)

def test_security_settings(out):
    c = cfg(out, "prod")
    assert c["version"] == 2
    assert c["source_of_truth"] == "config.json"
    assert c["client"]["enforce_auth_on_inference"] is True
    assert c["client"]["disable_content_logging"] is True
    assert c["governance"]["auth_config"]["is_enabled"] is True
    assert c["encryption_key"] == "env.BIFROST_ENCRYPTION_KEY"

def test_no_literal_secrets_only_env_refs(out):
    c = cfg(out, "dev"); text = json.dumps(c)
    assert "nvapi-" not in text and "sk-bf-" not in text
    assert '"env.NVIDIA_API_KEY"' in text and '"env.BIFROST_VK"' in text
    names = {"value", "encryption_key", "admin_username", "admin_password", "password"}
    found = []
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in names:
                    found.append((k, v))
                walk(v)
        elif isinstance(o, list):
            for i in o: walk(i)
    for env in ENVS:
        walk(cfg(out, env))
    assert found
    for k, v in found:
        assert isinstance(v, str) and v.startswith("env."), (k, v)

def test_limits_are_per_env_and_probe_key_exists(out):
    g = cfg(out, "dev")["governance"]
    rl = {r["id"]: r for r in g["rate_limits"]}
    assert rl["rl-dev"]["request_max_limit"] == 30 and rl["rl-dev-probe"]["request_max_limit"] == 2
    assert rl["rl-dev"]["token_max_limit"] == 60000
    assert rl["rl-dev"]["request_reset_duration"] == "1m" and rl["rl-dev"]["token_reset_duration"] == "1m"
    assert rl["rl-dev-probe"]["request_reset_duration"] == "1m"
    vks = {v["id"]: v for v in g["virtual_keys"]}
    assert vks["vk-dev"]["value"] == "env.BIFROST_VK" and vks["vk-dev-probe"]["value"] == "env.BIFROST_VK_PROBE"
    assert vks["vk-dev"]["rate_limit_id"] == "rl-dev"
    assert vks["vk-dev-probe"]["rate_limit_id"] == "rl-dev-probe"

def test_vk_provider_configs_allow_all_keys(out):
    for env in ENVS:
        for vk in cfg(out, env)["governance"]["virtual_keys"]:
            assert vk["provider_configs"]
            for pc in vk["provider_configs"]:
                assert pc["key_ids"], (env, vk["id"])
                assert pc["allowed_models"] == ["chat/glm", "chat/nemotron"]

def test_log_retention_per_env(out):
    assert cfg(out, "prod")["client"]["log_retention_days"] == 7
    assert cfg(out, "dev")["client"]["log_retention_days"] == 3
    assert cfg(out, "qa")["client"]["log_retention_days"] == 3

def test_provider_network_and_allowed_requests(out):
    p = cfg(out, "dev")["providers"]["nvidia-hosted"]
    cp = p["custom_provider_config"]
    assert cp["base_provider_type"] == "openai"
    assert cp["allowed_requests"] == {"list_models": True, "chat_completion": True, "chat_completion_stream": True}
    up = CAT["upstream"]
    assert p["network_config"]["base_url"] == up["base_url"]
    assert p["network_config"]["default_request_timeout_in_seconds"] == up["timeout_seconds"]
    assert p["network_config"]["stream_idle_timeout_in_seconds"] == up["timeout_seconds"]

def test_aliases_map_to_upstream(out):
    key = cfg(out, "dev")["providers"]["nvidia-hosted"]["keys"][0]
    assert key["aliases"]["chat/glm"] == "z-ai/glm-5.3-flash"
    assert set(key["models"]) == {"chat/glm", "chat/nemotron"}

def test_models_json_content(out):
    for env in ENVS:
        m = json.loads((out / env / "generated/models.json").read_text())["models"]
        assert m == [
            {"id": "nvidia-hosted/chat/glm", "provider": "nvidia-hosted", "alias": "chat/glm",
             "upstream": "z-ai/glm-5.3-flash", "context_window": 131072, "max_output_tokens": 8192,
             "capabilities": ["chat", "stream", "tools"]},
            {"id": "nvidia-hosted/chat/nemotron", "provider": "nvidia-hosted", "alias": "chat/nemotron",
             "upstream": "nvidia/nemotron-3.5-lightning-30b-a3b", "context_window": 131072,
             "max_output_tokens": 8192, "capabilities": ["chat", "stream"]},
        ]

def test_check_mode_detects_drift(out):
    gen_ok(out, "--check")
    p = out / "qa/generated/config.json"; orig = p.read_text()
    p.write_text(orig.replace('"request_max_limit": 30', '"request_max_limit": 99'))
    r = gen(out, "--check")
    assert r.returncode == 1 and "DRIFT:" in r.stdout
    p.write_text(orig)
    gen_ok(out, "--check")

def test_committed_outputs_have_no_drift():
    gen_ok(ROOT / "lab/envs", "--check")
