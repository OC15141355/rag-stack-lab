# raglab: a GitOps lab for NIM model management (Phase A design)

Date: 2026-11-24 · Status: **revision 2 after Tier-1 review** (code-reviewer, devils-advocate, sops-guardian,
fact-check: [2026-11-24-raglab-factcheck.md](2026-11-24-raglab-factcheck.md)) · awaiting owner review

## Purpose

A small, separate, on-demand Kubernetes lab to practise the target state from the Project investigation
(`docs/project-investigation/confluence/`):

- NIM Operator CRs managed by Argo CD, with custom health checks, sync waves and prune protection;
- Bifrost as the single gateway, configured from a git model catalogue, with per-environment limits;
- DEV → QA → PROD promotion through git, with smoke-test evidence;
- a layered, automated bootstrap replacing manual install steps.

There's no local GPU. Phase A uses **NVIDIA-hosted NIM endpoints**. Phase B (separate spec) adds a rented GPU node.

## Non-goals (Phase A)

RAG components, SSO, dashboards, the GPU Operator, NeMo microservices, running a model, the tailnet, and NFS/RWX
storage.

## Constraints

- **Separate** from the homelab cluster and its Argo CD (no CRDs, AppProjects or argocd-cm changes there).
- **Resource-wary host (hv-01):**
  - CPU: 6 physical cores, no SMT, and 10 vCPUs already allocated.
  - It hosts an etcd member (k8s-ctrl).
  - Storage: one DRAM-less NVMe carries root, the thin pool and swap. The thin pool is 72% full and over-committed;
    the `pve` volume group has 16 GiB free.
- **Public repo** is Argo's source. A merge to `main` must not equal control of the lab's secrets. No IPs, hostnames
  of the tailnet, keys or employer data in plaintext.
- NVIDIA developer program: hosted API under the API Trial Terms (read before publishing any benchmark numbers);
  self-hosted NIMs for dev/test only (Phase B).

## Architecture

```
GitHub rag-stack-lab (public, protected main, gitleaks + push protection)
  lab/ ──watched by──▶ Argo CD (lab VM, slim, pinned ≥ 3.6.2)
                          AppProject raglab (hand-applied, not in git sync)
                          ├─ raglab-system      : NIM Operator (controller only)
                          ├─ raglab-secrets     : SOPS → Secrets (CMP, fail-closed, SSA)
                          ├─ raglab-<env>       : Bifrost + smoke PostSync hook        (dev/qa/prod)
                          └─ raglab-nim-<env>   : NIMService ×2 (replicas 0), no hooks  (dev/qa/prod)
Bifrost (each env) ──HTTPS 443──▶ integrate.api.nvidia.com/v1
```

### Host and cluster

| Item | Choice | Why (review ref) |
|---|---|---|
| VM | hv-01, **2 vCPU, 5 GiB RAM**, `onboot: 0`, started for sessions, stopped after | RAM fits (~15 GiB available) |
| Disk | **Dedicated thick LV `raglab` (14 GiB) in VG `pve`**, exposed as an LVM storage restricted to node hv-01; raw, fully allocated; **no snapshots** | Can't fill the thin pool or root fs (DA M1, CR M8) |
| Disk IO | `mbps_wr=50`, `iops_wr=500` (tune after measuring) | etcd is fsync-sensitive; same NVMe (DA M8) |
| CPU | `cpuunits: 50` (relative weight vs default 100). **No `cpulimit`** (a no-op on a 2-vCPU VM) | Wins for k8s-ctrl under contention only (DA M8, FC 20) |
| Template | `qm clone 9001 --full --storage raglab` (never a linked clone onto the thin pool) | DA m1, CR M8 |
| Backups | Lab VM **not** added to any vzdump job; stated here (jobs are VM-ID lists today) | SG M3, FC 21 |
| OS / k8s | Ubuntu 24.04; **k3s pinned version**, install script fetched at a pinned tag + checksum; `--secrets-encryption`; Traefik bundled (v3); local-path only | SG M3, DA M6, FC 6/7 |
| Network | LAN only. **No tailnet in Phase A.** No `--accept-routes` ever | DA B2, m8 |

**Precheck before each session:** hv-01 root fs ≥ 20 GiB free, host memory PSI and IO PSI ≈ 0.
**Stop rule:** stop the lab VM if host IO PSI `some avg60` > 10, k8s-ctrl CPU steal > 10%, or any homelab etcd
alarm/leader change during a session.

### Resource budget (with chart defaults overridden)

| Component | Requests / limits | Notes |
|---|---|---|
| k3s + Traefik + CoreDNS + local-path | ~0.3 CPU / 0.8 GiB | |
| Argo CD (no Dex, no notifications, no ApplicationSet controller, 1 repo-server + CMP sidecar, Redis with auth) | ~0.4 / 1.1 GiB | |
| NIM Operator | 0.1–0.5 CPU / 128–256 MiB (chart default requests 500m; override) | pinned image digest, `pullPolicy: IfNotPresent` (chart default is `release-3.0` + `Always`) |
| Bifrost × 3 | 0.1 CPU / 512 MiB request, 768 MiB limit each | docs-sized |
| Smoke Jobs | 0.1 / 128 MiB, serialised | |
| **Total** | **~1.3 CPU / ~3.8 GiB** | inside 2 vCPU / 5 GiB |

## Repository and gates (must exist before any secret)

```
.gitignore                      secrets section ported from homelab-k8s (*.key, *.pem, age-key*.txt, .env*,
                                kubeconfig*, k3s.yaml, lab/bootstrap/inventory.ini, *.dec, editor swap files,
                                *secret* except **/secrets/*.sops.yaml)
.gitleaks.toml                  homelab rules + age secret key (incl. PQ/lowercase) + private key header + nvapi-
.sops.yaml                      ONE root file, ONE rule: path_regex ^lab/secrets/.*\.sops\.yaml$, lab recipient only,
                                encrypted_regex ^(data|stringData)$ (K8s Secret manifests only)
scripts/safety-check.sh         gitleaks (worktree + index) + structural check: every data/stringData leaf is ENC[…],
                                every lab/secrets file has a sops block, out/** has no nvapi-/sk-bf- values
scripts/pre-commit.sh           runs safety-check on staged blobs + message
.github/workflows/ci.yml        on: pull_request (never pull_request_target): gitleaks (digest-pinned) on tree + PR
                                range, structural check, kustomize build of every overlay, generate.py --check,
                                smoke.py self-test against the mock, examples/smoke ↔ lab/smoke drift check
lab/
  README.md                     session start/stop, bootstrap, promotion, rotation, teardown
  bootstrap/                    Ansible (inventory.example only; real inventory gitignored)
  argocd/
    appproject-raglab.yaml      HAND-APPLIED by bootstrap; NOT under the root app's path
    root-app.yaml               hand-applied once; path lab/argocd/apps
    apps/                       raglab-system, raglab-secrets, raglab-{dev,qa,prod}, raglab-nim-{dev,qa,prod}
  platform/nim-operator/values.yaml
  catalogue/catalogue.yaml + generate.py   → writes lab/envs/<env>/generated/{bifrost-config.json,models.json}
  envs/base/ + envs/{dev,qa,prod}/          kustomize; configMapGenerator (hash suffix → rollout)
  nim/base/ + nim/{dev,qa,prod}/
  smoke/smoke.py                copy of examples/smoke/smoke.py (CI drift check)
  secrets/{dev,qa,prod}.sops.yaml          K8s Secret manifests only
```

**GitHub settings:** secret scanning + push protection + validity checks **on**; branch protection on `main` and on
`env/qa`, `env/prod`: PR required, CI required, no force-push, no direct pushes (agents open PRs; the owner merges).
**One-off:** gitleaks over the full existing history before the first secret commit.

## Argo CD (bounded)

- Installed by bootstrap with Helm, **pinned ≥ 3.6.2** (CVE-2026-42880 fixed in 3.2.11/3.3.9+; FC 1). Slim values.
- **`argocd-cm` is set from Helm values at bootstrap**, including the Lua health checks. It is never synced from git
  (DA B1, CR m5).
- **AppProject `raglab`** (hand-applied, outside the root app's path), so a merge cannot widen it:
  - `sourceRepos`: this repo only.
  - destinations: `raglab-system`, `raglab-dev`, `raglab-qa`, `raglab-prod` only. **Not** `argocd` or `kube-system`.
  - cluster whitelist: `Namespace`, and `CustomResourceDefinition` only for `apps.nvidia.com`. If the operator chart
    needs ClusterRole/ClusterRoleBinding, enumerate them in the implementation plan with justification.
  - namespace whitelist: explicit kinds only. No `Pod` or `DaemonSet` outside the charts' needs; deny hostPath via the
    k3s Pod Security `restricted` label on `raglab-*` namespaces (the operator namespace gets `baseline`).
- **SOPS CMP:** a plain `sops -d` + kustomize CMP, **no exec/alpha plugins**, fail-closed loop copied from homelab
  (`exit 1` on any decrypt failure), selected by explicit `plugin.name` on `raglab-secrets` only. The age key is mounted
  **read-only into the CMP sidecar only**. A repo-server NetworkPolicy allows egress to DNS + github.com:443 only.
  Redis auth on.
- Every Secret-rendering app uses `ServerSideApply=true`. **Handover probe** (each session): zero Secrets in `argocd`
  or `raglab-*` carry `last-applied-configuration`.
- Env apps: `SkipDryRunOnMissingResource=true` + `syncPolicy.retry` (CRDs arrive via raglab-system) (CR M7).

## Components

**NIM CRs (`raglab-nim-<env>`, no hooks).** One `NIMService` per stand-in model, `replicas: 0`,
`spec.storage.emptyDir` (no PVC, no NIMCache, so no download and nothing to bind) (CR B2, FC 12). Health check Lua:
`NotReady` with `spec.replicas == 0` → **Healthy** ("scaled to zero, Phase A"); `Ready` → Healthy; `Failed` →
Degraded; otherwise Progressing (CR B1, FC 11). Kept in a separate app so its health can never block Bifrost's
PostSync. Profile pins are not expressible without a NIMCache; they arrive in Phase B (CR m8).

**Bifrost (`raglab-<env>`).** Image **pinned by digest** (current release, Renovate PRs, no auto-merge).
- **Config:** generated `config.json` (real Bifrost schema; `generate.py` rewritten, CR m6 / DA M3), mounted via
  `configMapGenerator`, so a change rolls the pod. Deployment `strategy: Recreate` (SQLite on an RWO PVC with
  local-path; consumer present, so it binds).
- **Source of truth and auth:** `source_of_truth: config.json` (git wins over UI edits). `governance.auth_config`
  enabled with admin credentials from the env Secret (FC 14).
- **Inference:** `client.enforce_auth_on_inference: true`. **One virtual key per env**, value `env.BIFROST_VK` from
  the Secret (FC 16). Custom OpenAI-compatible provider to `https://integrate.api.nvidia.com/v1` with
  `env.NVIDIA_API_KEY`.
- **Models:** `z-ai/glm-5.3-flash` and `nvidia/nemotron-3.5-lightning-30b-a3b`, with **aliases** `chat/glm`,
  `chat/nemotron` (FC 15; verify routing without a default provider in the plan).
- **Logging:** `disable_content_logging: true` (default is **off**, i.e. logging on; FC 17); `LOG_LEVEL=info`; a
  startup-log check that no resolved `env.*` value appears.
- **Exposure:** Service ClusterIP. Traefik IngressRoute **`PathPrefix(/v1)` only**; admin UI reached only by
  `kubectl port-forward` (DA M4, CR M4).

**NetworkPolicy (per env).** Bifrost ingress: Traefik, smoke Job. Egress: DNS, 443.

**Smoke.**
- **What runs:** `lab/smoke/smoke.py` (mounted from ConfigMap) as an Argo PostSync hook Job in `raglab-<env>`. It
  targets the **Service** (not Traefik; CR m4) and loops over the catalogue's models.
  - `--skip tools` where the catalogue says no tool support.
  - VK via env var (new `--header-env` option; never argv) (SG H5).
  - 429 backoff added to `smoke.py`; hooks serialised across envs (CR m3).
- **Extra checks:**
  - **limit check:** a dedicated per-env **probe virtual key** limited to 2 requests/min; 3 quick 1-token chats must get a Bifrost 429 on the third (only 2 calls ever reach upstream, so the 429 can't be NVIDIA's) (DA M3, CR M5);
  - **auth-negative** asserts Bifrost's own error body;
  - **config read-back** from Bifrost's API.
- **Output:** the JSON report goes to the Job log with the synced revision SHA.
- **Each session:** a hard refresh + sync of each env app (hooks only run on sync, DA M3).

## Promotion (honest version)

- Applications track: dev → `main`, qa → branch `env/qa`, prod → branch `env/prod` (matches
  `examples/argocd/applicationset.yaml`; DA M2).
- Promote = PR `main → env/qa`, then `env/qa → env/prod`. Everything (base, catalogue, generated config) moves together
  because it's the same commit.
- QA → PROD evidence: the QA PostSync smoke JSON for **the exact commit SHA** being promoted, pasted **redacted** (no
  IPs/hostnames) into the PR. This is **attested, not enforced**: GitHub can't see the cluster. Argo Notifications →
  commit status is backlog (CR M1).
- **Prod smoke detects, it doesn't prevent.** A failed prod hook means: revert PR on `env/prod`, re-sync.
- Argo app "Healthy" is **not** evidence. Hooks don't affect app health (FC 2).

## Secrets

- **Lab age key:** generated on the MacBook into **`~/.sops/raglab-age-key.txt`** (mode 600). Check the path doesn't
  exist first. **Never** written into `~/.config/sops/age/keys.txt` or `~/.sops/age-key.txt` (homelab keys). Used via
  `SOPS_AGE_KEY_FILE` (direnv in `lab/`).
  - **Backup:** one offline copy (password manager). Proven by a stdout-only test decrypt.
  - **Loss recovery:** new key → `sops updatekeys` → reissue the NVIDIA key and Bifrost secrets → re-bootstrap
    (SG M5).
- **Per env Secret:** `NVIDIA_API_KEY`, `BIFROST_ENCRYPTION_KEY`, `BIFROST_ADMIN_USER`/`_PASSWORD`, `BIFROST_VK`, `BIFROST_VK_PROBE`.
  - Created with `sops edit lab/secrets/<env>.sops.yaml` from the repo root (root `.sops.yaml` is found; FC 8). sops
    uses a 0600 temp file that it deletes (FC 10).
  - Editor swap/undo off for that session. **No** `export`/`echo`/`--from-literal` of keys.
- **Bootstrap:** the age key Secret is created from the workstation (`delegate_to: localhost`) with
  `kubectl create secret generic --from-file`.
  - `no_log: true` on every task touching it; no `register`/`slurp`/`--diff`/`log_path`.
  - The key never lands on the VM disk (SG H4).
- **History:** committed ciphertext is public forever. A compromised age key means **rotating every secret ever
  encrypted to it**, not just the key (SG H3). Age-key rotation is two-phase (add recipient → updatekeys → both
  identities in cluster → verify → remove old).
- **NVIDIA key:**
  - **Scope and expiry:** a Personal key, scoped to the API catalog/endpoints only, with the shortest expiry that
    covers the lab. A separate key per env if the quota allows; at least separate from any NGC-pull key (Phase B)
    (DA M5, FC 18).
  - **Rotation:** new key → `sops edit` → PR/sync → (config hash rolls Bifrost) → positive smoke → revoke the old key
    at NVIDIA → negative probe from a script reading the key from a file.
  - **Leak:** revoke first.
  - **Teardown:** revocation is **mandatory**.
- No employer data is ever sent to the hosted API.

## Testing / success criteria (Phase A done when)

1. From a fresh VM: bootstrap → all apps **Synced/Healthy and last operation Succeeded** (incl. hooks), with no manual
   cluster steps beyond the documented Proxmox VM creation and hand-applied AppProject/root app.
2. In dev, qa and prod, smoke passes: models, chat, stream, tools (where supported), auth-negative (Bifrost body) and
   limit-429. Report contains the synced SHA.
3. An **env-level** limit change flows main → env/qa → env/prod by PRs, Bifrost rolls (new pod), config read-back shows
   the new value, and QA evidence matches the promoted SHA.
4. NIMService shows the custom "scaled to zero" Healthy. Bifrost's data PVC carries `Prune=false,Delete=false` and
   survives removal from git **while an un-annotated control ConfigMap in the same app is pruned** (proves prune is on;
   DA M3).
5. During a 2-hour session: host IO/memory PSI and k8s-ctrl CPU steal stay under the stop-rule thresholds; zero
   OOMKills/evictions in the lab; homelab etcd health OK (`etcdctl endpoint health` on k8s-ctrl, read-only) before and
   after.
6. Gates work: a test commit containing a fake `nvapi-` string is blocked by the pre-commit hook, CI and GitHub push
   protection. A plaintext value under `lab/secrets` fails the structural check.
7. The learner rebuilds the lab from `lab/README.md` alone.

## Teardown checklist

Delete Applications (with resource finalizers) or simply destroy the VM.
- **Proxmox:** remove the `raglab` storage definition and LV.
- **Workstations:** remove kubeconfig contexts and known_hosts entries.
- **NVIDIA:** **revoke** the key(s).
- **Age key:** retire the lab key (keep the backup only if the history should stay decryptable).
- **Phase B only:** tailnet device and auth key.

## Phase B (outline; its own spec + review)

Rent one GPU VM; join it as a k3s **agent** with `--agent-token` (never the server token) over the tailnet using
**`tag:raglab`**.
- **Tailnet join:**
  - ephemeral, pre-authorised, tagged auth keys;
  - an ACL allowing only `tag:raglab ↔ tag:raglab` on the k3s/flannel ports, plus admin → `tag:raglab`;
  - no routes advertised or accepted;
  - `--flannel-iface tailscale0` with MTU tuned. Phase B reinstalls the k3s server with these options (cheap: the lab is rebuildable by design).
- **GPU stack:**
  - GPU Operator pinned (26.7.x) with `driver.enabled=false` on pre-installed drivers;
  - repo-server and the age key never schedule on the GPU node (taint).
- **NIM:**
  - a separate NGC pull key (the provider's root can read it);
  - **dev first**, then qa/prod, via the same promotion flow.
- **Teardown:** drain/delete node, remove the tailnet device, revoke keys, terminate the VM.

## Review outcome (2026-11-24, Tier 1)

- **Fixed in this revision:** CR B1, B2, M1–M8, m1–m10; DA B1, M1–M6, M8–M10, m1–m4, m7, m8; SG H1–H5, M1–M6.
- **Phantom:** DA M7 (cert-manager required). Admission webhook is off by default in NIM Operator v3.1.4
  (`admissionController.enabled: false`, verified in values.yaml; FC 13).
- **Security backlog (pre-existing, outside this lab):**
  - tailnet ACL grants `*:*` to the admin group, with LAN route and exit-node auto-approval for the owner's account;
  - homelab monitoring has `kubeEtcd` disabled (no etcd latency metrics);
  - orphaned `vm-100-disk-0` on hv-01's thin pool;
  - hv-01 runs on a single 45%-worn DRAM-less NVMe.
- **Noted, not adopted:** DA m5 (ceremony vs value). The three envs + gates are the learning objective; kept on
  purpose, and the VM is on-demand.
