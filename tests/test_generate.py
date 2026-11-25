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
    dev = CAT["environments"]["dev"]
    assert rl["rl-dev"]["request_max_limit"] == dev["requests_per_minute"]
    assert rl["rl-dev-probe"]["request_max_limit"] == dev["probe_requests_per_minute"] == 2
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
    up = CAT["providers"]["nvidia-hosted"]
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
    rpm = CAT["environments"]["qa"]["requests_per_minute"]
    mutated = orig.replace(f'"request_max_limit": {rpm}', '"request_max_limit": 99999')
    assert mutated != orig, "drift test must actually change the file"
    p.write_text(mutated)
    r = gen(out, "--check")
    assert r.returncode == 1 and "DRIFT:" in r.stdout
    p.write_text(orig)
    gen_ok(out, "--check")

def test_committed_outputs_have_no_drift():
    r = subprocess.run([sys.executable, str(GEN), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr

# ---- Phase B: dev-gpu env, nim-local provider, per-env serving ----
import hashlib

# sha256 of the committed Phase A outputs BEFORE the Phase B generator change. Must never change.
PHASE_A_SHA256 = {
    "dev/generated/config.json": "2c717f86ff378bbf4b97c21ae810d960b2ac879aa4e52b4b18df0850f1dc1eb0",
    "qa/generated/config.json": "7c3c2e5b3bc4a97a47211724430ca40c5f27b00784178f65b931e9c6a61b111c",
    "prod/generated/config.json": "bc02c6749fa3e199727c61393a00383813c1bf47281cd8d113d9451a5a3247a1",
    "dev/generated/models.json": "102b320a7943c2d5e89c637705a636b6a204e0bdce257ade86b18bd9706b2e1c",
    "qa/generated/models.json": "102b320a7943c2d5e89c637705a636b6a204e0bdce257ade86b18bd9706b2e1c",
    "prod/generated/models.json": "102b320a7943c2d5e89c637705a636b6a204e0bdce257ade86b18bd9706b2e1c",
}

def test_phase_a_outputs_byte_identical(out):
    for rel, want in PHASE_A_SHA256.items():
        assert hashlib.sha256((out / rel).read_bytes()).hexdigest() == want, rel
        assert hashlib.sha256((ROOT / "lab/envs" / rel).read_bytes()).hexdigest() == want, rel

def test_phase_a_envs_have_no_serving_and_no_gpu_models():
    for env in ENVS:
        assert "serving" not in CAT["environments"][env] and "dir" not in CAT["environments"][env]
    small = next(m for m in CAT["models"] if m["alias"] == "chat/small")
    assert small["envs"] == ["dev-gpu"]

def test_dev_gpu_written_under_lab_gpu():
    d = ROOT / "lab/gpu/envs/dev-gpu/generated"
    assert (d / "config.json").exists() and (d / "models.json").exists()
    assert not (ROOT / "lab/envs/dev-gpu").exists()

def write_cat(tmp_path, mutate):
    cat = yaml.safe_load((ROOT / "lab/catalogue/catalogue.yaml").read_text())
    mutate(cat)
    p = tmp_path / "cat.yaml"; p.write_text(yaml.safe_dump(cat)); return p

def test_dev_gpu_serving_is_hosted_or_nim_local():
    assert CAT["environments"]["dev-gpu"]["serving"] in ({"chat/small": "nvidia-hosted"}, {"chat/small": "nim-local"})

def test_dev_gpu_hosted_baseline(tmp_path):
    def hosted(c): c["environments"]["dev-gpu"]["serving"]["chat/small"] = "nvidia-hosted"
    o = tmp_path / "o"
    gen_ok(o, "--catalogue", str(write_cat(tmp_path, hosted)))
    c = cfg(o, "dev-gpu")
    jsonschema.validate(c, SCHEMA)
    assert set(c["providers"]) == {"nvidia-hosted"}
    key = c["providers"]["nvidia-hosted"]["keys"][0]
    assert key["name"] == "nvidia-dev-gpu" and key["value"] == "env.NVIDIA_API_KEY"
    small = next(m for m in CAT["models"] if m["alias"] == "chat/small")
    assert key["aliases"] == {"chat/small": small["upstream"]}
    for vk in c["governance"]["virtual_keys"]:
        assert vk["provider_configs"] == [{"provider": "nvidia-hosted", "weight": 1,
                                           "allowed_models": ["chat/small"], "key_ids": ["*"]}]
    m = json.loads((o / "dev-gpu/generated/models.json").read_text())["models"]
    assert [x["id"] for x in m] == ["nvidia-hosted/chat/small"]
    assert m[0]["capabilities"] == ["chat", "stream", "tools"]

def test_dev_gpu_cutover_to_nim_local(tmp_path):
    def cut(c): c["environments"]["dev-gpu"]["serving"]["chat/small"] = "nim-local"
    o = tmp_path / "o"
    gen_ok(o, "--catalogue", str(write_cat(tmp_path, cut)))
    c = cfg(o, "dev-gpu")
    jsonschema.validate(c, SCHEMA)
    assert set(c["providers"]) == {"nim-local"}, "only referenced providers are emitted"
    p = c["providers"]["nim-local"]
    assert p["network_config"]["base_url"] == "http://llama-8b.raglab-gpu.svc.cluster.local:8000"
    assert p["keys"][0]["value"] == "env.NIM_LOCAL_API_KEY" and p["keys"][0]["name"] == "nim-local-dev-gpu"
    for vk in c["governance"]["virtual_keys"]:
        assert vk["provider_configs"] == [{"provider": "nim-local", "weight": 1,
                                           "allowed_models": ["chat/small"], "key_ids": ["*"]}]
    m = json.loads((o / "dev-gpu/generated/models.json").read_text())["models"]
    assert [x["id"] for x in m] == ["nim-local/chat/small"]
    for rel, want in PHASE_A_SHA256.items():   # the cutover never touches Phase A envs
        assert hashlib.sha256((o / rel).read_bytes()).hexdigest() == want, rel

@pytest.mark.parametrize("mutate,msg", [
    (lambda c: c["environments"]["dev-gpu"]["serving"].update({"chat/small": "nope"}), "unknown provider"),
    (lambda c: c["environments"]["dev-gpu"]["serving"].update({"chat/missing": "nim-local"}), "unknown model"),
    (lambda c: c["environments"]["dev"].update({"serving": {"chat/small": "nim-local"}}), "restricted to"),
    (lambda c: c["environments"]["dev-gpu"].update({"serving": {}}), "serving is empty"),
])
def test_bad_serving_rejected(tmp_path, mutate, msg):
    r = gen(tmp_path / "o", "--catalogue", str(write_cat(tmp_path, mutate)))
    assert r.returncode == 2 and msg in r.stderr, r.stderr


@pytest.mark.parametrize("mutate", [
    lambda c: c.pop("default_provider"),
    lambda c: c.pop("providers"),
    lambda c: c["providers"]["nvidia-hosted"].pop("key_name"),
    lambda c: c["providers"]["nvidia-hosted"].pop("base_url"),
])
def test_missing_catalogue_keys_are_clean_errors(tmp_path, mutate):
    r = gen(tmp_path / "o", "--catalogue", str(write_cat(tmp_path, mutate)))
    assert r.returncode == 2 and "CATALOGUE ERROR" in r.stderr and "Traceback" not in r.stderr, r.stderr
