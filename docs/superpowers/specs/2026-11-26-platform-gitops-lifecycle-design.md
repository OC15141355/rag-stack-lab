# Platform GitOps reference: an NVIDIA AI platform and service lifecycle

Date: 2026-11-26 · Status: rev 1 (pre-review) · Research: `docs/research/2026-11-26-lifecycle-gitops-research.md`
Lab evidence: `docs/raglab-phase-a-findings.md`, `docs/raglab-phase-b-findings.md`

## 1. Problem and goal

The Project deploys models with hand-written manifests, from several fragmented branches, by a mix of Ansible and
manual steps. There is no canonical deployment branch, some deploys are half-applied, and secrets live in plaintext
`.env` files. Each model is its own one-off operation.

Goal: a **lifecycle**, not a per-model procedure. One repository structure in which:
- the **platform** (GPU Operator, NIM Operator, gateway, policies) is adopted, pinned, upgraded and retired as NVIDIA's
  product line moves (the NeMo Microservices sunset of 2026-10-01 is the motivating example); and
- **models as services** are proposed, cached, served, promoted DEV → QA → PROD, deprecated and retired by changing one
  catalogue entry, with the same automated checks every time.

Deliverables: (1) this design; (2) a working template, `reference/platform-gitops/`, that renders and validates in CI;
(3) an understanding doc for the owner; (4) a tidy of this repo (map, superseded docs marked, `08` corrected).

### Inputs (owner answers, 2026-11-26)
- Scope **C**: two lifecycles, as two layers (platform underneath services).
- **One small team** owns both layers (design so it can split later).
- Environments are probably **separate clusters** (DEV, QA, PROD); unconfirmed, so design for separate clusters.
- **Argo CD and Bifrost are planned but not deployed.** The structure must work before either exists.
- Restricted network: images and weights are mirrored in; some environments have no NGC access.

### Non-goals
Fine-tuning, evaluation and NeMo Helix (0.x, off the critical path); multi-team tenancy; choosing a promotion tool
(Kargo) now; the chat portal and Clio application code.

## 2. Principles

| # | Principle | Why (evidence) |
|---|---|---|
| P1 | **One `main` is the truth; environments are folders, never branches.** | Branch-per-env is the root cause of today's half-deploys; folder-per-env on main is the documented Argo practice (research §4). |
| P2 | **Desired state only changes through a merged PR.** No `kubectl edit`, no Ansible run that changes app state. | Argo self-heal reverts out-of-band edits (lab Phase B); manual changes are what made today's state unknowable. |
| P3 | **Two layers, two lifecycles, one repo.** Platform and services have different cadences and risks. | NVIDIA itself splits Infrastructure and Application branches (research §1). |
| P4 | **Pin and mirror everything.** Images by digest, charts by version from an internal OCI registry, weights pre-staged. | Air gap; a mutable tag is a silent change (lab: NIM 2.1.7 pinned by digest). |
| P5 | **The catalogue is the single source of what is offered.** Gateway config, NIM manifests and the model list are generated from it. | Lab Phase A/B: limits and the cutover propagated from one edit. |
| P6 | **Every gate is tested on its failure path.** | Eight review defects were checks that passed when broken; failure injection proved the smoke gate (lab Phase B). |
| P7 | **Controller-agnostic structure.** Every cluster folder deploys with `kubectl apply -k` before Argo exists. | Argo is not deployed yet; the structure must pay off on day one. |
| P8 | **Vendor lifecycle is an input, watched on a schedule.** | NeMo sunset found by accident; NVIDIA publishes EOL notices but no feed (research §1). |

## 3. Repository layout

```
platform-gitops/
├── README.md                    # how to read the repo; the lifecycle in one page
├── catalogue/
│   ├── models.yaml              # layer A: every service, its lifecycle state, owner, limits, support dates
│   ├── platform.yaml            # layer B: every platform component, pinned version per env, NVIDIA branch, support dates
│   └── schema/                  # JSON Schemas for both files (CI-enforced)
├── platform/                    # layer B building blocks (environment-neutral)
│   ├── crds/nim-operator/       # NIM Operator CRDs, applied separately and first (server-side)
│   ├── gpu-operator/            # Helm values (chart from the internal OCI registry)
│   ├── nim-operator/            # Helm values
│   ├── gateway/                 # Bifrost: Deployment, Service, NetworkPolicy (config is generated)
│   └── policies/                # namespaces, default-deny, quotas, Pod Security labels
├── services/                    # layer A building blocks (generated per model from the catalogue)
│   └── _generated/<model>/      # NIMCache + NIMService + NetworkPolicy; never edited by hand
├── clusters/                    # what each cluster runs; promotion = PR here
│   ├── dev/  qa/  prod/
│   │   ├── kustomization.yaml   # includes platform/ + services/ at this env's pinned versions
│   │   ├── values/              # env-only differences: sizes, storage classes, node selectors
│   │   └── gateway/             # generated Bifrost config.json + models.json for this env
├── argocd/                      # added in migration step 3; one Argo per cluster
│   ├── projects/                # AppProjects (default locked), hand-applied
│   └── apps/<env>/              # app-of-apps: crds → operators → caches → services → gateway
├── bootstrap/                   # the ONLY Ansible: cluster prerequisites, mirror credentials, install Argo
├── tools/
│   ├── generate.py              # catalogue → services/_generated + clusters/*/gateway (--check in CI)
│   ├── lifecycle_watch.py       # diffs NVIDIA EOL/release pages against catalogue support dates
│   └── smoke.py                 # promotion gate (chat, stream, tools, auth-negative, limit, real completion)
└── .gitlab-ci.yml               # render every cluster, schema-validate, generate --check, secret scan, smoke
```

Rules:
- `platform/` and `services/` hold no environment names. `clusters/<env>/` holds no logic: only references, pinned
  versions and differences.
- Anything under `_generated/` or `clusters/*/gateway/` is written by `generate.py`; CI fails if it differs from a
  fresh generation (`--check`).
- Image tags and digests appear only in `catalogue/`. Promotion therefore edits one file per environment.

## 4. Layer B: the platform lifecycle

Components and their version axis (one line each in `catalogue/platform.yaml`):

| Component | NVIDIA axis | Notes |
|---|---|---|
| GPU Operator (+ driver) | Infrastructure Branch (1 year; LTSB infra 3 years) | Bumps rename DCGM metrics (26.7.3): dashboards are part of the upgrade. |
| NIM Operator | Not on a public lifecycle page (ask NVIDIA) | CRDs upgraded explicitly by the `crds/` app, never by the Helm hook (needs the operator image pullable). |
| NIM images | Production Branch (9 months) for PROD; LTSB if offered; Feature Branch DEV-only | PB6 support ends January 2027: the first planned platform bump. |
| Gateway (Bifrost) | Upstream releases (not NVIDIA) | Pin `image.tag` + digest; file-only config (`source_of_truth: config.json`). |
| Policies, monitoring | Ours | |

States: `evaluating → adopted → deprecated → removed`. Each entry carries `version` per env, `nvidia_branch`,
`support_ends`, `replacement` (when deprecated) and `owner`.

Upgrade flow (same for every component): PR bumps DEV → platform smoke + service smoke on DEV → PR copies the pin to
QA → gate → PR to PROD in a change window. CRDs go first (separate app, server-side apply), operators second.

**Lifecycle watch** (P8): `tools/lifecycle_watch.py` runs on a schedule (CI), fetches NVIDIA's EOL Notices, EOL
Branches and release-notes pages, and opens an issue when (a) a page changes, or (b) any `support_ends` in either
catalogue is within 90 days. It reads only public pages and never changes the repo.

## 5. Layer A: the service lifecycle

States: `proposed → staged → dev → qa → prod → deprecated → retired`.

| State | What exists | Gate to leave it |
|---|---|---|
| proposed | catalogue entry only | owner, GPUs and profile known for each target env's hardware |
| staged | weights in the cache (NIMCache) in DEV | NIMCache Ready |
| dev / qa / prod | NIMService + gateway route in that env | smoke green on that env's SHA; QA uses PROD's hardware and profile |
| deprecated | still served; gateway lists it with `deprecated_after`; users told | date reached and replacement serving |
| retired | NIMService and route removed | cache deletion is a separate, explicit PR (weights are expensive to re-stage) |

Catalogue entry (abridged):
```yaml
- id: chat/glm                     # served name; preserved across moves
  owner: platform-team
  state: qa                        # how far it has been promoted
  nim: {kind: model-free, image: <registry>/nim/llm-nim@sha256:..., source: pvc}   # or model-specific
  weights: {pvc: glm-5-2-weights, size: 1536Gi}
  profiles: {dev: <id>, qa: <id>, prod: <id>}   # per hardware; qa == prod required
  gpus: 8
  limits: {context: 131072, max_output: 8192, rpm: {dev: 30, qa: 60, prod: 120}}
  capabilities: [chat, stream, tools]
  support_ends: null               # set from NVIDIA notices for model-specific NIMs
```

Default to the **model-free NIM**: NVIDIA names it as the replacement for the model-specific LLM NIMs whose support
ends in January 2027, and it turns a model change into a catalogue change, not a new image. Model-specific NIMs remain
allowed where a model has no model-free path. (UNVERIFIED: model-free NIM with custom weights from a pre-staged PVC in
an air gap is not documented on the pages fetched; to be proven in the next GPU session.)

## 6. Environments, promotion and Argo

- `clusters/<env>/` is the unit of deployment. Promotion = a PR that changes that env's pinned versions or a service's
  `state`, carrying the smoke evidence from the previous env. PROD requires an approval (protected branch rules /
  CODEOWNERS) and merge commits (squash breaks the evidence trail; lab Phase A).
- **One Argo CD per cluster**, each watching only `clusters/<env>` and `argocd/apps/<env>`. Reasons: air gap (no
  cross-cluster API access), blast radius (a DEV mistake cannot touch PROD), and the separate-cluster assumption.
- App-of-apps per cluster with sync waves: `crds` (wave −2, server-side) → `operators` (−1) → `caches` (0, prune and
  delete protected) → `services` (1) → `gateway` (2, PostSync smoke). Custom health checks for NIMCache, NIMService and
  ClusterPolicy in `argocd-cm`. AppProjects restrict each app to its namespaces; the `default` project is locked.
- ApplicationSets only for identical fan-out; sync waves across ApplicationSets are unreliable (research §4).
- Source Hydrator is Beta and cannot read OCI sources: not used. Kargo: optional later, not required.

## 7. Before Argo: the structure still deploys (P7)

Migration step 2 deploys `clusters/<env>` with a **protected GitLab CI job** from `main` only:
`kubectl apply --server-side -k clusters/<env>` with a scoped service account per cluster, after the render and
schema gates. No pruning (`kubectl` cannot prune safely without a controller): removals are explicit PR-reviewed
`kubectl delete` jobs. This is weaker than Argo (no drift correction), so a nightly CI job runs `kubectl diff -k` and
opens an issue on drift. Ansible shrinks to `bootstrap/`.

## 8. Secrets

No plaintext anywhere. SOPS + age (lab-proven: per-env recipients, a recipient check in CI, gitleaks with an `nvapi-`
rule because GitHub push protection misses NVIDIA keys). Argo decrypts through a CMP or KSOPS; the CI apply job
decrypts in the runner. If a vault arrives, External Secrets replaces SOPS without changing the layout.

## 9. Gates (CI and promotion)

| Gate | Where | Proves |
|---|---|---|
| render every `clusters/<env>` | CI, every PR | the folders build |
| schema validation against vendored CRDs (unknown fields rejected) | CI | no typo reaches a cluster |
| `generate.py --check` | CI | generated files match the catalogue |
| catalogue rules (qa profile == prod profile; digests not tags; state ordering) | CI | promotion invariants |
| secret scan (gitleaks + SOPS recipient rule) | pre-commit + CI | no plaintext key |
| smoke (chat, stream, tools, auth-negative, limit-429, real completion) | after each env deploy | the service works through the gateway |
| failure-path tests for each gate | CI | the gates fail when they should |

## 10. Defaults baked in from the lab (all hit live)

Cache mounted read-write (NIM 2.1.7 refuses read-only) · NetworkPolicy admits the gateway **and** the NIM Operator to
the NIM port · Bifrost `allow_private_network: true` for in-cluster providers only · tool calling via
`NIM_PASSTHROUGH_ARGS="--enable-auto-tool-choice --tool-call-parser <parser>"` · Bifrost virtual keys with explicit
`key_ids` · content logging off · no container `args` for Bifrost · a gateway `/v1/models` is not a health check ·
quote comma-containing args · profile names carry a version suffix · resolve revert conflicts by regenerating.

## 11. Migration from today (each step useful alone, each reversible)

| Step | Outcome | Needs |
|---|---|---|
| 0. Inventory and freeze | What runs where, from which branch; NeMo layer frozen (already proposed) | read access |
| 1. Reconcile into the layout | One `main`; the running state captured as `clusters/<env>`; branches archived read-only | team agreement |
| 2. Deploy from `main` by CI | Protected apply job; drift report; Ansible reduced to `bootstrap/` | CI service accounts |
| 3. Argo CD per cluster | Same folders; Argo takes over apply and drift correction | Argo install |
| 4. Gateway and catalogue | Bifrost from `platform/gateway`; config generated; smoke gates | Bifrost |
| 5. Lifecycle automation | `lifecycle_watch` live; model-free NIM proven; PB successor planned | GPU time (DEV) |

## 12. Template acceptance (what `reference/platform-gitops/` must prove in CI)

1. `kubectl kustomize clusters/{dev,qa,prod}` renders; all NIM objects validate against the vendored v3.1.4 CRDs.
2. `generate.py --check` passes; a catalogue edit changes only the expected generated files (tested).
3. Catalogue rules reject: a tag without digest; `qa` profile ≠ `prod` profile; a `prod` service with no `qa` history
   state; a deprecated entry with no `replacement`.
4. `lifecycle_watch.py` is tested against saved fixture pages (no network in CI): a changed page and a date within 90
   days both produce an issue body; nothing else does.
5. Each check has a failure-path test.
6. No environment name inside `platform/` or `services/`; no image tag outside `catalogue/` (tested).

## 13. Open questions (for the team / NVIDIA)

1. Cluster layout and number of Argo instances (assumed: one cluster and one Argo per env).
2. NIM Operator support branch and window (not public).
3. Successor to PB6 (EOL January 2027): name and date.
4. Model-free NIM from a pre-staged PVC with custom weights, air-gapped (UNVERIFIED; GPU session).
5. Whether QA hardware matches PROD (needed for the qa == prod profile rule).
