# 9. Target architecture: review of the proposed description

> **[MACRO: Page Properties]** Status DRAFT · Owner <author> · Last updated <date>

**Purpose:** check a proposed target-architecture description against the reference design and against what was
proven live in the lab, and give a corrected version.
Reference design: `docs/superpowers/specs/2026-11-26-platform-gitops-lifecycle-design.md`; template
`reference/platform-gitops/`; lab evidence: Phase A and Phase B findings.

## The proposal, in short

Control plane (git, catalogue, CI gates, Argo CD) separated from data plane (ingress, gateway, model runtime,
storage). Git holds `catalogue/models.yaml`, `overlays/{dev,qa,prod}/` (Helm values or Kustomize patches overriding
image digests, replicas, GPUs), `operators/` (GPU Operator v25.10.0, NIM Operator v3.1.4+) and a generated `bifrost/`
config. GitLab CI on every MR validates the catalogue, renders, runs smoke tests against the target environment and
blocks on failure; Argo CD syncs after merge. Argo manages NIMService/NIMCache, Bifrost config and Traefik Hub routes,
**not** the operators (Ansible bootstraps them).

## Verdict

**Aligned in shape.** The control/data plane split, git as the single source of truth, a catalogue generating the
gateway config, MR gates and Argo syncing NIM resources all match the reference design. **Five points need changing**;
the first two would cause real failures.

| # | Point | Problem | Change |
|---|---|---|---|
| 1 | Smoke tests on every MR against the target env | The change is not deployed until merge, so an MR-time smoke tests the **old** version | MR gates: schema, render, policy checks, plus "this exact artefact has a recorded smoke pass in the previous environment". Smoke runs **after** deploy and records that evidence. |
| 2 | Digests in the catalogue **and** in overlays | Two sources of truth: they drift | The catalogue holds per-environment values (digest, profile, GPUs, weights revision); per-env manifests are generated. Overlays only for things that never vary per model, or generated too. |
| 3 | Operators outside Argo (Ansible) | The platform lifecycle (what the NeMo sunset hit) sits outside GitOps: no drift detection, no DEV → QA → PROD path; NIM Operator CRD upgrades need an explicit step (the Helm hook needs the operator image) | Acceptable as a first step if operator versions are pinned in the same repo (`catalogue/platform.yaml`) and promoted by MR the same way. State who renders and applies `operators/`. |
| 4 | "NIM Operator v3.1.4+" | `+` is unpinned, contradicting the rest | Pin exactly. |
| 5 | Missing pieces | — | Secrets (Argo syncs Bifrost Secrets → SOPS or a vault, never plaintext); NetworkPolicies; weights (pre-staged, versioned, checksum-verified volumes); NVIDIA support dates in the catalogue; one Argo CD per cluster; catalogue fields for profile ID, GPUs, weights revision, tool parser. |

Minor: "on merge, Argo CD **deletes** the change" should read **detects**.

## Where the lab findings land in this architecture

> **[MACRO: Info panel]** Each was hit live on a rented A100 (2026-11-26) with NIM 2.1.7, NIM Operator 3.1.4 and
> Bifrost v2.6. Risks L8–L14 on page 5.

| Finding | Where it must appear |
|---|---|
| A read-only weights volume stops the NIM starting | NIMService manifests: cache mounted read-write; protect weights with separate volumes and a Retain policy instead |
| Deny-all NetworkPolicy blocks the NIM Operator's readiness check (NIMService NotReady forever) | NetworkPolicies (not in the proposal): admit the gateway **and** the NIM Operator to the NIM port |
| Bifrost refuses private-IP upstreams by default | Generated `bifrost/` config: `allow_private_network` on in-cluster providers only |
| Tool calling off; documented env vars ineffective; `NIM_PASSTHROUGH_ARGS` works | Catalogue field `tool_parser` (with `tools` in capabilities) feeding `NIM_PASSTHROUGH_ARGS` on the NIMService |
| The gateway model list answers with the model down | Smoke gate makes a real completion (and runs after deploy: point 1) |
| Hosted model retired overnight; hosted latency depends on caller location | Support dates in the catalogue, checked monthly; measure any hosted fallback from where it runs |
| A `git revert` can conflict in generated config | CI check that generated `bifrost/` and manifests equal a fresh render; rule: regenerate, never hand-merge |

## Corrected description

> The target architecture separates the **control plane** (git, catalogue, CI gates, Argo CD) from the **data plane**
> (ingress, gateway, model runtime, storage). Promotion is a declarative git operation; serving is a direct path:
> client → Traefik → Bifrost → NIM, with the gateway as the only intermediary.
>
> **Git repository** (one `main`, folders per environment, no environment branches):
> - `catalogue/models.yaml`: per model and **per environment**: image digest, profile ID, GPUs, weights revision and
>   checksum, limits, capabilities, tool parser, owner, support end date.
> - `catalogue/platform.yaml`: pinned GPU Operator, NIM Operator (exact, e.g. 3.1.4), Bifrost and Traefik versions per
>   environment, with NVIDIA support dates.
> - `clusters/{dev,qa,prod}/`: generated from the catalogue, never hand-edited: NIMCache/NIMService, NetworkPolicies,
>   Bifrost config.
> - `secrets/{env}/`: SOPS-encrypted, one key per environment.
>
> **CI (GitLab):** on every MR, validate the catalogue, render all environments and check the committed output matches,
> run policy checks, and require a recorded smoke pass in the previous environment for anything promoted. After
> deploy, smoke tests (real completions) run in that environment and record evidence.
>
> **Argo CD:** one per cluster; syncs namespace-scoped resources (NIM resources, policies, gateway config). Operators
> are bootstrapped by Ansible from versions pinned in `catalogue/platform.yaml` and promoted DEV → QA → PROD by MR the
> same way.
