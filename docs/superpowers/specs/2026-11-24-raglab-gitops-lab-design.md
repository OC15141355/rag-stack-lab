# raglab: a GitOps lab for NIM model management (Phase A design)

Date: 2026-11-24 · Status: awaiting review

## Purpose

A small, separate, on-demand Kubernetes lab to practise the target state from the Project investigation
(`docs/project-investigation/confluence/`) end to end:

- NIM Operator CRs (`NIMService`, `NIMCache`) managed by Argo CD, with custom health checks, sync waves and prune
  protection;
- Bifrost as the single gateway, configured from a git model catalogue, with per-environment limits;
- DEV → QA → PROD promotion by pull request, gated by smoke tests;
- a layered, automated bootstrap (Ansible) replacing the manual install steps seen in the Project.

There's no local GPU. Phase A uses **NVIDIA-hosted NIM endpoints** (developer program). Phase B (separate spec) adds a
rented GPU node so one `NIMService` actually runs.

## Non-goals (Phase A)

RAG components (OpenSearch, ingestion), Keycloak SSO in front of Bifrost, dashboards, the GPU Operator, NeMo
microservices (sunset; not used), and running any model locally.

## Constraints

- **Separate from the homelab cluster and its Argo CD.** No CRDs, AppProject changes or argocd-cm edits on the
  homelab.
- **Resource-wary host:** the Proxmox host also runs a homelab etcd member and has more vCPUs allocated than cores. The
  lab must never compete with it and must not fill the host's over-committed thin pool.
- **Public repo:** manifests live in this public repo. Secrets are SOPS-encrypted with a lab-only age key; no IPs,
  tailnet names or keys in plaintext.
- **NVIDIA developer program terms:** hosted API is for prototyping; self-hosted NIMs only for dev/test (Phase B).

## Architecture

```
rag-stack-lab (GitHub, public)  ──watched by──▶  Argo CD (in the lab cluster)
  lab/                                             │
                                                   ├─ raglab-system : NIM Operator (no GPU → controller only)
                                                   ├─ raglab-dev    : Bifrost + NIM CRs (replicas 0) + smoke hook
                                                   ├─ raglab-qa     : same, pinned
                                                   └─ raglab-prod   : same, pinned
Bifrost (each env) ──HTTPS──▶ integrate.api.nvidia.com/v1  (hosted NIMs, NVIDIA developer API key)
```

### Host and cluster

| Item | Choice | Why |
|---|---|---|
| VM | Proxmox host hv-01, **2 vCPU, 5 GiB RAM, 30 GiB disk** | Fits ~15 GiB free; small enough not to matter |
| Disk | Proxmox `local` (directory) storage, **not** `local-lvm` | Thin pool is over-committed; a lab disk must not be able to fill it |
| CPU priority | `cpuunits: 50` (default 100) + `cpulimit: 2` | Under contention the homelab control plane and etcd win |
| Lifecycle | **On demand:** started for lab sessions, stopped after (`onboot: 0`) | Zero cost when idle |
| OS | Ubuntu 24.04 cloud-init from the existing template | Matches homelab VMs |
| Kubernetes | **k3s** single node (built-in Traefik + local-path); `nfs-client` provisioner for an RWX class | Light; Traefik matches the Project's ingress |
| Network | LAN + tailnet (for Phase B node join); no public exposure | |

### Resource budget (target)

| Component | Requests (CPU / mem) | Notes |
|---|---|---|
| k3s + Traefik + CoreDNS + local-path | ~0.3 / 0.8 GiB | |
| Argo CD (no Dex, no HA, 1 repo-server, Redis) | ~0.3 / 0.9 GiB | ApplicationSet controller only if used |
| NIM Operator controller | ~0.1 / 0.25 GiB | No GPU, so no NIM pods |
| Bifrost × 3 | ~0.15 / 0.25 GiB each | SQLite, small PVC each |
| Smoke Jobs | burst ~0.1 / 0.1 GiB | Short-lived |
| **Total** | **~1.2 CPU / ~3 GiB** | Leaves headroom inside 2 vCPU / 5 GiB |

Every workload sets requests and limits.

## Repository layout (`lab/`)

```
lab/
  README.md                       how to start/stop, bootstrap, promote, tear down
  bootstrap/                      Ansible: layered install (see below)
    inventory.example.ini
    playbooks/{01-platform,02-foundation,03-handover}.yml
  argocd/
    root-app.yaml                 app-of-apps, hand-applied once by bootstrap
    apps/                         Applications: nim-operator, secrets, env-dev, env-qa, env-prod
    argocd-cm-health.yaml         Lua health checks for apps.nvidia.com NIMCache/NIMService
  platform/
    nim-operator/values.yaml      chart pinned (NIM Operator v3.1.4); GPU-less settings
    nfs-provisioner/              RWX storage class (optional, Phase B cache)
  catalogue/
    catalogue.yaml                models, per-env limits/pins (from examples/model-catalogue)
    generate.py                   → out/<env>/bifrost-config.json, models.json (committed; CI --check)
  envs/
    base/                         Bifrost Deployment/Service/ConfigMap, NetworkPolicy, NIMService/NIMCache, smoke hook
    dev/  qa/  prod/              kustomize overlays: pins, limits, replicas, generated config
  secrets/                        SOPS-encrypted: NVIDIA API key, Bifrost encryption key (per env)
  .sops.yaml                      lab age recipient only
```

The repo's existing `examples/` (catalogue, smoke tests, NIM Operator manifests, Argo health checks) are the starting
point; `lab/` is the live, synced version.

## Components

**Bootstrap (Ansible, from the admin workstation).** It mirrors the Project's layers, automated:
1. *Platform:* create VM settings checklist (manual Proxmox step, documented), install k3s pinned, install Argo CD
   pinned (slim values), register the repo (public; no credentials), install the SOPS decryption plugin (CMP sidecar,
   lab age key as a Secret created from a local file).
2. *Foundation:* apply `argocd/root-app.yaml`. From here Argo CD owns everything, including the NIM Operator.
3. *Handover check:* wait for all Applications Healthy; print the access commands.

**NIM Operator.** Installed by Argo CD in `raglab-system`. No GPU Operator in Phase A. CRDs via `ServerSideApply=true`.

**NIM CRs (per env).** One `NIMService` per stand-in model, **`replicas: 0`**, pinned image and profile placeholders,
`spec.storage.pvc` to a small pre-created PVC. **No `NIMCache` in Phase A**: a real cache object starts a model
download job. `NIMCache` arrives with Phase B. Sync waves order PVC (wave 0) before NIMService (wave 1); the PVC carries
`argocd.argoproj.io/sync-options: Prune=false,Delete=false`, the same protection Phase B's caches will get.
How Argo reports a 0-replica NIMService is an expected **lab finding** to record.

**Bifrost (per env).** Pinned image tag (2.5.x); config generated from the catalogue: a custom OpenAI-compatible
provider with `base_url` `https://integrate.api.nvidia.com/v1`, the NVIDIA key from a Secret, models
`z-ai/glm-5.3-flash` and `nvidia/nemotron-3.5-lightning-30b-a3b` (stand-ins for GLM 5.2 / Nemotron 3 Super, not on the
hosted API), served under Project-style names (`chat/glm`, `chat/nemotron`) if Bifrost aliasing supports it (else
documented), `enforce_auth_on_inference: true`, one virtual key per env, rate/token limits per env from the catalogue,
**content logging off**. Exposed in-cluster and via a Traefik IngressRoute (`Host: raglab-<env>.lab`, reached with
`curl --resolve`; no DNS changes).

**NetworkPolicy (per env).** Ingress to Bifrost only from Traefik and the smoke Job. Egress from Bifrost only to DNS and
HTTPS (443). NIM pods (Phase B) only reachable from Bifrost.

**Smoke gate.** `examples/smoke/smoke.py` mounted from a ConfigMap; an Argo **PostSync hook Job** per env runs it
against that env's Bifrost (models, chat, stream, tools; `--expect-auth`). A failure marks the sync failed. Thresholds
are looser in dev.

**Secrets.** SOPS with a **lab-only age key** (generated on the admin workstation; private key never committed or
shared with the homelab key). The NVIDIA API key is encrypted by the user locally (`sops`), never pasted into chat or
logs. Secret-rendering apps use `ServerSideApply=true` (avoids plaintext in `last-applied` annotations).

## Promotion flow

- **dev** overlay follows `main` (catalogue version + image tags from `base`).
- **qa** and **prod** overlays carry explicit pins (catalogue revision, Bifrost tag, NIM image/profile).
- Promote = PR copying QA's pins to prod; the PR template requires "QA last sync + smoke: Healthy/passed (screenshot
  or `argocd app get` output)". Merge → Argo syncs prod → PostSync smoke runs in prod.
- CI on the repo (GitHub Actions, public runners): `generate.py --check`, `kubectl kustomize` for each overlay, YAML
  lint, `smoke.py` self-test against the mock. Cluster-dependent checks happen in-cluster (hooks).

## Error handling and safety

- Prune protection on caches/PVCs; no `Replace=true` anywhere.
- Hosted API failures (rate limit, outage) surface as smoke failures, not as silent passes; documented in the lab
  README.
- If the VM misbehaves, stop it; nothing on the homelab depends on it.
- Teardown: `argocd app delete` the root app (cascade), then stop/destroy the VM; revoke the NVIDIA key if no longer
  needed.

## Testing / success criteria (Phase A done when)

1. Bootstrap from a fresh VM to all Applications Healthy without manual cluster steps beyond the documented Proxmox VM
   creation.
2. `smoke.py` passes in dev, qa and prod through Bifrost (via Traefik), and `--expect-auth` shows unauthenticated calls
   rejected.
3. A catalogue change (e.g. a token limit) flows dev → qa → prod by PRs, with QA smoke as the gate, and prod's Bifrost
   reflects it.
4. Argo shows custom health for NIMService; removing the model PVC manifest from git does **not** delete the PVC.
5. VM stays within its budget (≤ 2 vCPU busy, ≤ 5 GiB), and homelab etcd/control-plane metrics show no change while the
   lab runs.
6. The runbook in `lab/README.md` lets the learner rebuild it from scratch.

## Phase B (separate spec, outline only)

Rent one GPU VM (e.g. NVIDIA Brev, L4/L40S/A100) for a few hours; join it to the lab k3s as an agent over the tailnet;
install the GPU Operator (pinned, current 26.7.x) via Argo; set one `NIMService` to 1 replica using the model-free vLLM
NIM with a small model and a `NIMCache`; switch prod's Bifrost provider for one model from hosted to in-cluster; run
the cutover runbook; tear down the GPU node. Budget about USD 3–12.

## Open questions

- Bifrost model aliasing to `chat/<name>` (verify in Bifrost config docs during implementation).
- Exact NIM Operator behaviour with `replicas: 0` and a plain PVC instead of a `NIMCache` (record as findings).
- Whether to use ApplicationSet (list generator) or three Applications (default: three Applications; simpler).
