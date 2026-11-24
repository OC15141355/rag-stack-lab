#!/usr/bin/env python3
"""Generate per-env Bifrost config.json + models.json from catalogue.yaml.

Secrets are never written: every credential is an `env.VAR` reference resolved by Bifrost at startup
from the bifrost-env Secret. Output is validated in CI against the vendored Bifrost schema.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
ENVS = ("dev", "qa", "prod")

def build_config(cat: dict, env: str) -> dict:
    up, models, lim = cat["upstream"], cat["models"], cat["environments"][env]
    prov = up["provider"]
    aliases = {m["alias"]: m["upstream"] for m in models}
    rl_id, vk_id = f"rl-{env}", f"vk-{env}"
    return {
        "version": 2,
        "source_of_truth": "config.json",
        "encryption_key": "env.BIFROST_ENCRYPTION_KEY",
        "client": {
            "enforce_auth_on_inference": True,
            "enable_logging": True,
            "disable_content_logging": True,
            "log_retention_days": lim["log_retention_days"],
        },
        "config_store": {"enabled": True, "type": "sqlite", "config": {"path": "/app/data/config.db"}},
        "logs_store": {"enabled": True, "type": "sqlite", "config": {"path": "/app/data/logs.db"}},
        "providers": {
            prov: {
                "keys": [{
                    "name": f"nvidia-{env}",
                    "value": "env.NVIDIA_API_KEY",
                    "weight": 1,
                    "models": sorted(aliases),
                    "aliases": aliases,
                }],
                "network_config": {
                    "base_url": up["base_url"],
                    "default_request_timeout_in_seconds": up["timeout_seconds"],
                    "stream_idle_timeout_in_seconds": up["timeout_seconds"],
                },
                "custom_provider_config": {
                    "base_provider_type": "openai",
                    "allowed_requests": {
                        "list_models": True, "chat_completion": True, "chat_completion_stream": True,
                    },
                },
                "store_raw_request_response": False,
            }
        },
        "governance": {
            "auth_config": {
                "is_enabled": True,
                "admin_username": "env.BIFROST_ADMIN_USER",
                "admin_password": "env.BIFROST_ADMIN_PASSWORD",
            },
            "rate_limits": [
                {"id": rl_id,
                 "request_max_limit": lim["requests_per_minute"], "request_reset_duration": "1m",
                 "token_max_limit": lim["tokens_per_minute"], "token_reset_duration": "1m"},
                {"id": f"{rl_id}-probe",
                 "request_max_limit": lim["probe_requests_per_minute"], "request_reset_duration": "1m"},
            ],
            "virtual_keys": [
                {"id": vk_id, "name": vk_id, "value": "env.BIFROST_VK", "is_active": True,
                 "rate_limit_id": rl_id,
                 "provider_configs": [{"provider": prov, "weight": 1, "allowed_models": sorted(aliases),
                                   "key_ids": ["*"]}]},
                {"id": f"{vk_id}-probe", "name": f"{vk_id}-probe", "value": "env.BIFROST_VK_PROBE",
                 "is_active": True, "rate_limit_id": f"{rl_id}-probe",
                 "provider_configs": [{"provider": prov, "weight": 1, "allowed_models": sorted(aliases),
                                   "key_ids": ["*"]}]},
            ],
        },
    }

def build_models(cat: dict) -> dict:
    prov = cat["upstream"]["provider"]
    # id = "<provider>/<alias>" routed request string; exact form is verified live in acceptance (Task 11).
    return {"models": [{"id": f"{prov}/{m['alias']}", "provider": prov, "alias": m["alias"], "upstream": m["upstream"],
                        "context_window": m["context_window"], "max_output_tokens": m["max_output_tokens"],
                        "capabilities": m["capabilities"]} for m in cat["models"]]}

def render(obj: dict) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path, default=LAB / "envs", help="root dir holding <env>/generated (default lab/envs)")
    a = ap.parse_args()
    cat = yaml.safe_load((HERE / "catalogue.yaml").read_text())
    drift = 0
    for env in ENVS:
        out = a.out / env / "generated"
        for name, obj in (("config.json", build_config(cat, env)), ("models.json", build_models(cat))):
            p, want = out / name, render(obj)
            if a.check:
                if not p.exists() or p.read_text() != want:
                    print(f"DRIFT: {p} differs from catalogue"); drift = 1
            else:
                out.mkdir(parents=True, exist_ok=True); p.write_text(want); print(f"wrote {p}")
    return drift

if __name__ == "__main__":
    sys.exit(main())
