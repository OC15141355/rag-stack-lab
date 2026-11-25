# Platform GitOps reference: an NVIDIA AI platform and service lifecycle

Date: 2026-11-26 · Status: **rev 2** (after reviewer + devil's advocate; triage in §15)
Research: `docs/research/2026-11-26-lifecycle-gitops-research.md` (fact-checked: branch lengths, PB6 and model-NIM
end of support January 2027, Source Hydrator Beta all CONFIRMED against primary pages)
Lab evidence: `docs/raglab-phase-a-findings.md`, `docs/raglab-phase-b-findings.md`

## 1. Problem and goal

The Project deploys models with hand-written manifests from several fragmented branches, by a mix of Ansible and manual
steps. There is no canonical deployment branch, some deploys are half-applied, and secrets live in plaintext `.env`
files. Each model is a one-off operation.

Goal: a **lifecycle**, not a per-model procedure, in one repository:
- the **platform** (GPU Operator, NIM Operator, gateway, Argo CD, policies, storage) is adopted, pinned, upgraded and
  retired as NVIDIA's product line moves (the NeMo Microservices sunset of 2026-10-01 is the motivating example);
- **models as services** move through DEV → QA → PROD and are deprecated and retired by editing one catalogue entry,
  with the same automated checks every time.

Deliverables: (1) this design; (2) a template, `reference/platform-gitops/`, proven in CI; (3) an understanding doc for
the owner; (4) a tidy of this repo.

Inputs (owner, 2026-11-26): two layers (platform under services); **one small team**; probably **separate clusters**
per environment (unconfirmed); **Argo CD and Bifrost planned, not deployed**; restricted network, no NGC in some envs.

Non-goals: fine-tuning, evaluation, NeMo Helix (0.x); multi-team tenancy; a promotion tool (Kargo); application code.

## 2. Principles

| # | Principle | Evidence |
|---|---|---|
| P1 | **One `main`; environments are folders, never branches.** | Branch-per-env caused today's half-deploys; folder-per-env is the documented Argo practice (research §4). |
| P2 | **Desired state changes only through a merged PR, with one written break-glass exception (§9).** | Argo self-heal reverts out-of-band edits (Phase B); incidents still need a fast path. |
| P3 | **Two layers, one repo.** | NVIDIA splits Infrastructure and Application branches (research §1). |
| P4 | **Pin, mirror and verify every artifact: images, charts and weights.** | Air gap; mutable tags are silent changes; weights are the largest supply-chain item. |
| P5 | **One catalogue is the source of what runs where, per environment.** | Phase A/B: limits and cutover propagated from one edit. |
| P6 | **What deploys is what was reviewed.** Each environment's final manifests are generated and committed; the PR diff *is* the change. | Argo Source Hydrator is Beta and cannot use OCI (confirmed), so render in CI ourselves. |
| P7 | **Every gate is tested on its failure path.** | Eight lab review defects were checks that passed when broken. |
| P8 | **Adopt in order of payoff.** Each migration step is useful alone; the heavy parts wait until they pay. | A small team must not drown in ceremony (DA I12). |

## 3. Repository layout

```
platform-gitops/
├── catalogue/
│   ├── services.yaml        # layer A: every model/service, per-environment block (§5)
│   ├── platform.yaml        # layer B: every platform component, per-environment version (§4)
│   └── evidence/            # promotion evidence: which (image, profile, weights) passed which env's smoke
├── platform/                # layer B sources, environment-neutral
│   ├── charts/              # VENDORED chart archives (.tgz) + checksums; CI renders offline
│   ├── values/<component>/  # base.yaml + <env>.yaml
│   └── manifests/           # namespaces, default-deny, quotas, Pod Security, gateway Deployment
├── services/templates/      # templates for NIMCache, NIMService, weights PVC + verify Job, NetworkPolicy, speech Deployment
├── clusters/<env>/          # GENERATED, committed, never hand-edited; one folder per cluster
│   ├── 00-crds/             # applied first, server-side
│   ├── 10-platform/         # rendered charts + manifests (cluster-scoped objects live here only)
│   ├── 20-weights/          # weights PVCs (Retain) + verify Jobs; own Argo app, outside the wave chain
│   ├── 30-services/         # NIMCache, NIMService, NetworkPolicy per service (namespace-scoped)
│   └── 40-gateway/          # Bifrost config.json + models.json + smoke Job
├── argocd/                  # migration step 4: one Argo per cluster; projects + per-env apps (hand-applied)
├── bootstrap/               # the ONLY Ansible: node prerequisites, registry trust, install Argo
├── tools/                   # render.py (the single generator), checks, smoke.py, lifecycle checklist
├── CODEOWNERS               # catalogue/, platform/, services/, tools/, clusters/prod → PROD approvers
└── .gitlab-ci.yml           # GitLab translation of the CI proven in this repo's GitHub Actions (§12)
```

Rules (all CI-enforced):
- `clusters/` is output. CI regenerates it with `tools/render.py` and fails on any difference (`--check`).
- Image references, chart versions and weight revisions appear only in `catalogue/` and in generated `clusters/`.
- A PR whose regenerated output changes more than one environment fails unless it carries the `multi-env` label and
  PROD approval. This is the isolation that folders alone do not give (a shared template change shows up in all three
  environments' diffs, and is gated accordingly).
- No revision or commit annotations in pod templates: an unrelated merge must not roll PROD pods (Phase A behaviour).

## 4. Layer B: the platform lifecycle

`catalogue/platform.yaml`, one entry per component, version **per environment**:

```yaml
- id: gpu-operator
  owner: platform-team
  nvidia_branch: infrastructure      # infrastructure | production | ltsb | feature | none
  support_ends: 2027-07-01           # from NVIDIA notices; null = unknown (CI warning + named owner + review date)
  envs:
    dev:  {chart: gpu-operator, version: v26.7.3}
    qa:   {chart: gpu-operator, version: v26.7.3}
    prod: {chart: gpu-operator, version: v25.10.0}
  notes: "bumps rename DCGM metrics (26.7.3): dashboards are part of the upgrade; driver bumps evict GPU pods"
```

Components in scope: GPU Operator, NIM Operator (+ its CRDs as a separate entry), Argo CD, cert-manager (operator
webhooks), LeaderWorkerSet (multi-node), the gateway, the SOPS/KSOPS plugin, RWX storage provisioner, internal
registry, CI runners, monitoring. Each has `nvidia_branch`, `support_ends`, `owner`.

Upgrade: PR bumps DEV's version → render → DEV platform + service smoke → PR to QA → PR to PROD inside a sync window.
CRDs first (their own folder and app, server-side apply), then the operator. GPU Operator driver changes are planned
outages for that node's models.

**Lifecycle check** (P8, monthly, human-owned): a checklist in `tools/lifecycle-checklist.md` that walks NVIDIA's EOL
Notices, EOL Branches and release notes and updates `support_ends`. An optional helper script extracts dates from
those pages on a connected host and **fails loudly** if it finds none; it is not a gate and never writes to the repo.
CI warns on any `support_ends` within 90 days (already true for the PB6 entries: the first real warning).

Known now: PB6 and the model-specific Llama/Nemotron LLM NIMs reach end of support January 2027; NVIDIA offers the
model-free NIM or another supported model-specific NIM as replacements. The NIM Operator's support window is not on
a public page (ask NVIDIA).

## 5. Layer A: the service lifecycle

`catalogue/services.yaml`, per-environment blocks so one model can be in PROD on version N while N+1 goes through DEV:

```yaml
- id: chat/glm                       # served name, preserved across moves
  owner: platform-team
  kind: nim-llm                      # nim-llm | deployment (e.g. speech: own ports, own smoke)
  capabilities: [chat, stream, tools]
  tool_parser: <parser>              # per model; feeds NIM_PASSTHROUGH_ARGS
  limits: {context: 131072, max_output: 8192}
  envs:
    dev:
      enabled: true
      image: <registry>/nim/<image>@sha256:...
      profile_id: <64-hex id>        # the ID, not the versioned name
      gpus: 8
      weights: {source_uri: <internal mirror path>, revision: r2026-11, manifest_sha256: <sha>, pvc: glm-r2026-11, size: 1536Gi}
      rpm: 30
    qa:   {...}
    prod: {...}
  deprecated: {after: null, replacement: null}
  retired: false
```

- **Lifecycle state is derived**, not typed: a service is "in" an environment when that block is `enabled`; deprecated
  and retired are flags. No separate state machine to maintain.
- **Default: model-specific NIMs, pinned** (what runs today). The model-free NIM is a layer-B entry in state
  `evaluating`, adopted per model only after an air-gapped proof on that model's hardware (UNVERIFIED today; next
  GPU session). Given the January 2027 end of support, that proof is scheduled before migration step 4.
- **Weights are versioned artifacts.** Each revision gets its own PVC (`pvc.create: false` in the NIMCache, separately
  managed PVC with `persistentVolumeReclaimPolicy: Retain`), filled by a tracked transfer into each environment and
  checked by a verify Job against `manifest_sha256` before the service may start. A revert changes the pointer back to
  a PVC that still exists; nothing overwrites weights. No NGC/HF credentials in air-gapped environments.

## 6. Promotion

- A promotion PR copies a service's (or component's) block from the previous environment, for example
  `envs.qa` → `envs.prod`.
- **Evidence rule:** the smoke Job writes a report naming `(image digest, profile_id, weights revision)` and the hash
  of that environment's rendered `30-services` + `40-gateway`. The promotion PR adds it to `catalogue/evidence/`. CI
  rejects a PROD block whose triple has no QA pass recorded, and a QA block with no DEV pass. (This replaces the rev-1
  "qa profile == prod profile" rule, which would have blocked every profile change.)
- The PR's own regenerated `clusters/prod/` diff is the exact PROD change, reviewed by a PROD approver (CODEOWNERS).
- If the GitLab tier cannot enforce approvals (CE), PROD apply/sync is a protected manual job runnable only by named
  users (open question).

## 7. Deploying: before Argo, and with Argo

**Before Argo (migration step 3):** protected CI jobs on main only, per environment:
- `services` job: applies `30-services` and `40-gateway` as a **namespace-scoped** service account (no RBAC verbs),
  automatic after DEV, manual for QA/PROD.
- `platform` job: applies `00-crds` then `10-platform` (cluster-scoped), **manual, two-person**, short-lived
  credentials. Ordered passes with `kubectl wait` between them (CRDs established before CRs; never one mixed apply).
- Plain rendered YAML is applied (`kubectl apply --server-side -f`), because `kubectl apply -k` cannot render Helm.
  Helm hooks are not run: anything a hook did (CRD upgrades) is an explicit rendered step.
- Each environment has its own protected runner and its own age key; merge-request pipelines never run on QA/PROD
  runners.
- Deletes are explicit PR-reviewed jobs; CI rejects any delete touching NIMCache, PVCs or `20-weights` unless the PR
  carries the `delete-weights` label and PROD approval.
- Drift: every applied object carries a `managed-by: platform-gitops` label; a nightly job lists labelled objects not
  in the rendered set (orphans, e.g. a retired NIMService still holding 8 GPUs) and unlabelled objects in managed
  namespaces, and runs `kubectl diff --server-side` on the rendered set. Tested against a known-orphan fixture.

**With Argo (migration step 4):** one Argo per cluster (air gap, blast radius), each watching only `clusters/<env>`.
- Apps: `crds` → `platform` → `services` → `gateway` (waves on Applications, with Argo's Application health check
  enabled); `weights` is its own app outside the chain, so a 1.5 TB transfer never blocks an urgent gateway fix.
- DEV auto-sync; QA and PROD **manual sync inside sync windows**. PROD PostSync smoke has `retry.limit: 0`.
- Custom health: NIMCache, NIMService (scaled-to-zero counts as Healthy, as in Phase A), ClusterPolicy.
- AppProjects per layer; `default` project locked; the NIM Operator is managed from the platform project only
  (its ClusterRole can read all Secrets: Phase A).
- Handover per environment: disable that env's CI apply jobs → first Argo sync with `ServerSideApply=true`,
  `prune: false` → review the diff → enable sync. Stale Helm release Secrets removed deliberately (no `helm uninstall`).

## 8. Secrets

- No plaintext anywhere. SOPS + age, one recipient per environment (lab-proven: recipient check in CI; gitleaks with an
  `nvapi-` rule because GitHub push protection misses NVIDIA keys).
- Argo decrypts via KSOPS/CMP; CI decrypts only on that environment's runner.
- Bifrost secrets by `existingSecret`/env references; the generator stamps a hash of each referenced Secret on the pod
  template, because Secret changes via `envFrom` do not restart pods (Phase A).
- A vault later replaces SOPS via External Secrets without changing the layout.

## 9. Break-glass (P2's one exception)

During an incident a named person may: pause sync on one app (or skip the CI job), change the live object, and record
it. Within one working day they open a reconciling PR that makes git match, or revert the live change. The nightly
drift job reports any app still paused and any object still differing. Includes the stale-operation recovery from
Phase B (terminate the old operation before syncing the fix).

## 10. Gates

| Gate | Where |
|---|---|
| `render.py --check` (generated = committed); golden-output tests reviewed with the generator | CI |
| schema validation of every rendered object against vendored CRDs/JSON Schemas (unknown fields rejected) | CI |
| catalogue rules: digests only; profile IDs (64-hex); evidence rule; weights fields complete; deprecated needs replacement | CI |
| one-environment-per-PR rule; no pod-template revision annotations; no image refs outside catalogue/clusters | CI |
| known-bad defaults rejected: read-only NIM cache, empty Bifrost `key_ids`, `authSecret` in air-gapped envs, missing operator→NIM NetworkPolicy rule | CI |
| secret scan (gitleaks + SOPS recipient rule) | pre-commit + CI |
| smoke: chat, stream, tools, auth-negative, limit-429 (message marker), a real completion | after each deploy |
| a failure-path fixture for every CI check (meta-test fails if a check has none) | CI |

Schema validity is not runtime validity (read-only cache and empty `key_ids` are both schema-valid): hence the
known-bad-defaults gate and the live smoke.

## 11. Defaults from the lab (all hit live)

Cache mounted read-write · NetworkPolicy admits the gateway **and** the NIM Operator (accepted risk: the operator can
call the model) · in-cluster egress must allow the internal registry/mirror ranges (the lab's "public 443 only" policy
would block an air gap) · Bifrost `allow_private_network: true` for in-cluster providers only · tool calling via
`NIM_PASSTHROUGH_ARGS` with the per-model `tool_parser` · Bifrost `key_ids` explicit, content logging off, no container
`args`, file-based config, every governance section always emitted (an absent section does not prune) · `/v1/models`
is not a health check · quote comma-containing args · compare profile IDs, not names · resolve revert conflicts by
regenerating · smoke deadline sized from the model's measured cold start (900 s fails a 750B model).
These defaults were proven on a model-specific 8B NIM; each is re-checked when a model-free or larger NIM is adopted.

## 12. Migration from today (adopt in order of payoff)

| Step | Outcome | Done when |
|---|---|---|
| 0. Inventory and freeze | what runs where, from which branch; NeMo layer frozen | written inventory per env |
| 0.5 Rotate | every credential ever in a `.env` or branch rotated; full-history gitleaks scan; archived branches treated as compromised | old credentials fail a live probe |
| 1. One main | the running state captured as **top-level desired objects only** (NIMCache, NIMService, `helm get values`), secrets straight into SOPS | `kubectl diff --server-side` of the render is empty and the orphan list is empty, per env |
| 2. Catalogue-lite | services/platform catalogue + render for what exists; gates in CI | `render --check` green |
| 3. Deploy from main by CI | §7 jobs; Ansible reduced to `bootstrap/` | a DEV change ships with no manual step |
| 4. Argo per cluster | §7 handover | CI apply disabled for that env |
| 5. Gateway | Bifrost from the catalogue; smoke gates; evidence rule active | QA→PROD promotion with evidence |
| 6. Lifecycle | monthly checklist live; model-free proof; PB-successor bump | first deprecation handled through the catalogue |

## 13. Template acceptance (`reference/platform-gitops/`, run in this repo's CI)

1. `tools/render.py` renders `clusters/{dev,qa,prod}` offline from the catalogue, templates and vendored charts;
   `--check` passes; golden tests cover a version bump in one env changing only that env.
2. Every rendered object validates against vendored schemas (NIM Operator v3.1.4 CRDs at minimum).
3. Each rule in §10 rejects its failure fixture and accepts the good tree (meta-test: no check without a fixture).
4. The evidence rule: a PROD block without a recorded QA pass is rejected; with one, accepted.
5. The orphan/drift lister finds a planted orphan in a fixture inventory and nothing in a clean one.
6. A speech service (`kind: deployment`) renders and passes the same gates.
7. The GitLab CI file is linted structurally (YAML, job names, protected/manual rules present); it is a translation
   and states so.

## 14. Open questions

1. Cluster layout and Argo instances per environment (assumed one each).
2. GitLab tier (CE cannot enforce approvals) and whether PROD reads from a mirror (then: signed commits verified by
   Argo, mirror provenance recorded).
3. NIM Operator support branch; PB6 successor name and date.
4. Model-free NIM from a pre-staged PVC, air-gapped, for each model (UNVERIFIED).
5. QA hardware equal to PROD; 750B cold-start time (sizes smoke deadlines and outage windows).
6. Age-key custody and rotation for three environment keys (still open in the lab).

## 15. Review triage (rev 1 → rev 2)

Reviewer (Sonnet, fact-check + consistency) and devil's advocate (Opus), independent contexts.
Must-land, all adopted above: per-env catalogue (DA C1, reviewer C1/I1); generated per-env output + multi-env gate +
CODEOWNERS on shared paths (DA C2, reviewer C1/C2); rotation step (DA C3); split and scoped CI apply, per-env runners
and keys (DA C4); offline Helm via vendored charts and rendered YAML, ordered passes, weights deletion guard (DA C5,
reviewer §3); versioned, verified weights (DA C6); model-specific default, model-free gated (DA C7, reviewer C4);
evidence rule (DA I1/I2, reviewer I3); no revision annotations, manual PROD sync, sync windows (DA I2/I3, reviewer C3);
weights app outside the chain, PROD smoke retry 0 (DA I4, reviewer I4); break-glass (DA I5); orphan detection (DA I6);
migration acceptance + Argo handover (DA I7/I8); lifecycle watch demoted to a checklist (DA I9, reviewer I7); one
generator, golden tests (DA I10); speech + missing platform entries (DA I11); payoff-ordered adoption, derived states
(DA I12); air-gap egress, operator RBAC (reviewer I5); NIM images moved to layer A (reviewer I6); Secret-hash
annotation, no authSecret in air gap, profile IDs (DA M1-M3).
Backlog (open questions §14): GitLab tier (DA I13), mirror signing (DA I14), key custody (DA M6).
Phantoms: none; every checked claim reproduced (no `--enable-helm` on `kubectl apply`; two generators in this repo;
`authSecret` in lab manifests; revision annotation reaches the pod template).
