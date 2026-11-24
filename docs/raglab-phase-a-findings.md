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

## Acceptance status (2026-11-25, read-only against the lab plus allowed temp-app probes)

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Bootstrap -> all Applications Synced/Healthy (fresh-VM rebuild not re-run) | PASS (live state); rebuild BLOCKED | All 9 Applications Synced/Healthy (`kubectl get applications -A`). Handover re-run (T9): strict handover failed only on smoke (NVIDIA key), passed with an explicit allow-list. The from-scratch rebuild (Task 11 Step 8) is owner-run and not done. |
| 2 | Smoke passes in dev/qa/prod | BLOCKED | NVIDIA key is `PENDING-...`; chat/stream/tools/limit-429 fail upstream with 401. auth-negative PASS and revision recorded (dev, 8b7c3c8). Needs the owner key (runbook section 3). |
| 3 | Promotion main -> env/qa -> env/prod | BLOCKED | Needs working smoke evidence (criterion 2). env/qa and env/prod exist and are protected. |
| 4 | NIMService "scaled to zero" Healthy (read-only part) | PASS | Argo resource health for glm and nemotron in raglab-nim-dev/qa/prod: `Healthy`, message `scaled to zero (Phase A)` (via `argocd app get -o json`; the Application CR's `status.resources` omits per-resource health, and kubectl shows `NotReady`). |
| 4 | Prune protection (PR removing canary + PVC) | NOT RUN | Needs merge-and-revert PRs on main; deferred to the owner. |
| 5 | Host impact over 2 h | PARTIAL | At ~4.5 h: hv-01 PSI io/mem ~0, cpu some ~1.7; lab node 140m / 2757Mi (56%); 0 OOM/evict. etcd `endpoint health` before/after NOT run (no direct ssh to k8s-ctrl; needs the ProxyJump alias). Owner check. |
| 6 | Gates | PARTIAL | GitHub push protection: `secret_scanning_push_protection: enabled`, `secret_scanning: enabled` (`gh api repos/OC15141355/rag-stack-lab`). No fake key pushed; the `--no-verify` push test was deliberately not attempted. Hook/CI/structural coverage is by the test suite (PR #1). |
| 7 | Runbook | WRITTEN, rebuild test pending | `lab/README.md`. Section 2.1 (Proxmox) is reconstructed from notes, not replayed. |

### Task 11 negative probes (temporary Applications in `raglab-apps`, all deleted afterwards)

| Probe | Result | Message |
|---|---|---|
| (a) project `raglab-platform` | PASS (rejected) | `application 'probe-a' in namespace 'raglab-apps' is not permitted to use project 'raglab-platform'` |
| (b) project `default` | PASS (rejected) | `application 'probe-b' in namespace 'raglab-apps' is not permitted to use project 'default'` |
| (c) project `raglab`, destination `raglab-system` | PASS (rejected) | `InvalidSpecError: application destination server 'https://kubernetes.default.svc' and namespace 'raglab-system' do not match any of the allowed destinations in project 'raglab'` |
| (d) plugin `sops-kustomize` on `lab/envs/dev` | PASS (fails) | `ComparisonError ... CMP processing failed for application "raglab-apps_probe-d" ... sops-kustomize: not permitted for ...` (guard rejected it before any decrypt) |

After the probes, `kubectl -n raglab-apps get applications` shows only the 7 real apps.
