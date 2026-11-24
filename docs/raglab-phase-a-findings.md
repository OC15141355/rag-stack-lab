# raglab Phase A — run findings (2026-11-25, autonomous run)

Status: **partially complete.** The run stopped at the usage limit. The ledger is `.superpowers/sdd/progress.md` (local, gitignored).

## Done
- T1 repo gates (PR #1): gitleaks, structural secrets checker, hook, CI (30→114 tests across tasks).
- T2: secret scanning + push protection on; `main`, `env/qa`, `env/prod` protected (CI `gates` + PR required).
- T3: lab age key `~/.sops/raglab-age-key.txt` (backup on core-01 `~/.homelab-backup/`), `.sops.yaml`, 3 env secrets.
- T4 catalogue + schema-valid Bifrost config (PR #3). T5 smoke tooling (PR #4). T6 manifests (PR #5). T7 bounded Argo CD (PR #6).
- T8: VM 101 `raglab` on hv-01 (2 vCPU, 5 GiB, cpuunits 50, IO caps, onboot 0). Dedicated 14G LV mounted as dir storage `raglab`.
- T9: bootstrap ran. k3s v1.37.2 with secrets encryption, Argo CD v3.6.2, operator and NIM apps Healthy. **PR #7 (playbooks) is NOT merged or reviewed.**
- Fix (this PR): `raglab-secrets` app lacked a destination namespace, so Bifrost pods failed on the missing `bifrost-env`.

## Owner TODO (blocking)
1. **NVIDIA key:** every env secret has `NVIDIA_API_KEY=PENDING-...`. Run `sops edit lab/secrets/<env>.sops.yaml` (with `SOPS_AGE_KEY_FILE=~/.sops/raglab-age-key.txt`), PR, merge. Then `kubectl -n raglab-<env> rollout restart deploy/bifrost`.
2. Copy the lab age key into your password manager.
3. Review and merge PR #7. Then: T10 PR template, T11 acceptance (criteria 1–7), `lab/README.md` runbook, final whole-branch review.

## Things that affect work (the Project investigation)
- **Bifrost virtual keys deny all upstream keys by default** (v2 semantics: empty `key_ids` = deny). Configs need `key_ids: ["*"]` or explicit IDs, and a schema-valid config can still fail at runtime.
- **Bifrost logs prompt content by default** (`disable_content_logging` defaults false). Turn it off explicitly.
- **Bifrost container `args` break its entrypoint:** unknown flags make `docker-entrypoint.sh` loop forever. Use `APP_*` env vars.
- **Argo CD's built-in `default` project allows everything.** Lock it, or any merged Application can escape project bounds.
- **The NIM Operator ClusterRole can read and write Secrets and create Pods in every namespace.** Whoever controls the operator, or its values, can read every Secret. Keep the operator's config out of auto-synced git.
- **NIM Operator upgrades of single-replica NIMs are outages** (`maxSurge: 0`, hard-coded). Already in the confluence pages.
- **The operator chart's default image is the floating `release-3.0` tag with `Always` pull.** Pin a digest.
- **Apps-in-any-namespace changes `ARGOCD_APP_NAME`** to `<ns>_<name>` for CMP plugins.

## Verified live (2026-11-25, dev smoke at 8b7c3c8)
- All 9 Applications are Synced/Healthy. `raglab-secrets` decrypts via the CMP, so the app-name guard (`raglab-apps_raglab-secrets`) and the sidecar `readOnlyRootFilesystem` both work.
- The model string `nvidia-hosted/chat/glm` routes: Bifrost `routing_info` shows provider `nvidia-hosted`, model `chat/glm`, key `nvidia-dev`.
- `key_ids: ["*"]` works (the provider key was selected). The 401 is NVIDIA's own, because of the placeholder key.
- auth-negative passes with the Bifrost body; revision is recorded.
- **Better limit marker:** Bifrost errors carry `"is_bifrost_error": true|false`. Upstream errors are `false`. Switch `--expect-limit` from "rate limit" to `"is_bifrost_error":true` once a real gateway 429 confirms it.
- limit-429 can't be judged until upstream calls succeed (requests 1-2 must be 200). It needs the real NVIDIA key.

## Not yet verified live (T11)
- whether rate-limit changes propagate to existing limit rows
- the generic `--expect-limit "rate limit"` marker
- the negative probes (child app with project default or raglab-platform must be rejected)

## Deviations from the plan
- The VM was built from the verified Ubuntu cloud image, not the 20G template. Nested LVM was refused, so storage is ext4 on a dedicated LV (fstab `nofail`).
- Applying the locked `default` project needed `--force-conflicts`.
- The `argocd` namespace was created ad hoc by bootstrap.
- The stricter secrets check (R3: every leaf must be ENC) was adopted beyond the plan.
