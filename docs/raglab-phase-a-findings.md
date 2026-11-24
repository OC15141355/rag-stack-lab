# raglab Phase A — run findings (2026-11-25, autonomous run)

Status: **complete except items blocked on the NVIDIA key and owner checks.** The ledger is `.superpowers/sdd/progress.md` (local, gitignored).

## OWNER TODOs
1. Add the NVIDIA key (runbook section 3).
2. Copy the age key to the password manager.
3. Set `strict: false` on the `env/*` branch protection (keep the `gates` check), or the second promotion blocks as "out of date" (an automated attempt was refused by the permission policy).
4. Delete merged remote branches (`feat/*`, `fix/*`, `docs/*`; an automated attempt was refused by the permission policy).
5. etcd health check (criterion 5).
6. Rebuild test (criterion 7).
7. The prune test (criterion 4).
8. ~~After a real key: smoke, promotion, limit marker~~ — done 2026-11-25 (see "Live with real key").

## Done
- T1 repo gates (PR #1): gitleaks, structural secrets checker, hook, CI (30→114 tests across tasks).
- T2: secret scanning + push protection on; `main`, `env/qa`, `env/prod` protected (CI `gates` + PR required).
- T3: lab age key `~/.sops/raglab-age-key.txt` (offline backup in the owner's private location), `.sops.yaml`, 3 env secrets.
- T4 catalogue + schema-valid Bifrost config (PR #3). T5 smoke tooling (PR #4). T6 manifests (PR #5). T7 bounded Argo CD (PR #6).
- T8: VM 101 `raglab` on hv-01 (2 vCPU, 5 GiB, cpuunits 50, IO caps, onboot 0). Dedicated 14G LV mounted as dir storage `raglab`.
- T9: bootstrap ran. k3s v1.37.2 with secrets encryption, Argo CD v3.6.2, operator and NIM apps Healthy. PR #7 (playbooks) merged and reviewed.
- Fix (this PR): `raglab-secrets` app lacked a destination namespace, so Bifrost pods failed on the missing `bifrost-env`.

## Things that affect work (the Project investigation)
- **Bifrost virtual keys deny all upstream keys by default** (v2 semantics: empty `key_ids` = deny). Configs need `key_ids: ["*"]` or explicit IDs, and a schema-valid config can still fail at runtime.
- **Bifrost logs prompt content by default** (`disable_content_logging` defaults false). Turn it off explicitly.
- **Bifrost container `args` break its entrypoint:** unknown flags make `docker-entrypoint.sh` loop forever. Use `APP_*` env vars.
- **Argo CD's built-in `default` project allows everything.** Lock it, or any merged Application can escape project bounds.
- **The NIM Operator ClusterRole can read and write Secrets and create Pods in every namespace.** Whoever controls the operator, or its values, can read every Secret. Keep the operator's config out of auto-synced git.
- **NIM Operator upgrades of single-replica NIMs are outages** (`maxSurge: 0`, hard-coded). Already in the confluence pages.
- **The operator chart's default image is the floating `release-3.0` tag with `Always` pull.** Pin a digest.
- **Apps-in-any-namespace changes `ARGOCD_APP_NAME`** to `<ns>_<name>` for CMP plugins.
- **`sops updatekeys` is not a rotation.** It keeps the data key; old-key holders plus public history still decrypt new values (proven by the reviewer). Use `sops rotate -i --add-age/--rm-age` (new data key) BEFORE entering new values.
- **Every commit to a tracked branch rolls Bifrost and reruns smoke**: the revision annotation reaches the pod template. That costs NVIDIA calls and can trip the probe key within 60 s.
- **App-of-apps on `main` = control of everything it defines.** Whoever merges to `main` controls the qa/prod app definitions and every env Secret.
- **Squash vs merge on protected promotion branches:** promote with "Create a merge commit"; a squash rewrites the SHA the evidence refers to.
- **`envFrom` Secret changes don't roll pods.** After a Secret change, `rollout restart` Bifrost.

## Verified live (2026-11-25, dev smoke at 8b7c3c8)
- All 9 Applications are Synced/Healthy. `raglab-secrets` decrypts via the CMP, so the app-name guard (`raglab-apps_raglab-secrets`) and the sidecar `readOnlyRootFilesystem` both work.
- The model string `nvidia-hosted/chat/glm` routes: Bifrost `routing_info` shows provider `nvidia-hosted`, model `chat/glm`, key `nvidia-dev`.
- `key_ids: ["*"]` works (the provider key was selected). The 401 is NVIDIA's own, because of the placeholder key.
- auth-negative passes with the Bifrost body; revision is recorded.
- **Limit marker (corrected after a live test):** the gateway's own governance 429 carries `"is_bifrost_error": false`, the same as upstream errors, so that field does NOT identify gateway errors. The reliable marker is the message `Rate limit exceeded: rate limit violated for vk_model_config ...`, so the smoke Job uses `--expect-limit "rate limit violated for vk"`.
- limit-429 can't be judged until upstream calls succeed (requests 1-2 must be 200). It needs the real NVIDIA key.

## Not yet verified live
- whether rate-limit changes propagate to existing limit rows (read-back command: runbook 4.1, UNVERIFIED against a live Bifrost)
- the generic `--expect-limit "rate limit"` marker (needs a real gateway 429)

(The negative probes for project/destination/CMP-guard rejection are now verified; see below.)

## Residual risks
- **Merge to `main` controls qa/prod and all env Secrets.** The secrets app and child app `targetRevision`s come from `main`. The project bounds protect the age key and cluster RBAC, not the env Secrets.
- **Hand-applied files go live at the next bootstrap re-run.** Record the bootstrap SHA and review `git diff <sha>..HEAD -- lab/argocd/hand-applied lab/argocd/argocd-values.yaml lab/bootstrap` first (runbook 1.4 step 6).
- **The operator chart comes from a mutable Helm repo:** the version is pinned, the templates are not digest-pinned.

## Deviations from the plan
- The VM was built from the verified Ubuntu cloud image, not the 20G template. Nested LVM was refused, so storage is ext4 on a dedicated LV (fstab `nofail`).
- Applying the locked `default` project needed `--force-conflicts`.
- The stricter secrets check (R3: every leaf must be ENC) was adopted beyond the plan.
- No config read-back in smoke (rate limits / VK config are not checked at runtime).
- No startup-log env-value check (nothing asserts that env values were not logged).
- No hook serialisation across envs: smoke hooks for dev/qa/prod can run concurrently against the same upstream key.
- No Renovate (pins are updated by hand).
- Repo-server egress allows any public 443, not `github.com` only.
- `secret_scanning_validity_checks` is not enabled (the spec asked for it).
- `examples/smoke` diverged from `lab/smoke`.

## Acceptance status (2026-11-25, read-only against the lab plus allowed temp-app probes)

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Bootstrap -> all Applications Synced/Healthy | BLOCKED | Live check (`kubectl get applications -A`, read-only): qa and prod last operation `Failed`, dev retrying (OutOfSync/Running), because the smoke hooks fail upstream (no real NVIDIA key). Re-check live. Strict handover fails only on smoke and passes with an explicit allow-list. The from-scratch rebuild (Task 11 Step 8) is owner-run and not done. |
| 2 | Smoke passes in dev/qa/prod | BLOCKED | NVIDIA key is `PENDING-...`; chat/stream/tools/limit-429 fail upstream with 401. auth-negative PASS and revision recorded (dev, 8b7c3c8). Needs the owner key (runbook section 3). |
| 3 | Promotion main -> env/qa -> env/prod | BLOCKED | Needs working smoke evidence (criterion 2) and `strict: false` on `env/*`. Evidence of a config change = the `bifrost-config-<hash>` ConfigMap name changed, plus the runbook 4.1 config read-back. env/qa and env/prod exist and are protected. |
| 4 | NIMService "scaled to zero" Healthy (read-only part) | PASS | Argo resource health for glm and nemotron in raglab-nim-dev/qa/prod: `Healthy`, message `scaled to zero (Phase A)` (via `argocd app get -o json`; the Application CR's `status.resources` omits per-resource health, and kubectl shows `NotReady`). |
| 4 | Prune protection (PR removing canary + PVC) | NOT RUN | Needs merge-and-revert PRs on main; deferred to the owner. |
| 5 | Host impact over 2 h | PARTIAL | At ~4.5 h: hv-01 PSI io/mem ~0, cpu some ~1.7; lab node 140m / 2757Mi (56%); 0 OOM/evict. etcd `endpoint health` before/after NOT run (no direct ssh to k8s-ctrl; needs the ProxyJump alias). Owner check. |
| 6 | Gates | PARTIAL | GitHub push protection: `secret_scanning_push_protection: enabled`, `secret_scanning: enabled` (`gh api repos/OC15141355/rag-stack-lab`); validity checks not enabled. No fake key pushed; the `--no-verify` push test was deliberately not attempted. Hook/CI/structural coverage is by the test suite (PR #1). |
| 7 | Runbook | WRITTEN, rebuild test pending | `lab/README.md`. Section 2.1 (Proxmox) is reconstructed from notes, not replayed. |

### Task 11 negative probes (temporary Applications in `raglab-apps`, all deleted afterwards)

| Probe | Result | Message |
|---|---|---|
| (a) project `raglab-platform` | PASS (rejected) | `application 'probe-a' in namespace 'raglab-apps' is not permitted to use project 'raglab-platform'` |
| (b) project `default` | PASS (rejected) | `application 'probe-b' in namespace 'raglab-apps' is not permitted to use project 'default'` |
| (c) project `raglab`, destination `raglab-system` | PASS (rejected) | `InvalidSpecError: application destination server 'https://kubernetes.default.svc' and namespace 'raglab-system' do not match any of the allowed destinations in project 'raglab'` |
| (d) plugin `sops-kustomize` on `lab/envs/dev` | PASS (fails) | `ComparisonError ... CMP processing failed for application "raglab-apps_probe-d" ... sops-kustomize: not permitted for ...` (guard rejected it before any decrypt) |

After the probes, `kubectl -n raglab-apps get applications` shows only the 7 real apps.

## Live with real key (2026-11-25)
- Key checked with a 1-token hosted call (HTTP 200), then written into all 3 env secrets via pipes. No plaintext on disk or in git (0 `nvapi` matches in the encrypted files).
- `envFrom` Secret updates do not restart pods: after the secrets sync, run `kubectl -n raglab-<env> rollout restart deploy/bifrost`.
- **dev smoke at 800e3e6: 9 passed, 1 skipped, 0 failed**
  - chat, stream and tools (3/3) on `nvidia-hosted/chat/glm`; chat and stream on `nvidia-hosted/chat/nemotron` (tools skipped by capability)
  - auth-negative passes; limit-429 returns `[200, 200, 429]`
- Both stand-ins spend most output on reasoning tokens (33 of 33 and 170 of 174 on a one-word answer). Budget `max_tokens` accordingly; the same applies to GLM 5.2 and Nemotron 3 Super at work.
- Gateway governance 429 body: `is_bifrost_error: false`, message `Rate limit exceeded: rate limit violated for vk_model_config *`. The marker was switched to the message.
