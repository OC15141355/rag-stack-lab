# platform-gitops: a template for an NVIDIA AI platform and its model services

A repository skeleton for running GPU models as services through DEV, QA and PROD from **one `main` branch**.
Environments are folders, not branches. Every change is a merged PR, and the PR diff shows exactly what will
deploy. The design and its reasoning are in rag-stack-lab's
`docs/superpowers/specs/2026-11-26-platform-gitops-lifecycle-design.md`. This page covers how to use the template.

Everything here is an **EXAMPLE**. The registry (`registry.internal.example`), every digest, profile ID, weights hash,
CIDR, date and age recipient is a placeholder that shows the shape. The two vendored chart archives are real.

## Layout

```
catalogue/services.yaml   layer A: each model/service, one block per env (image, profile, GPUs, weights, rpm)
catalogue/platform.yaml   layer B: environments + each platform component, version per env, owner, support end
catalogue/evidence/       smoke passes: which (image digest, profile, weights revision) passed in which env
catalogue/schema/         JSON Schemas for the three file types above
platform/charts/          vendored chart archives + SHA256SUMS (rendering never touches the network)
platform/values/<c>/      base.yaml + <env>.yaml per chart (no image refs: those come from the catalogue)
platform/manifests/       namespaces + Pod Security, default-deny, GPU quota, Retain StorageClass, gateway sources
services/templates/       NIMCache, NIMService, NetworkPolicy, weights PVC + verify Job, speech Deployment, smoke Jobs
clusters/<env>/           GENERATED and committed. Never edit by hand. 00-crds, 10-platform, 20-weights, 30-services, 40-gateway
secrets/<env>/            SOPS files, one age recipient per env (.sops.yaml)
argocd/                   one Argo CD per cluster: projects, app-of-apps, weights app, health checks (migration step 4)
bootstrap/README.md       what Ansible still does (and nothing else)
tools/render.py           THE generator: catalogue + templates + charts -> clusters/
tools/checks.py           every CI gate (python3 tools/checks.py --list)
tools/drift.py            nightly orphan / hand-applied object report
tools/smoke.py            the gateway smoke (copy of rag-stack-lab lab/smoke/smoke.py)
tools/verify_weights.py   checks a weights PVC against the catalogue's manifest hash
tools/lifecycle-checklist.md   the monthly human check of NVIDIA's EOL notices
CODEOWNERS, .gitlab-ci.yml     approvals and the CI (a translation of the GitHub CI that proves this template)
```

`python3 tools/render.py` regenerates `clusters/`. It needs Python with PyYAML and the helm version pinned in
`catalogue/platform.yaml`. `python3 tools/render.py --check` and `python3 tools/checks.py` are the gates. CI fails
when `clusters/` does not match a fresh render.

## The lifecycle in one paragraph

A service is in an environment when that environment's block says `enabled: true`. Deprecated and retired are
flags on the service. No other state exists. Every change is a PR that edits the catalogue (or a template),
re-runs `tools/render.py` and commits the result. The rendered diff under `clusters/<env>/` is what deploys, and
CODEOWNERS sends `clusters/prod/` to a PROD approver. A PR whose render changes more than one environment fails
unless it has the `multi-env` label. A PR that removes a NIMCache or weights PVC fails unless it has the
`delete-weights` label. DEV deploys automatically after a merge. QA and PROD deploy by a manual job, or a manual
Argo sync inside a sync window. After each deploy the smoke Job runs (chat, stream, tools, auth-negative,
limit-429). Its report names the render hash. It becomes the evidence that lets the same triple go to the next
environment.

## How to promote (DEV to QA, QA to PROD)

1. Deploy to the source environment and get a passing smoke. The `services:<env>` job keeps the report as an artifact.
2. Add a record to `catalogue/evidence/<source env>/` with the image digest, `profile_id`, weights revision, the
   render hash from the report (`revision=` line) and the pass counts.
3. In `catalogue/services.yaml`, copy the service's `envs.<source>` block to `envs.<target>`. Keep the target's own
   `rpm` if it differs.
4. Run `python3 tools/render.py` and commit. The diff should touch only `clusters/<target>/`.
5. Open the PR. CI's evidence check rejects a QA block without a DEV pass, and a PROD block without a QA pass, for
   that exact triple. A PROD approver reviews the `clusters/prod/` diff.
6. After the merge, run the manual `weights:<target>` job, then `services:<target>` (or sync in Argo inside the
   window). Weights go first: the NIMService will not start until its weights are verified.

Platform components promote the same way. Copy the component's `envs.<source>` block in `catalogue/platform.yaml`.

## How to add a model

1. Mirror the NIM image into the internal registry. Record its **digest**.
2. On the target hardware, run `list-model-profiles` with that image and record the **64-hex profile ID**. Do not
   use the versioned name.
3. Transfer the weights into the internal mirror under a new revision and produce `MANIFEST.sha256`. Record its
   sha256 as `manifest_sha256`.
4. Add a service to `catalogue/services.yaml` with only `envs.dev` enabled. Fill in `served_model`,
   `tool_parser` (if it has `tools`), `limits`, a measured `cold_start_seconds`, and the `weights` block with a new
   PVC name (`<model>-<revision>`).
5. Render, commit and open the PR. After the merge, `weights:dev` creates the PVC. Fill it (bootstrap/) and the verify
   Job marks it checked. `services:dev` then starts the NIMService, adds the model to the gateway and smokes it.
6. Promote it as above.

A non-LLM service (speech) uses `kind: deployment` with `ports` and `health_path`. It gets a plain Deployment,
Service, NetworkPolicy and a health smoke, and passes the same evidence rule.

## How to upgrade a platform component

1. Vendor the new chart archive: run `helm pull <chart> --repo <repo> --version <v>` once on a connected host, copy
   it to `platform/charts/`, and add its sha256 to `SHA256SUMS`. Mirror the new images and record their digests.
2. In `catalogue/platform.yaml`, change **only `envs.dev`** (version and images). If the operator ships CRDs, bump
   the `-crds` entry in the same PR or an earlier one, because CRDs apply first.
3. Read the release notes into `notes`, for example renamed DCGM metrics (dashboards move with the upgrade) or a
   driver change (a planned outage per node).
4. Render, commit and open the PR. The diff shows `clusters/dev/00-crds` and `10-platform` only. After the merge,
   run `platform:dev` (manual, two-person). Then re-run the DEV service smoke.
5. Promote to QA, then PROD, in separate PRs inside the sync window.

## How to retire a model

1. Set `deprecated: {after: <date>, replacement: <service id>}`. CI requires a real, non-retired replacement. Move
   clients, which the gateway logs can show.
2. Disable the service env by env (`enabled: false`), PROD last, one PR per environment. CI blocks each removal of
   its NIMCache and weights PVC until the PR has the `delete-weights` label. Deleted PVCs keep their volumes
   (Retain) until someone releases them on purpose.
3. When no block is enabled, set `retired: true`. The nightly drift job must show no ORPHAN for it. An orphan
   would be a NIMService still holding GPUs.

## Gates (all offline; `python3 tools/checks.py --list`)

The gates cover: render-check, chart checksums, catalogue schema, CRD schema (unknown fields rejected), gateway
schema, digests only, 64-hex profile IDs, evidence, complete weights, deprecated needs a replacement, retired
means disabled, no revision annotations in pod templates, image references only in `catalogue/` and `clusters/`, a
writable NIM cache, non-empty `key_ids`, no NGC credentials in air-gapped envs, NIM ingress from the gateway and
the operator, air-gapped egress only to internal ranges, weights storage (no operator-created PVC, Retain, never
pruned), scope placement plus the managed-by label, the Secret-hash annotation, SOPS recipients, one environment
per PR, the weights delete guard, and the support-end **warning**. Every gate has a failing fixture in
rag-stack-lab's `tests/reference/fixtures/`.

## Break-glass

During an incident, a named person may pause one Argo app (or skip the CI job), change the live object and record
what they did. Within one working day they open a PR that makes git match, or they revert the live change. The
nightly drift job reports apps still paused and objects still different. If an Argo operation is stuck, terminate
it before syncing the fix.

## Known limits of the template

- Only the GPU Operator v26.7.3 and NIM Operator 3.1.4 charts are vendored. Argo CD, cert-manager, KSOPS, storage,
  registry, runners and monitoring are tracked in the catalogue (`kind: external`) but installed by `bootstrap/`.
- Core Kubernetes kinds are not schema-validated offline (no vendored Kubernetes schemas). NIM and GPU Operator
  CRs and the Bifrost config are.
- UNVERIFIED, prove in DEV first: the NIMCache caching Job on a pre-staged PVC in an air gap, and the NIMService
  init container seeing the cache volume. The init container fails closed: if it cannot see the volume, the model
  does not start.
- The `ClusterPolicy` still names upstream images for operands this template disables. Re-point any operand you
  enable through `image_values`.
