#!/usr/bin/env python3
"""Generate gateway config and a consumer catalogue from catalogue.yaml.

Run:   uv run --with pyyaml python examples/model-catalogue/generate.py --env dev
CI:    ... generate.py --env all --check     (non-zero exit on drift)

Needs PyYAML for catalogue.yaml. If PyYAML is missing, a catalogue.json with the
same content is accepted instead. Stdlib otherwise. Python 3.11+.
Output is deterministic (sorted keys, no timestamps) so --check is meaningful.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENVS = ("dev", "qa", "prod")
STATUSES = {"active", "deprecated", "retired"}
CAPS = {"chat", "streaming", "tools", "reasoning", "vision", "embeddings", "json_mode"}
LIMIT_KEYS = {"requests_per_minute", "tokens_per_minute", "budget_usd_per_month"}
MODEL_REQUIRED = ["id", "display_name", "description", "family", "owner", "status",
                  "nim", "context_window", "max_output_tokens", "capabilities", "environments"]
ENV_REQUIRED = ["enabled", "nim_tag", "nim_profile", "endpoint"]


def load_catalogue(path: Path | None) -> dict:
    yml, jsn = HERE / "catalogue.yaml", HERE / "catalogue.json"
    if path is None:
        path = yml if yml.exists() else jsn
    if path.suffix == ".json":
        return json.loads(path.read_text())
    try:
        import yaml  # type: ignore
    except ImportError:
        if jsn.exists():
            print("PyYAML not found; falling back to catalogue.json", file=sys.stderr)
            return json.loads(jsn.read_text())
        sys.exit("error: PyYAML is required to read catalogue.yaml.\n"
                 "  run with: uv run --with pyyaml python examples/model-catalogue/generate.py ...\n"
                 "  or provide catalogue.json with the same content.")
    return yaml.safe_load(path.read_text())


def validate(cat: dict) -> list[str]:
    errs: list[str] = []

    def limits_ok(where: str, lim: object) -> None:
        if lim is None:
            return
        if not isinstance(lim, dict):
            errs.append(f"{where}: limits must be a mapping")
            return
        for k, v in lim.items():
            if k not in LIMIT_KEYS:
                errs.append(f"{where}: unknown limit '{k}'")
            elif isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                errs.append(f"{where}.{k}: must be a non-negative number")

    if cat.get("schema_version") != 1:
        errs.append("schema_version must be 1")
    limits_ok("defaults.limits", (cat.get("defaults") or {}).get("limits"))
    models = cat.get("models")
    if not isinstance(models, list) or not models:
        return errs + ["models must be a non-empty list"]
    seen: set[str] = set()
    for i, m in enumerate(models):
        mid = m.get("id", f"#{i}") if isinstance(m, dict) else f"#{i}"
        w = f"model {mid}"
        if not isinstance(m, dict):
            errs.append(f"{w}: must be a mapping")
            continue
        for f in MODEL_REQUIRED:
            if m.get(f) in (None, "", [], {}):
                errs.append(f"{w}: missing required field '{f}'")
        if mid in seen:
            errs.append(f"{w}: duplicate id")
        seen.add(mid)
        if m.get("status") not in STATUSES:
            errs.append(f"{w}: status must be one of {sorted(STATUSES)}")
        for f in ("context_window", "max_output_tokens"):
            if not isinstance(m.get(f), int) or isinstance(m.get(f), bool) or m[f] < 1:
                errs.append(f"{w}: {f} must be a positive integer")
        if (isinstance(m.get("context_window"), int) and isinstance(m.get("max_output_tokens"), int)
                and m["max_output_tokens"] > m["context_window"]):
            errs.append(f"{w}: max_output_tokens exceeds context_window")
        bad = set(m.get("capabilities") or []) - CAPS
        if bad:
            errs.append(f"{w}: unknown capabilities {sorted(bad)}")
        nim = m.get("nim") or {}
        for f in ("image", "model_name"):
            if not nim.get(f):
                errs.append(f"{w}: nim.{f} is required")
        limits_ok(f"{w}.limits", m.get("limits"))
        envs = m.get("environments") or {}
        for e in ENVS:
            if e not in envs:
                errs.append(f"{w}: environments.{e} missing")
                continue
            ev = envs[e]
            for f in ENV_REQUIRED:
                if ev.get(f) in (None, ""):
                    errs.append(f"{w}.{e}: missing '{f}'")
            if str(ev.get("nim_tag", "")).lower() == "latest":
                errs.append(f"{w}.{e}: nim_tag must be pinned, not 'latest'")
            if ev.get("endpoint") and not str(ev["endpoint"]).startswith(("http://", "https://")):
                errs.append(f"{w}.{e}: endpoint must be http(s)")
            limits_ok(f"{w}.{e}.limits", ev.get("limits"))
        for e in envs:
            if e not in ENVS:
                errs.append(f"{w}: unknown environment '{e}'")
    return errs


def effective_limits(cat: dict, m: dict, env: str) -> dict:
    """defaults < model.limits < model.environments[env].limits"""
    out: dict = {}
    for layer in ((cat.get("defaults") or {}).get("limits"), m.get("limits"),
                  m["environments"][env].get("limits")):
        out.update(layer or {})
    return dict(sorted(out.items()))


def served(cat: dict, env: str):
    """Models that are routed in this env (enabled and not retired)."""
    for m in cat["models"]:
        if m["status"] != "retired" and m["environments"][env]["enabled"]:
            yield m


def provider_name(m: dict) -> str:
    return f"nim-{m['id']}"


def gen_bifrost(cat: dict, env: str) -> dict:
    providers, vk_provider_configs, rate_limits = {}, [], []
    for m in served(cat, env):
        ev, lim, pn = m["environments"][env], effective_limits(cat, m, env), provider_name(m)
        providers[pn] = {
            "keys": [{"name": f"{pn}-key", "value": "env.NIM_DUMMY_KEY",
                      "models": [m["nim"]["model_name"]], "weight": 1.0}],
            "network_config": {"base_url": ev["endpoint"],
                               "default_request_timeout_in_seconds": 600,
                               "stream_idle_timeout_in_seconds": 300, "max_retries": 1},
            "custom_provider_config": {
                "base_provider_type": "openai",
                "allowed_requests": {"chat_completion": True, "chat_completion_stream": True}},
        }
        rl_id = f"rl-{env}-{m['id']}"
        rate_limits.append({"id": rl_id,
                            "token_max_limit": lim.get("tokens_per_minute"),
                            "token_reset_duration": "1m",
                            "request_max_limit": lim.get("requests_per_minute"),
                            "request_reset_duration": "1m"})
        vk_provider_configs.append({"provider": pn, "weight": 1.0,
                                    "allowed_models": [m["nim"]["model_name"]],
                                    "key_ids": ["*"],
                                    # UNVERIFIED: per-provider-config rate_limit_id in config.json
                                    "rate_limit_id": rl_id})
    # Budgets per model live in the catalogue; Bifrost budgets attach to a virtual key,
    # provider config or model config. Emit them as a sidecar list for review.
    budgets = [{"id": f"budget-{env}-{m['id']}", "max_limit": effective_limits(cat, m, env).get("budget_usd_per_month"),
                "reset_duration": "1M", "provider": provider_name(m)}
               for m in served(cat, env)]
    return {
        "_generated": "DO NOT EDIT. Source: examples/model-catalogue/catalogue.yaml",
        "_environment": env,
        "providers": providers,
        "governance": {
            "rate_limits": rate_limits,
            "virtual_keys_template": [{"name": f"default-{env}", "is_active": True,
                                       "provider_configs": vk_provider_configs}],
            "budgets_by_provider": budgets,
        },
    }


def gen_models(cat: dict, env: str) -> dict:
    items = []
    for m in served(cat, env):
        ev = m["environments"][env]
        items.append({
            "id": m["id"],
            "gateway_model": f"{provider_name(m)}/{m['nim']['model_name']}",
            "display_name": m["display_name"], "description": m["description"],
            "family": m["family"], "status": m["status"], "owner": m["owner"],
            "context_window": m["context_window"], "max_output_tokens": m["max_output_tokens"],
            "capabilities": sorted(m["capabilities"]),
            "limits": effective_limits(cat, m, env),
            "deployment": {"image": f"{m['nim']['image']}:{ev['nim_tag']}",
                           "nim_tag": ev["nim_tag"], "nim_profile": ev["nim_profile"]},
        })
    return {"environment": env, "schema_version": 1, "models": sorted(items, key=lambda x: x["id"])}


def render(obj: dict) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env", default="all", choices=[*ENVS, "all"])
    ap.add_argument("--catalogue", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=HERE / "out")
    ap.add_argument("--check", action="store_true", help="fail if committed output differs")
    ap.add_argument("--print", dest="show", action="store_true", help="print generated files")
    a = ap.parse_args()

    cat = load_catalogue(a.catalogue)
    errs = validate(cat)
    if errs:
        print("catalogue invalid:", *errs, sep="\n  - ", file=sys.stderr)
        return 2

    drift = 0
    for env in (ENVS if a.env == "all" else (a.env,)):
        files = {"bifrost-providers.json": render(gen_bifrost(cat, env)),
                 "models.json": render(gen_models(cat, env))}
        for name, text in files.items():
            p = a.out / env / name
            if a.check:
                if not p.exists() or p.read_text() != text:
                    print(f"DRIFT: {p} differs from catalogue", file=sys.stderr)
                    drift += 1
                else:
                    print(f"ok: {p}")
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
                print(f"wrote {p}")
                if a.show:
                    print(text)
    if drift:
        print("run generate.py and commit the result", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
