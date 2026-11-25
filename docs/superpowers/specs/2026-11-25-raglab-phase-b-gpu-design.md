# raglab Phase B: a standalone rented GPU cluster, one real NIM (design, rev 2)

Date: 2026-11-25 · Status: **rev 2, owner decisions applied, Tier-1 review findings applied; not yet re-reviewed** ·
Follows [Phase A](2026-11-24-raglab-gitops-lab-design.md) (complete; see [findings](../../raglab-phase-a-findings.md)).
Fact base: [Phase B fact-check](2026-11-25-raglab-phase-b-factcheck.md) (2026-11-25).

Rev 1 joined the rented GPU VM to the existing lab cluster over a VPN. **Rev 2 replaces that with a standalone design:** the
rented VM is its own single-node cluster, bootstrapped from this repo, with no connection to the home network or the
home lab cluster. This removes the VPN/ACL/pod-network risks of rev 1 entirely (see section 13, rejected alternatives).

Conventions: `UNVERIFIED:` marks a fact not confirmed against a primary source (the fact-check lists what it resolved).
This is a public repo: no addresses, hostnames, or network details of the home environment appear here. Pre-existing
home-lab issues are recorded privately and are out of scope for this document.

## 1. Purpose

Rehearse, on real GPU hardware and at lab scale, the operator migration described in the target-state investigation:

1. Rent **one** Lambda on-demand A100 40GB VM for at most 5 hours.
2. Bootstrap it with the **same repo and the same playbooks** as Phase A plus a GPU overlay/variables: single-node k3s,
   Argo CD, then GPU Operator, NIM Operator, one `NIMCache` and one `NIMService`, and **one** Bifrost environment (`dev-gpu`).
3. Cut `dev-gpu` Bifrost from the hosted provider to the in-cluster NIM, then back (rollback rehearsal).
4. Terminate the VM and prove nothing is left running, billing or credentialed.

The home lab (dev/qa/prod) is **untouched** and stays on the hosted provider throughout.

### 1.1 Work relevance (what this teaches for the Project)

- **GPU Operator + NIM Operator lifecycle** on a real GPU: install order, driver/toolkit/CDI choices, operand health, hand-applied vs GitOps boundaries.
- **NIMCache**: download, profile discovery, **profile pinning** (cache and service must agree), what a cache is and what deleting it costs.
- **Cold-start time** of a real NIM from empty cache and from warm cache: the number needed to size cutover windows in doc 12.
- **The Bifrost cutover pattern**: a provider entry, per-env serving map, egress NetworkPolicy, client-visible id change, smoke gate, rollback by revert.
- **Gaps you only find on hardware**: no matching profile for a GPU, Pod Security vs operator-rendered pods, containerd/runtime integration.
- Stretch (section 12): NIMCache from a mirrored source, as an air-gap rehearsal.

## 2. Non-goals

- No benchmark numbers for publication (self-hosted NIMs are dev/test only under NVIDIA's terms; hosted API is under trial terms).
- No employer data. Prompts are synthetic smoke prompts only.
- No VPN, no joining the home lab, no remote-cluster registration in the home lab's Argo CD (deferred, section 13).
- No qa/prod cutover (the home lab's qa/prod stay on hosted and unchanged); no promotion flow in this phase.
- No multi-GPU, MIG, time-slicing, multi-node, NeMo microservices, LoRA, RAG components, SSO, Prometheus/DCGM dashboards.
- No persistent GPU infrastructure and no provider-side persistent storage.
- No production-grade HA: one node, one replica; outages on any NIMService change are expected.

## 3. Final decisions

Owner-final items are marked **Owner**. The rest are decided in this revision with a stated reason.

| # | Decision | Final | Reason / residual |
|---|---|---|---|
| D1 | Shape | **Standalone** single-node cluster on the rented VM (**Owner**) | No link to the home network or home cluster; the largest risk class of rev 1 disappears |
| D2 | Provider and GPU | **Lambda on-demand A100 40GB**, about USD 1.99/h, per-minute billing, terminate-only (**Owner**) | The 8B NIM lists A100 in its verified GPUs (fact-check section 2). Filesystems bill until deleted: create none |
| D3 | Session and budget | **Session at most 5 h, hard cap USD 15, expected about 10** (**Owner**) | 5 h x 1.99 is about 10. No provider-side hard cap is known (`UNVERIFIED:` whether Lambda offers a spend limit): the cap is enforced by procedure and alarms, not by the provider |
| D4 | Access | **Owner SSHes in from home; provider firewall allows inbound SSH from the owner's home address only; nothing else exposed** (**Owner**). No Lambda API key on the VM, ever | The Kubernetes API, Argo CD UI and Bifrost are reached only through SSH port-forward |
| D5 | Model | **`meta/llama-3.1-8b-instruct` NIM** on one A100. Pin the **tag** (2.1.7 seen on NGC on 2026-11-17; docs said 2.1.6; resolve at session time) and the **image digest**. Fallback: the model-free vLLM NIM | Per-model NIM exercises NIMCache profile pinning; the model-free NIM does not |
| D6 | GPU Operator | **v26.7.3** (chart version string `v26.7.3`; verify `targetRevision` resolves before the session). **NRI plugin path** (`cdi.enabled=true`, `cdi.nriPluginEnabled=true`, needs containerd 1.7.30 or newer). `driver.enabled=false`; `toolkit.enabled=false` if the toolkit is preinstalled | NRI avoids the k3s containerd path variables. With NRI there is **no `nvidia` RuntimeClass** |
| D7 | Pod Security | **GPU namespace `baseline`; `gpu-operator` `privileged`; Bifrost namespace stays `restricted`** | Operator-rendered pods and NIMCache jobs carry no seccomp profile in v3.1.4, so they cannot pass `restricted`. Decided, not speculative (fact-check section 6) |
| D8 | NGC key | **New key, pull-only if the console allows it, 3-day expiry, revoked at teardown** | The key sits on a provider-owned VM: accepted residual, short-lived |
| D9 | Hosted key on the VM | **A separate, short-lived hosted key (own `nvapi-` key), used only by `dev-gpu`'s "before" state; revoked at teardown** | Justification in section 8.3. Never the Phase A key |
| D10 | Age key | **Separate session-only age key**, separate secrets file `lab/gpu/secrets/gpu.sops.yaml` encrypted **only** to the session key | The Phase A lab age key never leaves the Mac. File path chosen so the home lab's secrets app cannot see it (section 5.2) |
| D11 | Repo isolation | **All GPU material in new paths** (`lab/gpu/...`); GPU Argo apps live under a separate root used only on the rented cluster; applied only when GPU playbook variables are set | Phase A is not weakened; shared-file edits are minimised and reverted at teardown |
| D12 | Cutover shape | `dev-gpu` Bifrost: hosted provider to `nim-local`, then back | qa/prod are not touched |

## 4. Architecture

```
  owner's Mac                                     Lambda A100 40GB VM (public, SSH from owner only)
  ------------                                    ---------------------------------------------------
  ssh + port-forward  ---- SSH (owner IP only) -->  single-node k3s (API bound to loopback or firewalled)
  session age key                                    Argo CD (repo-server + SOPS CMP, session age key)
  (NGC/hosted keys                                   GPU Operator (hand-applied) + NFD
   never on disk                                     NIM Operator (hand-applied)
   in plaintext)                                     ns raglab-gpu:   NIMCache + NIMService (Llama 3.1 8B)
                                                     ns raglab-dev-gpu: Bifrost (dev-gpu env)
                                                              |
                                                              | outbound 443 only
                                                              v
                                          github.com (repo), nvcr.io / NGC (images, weights),
                                          NVIDIA hosted API (the "before" provider), package repos
```

- **One node, one cluster, one Argo CD.** The control plane and the GPU share the node, so no taints, agent tokens or
  cross-node networking are needed. Traefik and servicelb are disabled at k3s install (nothing is published).
- **Nothing on the VM can reach, or authenticate to, the home environment.** There is no VPN client, no kubeconfig
  for any home cluster, no home credentials. The VM is a throwaway.
- **Argo CD pulls the public repo over HTTPS** with no repository credentials.
- **Cluster-scoped objects and operators are hand-applied, not auto-synced** (the Phase A platform rule), here in a
  separate project (section 6).

### 4.1 Host and network posture

- Provider firewall: inbound **TCP 22 from the owner's current home address only** (a single /32; `UNVERIFIED:` how the
  Lambda console expresses and defaults this, and whether firewall rules are account-level and persist after termination).
  No other inbound. Verify from outside the VM that only SSH answers.
- SSH: a **session-only keypair** uploaded for this instance, key-only auth, **no agent forwarding**, no credentials
  other than the session SSH key used from the Mac. The Mac-side kubeconfig is not needed: use `kubectl` on the VM, or
  an SSH tunnel to the API for local tools.
- k3s API and kubelet ports listen on the VM but are firewalled; services use ClusterIP only.
- The VM's disk size and local storage are provider-set (`UNVERIFIED:` size on this SKU); weights and images must fit (about 60 GB plus operator images).

### 4.2 Bootstrap (same playbooks, GPU overlay)

- Reuse `01-platform.yml`, `02-argocd.yml`, `03-handover.yml` with a **GPU variable set** supplied at run time
  (an uncommitted inventory for the VM and uncommitted extra-vars): GPU mode on, k3s version pinned (must bundle
  containerd 1.7.30 or newer, or 2.1+; `UNVERIFIED:` which k3s release; resolve before the session), Traefik/servicelb off,
  **session age key** installed for the CMP (not the Phase A key), root app path set to the GPU root.
- With the variables unset the playbooks behave exactly as in Phase A (regression check in CI: render/lint both modes).
- A new `04-gpu-prep.yml` (only when GPU mode is on): verify `nvidia-smi`, containerd version, whether the NVIDIA container
  toolkit is preinstalled, and record the results.
- Secrets passed to playbooks are `no_log: true`, never in committed inventory, never on argv (stdin or a mode-600 file).

## 5. Repo layout and Phase A isolation

### 5.1 New paths (nothing shared unless listed in 5.3)

```
lab/gpu/
  argocd/root-app.yaml              hand-applied on the rented cluster only (path: lab/gpu/argocd/apps)
  argocd/apps/*.yaml                raglab-gpu-nim, raglab-dev-gpu, raglab-gpu-secrets (GPU cluster only)
  argocd/hand-applied/*.yaml        AppProject raglab-gpu-platform, GPU Operator app, NIM Operator app, namespaces
  nim/                              NIMCache, NIMService, NetworkPolicy (kustomize)
  envs/dev-gpu/                     Bifrost overlay (references lab/envs/base)
  secrets/gpu.sops.yaml             encrypted ONLY to the session age key
  secrets/kustomization.yaml
tests/fixtures/crds/                vendored v3.1.4 NIMCache and NIMService CRDs (plus k3s Argo CRDs already there)
```

The home lab's Argo root watches `lab/argocd/apps` only; it never sees `lab/gpu/...`. The rented cluster's root watches
`lab/gpu/argocd/apps` only.

### 5.2 Why the secrets file is not in `lab/secrets/`

The current `.sops.yaml` rule matches `^lab/secrets/[a-z0-9-]+\.sops\.yaml$`, and the home lab's `raglab-secrets` app renders
the whole `lab/secrets` directory through a fail-closed SOPS CMP. A file there would (a) match the Phase A recipient rule,
and (b) make the home lab's secrets app try to render a file it cannot decrypt, **breaking Phase A sync**. The GPU file
therefore lives in `lab/gpu/secrets/` and is encrypted to the session key only.

### 5.3 Shared files that change (each needs a revert PR at teardown)

| File | Change | Why shared |
|---|---|---|
| `.sops.yaml` | A **second creation rule placed before the existing one**, `path_regex: ^lab/gpu/secrets/[a-z0-9-]+\.sops\.yaml$`, recipient = session age public key only. Removed after | First matching rule wins; order matters |
| `lab/catalogue/catalogue.yaml`, `generate.py`, schema | `nim-local` provider, `chat/small` model, per-env `serving` map; generator emits only the providers an env references | Single source of truth for models |
| CI config and gitleaks config | CRD validation of GPU overlays, NGC key pattern next to the `nvapi-` pattern | Pipeline is shared |

Generator changes must keep the Phase A envs byte-identical (`generate.py --check` on dev/qa/prod must show no diff).
If the generator change is backwards-compatible and CI-green it could be kept, but the owner's rule is **revert**; keeping is a
post-session decision, not a plan.

## 6. GPU Operator and NIM Operator (hand-applied, separate project)

Delivery rule inherited from Phase A: operators and cluster-scoped objects are **hand-applied, never auto-synced from `main`**,
with inline `valuesObject` so a merge cannot change them. Phase A's `raglab-platform` whitelist ("only what chart 3.1.4 renders")
is not widened. Instead, on the rented cluster only:

- **New AppProject `raglab-gpu-platform`** and Applications `raglab-gpu-operator` and `raglab-nim-operator`, all under
  `lab/gpu/argocd/hand-applied/`, applied by hand after reviewing the diff. Whitelists are enumerated from
  `helm template --include-crds` at the pinned versions and recorded in the plan; anything else is rejected.
- **GPU Operator chart `v26.7.3`.** Pre-session: confirm the chart/`targetRevision` string resolves from the chosen source (OCI or Helm repo), record
  the rendered-manifest hash (the Helm repo is mutable), and list its cluster-scoped kinds.
- Argo Application options: `ServerSideApply=true` (large CRDs and the ClusterPolicy), and `ignoreDifferences` on the `ClusterPolicy`
  (the operator mutates defaults and status). **Helm hook mapping:** Argo converts Helm hooks to its own phases
  (pre-install/pre-upgrade to PreSync, post-delete to PostDelete). The chart's CRD-upgrade and cleanup hook jobs must be
  checked in the rendered output (`UNVERIFIED:` which hooks exist at 26.7.3) and any that cannot run under the project whitelist
  are handled explicitly rather than silently skipped.
- **Values (starting point):**
  - `driver.enabled=false` (Lambda Stack ships drivers; confirmed to ship drivers, fact-check section 1). Gate: `nvidia-smi` passes first.
  - `toolkit.enabled=false` **if** the toolkit is preinstalled and works with the NRI path; otherwise `true` (`UNVERIFIED:` default and need with NRI).
  - `cdi.enabled=true`, `cdi.nriPluginEnabled=true`. Requires containerd 1.7.30 or newer (or 2.1/2.2/2.3). `UNVERIFIED:` that k3s's embedded
    containerd exposes NRI as the operator expects.
  - DCGM exporter, ServiceMonitor, MIG manager off. NFD on (default).
  - **No k3s containerd variables** in the NRI path.
- **Fallback if NRI cannot be used** (containerd too old or NRI unavailable): classic toolkit path with the k3s variables, using the containerd
  **v3 template for k3s with containerd 2.x (`config-v3.toml.tmpl`)** and the k3s socket path. `UNVERIFIED:` exact values (fact-check section 3:
  the official page has no k3s section). This fallback restores the `nvidia` RuntimeClass and the whitelist entry for it.
- **RuntimeClass:** with NRI there is no `nvidia` RuntimeClass, so **do not set `runtimeClassName: nvidia`** on NIMService/NIMCache
  (the field exists in v3.1.4; leave it empty) and do not whitelist `RuntimeClass`. If the fallback path is used, set it and whitelist it.
- **NIM Operator v3.1.4** (current as of 2026-11-18): same hand-applied pattern, version pinned, whitelist enumerated from the chart.
- Success signal: node shows `nvidia.com/gpu: 1` allocatable; a one-off `nvidia-smi` pod succeeds.

## 7. NIMCache, NIMService, Pod Security, NetworkPolicy

### 7.1 Go/no-go on the profile (before any download)

Pre-session, from the support matrix: the 8B NIM lists A100 40/80 GB; generic vLLM profiles have readable names
(for example `vllm-bf16-tp1-pp1`). Record the **expected profile** and the **pinned tag and digest**.

**At session time, right after the node is Ready and the GPU Operator is healthy:** run the NIM container's `list-model-profiles`
(one-shot Job, or `docker`/`ctr` on the host if the image provides it; `UNVERIFIED:` which is available) against the actual A100 and compare with the
pre-session choice. **No matching profile means abort before the NIMCache downloads any weights.** This costs a minimal image pull
and a few minutes, and bounds the worst case.

### 7.2 NIMCache

Field names confirmed against v3.1.4 (`nimcache_types.go`), values are placeholders.

```yaml
apiVersion: apps.nvidia.com/v1alpha1
kind: NIMCache
metadata:
  name: llama-8b
  annotations: {argocd.argoproj.io/sync-wave: "0", argocd.argoproj.io/sync-options: "Prune=false,Delete=false"}
spec:
  source:
    ngc:
      modelPuller: nvcr.io/nim/meta/llama-3.1-8b-instruct@sha256:<DIGEST pinned in plan>   # tag resolved at session time
      pullSecret: ngc-pull
      authSecret: ngc-api-key
      model:
        profiles: ["<PROFILE-ID from section 7.1, pinned>"]
  storage:
    pvc: {create: true, storageClass: local-path, size: 60Gi, volumeAccessMode: ReadWriteOnce}
  tolerations: []          # single node, no GPU taint
  resources: {cpu: "2", memory: 8Gi}
  userID: 1000
  groupID: 2000
```

- **Storage:** `local-path` PVC on the single node. Weights are re-downloadable catalogue content; the PV dies with the VM, which is the intent.
  Budget 20 to 40 minutes for the download (doc 29), included in the timeline. Whether the NIMCache job requests a GPU by default is
  `UNVERIFIED:` (fact-check section 6); with one GPU and one job at a time this should not conflict, but confirm it releases the GPU before the NIMService starts.
- **Profile pinning** exists in two places: cache `model.profiles` and service `storage.nimCache.profile`. They must carry the same ID.
- `Prune=false,Delete=false` stays (it rehearses the production safeguard); teardown does not rely on Argo to delete it, because the VM is terminated.
- **CRD validation in CI (plan item):** vendor the **v3.1.4 NIMCache and NIMService CRDs** into `tests/fixtures/crds/` and validate the
  `lab/gpu/nim` overlays against them (kubeconform or equivalent) so field-name mistakes are caught before any paid hour.

### 7.3 NIMService

```yaml
apiVersion: apps.nvidia.com/v1alpha1
kind: NIMService
metadata: {name: llama-8b, annotations: {argocd.argoproj.io/sync-wave: "1"}}
spec:
  image:
    repository: nvcr.io/nim/meta/llama-3.1-8b-instruct
    tag: "<same pinned tag as the cache>"
    pullPolicy: IfNotPresent
    pullSecrets: [ngc-pull]
  authSecret: ngc-api-key            # optional per the types; test warm-cache start without it
  storage:
    nimCache: {name: llama-8b, profile: "<same PROFILE-ID>"}
    readOnly: true
    sharedMemorySizeLimit: 8Gi       # UNVERIFIED value
  labels: {app.kubernetes.io/component: nim-llm}
  resources: {requests: {cpu: "4", memory: 24Gi, nvidia.com/gpu: 1}, limits: {memory: 24Gi, nvidia.com/gpu: 1}}
  # runtimeClassName: intentionally unset (NRI path has no 'nvidia' RuntimeClass)
  replicas: 1
  userID: 1000
  groupID: 2000
  startupProbe:
    enabled: true
    probe:
      httpGet: {path: /v1/health/ready, port: api}
      initialDelaySeconds: 60
      periodSeconds: 10
      timeoutSeconds: 5
      failureThreshold: 120
  expose: {service: {type: ClusterIP, port: 8000}}
```

- **Record the real cold-start-to-Ready time** (from empty cache and, if time allows, after a pod restart with a warm cache): the key number this lab produces.
- Tool calling for this NIM may need a flag or parser setting (`UNVERIFIED:` name); the smoke `tools` check is the test.
- Single replica: the operator template uses `maxSurge: 0`, so any spec change that restarts the pod is a short outage. Treat spec edits as windows.
- With only a GPU Operator ClusterPolicy and no taint, the NIM pod and NIMCache job must be able to schedule on the same node; the GPU is exclusive to one at a time.

### 7.4 Pod Security (decided)

| Namespace | Enforce | Warn/audit | Reason |
|---|---|---|---|
| `gpu-operator` | `privileged` | n/a | operator operands need host access |
| `raglab-gpu` (NIMCache jobs, NIMService) | `baseline` | `restricted` | operator-rendered pods and NIMCache jobs have no seccomp profile in v3.1.4 manifests, so `restricted` fails; this is a decided finding, not a trial |
| `raglab-dev-gpu` (Bifrost) | `restricted` | n/a | unchanged from Phase A |

### 7.5 NetworkPolicy

- In `raglab-gpu`: default-deny ingress; allow TCP 8000 to `nim-llm` pods **only** from Bifrost pods in `raglab-dev-gpu`
  (namespaceSelector on `kubernetes.io/metadata.name` plus podSelector). Egress for the NIM: DNS only, plus 443 to **public** addresses
  (RFC1918, link-local, CGNAT excluded) if the NIM or the NIMCache job needs NGC. The NIMCache job pods do not carry `nim-llm`; get their labels from the live cluster (`UNVERIFIED:`).
- **Bifrost side:** Phase A's base egress allows only DNS and public 443 and **excludes RFC1918**, so Bifrost cannot reach a cluster-internal NIM. The `dev-gpu` overlay adds an
  **egress rule to the `raglab-gpu` namespace (`nim-llm`, TCP 8000)**. Because this lives in the `dev-gpu` overlay, the Phase A base is not changed.
- **Probes (must run):** positive: a Bifrost pod gets HTTP 200 from `/v1/health/ready`. Negative: a throwaway `restricted` pod in `raglab-dev-gpu` without the Bifrost label times out; a pod in another namespace times out.
  Verify enforcement on this k3s (`UNVERIFIED:` embedded policy controller behaviour), do not assume it.

## 8. Secrets and credentials

### 8.1 What exists on the VM, and what does not

| Credential | On the VM? | Notes |
|---|---|---|
| Lambda API key | **Never** | Rent and terminate from the Mac console/CLI only |
| Phase A lab age key | **Never** | Stays on the Mac |
| Session age key (private) | Yes, as the CMP's key | Decrypts only `lab/gpu/secrets/gpu.sops.yaml` |
| NGC key and pull secret | Yes, as Kubernetes Secrets | Residual below |
| Session hosted `nvapi-` key | Yes, as a Kubernetes Secret, `dev-gpu` only | Section 8.3 |
| Any home credential, kubeconfig, VPN auth | **Never** | Negative probe in section 11 |
| Owner's personal SSH key | Not needed | Use a session-only keypair; no agent forwarding |

### 8.2 Session age key and the secrets file

- Generate the **session age key on the Mac** for this session. Add its **public** key to `.sops.yaml` as a **second creation rule for `lab/gpu/secrets/` only**
  (placed before the existing rule). The Phase A rule and key are untouched.
- `gpu.sops.yaml` is encrypted **only** to the session key. After teardown the private key is deleted, which makes the committed ciphertext permanently undecryptable;
  the `.sops.yaml` rule is removed by the revert PR.
- The session private key is delivered to the VM at bootstrap via stdin (not argv, not committed), and read by the CMP only.
- The structural check (every leaf `ENC[...]`) and gitleaks must pass before commit. Editing uses `sops` with the session key only.

### 8.3 NGC key (D8) and building the secrets without printing them

- Create a **new** NGC key. Pre-session: confirm in the console that the "Private Registry" scope **does not allow push**, choose pull-only scopes if available,
  and confirm the NGC organisation is personal (not an employer's). Expiry **3 days**; revoked at teardown, not just left to expire.
- Build `ngc-api-key` (`NGC_API_KEY`) and `ngc-pull` (`kubernetes.io/dockerconfigjson`, user `$oauthtoken`) **without printing the key**:
  a small Python script reads the key from a mode-600 file (never argv, never an environment variable, never echoed), computes the `auth`
  field itself, writes the Secret manifest to **stdout**, and pipes that into `sops` encrypt (reading stdin, writing the encrypted file). The plaintext exists only in the pipe.
  The key file is deleted after use. Shell history must not contain any key.
- **Accepted residual:** the key sits on a provider-owned VM; the provider's root can read it while it exists, and the pods' tmpfs/environment expose it. Mitigations: new key,
  pull scope, 3-day expiry, revocation at teardown, no reuse, non-root pods. Public git keeps only ciphertext that nobody can decrypt after the session key is deleted.

### 8.4 The hosted key: the minimal-exposure option (D9)

Options considered for `dev-gpu`'s "before" provider:

1. **No hosted provider on the VM at all.** Minimal exposure, but there is nothing to roll back to: the "cutover" would be from nothing to the NIM, and the rollback
   rehearsal could only prove failure detection, not a passing hosted-path smoke. This loses the cutover pattern the phase exists to teach.
2. **Reuse the Phase A hosted key.** Rejected: it is the key for the home lab; a leak on a provider-owned VM would force breaking Phase A.
3. **A separate, short-lived hosted key used only by `dev-gpu`.** Chosen. The blast radius of a trial-tier hosted key is quota and abuse of one account for one session
   (`UNVERIFIED:` that the hosted trial has no billing exposure, check terms). It is created fresh for the session, held only in `gpu.sops.yaml`, **revoked at teardown**, and
   the model smoke is limited to the few calls needed.

Reduced variant if the owner prefers zero hosted exposure: run the cutover as option 1 and record that the rollback rehearsal was reduced to failure detection plus restart.
This is an open question (section 14), default = option 3.

## 9. Bifrost change (dev-gpu only)

- **Catalogue:** new provider `nim-local` (custom OpenAI-compatible, `base_url` = the in-cluster NIMService URL on port 8000; **confirm the Service name** from the live cluster,
  `UNVERIFIED:`); key `value` a non-secret placeholder (`UNVERIFIED:` Bifrost accepts a literal non-empty value and a plain-HTTP base URL for a custom provider).
  New model alias `chat/small` with `[chat, stream, tools]`, upstream name = the NIM's served model name.
- **Per-env `serving` map:** `dev-gpu: chat/small: nvidia-hosted | nim-local`. The Phase A envs have no `chat/small` serving change, so they are unaffected.
  Hosted baseline for `chat/small` needs a hosted model: use `meta/llama-3.1-8b-instruct` hosted if the authenticated model list shows it (`UNVERIFIED:`),
  else a stand-in (the PR text must then say the cutover is not like-for-like).
- **`generate.py` change:** providers become a map; each env's `config.json` includes only providers it references; each env's `models.json` ids are `<provider>/<alias>`, so smoke follows the catalogue.
  Virtual-key **`allowed_models`** and **`key_ids`** are regenerated for `dev-gpu` to include the new ids.
- **Client-visible model id changes at cutover:** `nvidia-hosted/chat/small` becomes `nim-local/chat/small` (Bifrost routes on `<provider>/<model>`). Accepted in this lab.
- **Egress NetworkPolicy** to the NIM namespace is part of the `dev-gpu` overlay (section 7.5).
- **Argo `selfHeal` is on:** any failure injection (stop the NIM, break a provider) must go **through git**, not `kubectl patch`.
- **Smoke checks expected to pass after cutover** (existing suite, driven by `models.json`): list models, chat, stream, tools, auth-negative (Bifrost body), limit-429
  (`[200, 200, 429]` with the gateway marker). Plus: `routing_info` shows provider `nim-local`; a direct NIM check via port-forward (`/v1/health/ready` and a chat call);
  the hosted path still passes before cutover and after rollback.

### 9.1 Cutover and rollback (rehearsed once, repeated as teardown step zero)

1. Before: `dev-gpu` serves `chat/small` from `nvidia-hosted`; smoke passes (baseline saved).
2. Cutover PR: `serving` to `nim-local`; Argo syncs, ConfigMap hash rolls the pod; smoke passes with `routing_info` = `nim-local`.
3. Failure injection (via PR): NIMService `replicas: 0`; smoke on `nim-local/chat/small` **fails** with a gateway upstream error (proves the gate detects a dead backend).
4. Rollback PR: `serving` back to `nvidia-hosted`; smoke passes; the NIMCache PVC is kept.
5. Roll forward (`replicas: 1`, cutover PR) and smoke again, if time remains before the T+4:15 limit.

The rented cluster tracks `main`. (Open question: use a dedicated session branch to keep session PR churn off `main`, section 14.)

## 10. Session plan, time box and cost control

### 10.1 Preparation before renting (no GPU hour is spent finding things out)

- **Resolved and recorded:** the NIM tag and digest, the expected profile ID, the GPU Operator and NIM Operator chart versions (and that `targetRevision` v26.7.3 resolves),
  the k3s release and its bundled containerd version (must support NRI per D6), the Lambda image's driver and toolkit state if knowable, rendered-manifest hashes.
- **PRs ready and CI-green** (held, not merged): catalogue/generator change, `lab/gpu/...` tree, `.sops.yaml` rule, CRD fixtures; the cutover, failure-injection and rollback PRs as drafts.
- **Secrets prepared:** session age key generated, NGC key and session hosted key created, `gpu.sops.yaml` encrypted and checked, key files deleted.
- **Provider:** account funded and a billing alert set if the console has one (`UNVERIFIED:`), SSH session keypair uploaded, firewall rule for the owner's current address ready.
- **Alarms in the calendar** (they are the only guard, since no provider-side cap is known): T+3:00 checkpoint, T+4:15 teardown start, T+4:45 and T+5:00 hard stop.

### 10.2 Timeline

| Time | Step | Gate |
|---|---|---|
| T+0:00 | Rent the VM (record instance id); apply firewall; SSH in | `nvidia-smi` passes; only SSH reachable from outside |
| T+0:10 | Bootstrap (playbooks with GPU variables): k3s, Argo CD, session age key | node Ready; Argo healthy |
| T+0:35 | Hand-apply namespaces, `raglab-gpu-platform`, GPU Operator, NIM Operator | `nvidia.com/gpu: 1`; `nvidia-smi` pod passes |
| T+0:50 | **Go/no-go:** `list-model-profiles` on the real A100 (section 7.1) | **no matching profile: abort before NIMCache** |
| T+0:55 | Secrets via CMP; apply NIMCache (pinned profile) | cache job running |
| T+1:30 to 2:15 | Weights download | NIMCache Ready |
| T+2:15 | NIMService `replicas: 1`; record cold start | NIMService Ready |
| **T+3:00** | **ABORT CHECKPOINT: if NIMService is not Ready, tear down.** Do not extend | |
| T+3:00 | NetworkPolicy probes; Bifrost `dev-gpu` baseline; cutover; smoke | smoke green on the SHA |
| T+3:40 | Failure injection; rollback; smoke; roll forward (if time) | rollback smoke passes |
| **T+4:15** | **Teardown begins regardless of state** | |
| T+4:30 | VM terminated | provider shows nothing |
| T+5:00 | Hard stop; everything else is after billing | |

If the checkpoint is hit, a second session may be scheduled with the findings; the first is not extended.

### 10.3 Cost controls (honest limits)

- Rate about USD 1.99/h, per-minute billing; 5 h is about 10; the cap is USD 15, reached at about 7.5 h.
- **There is no known provider-side hard cap** (`UNVERIFIED:` whether Lambda offers a spend limit or auto-terminate). Controls are procedural: the preparation in 10.1, calendar alarms, termination as the first teardown step.
- OS shutdown does not necessarily stop billing; **terminate** does. Do not rely on a laptop timer.
- No persistent filesystems, volumes, snapshots or reserved addresses are created; the console must show none at the end. (Filesystems bill until deleted.)
- Next-day bill check reconciles hours x rate.

## 11. Teardown (in this order; evidence for each)

**Termination comes first so billing stops before any tidy-up. Repo reverts happen after billing has stopped.**

| # | Step | Evidence |
|---|---|---|
| 1 | **Terminate the Lambda instance**, then verify in the console (and CLI) **zero running instances and zero filesystems**. Remove the instance-specific firewall rule if it persists | console/CLI listing |
| 2 | **Revoke the NGC key** and the **session hosted key** (revoke, not just expire); confirm each now fails (negative probe from a script reading the key from a file) | 401 responses |
| 3 | **Delete the session age key file** (and the session SSH keypair); remove known_hosts and SSH config entries; no key in shell history | files gone |
| 4 | **Revert PRs for shared files** (`.sops.yaml` rule, catalogue/generator, CI/gitleaks changes as decided); delete or archive `lab/gpu/secrets/gpu.sops.yaml` (now undecryptable) | merged PRs; `git diff` |
| 5 | **Next-day bill check**; console still shows nothing running | bill vs hours x rate |

Plus, before step 1: save evidence (cold-start time, smoke JSON with the SHA, redacted `kubectl get nimcache,nimservice -o yaml`) off the VM, because nothing on it survives.
After step 4: Phase A regression (all Phase A apps Synced and Healthy in the home lab; the home lab was never changed, so any drift is not caused by this session).

## 12. Success criteria (testable)

1. **NIM Ready on the A100 with a pinned profile:** the NIMService is Ready, the profile ID in cache and service are identical and match the go/no-go result, zero restarts; **NIMCache Ready**.
2. **Smoke via dev-gpu Bifrost passes against the in-cluster NIM:** chat, stream, tools, auth-negative, limit-429 (gateway marker) on the exact SHA; `routing_info` shows `nim-local`.
3. **Rollback passes:** the injected NIM outage makes smoke fail; the revert PR restores a passing smoke on the previous (hosted) provider; the NIMCache survived.
4. **Cold-start time recorded** (empty cache to Ready; warm restart if time allows).
5. **Total spend at or under the cap (USD 15)**, reconciled with the next-day bill.
6. **No home credentials or network reachable from the VM:** negative probe from the VM: no VPN client or tunnel interface present, no kubeconfig or credentials for any home cluster,
   no Phase A age key (the CMP key's public recipient matches only the session key), and the only secrets present are the three listed in section 8.1. There is no route to home, so the probe confirms the absence of credentials and VPN rather than testing reachability.
7. **External exposure:** from outside, only SSH from the owner's address answers; nothing else.
8. **Isolation of Phase A:** home lab Argo never syncs a GPU app; `generate.py --check` shows the Phase A envs unchanged; Phase A apps remain Synced/Healthy.
9. **NetworkPolicy:** Bifrost reaches the NIM (200 on `/v1/health/ready`); a non-Bifrost pod and a pod in another namespace cannot.
10. **Teardown:** every step in section 11 ticked with evidence; provider shows no instance or filesystem; NGC and session hosted keys fail negative probes.
11. **Hygiene:** `git log -p` and `git grep` show no NGC or `nvapi-` value, no address or network detail of the home environment; gitleaks passes.
12. **Learning output:** a short findings note (like `raglab-phase-a-findings.md`) records timings, surprises and each `UNVERIFIED:` item resolved.

**Stretch (only if all of the above is met before T+3:40):** NIMCache from a **mirrored source** (air-gap rehearsal): mirror the image to an in-cluster registry and serve weights from
a local store (the NIMCache source types other than NGC, and how the NIM validates profile and licence offline, are `UNVERIFIED:`). Not required for success.

## 13. Alternatives considered and rejected or deferred

- **Join the rented VM to the lab cluster over the tailnet (rev 1): rejected** because of the two blockers found in review: (1) a hostile or compromised rented node sits on the lab's pod network
  and can reach internal services regardless of NetworkPolicy; (2) tailnet access control errors can expose the home network. Both disappear with the standalone design.
- **Register the rented cluster as a remote cluster in the lab's Argo CD: deferred.** It would put a credential for the rented cluster inside the home lab and a path from the home lab to it; not needed to meet the goals. Revisit only with a clear need and a threat model.
- **k3s built-in VPN integration, WireGuard backends, public API exposure:** not applicable once there is no link; public exposure rejected.
- **Brev, RunPod, hyperscaler L40S:** not chosen; Lambda is the owner's decision. (RunPod pods are containers; Brev hourly price unknown.)
- **H100 or Nemotron-class model:** not needed; the 8B NIM runs on one A100 40GB.

## 14. Open questions and remaining UNVERIFIED items

Resolved by the fact-check (2026-11-25) and not open: Lambda is a VM with drivers and per-minute billing and terminate ends billing; the 8B NIM lists A100;
GPU Operator `v26.7.3` is current and has the NRI path; NIM Operator v3.1.4 field names (`runtimeClassName`, `tolerations`, `nodeSelector`, `authSecret` optional, PVC storage).

Open before renting (resolve from primary sources and record):

1. Lambda: root/sudo for the default user; availability of A100 40GB at the time; firewall rule model, defaults and persistence; any spend limit, billing alert or auto-terminate; boot disk size on this SKU; whether Docker/the NVIDIA toolkit are preinstalled.
2. NIM image: the current tag at session time (2.1.7 vs 2.1.6) and its digest; actual profile IDs on A100 40GB; tool-calling enable flag; whether a free Developer Program account can pull it (needs a logged-in pull); minimum VRAM and cache size for the 8B.
3. GPU Operator 26.7.3: `targetRevision` string resolves; default of `cdi.nriPluginEnabled`; whether `toolkit.enabled=false` works on the Lambda image; which k3s release bundles containerd 1.7.30 or newer and exposes NRI as required; which Helm hooks the chart renders; complete cluster-scoped kind list; the exact `config-v3.toml.tmpl` form for the fallback.
4. NIM Operator v3.1.4: NIMCache job GPU request default; job pod labels; Service name; whether any field exposes `securityContext` (assumed no).
5. NGC: key scope names; whether pull-only scoping is possible and "Private Registry" excludes push; whether the NGC organisation is personal; revocation behaviour.
6. Hosted baseline: whether `meta/llama-3.1-8b-instruct` is callable on the hosted API with the owner's key; whether a trial-tier key has any billing exposure.
7. Bifrost: plain-HTTP `base_url` and a literal placeholder key for a custom provider; whether a provider-neutral model id is possible so cutover does not change the client string.
8. Argo `selfHeal` with `ignoreDifferences` on the ClusterPolicy: confirm there is no sync loop with `ServerSideApply=true`.
9. NetworkPolicy enforcement by k3s's embedded controller (same-node case) must be probed.
10. Owner choices still to confirm: **hosted key option** (default option 3, section 8.4); session branch vs tracking `main` (section 9.1); whether the home address is stable for the session (a changed address locks the owner out, and re-opening the firewall needs the provider console, not the VM).
