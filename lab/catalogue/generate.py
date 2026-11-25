#!/usr/bin/env python3
"""Generate per-env Bifrost config.json + models.json from catalogue.yaml.

Secrets are never written: every credential is an `env.VAR` reference resolved by Bifrost at startup
from the bifrost-env Secret. Output is validated in CI against the vendored Bifrost schema.

Serving rule:
  - an env WITHOUT `serving` serves every model that has no `envs` restriction, all from
    `default_provider` (the Phase A shape; its output must stay byte-identical);
  - an env WITH `serving: {alias: provider}` serves exactly those aliases, each from the named provider.
config.json holds only the providers an env references; models.json ids are `<provider>/<alias>`.
Output dir: `<lab>/<env.dir or envs/<env>>/generated`, or `<--out>/<env>/generated` when --out is given.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
LAB = HERE.parent


class CatalogueError(ValueError):
    pass


def serving(cat: dict, env: str) -> dict[str, str]:
    """alias -> provider for one env (validated)."""
    e = cat["environments"][env]
    models = {m["alias"]: m for m in cat["models"]}
    if "serving" not in e:
        prov = cat["default_provider"]
        if prov not in cat["providers"]:
            raise CatalogueError(f"default_provider {prov!r} is not in providers")
        return {a: prov for a, m in models.items() if "envs" not in m}
    out = {}
    for alias, prov in e["serving"].items():
        if alias not in models:
            raise CatalogueError(f"{env}: serving references unknown model {alias!r}")
        if prov not in cat["providers"]:
            raise CatalogueError(f"{env}: serving references unknown provider {prov!r}")
        allowed = models[alias].get("envs")
        if allowed is not None and env not in allowed:
            raise CatalogueError(f"{env}: model {alias!r} is restricted to {allowed}")
        out[alias] = prov
    if not out:
        raise CatalogueError(f"{env}: serving is empty")
    return out


def by_provider(cat: dict, env: str) -> dict[str, dict[str, str]]:
    """provider -> {alias: upstream model name} for one env."""
    up = {m["alias"]: m["upstream"] for m in cat["models"]}
    out: dict[str, dict[str, str]] = {}
    for alias, prov in serving(cat, env).items():
        out.setdefault(prov, {})[alias] = up[alias]
    return out


def provider_block(cat: dict, env: str, prov: str, aliases: dict[str, str]) -> dict:
    p = cat["providers"][prov]
    return {
        "keys": [{
            "name": f"{p['key_name']}-{env}",
            "value": f"env.{p['key_env']}",
            "weight": 1,
            "models": sorted(aliases),
            "aliases": aliases,
        }],
        "network_config": {
            "base_url": p["base_url"],
            "default_request_timeout_in_seconds": p["timeout_seconds"],
            "stream_idle_timeout_in_seconds": p["timeout_seconds"],
        },
        "custom_provider_config": {
            "base_provider_type": "openai",
            "allowed_requests": {
                "list_models": True, "chat_completion": True, "chat_completion_stream": True,
            },
        },
        "store_raw_request_response": False,
    }


def build_config(cat: dict, env: str) -> dict:
    lim = cat["environments"][env]
    provs = by_provider(cat, env)
    rl_id, vk_id = f"rl-{env}", f"vk-{env}"

    def pcs():
        return [{"provider": p, "weight": 1, "allowed_models": sorted(provs[p]), "key_ids": ["*"]}
                for p in sorted(provs)]

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
        "providers": {p: provider_block(cat, env, p, provs[p]) for p in sorted(provs)},
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
                 "rate_limit_id": rl_id, "provider_configs": pcs()},
                {"id": f"{vk_id}-probe", "name": f"{vk_id}-probe", "value": "env.BIFROST_VK_PROBE",
                 "is_active": True, "rate_limit_id": f"{rl_id}-probe", "provider_configs": pcs()},
            ],
        },
    }


def build_models(cat: dict, env: str) -> dict:
    serv = serving(cat, env)
    # id = "<provider>/<alias>": the routed request string (verified live in Phase A).
    return {"models": [{"id": f"{serv[m['alias']]}/{m['alias']}", "provider": serv[m["alias"]],
                        "alias": m["alias"], "upstream": m["upstream"],
                        "context_window": m["context_window"], "max_output_tokens": m["max_output_tokens"],
                        "capabilities": m["capabilities"]}
                       for m in cat["models"] if m["alias"] in serv]}


def render(obj: dict) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def out_dir(cat: dict, env: str, root: Path | None) -> Path:
    if root is not None:
        return root / env / "generated"
    return LAB / cat["environments"][env].get("dir", f"envs/{env}") / "generated"


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path, default=None,
                    help="root dir holding <env>/generated (default: per-env dir under lab/)")
    ap.add_argument("--catalogue", type=Path, default=HERE / "catalogue.yaml")
    a = ap.parse_args()
    cat = yaml.safe_load(a.catalogue.read_text())
    drift = 0
    try:
        for env in cat["environments"]:
            out = out_dir(cat, env, a.out)
            for name, obj in (("config.json", build_config(cat, env)), ("models.json", build_models(cat, env))):
                p, want = out / name, render(obj)
                if a.check:
                    if not p.exists() or p.read_text() != want:
                        print(f"DRIFT: {p} differs from catalogue"); drift = 1
                else:
                    out.mkdir(parents=True, exist_ok=True); p.write_text(want); print(f"wrote {p}")
    except CatalogueError as e:
        print(f"CATALOGUE ERROR: {e}", file=sys.stderr)
        return 2
    except KeyError as e:
        print(f"CATALOGUE ERROR: missing required key {e}", file=sys.stderr)
        return 2
    return drift


if __name__ == "__main__":
    sys.exit(main())
