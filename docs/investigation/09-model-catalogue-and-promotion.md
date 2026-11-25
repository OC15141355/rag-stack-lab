# 09. Model catalogue and DEV → QA → PROD promotion

> **Superseded (2026-11-26)** by [`reference/platform-gitops/`](../../reference/platform-gitops/) and the design [`2026-11-26-platform-gitops-lifecycle-design.md`](../superpowers/specs/2026-11-26-platform-gitops-lifecycle-design.md). Kept for background: the reference adds per-environment blocks, an evidence rule and rendered output.

Design plus runnable examples for the two items [05 §3](05-gap-analysis.md) re-scopes: "model metadata" and "promotion". NVIDIA ships neither (no metadata API on the NIM Operator, no promotion workflow), so both become ordinary git and CI work.

Example files: [`catalogue.yaml`](../../examples/model-catalogue/catalogue.yaml), [`schema.json`](../../examples/model-catalogue/schema.json), [`generate.py`](../../examples/model-catalogue/generate.py), [`promotion.gitlab-ci.yml`](../../examples/gitlab-ci/promotion.gitlab-ci.yml). Gateway background: [06](../prereading/06-bifrost-llm-gateway.md), [22](../prereading/22-bifrost-deployment.md).

## The plain version

Keep one file in git that describes every model: its name, what it can do, which NIM image and tag runs it, how much context it holds, and how fast people may call it. A small script reads that file and writes the gateway's configuration and a JSON list for any UI that wants to show the models. Nobody edits the generated files by hand, and CI complains if they drift.

To move a model from DEV to QA to PROD, you do not click anything in a model store. You open a merge request that changes the pinned version for that one environment. Reviewers approve it, a smoke test runs against the target, and PROD is only reachable after the QA smoke test passed. The merge request history and GitLab's deployment log are the record of who changed what and when.

## 1. Catalogue design

**Why git.** There is no NVIDIA component that stores model metadata for a gateway to read. Entity Store holds pointers and records, not descriptions, limits or capabilities ([04](04-nemo-entity-and-data-store.md)). A file in git gives review, history, rollback and a diff for every change, with no new service to run or secure.

**Why generated config.** The same facts (a context window, a rate limit) are needed in the gateway, the UI and the NIM spec. Writing them three times guarantees drift. One source plus a generator means a change is made once, reviewed once, and the derived files are checked in CI (`--check`).

**Where each limit is enforced.** Do not blur these:

| Limit | Enforced by | Source of truth |
|---|---|---|
| Context window / max sequence length | The NIM engine (`max_model_len`-style setting in the NIM spec); requests over it fail there | `context_window` in the catalogue; apply it to the `NIMService` env/profile (UNVERIFIED: exact env var per NIM; confirm in the NIM docs) |
| Max output tokens | Request parameter bound by the engine; the gateway does not clamp it | `max_output_tokens`, published in `models.json` so clients set sane values |
| Requests per minute, tokens per minute | The gateway (virtual-key rate limits) | `limits.*` in the catalogue |
| Spend / budget per period | The gateway (budgets) | `limits.budget_usd_per_month` |
| Who may call which model | The gateway (virtual-key `provider_configs` / `allowed_models`) | derived from `enabled` and `status` |

**Limit inheritance.** `defaults.limits` < model `limits` < per-env `limits`. Merged values are emitted per environment, so DEV can be looser than PROD without separate files.

**Promotion state lives in the same file.** Each model has `environments.dev|qa|prod` blocks with `nim_tag`, `nim_profile`, `endpoint` and `enabled`. Promoting means copying the DEV tag and profile into the QA block (then QA into PROD) in a merge request. Tags must be pinned; `latest` is rejected by both the schema and the script.

**Lifecycle.** `status: active | deprecated | retired`. Registering a model is adding an entry. Updating is editing it. Removing is `status: retired` (kept for history, dropped from all generated output) and later deleting the entry. Per environment, `enabled: false` withdraws it from one environment only.

## 2. Walkthrough of the files

- **`catalogue.yaml`**: two models (a GLM 5.2-class model and Nemotron 3 Super). Names, sizes and tags are placeholders marked `PLACEHOLDER`; fill them from the vendor model cards and NIM support matrix.
- **`schema.json`**: JSON Schema (draft 2020-12) of the file. Use it in an editor or a CI step with a schema validator if one is available. The script does not depend on it.
- **`generate.py`**: Python 3.11+, stdlib plus PyYAML (`uv run --with pyyaml ...`). If PyYAML is missing it falls back to a `catalogue.json` of the same content, else prints a clear error. It validates required fields, enum values, `max_output_tokens <= context_window`, no `latest`, then writes per environment:
  - `out/<env>/bifrost-providers.json`: a Bifrost config fragment. One custom provider per model (`nim-<id>`, `base_provider_type: openai`, `base_url` from the env endpoint, key `models` restricted to that model), a `governance.rate_limits` list, and a virtual-key template whose `provider_configs[].allowed_models` allow only enabled models.
  - `out/<env>/models.json`: the consumer catalogue (id, `gateway_model` as clients must send it, display name, description, family, status, owner, context window, max output, capabilities, effective limits, pinned image/tag/profile). Serve it statically or load it in an inference service.
  - `--check`: regenerate in memory and compare with the committed files; exit 1 on drift, 2 on an invalid catalogue.
- **`promotion.gitlab-ci.yml`**: the pipeline (section 3).

Run and output (real run, `--env dev`, trimmed with `...`):

```
$ uv run --with pyyaml python examples/model-catalogue/generate.py --env dev --print
wrote .../examples/model-catalogue/out/dev/bifrost-providers.json
{
  "_environment": "dev",
  "_generated": "DO NOT EDIT. Source: examples/model-catalogue/catalogue.yaml",
  "governance": {
    "budgets_by_provider": [ { "id": "budget-dev-glm-5-2", "max_limit": 200, "provider": "nim-glm-5-2", "reset_duration": "1M" }, ... ],
    "rate_limits": [
      { "id": "rl-dev-glm-5-2", "request_max_limit": 120, "request_reset_duration": "1m",
        "token_max_limit": 60000, "token_reset_duration": "1m" }, ... ],
    "virtual_keys_template": [ { "is_active": true, "name": "default-dev", "provider_configs": [
        { "allowed_models": ["glm-5.2"], "key_ids": ["*"], "provider": "nim-glm-5-2",
          "rate_limit_id": "rl-dev-glm-5-2", "weight": 1.0 }, ... ] } ]
  },
  "providers": {
    "nim-glm-5-2": {
      "custom_provider_config": { "allowed_requests": { "chat_completion": true, "chat_completion_stream": true },
                                  "base_provider_type": "openai" },
      "keys": [ { "models": ["glm-5.2"], "name": "nim-glm-5-2-key", "value": "env.NIM_DUMMY_KEY", "weight": 1.0 } ],
      "network_config": { "base_url": "http://nim-glm-5-2.nim-dev.svc:8000/v1",
                          "default_request_timeout_in_seconds": 600, "max_retries": 1,
                          "stream_idle_timeout_in_seconds": 300 } },
    ...
wrote .../out/dev/models.json
{ "environment": "dev", "models": [ { "capabilities": ["chat","reasoning","streaming","tools"],
  "context_window": 131072, "deployment": { "image": "registry.example.internal/nim/glm-5-2:1.0.0-rc2",
  "nim_profile": "vllm-fp8-tp8-PLACEHOLDER", "nim_tag": "1.0.0-rc2" }, "gateway_model": "nim-glm-5-2/glm-5.2",
  "limits": { "budget_usd_per_month": 200, "requests_per_minute": 120, "tokens_per_minute": 60000 }, ... } ] }
```

Drift and validation checks also exercised:

```
$ generate.py --check                      -> ok: ... (6 files), exit 0
$ (hand-edit out/prod/bifrost-providers.json) generate.py --check
DRIFT: .../out/prod/bifrost-providers.json differs from catalogue   -> exit 1
$ (set nim_tag: latest) generate.py --env dev
catalogue invalid:
  - model nemotron-3-super.qa: nim_tag must be pinned, not 'latest'   -> exit 2
```

## 3. Promotion flow

```
 MR #1: edit dev pin ──► validate ──► generate-check ──► deploy-dev ──► smoke-dev
                                                                          │ green
 MR #2: copy dev pin → qa (approvers review the diff) ◄───────────────────┘
        merge ──► promote-qa (manual, protected env "qa") ──► smoke-qa
                                                                  │ green
 MR #3: copy qa pin → prod (approvers review the diff) ◄──────────┘
        merge ──► promote-prod (manual, protected env "prod", needs smoke-qa)
```

Two layouts are shown in the CI file's comments:

- **Environment branches** (`dev`, `qa`, `prod`; rules on `$CI_COMMIT_BRANCH`): promotion is an MR between branches. Simple to explain, but branches can diverge, and `needs:` cannot span pipelines, so the QA→PROD gate is the MR rule "pipelines must succeed" plus approvals.
- **Directory per env on `main`** (`envs/<env>/…`, CODEOWNERS per directory, `rules:changes`): one history, no branch drift, and the whole chain is one pipeline so `needs: [smoke-qa]` gates PROD directly. Preferred when the delivery tool (Argo CD, Ansible) can read a path. (The sample catalogue keeps all envs in one file; to use this layout, split pins into per-env files or use CODEOWNERS sections plus `rules:changes`. UNVERIFIED: CODEOWNERS cannot restrict by YAML key, only by file.)

Approvals use GitLab merge request approval rules and protected environments (allowed deployers, required approvals on `prod`). The smoke job calls `python examples/smoke/smoke.py --base-url $NIM_OR_GATEWAY_URL --model $MODEL` for each model; per 05 ticket N8 it should cover chat, streaming, tool call and the context limit.

**Audit trail.** The MR (diff of the pinned version, approvers, timestamps) and the environment's deployment log (who triggered, which commit and pipeline, when) together answer who, when and what. Job logs show the smoke result that justified the promotion.

## 4. Acceptance criteria mapping

| Typical criterion | How it is met | Evidence |
|---|---|---|
| Models can be registered, listed, updated, removed | Add / read / edit / `status: retired` entries in `catalogue.yaml`; listing = `models.json` or gateway `GET /v1/models` | MR history; `models.json` |
| Metadata complete and queryable | Schema and script reject missing fields; `models.json` served statically or loaded by a service; gateway lists models too | `generate.py` exit 2 on gaps |
| Limits enforced | Context in the NIM spec; rate, token and budget limits in the gateway from generated config | Probe: over-limit call returns 429 (rate) or 402 (budget), per [06](../prereading/06-bifrost-llm-gateway.md) |
| Promotion logged with who/when/what | MR approvals plus GitLab deployment log per environment | Merge request, Environments page |
| Smoke tests gate QA→PROD | `promote-prod` needs `smoke-qa` (single pipeline) or MR requires passing pipeline | CI job graph |
| Reproducibility | Pinned tag and profile per env, deterministic generated output, `--check` in CI; rollback = revert the MR | Git history |

## 5. UNVERIFIED

Checked on 2026-11-19 against docs.getbifrost.ai (virtual keys, custom providers) and `transports/config.schema.json` in maximhq/bifrost (only the first ~100 KB of a 619 KB schema read).

Confirmed from those sources: `providers.<name>.keys[].{name,value,models,weight}`; `custom_provider_config.{base_provider_type,allowed_requests,request_path_overrides}`; `network_config.base_url`; governance `virtual_keys[].provider_configs[].{provider,weight,allowed_models,blacklisted_models,key_ids}`; virtual key `rate_limit_id`, `allow_all_providers`, `team_id`, `customer_id`, `is_active`; `budgets[].{max_limit,reset_duration,virtual_key_id,provider_config_id,model_config_id,team_id,customer_id}`; `rate_limits[].{token_max_limit,token_reset_duration,request_max_limit,request_reset_duration}`; the singular `budget` / `budget_id` fields are ignored from v1.5.0, use the `budgets` array.

- UNVERIFIED: `rate_limit_id` on a `provider_configs` entry in `config.json` (the generated virtual-key template uses it for per-model limits). The `budgets` schema has `provider_config_id` and `model_config_id`, which suggests per-provider and per-model scoping exists, but the `virtual_key_provider_config` definition was not read. Fallback: one virtual key per model, or the model-config route.
- UNVERIFIED: `budgets_by_provider` in the output is a review sidecar, not a Bifrost field. Convert it to `budgets` entries with `provider_config_id` or `model_config_id` once the right scoping is confirmed.
- UNVERIFIED: whether a custom provider needs a key entry at all (docs always show one; the sample uses a dummy `env.NIM_DUMMY_KEY`).
- UNVERIFIED: whether `base_url` should end in `/v1` (the sample includes it; see [22](../prereading/22-bifrost-deployment.md)). Probe for a doubled `/v1/v1`.
- UNVERIFIED: whether `keys[].models` accepts values other than `["*"]` as an enforced allow-list (docs only show the wildcard). The virtual-key `allowed_models` is the documented enforcement point.
- UNVERIFIED: per-env `models` key values with embedded slashes (`org/model`), and whether the NIM-served model id matches `nim.model_name`; read it from the NIM's `/v1/models`.
- UNVERIFIED: whether governance counters are shared across gateway replicas (carried from 22).
- UNVERIFIED: the exact NIM setting that enforces `context_window`, and whether a NIM profile can cap it.
- UNVERIFIED: GitLab tier needed for required approvals on protected environments (believed Premium or higher); also that `rules: when: manual` on a protected environment blocks non-allowed users in your version.
- Placeholders: every model name, size, tag, profile, registry path and endpoint in `catalogue.yaml` is illustrative.

## References

- Bifrost custom providers: https://docs.getbifrost.ai/providers/custom-providers
- Bifrost virtual keys and governance: https://docs.getbifrost.ai/features/governance/virtual-keys
- Bifrost config schema: https://github.com/maximhq/bifrost/blob/main/transports/config.schema.json
- GitLab environments and deployments: https://docs.gitlab.com/ci/environments/
- GitLab protected environments: https://docs.gitlab.com/ci/environments/protected_environments/
- GitLab merge request approvals: https://docs.gitlab.com/ee/user/project/merge_requests/approvals/
- GitLab CI `rules` and `needs`: https://docs.gitlab.com/ci/yaml/
- NVIDIA NIM Operator docs: https://docs.nvidia.com/nim-operator/latest/
- In this repo: [05 gap analysis](05-gap-analysis.md), [03](03-nvidia-recommended-deployment.md), [04](04-nemo-entity-and-data-store.md)
