# platform-gitops: a template for an NVIDIA AI platform and its model services

A repository skeleton for running GPU models as services through DEV, QA and PROD from **one `main` branch**.
Environments are folders, not branches. Every change is a merged PR, and the PR diff shows exactly what will
deploy. The design and its reasoning are in rag-stack-lab's
`docs/superpowers/specs/2026-11-26-platform-gitops-lifecycle-design.md`. This page covers how to use the template.

It suits a typical starting point: models deployed by hand from several branches, some deploys half-applied, and
credentials kept in local files. Migration steps are in the design, section 12.

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
services/templates/       NIMCache, NIMService, NetworkPolicy, weights PVC, verify Job, speech Deployment, smoke Jobs
clusters/<env>/           GENERATED and committed, never edited by hand:
                            00-crds  10-platform  20-weights (+ 20-weights/verify/)  30-services  40-gateway
secrets/<env>/            SOPS files, one age recipient per env (.sops.yaml), + a kustomization.yaml index
argocd/                   one Argo CD per cluster: projects, app-of-apps, weights apps, health checks, SOPS plugin
bootstrap/README.md       what Ansible still does (and nothing else)
tools/render.py           THE generator: catalogue + templates + charts -> clusters/
tools/checks.py           every CI gate (python3 tools/checks.py --list)
tools/drift.py            nightly orphan / hand-applied object report
tools/prune.py            what a merge removed, for the explicit delete job
tools/wait_jobs.py        waits for Jobs, failing fast on the first failure
tools/smoke.py            the gateway smoke (copy of rag-stack-lab lab/smoke/smoke.py)
tools/verify_weights.py   checks a weights PVC against the catalogue's manifest hash
tools/lifecycle-checklist.md   the monthly human check of NVIDIA's EOL notices
tests/                    the template's own tests: every gate against a good and a bad fixture
CODEOWNERS, .gitlab-ci.yml     approvals and the CI (a translation of the GitHub CI that proves this template)
```

## Running the tools

You need Python 3.10+ with PyYAML and jsonschema (`pip install pyyaml jsonschema pytest`) and the helm version
pinned in `catalogue/platform.yaml` (`tools.helm`).

```
python3 tools/render.py            # regenerate clusters/
python3 tools/render.py --check    # CI: fail if clusters/ differs from a fresh render
python3 tools/checks.py            # CI: every gate (FAIL blocks, WARN does not); --list names them
python3 tools/checks.py --base <target-branch tree> --labels multi-env   # the PR gates
python3 -m pytest -q               # the template's own tests (REQUIRE_HELM=1 makes a missing helm fail, not skip)
```

The helm pin is an exact version, not a minor version. Different helm builds render different bytes (labels,
capability defaults), and `--check` compares bytes. To bump helm, change `tools.helm`, re-render, and review the diff
like any other change.

## The lifecycle in one paragraph

A service is in an environment when that environment's block says `enabled: true`. Deprecated and retired are
flags on the service. No other state exists. Every env block is written out in full, with no YAML anchors, so an
edit to one env can never move another. Every change is a PR that edits the catalogue (or a template), re-runs
`tools/render.py` and commits the result. The rendered diff under `clusters/<env>/` is what deploys, and CODEOWNERS
sends `clusters/prod/` to a PROD approver. A PR whose render changes more than one environment fails unless it has
the `multi-env` label. A PR that removes a NIMCache or weights PVC fails unless it has the `delete-weights` label.
DEV deploys automatically after a merge. QA and PROD deploy by manual jobs, or by manual Argo syncs inside a sync
window. After each deploy the smoke Job runs (chat, stream, tools, auth-negative, limit-429). Its result becomes the
evidence that lets the same triple go to the next environment.

## How a Secret reaches the cluster

1. Create or change a Secret with `sops -e`. `.sops.yaml` encrypts `secrets/<env>/` to that environment's age
   recipient only. Add the file to `secrets/<env>/kustomization.yaml` (CI checks the index lists exactly the files).
2. **CI path** (`services:<env>`): that env's protected runner holds that env's age key (`SOPS_AGE_KEY_<ENV>`). It runs
   `sops --decrypt <file> | kubectl apply --server-side -f -` for each file, before 30-services and 40-gateway.
   Plaintext goes only through the pipe, never to disk or the log. A decrypt failure fails the job (`pipefail`).
3. **Argo path**: the `<env>-secrets` app reads `secrets/<env>` through the `sops-kustomize` Config Management Plugin
   (`argocd/config/cmp-plugin.yaml`, the shape proven in rag-stack-lab's lab). The plugin admits only that app and
   that path, decrypts with that cluster's key, and fails closed.
4. Pods that take a Secret through `envFrom` carry `platform-gitops/secret-hash.<name>`, the sha256 of the SOPS file,
   so a changed Secret rolls the pod. Without it, an `envFrom` change does not restart pods.

## How to promote (DEV to QA, QA to PROD)

1. Deploy to the source environment and get a passing smoke. The `services:<env>` job keeps the report as an artifact.
2. Add a record to `catalogue/evidence/<source env>/` with these fields:
   - the image digest, `profile_id` and weights revision;
   - `service_hash` (`python3 tools/render.py --service-hash <source env> <service>`);
   - `render_hash` (the report's `revision=` line);
   - the pass counts. `result: pass` needs `failed: 0` and `passed > 0`.
3. In `catalogue/services.yaml`, write the service's `envs.<target>` block out as a full copy of `envs.<source>`.
   Do not use YAML aliases. Keep the target's own `rpm` if it differs.
4. Run `python3 tools/render.py` and commit. The diff should touch only `clusters/<target>/`.
5. Open the PR. CI enforces three things:
   - a QA block needs a DEV pass, and a PROD block needs a QA pass, for that exact triple (`evidence`);
   - the source env's record carries the service hash that the current templates render for the promoted block
     (`evidence-fresh`). If a template changed since the smoke, re-smoke the source env.
   - A PROD approver reviews the `clusters/prod/` diff.
6. After the merge, run the target's manual jobs in stage order (see below).

Platform components promote the same way. Copy the component's `envs.<source>` block in `catalogue/platform.yaml`.

## Deploy order

**CI (migration step 3).** The jobs run in stage order. Platform and verify jobs appear only when their folder
changed. They are manual and block the pipeline until run, so the services job can never run before them.

`platform:<env>` (CRDs, then wait for them to be established, then 10-platform) -> `weights:<env>` (creates the
PVCs) -> **the transfer** (bootstrap/) -> `verify:<env>` (runs the verify Jobs, fails fast) -> `services:<env>`
(Secrets, then 30-services, then 40-gateway, then the smoke) -> `prune:<env>` (explicit deletes, manual).

**Argo (migration step 4).** In DEV the root app and its children are automated, and waves order them: crds 0 ->
platform 1 -> secrets 2 -> services 3 -> gateway 4. In QA and PROD the root and every child are **manual** and carry
**no waves**, so syncing the root only creates the child Application objects and never waits on them. Sync the
children by hand, inside the window, in this order:
`crds -> platform -> secrets -> weights -> (transfer) -> weights-verify -> services -> gateway`.
UNVERIFIED on a live Argo CD: that a manual root with wave-less manual children never blocks. Prove it in QA first.

## How to add a model

1. Mirror the NIM image into the internal registry. Record its **digest**.
2. On the target hardware, run `list-model-profiles` with that image and record the **64-hex profile ID**. Do not
   use the versioned name.
3. Put the weights in the internal mirror under a new revision with a `MANIFEST.sha256`, and record the manifest's
   sha256 as `manifest_sha256`.
4. Add the service to `catalogue/services.yaml` with only `envs.dev` enabled. Fill in `served_model`,
   `tool_parser` (if it has `tools`), `limits`, a measured `cold_start_seconds`, and the `weights` block with a new
   PVC name (`<model>-<revision>`).
5. Render, commit, PR, merge. The weights go in a fixed order, and each step must finish before the next:
   1. **PVC**: `weights:dev` (or the `dev-weights` app) creates it.
   2. **Transfer**: the tracked copy from the mirror into the PVC (bootstrap/).
   3. **Verify**: `verify:dev` (or a manual sync of `dev-weights-verify`) checks every file against the manifest. It
      rejects files the manifest does not list, then writes the marker.
   4. **Service**: `services:dev` starts the NIMService. Its init container refuses to start without the marker.
      The job then adds the model to the gateway and smokes it.
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
2. Disable the service env by env (`enabled: false`), PROD last, one PR per environment. `kubectl apply` never
   deletes, so after each merge:
   - **CI**: run the manual `prune:<env>` job. It deletes what the merge removed from 30-services and 40-gateway
     (`tools/prune.py`, previous commit vs this one) and keeps the delete list as an artifact.
   - **Argo**: DEV prunes automatically. In QA and PROD, prune is a manual, reviewed sync (tick Prune) of the
     `services` and `gateway` apps.
3. Weights go last, on purpose:
   - The PR that drops the NIMCache and PVC needs the `delete-weights` label.
   - The CI prune job deletes them only when the person running it sets `DELETE_WEIGHTS=true`.
   - Deleted PVCs keep their volumes (Retain) until someone releases them on purpose.
   - Namespaces and CRDs are never pruned (`Prune=false,Delete=false`).
4. When no block is enabled, set `retired: true`. The nightly drift job must show no ORPHAN for it. An orphan
   would be a NIMService still holding GPUs.

## Gates (all offline; `python3 tools/checks.py --list`)

The gates cover:
- render-check, chart checksums, catalogue schema, and no YAML aliases;
- CRD schema (unknown fields rejected) and gateway schema;
- digests only, 64-hex profile IDs, evidence (valid passes only), and complete weights;
- deprecated needs a replacement, and retired means disabled;
- no revision annotations in pod templates, and image references (including dotless and bare names) only in
  `catalogue/` and `clusters/`;
- a writable NIM cache, non-empty `key_ids`, no NGC credentials in air-gapped envs, and NIM ingress from the gateway
  and the operator;
- air-gapped egress: only internal ranges or named in-cluster namespaces, never a rule without `to`;
- weights storage, the weights verify gate, and Namespaces/CRDs never pruned;
- scope placement plus the managed-by label, the envFrom Secret hash, and SOPS recipients plus the index;
- the PR gates: one environment per PR, the weights delete guard, and fresh evidence;
- the support-end **warning**.

Every gate has a failing fixture in `tests/fixtures/<gate>/`, and a meta-test fails if one is missing.

## Break-glass

During an incident, a named person may pause one Argo app (or skip the CI job), change the live object and record
what they did. Within one working day they open a PR that makes git match, or they revert the live change. The
nightly drift job shows objects that still differ (`kubectl diff`) and unlabelled or orphaned objects. It does
**not** report paused Argo apps (see Known limits), so check them by hand. If an Argo operation is stuck, terminate it
before syncing the fix.

## Approvals (CODEOWNERS)

`catalogue/`, `platform/`, `services/`, `tools/` and `clusters/prod/` need a PROD approver. That includes a
catalogue change that only touches a DEV block. CODEOWNERS works on paths, not on which YAML block changed, so the
rule is deliberately strict. The one-env-per-pr gate shows which environments a change actually renders into.

## Known limits of the template

- **Charts.** Only the GPU Operator v26.7.3 and NIM Operator 3.1.4 charts are vendored. Argo CD, cert-manager, the
  SOPS plugin, storage, registry, runners and monitoring are tracked in the catalogue (`kind: external`) but
  installed by `bootstrap/`.
- **Schemas.** Core Kubernetes kinds are not schema-validated offline (no vendored Kubernetes schemas). NIM and GPU
  Operator CRs and the Bifrost config are.
- **Paused Argo apps.** The drift job does not report them, because that needs the Argo API. Check by hand after
  break-glass.
- **render_hash.** In evidence records it is env-wide and comes from the smoke report. It ties a record to its report
  but cannot be recomputed later. `service_hash` is the value CI recomputes.
- **UNVERIFIED, prove in DEV first:**
  - the NIMCache caching Job on a pre-staged PVC in an air gap;
  - the NIMService init container seeing the cache volume (it fails closed: if it cannot see the volume, the model
    does not start);
  - manual Argo ordering with wave-less children.
- **GitLab CI.** The GitLab file is a structural translation and has not run on GitLab.
- **ClusterPolicy images.** The `ClusterPolicy` still names upstream images for operands this template disables.
  Re-point any operand you enable through `image_values`.
