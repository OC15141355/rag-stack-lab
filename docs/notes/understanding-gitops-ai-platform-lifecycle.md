# Understanding: running an NVIDIA AI platform as a lifecycle, with GitOps

For: me (the owner). Written 2026-11-26 after Phase A (home lab, hosted NIMs) and Phase B (rented A100, real NIM).
Design: [`docs/superpowers/specs/2026-11-26-platform-gitops-lifecycle-design.md`](../superpowers/specs/2026-11-26-platform-gitops-lifecycle-design.md) ·
Template: [`reference/platform-gitops/`](../../reference/platform-gitops/) · Research: [`docs/research/`](../research/2026-11-26-lifecycle-gitops-research.md)

This is the "why" behind the design, so I can explain and defend it, not just point at it.

---

## 1. What is actually wrong today

Today: model manifests written by hand, spread over branches that each hold part of a deploy, applied by Ansible
*or* by hand, with secrets in plaintext `.env` files.

The real problem is not "no Argo" or "Ansible is bad". It is that **nobody can answer "what is supposed to be running in
PROD right now?"** from one place. Every other symptom follows:

| Symptom | Root cause |
|---|---|
| Half deploys | A deploy is a sequence of human steps across branches; any step can be skipped. |
| Can't tell what's live | Desired state is spread over branches, Ansible vars and people's memories. |
| QA doesn't predict PROD | QA and PROD are built by different branches/steps, not the same artefact. |
| Fear of changing anything | No way to diff "what we want" against "what is". |
| Secrets risk | Plaintext `.env` in repos means every branch's history holds the credentials. |
| Each model is a project | There is no shared shape for "a model", so each one is hand-built. |

So the fix is: **one written description of the desired state, per environment, in one place, that machines apply and
check.** That is all GitOps means.

## 2. GitOps in one paragraph

You write down what you want (YAML in git). A controller (Argo CD, or before it a CI job) makes the cluster match it,
and keeps checking. You change the cluster only by changing git, through a reviewed merge. That gives you, for free:
an audit log (git history), review (merge requests), rollback (`git revert`), and drift detection (git vs cluster).

The two rules that matter most, and that the current repos break:
1. **One `main` branch is the truth. Environments are folders, not branches.** Branch-per-environment means every
   environment is a *different* history; they drift apart, merges between them get skipped, and "promote to PROD"
   becomes a risky merge instead of copying a known-good value. Folders on one branch keep all environments side by
   side, so the difference between QA and PROD is a visible diff.
2. **Nothing changes the cluster except a merge.** The moment someone `kubectl edit`s PROD, git stops being the truth.
   (There is one written exception, break-glass, for incidents: see §8.)

## 3. Why "lifecycle", and why two of them

The current approach treats each model as a deployment job. But things don't stand still:

- **Models change:** new versions, new profiles, new models, old ones retired. NVIDIA is already retiring model-specific
  NIMs (Llama 3.1 8B, 3.3 70B, Nemotron Super 49B, Nemotron 3 Nano: support ends January 2027). In Phase B the hosted
  Llama 3.1 8B vanished overnight (HTTP 410).
- **The platform changes:** NVIDIA's own products are moving under us. NeMo Microservices hit end of support on
  2026-10-01 (we caught that; nobody else had). The NIM Operator deprecated its NeMo CRDs. GPU Operator upgrades rename
  metrics. Production Branch 6 ends January 2027.

So there are two lifecycles with different speeds and risks, and the design keeps them as two layers:

| | Layer B: platform | Layer A: services (models) |
|---|---|---|
| What | GPU Operator, NIM Operator, gateway, Argo, cert-manager, storage, registry, policies | each model/service the users call |
| Changes | a few times a year, driven by NVIDIA's release/EOL cadence | often, driven by users and new models |
| Risk | cluster-wide (one bad operator upgrade hits everything) | per model |
| Lifecycle | evaluate → adopt → upgrade → deprecate → remove | enabled in DEV → QA → PROD → deprecated → retired |

NVIDIA itself splits it this way: an **Infrastructure Branch** for drivers and operators (1 year; 3 for LTSB) and
**Production / LTSB branches** for the application layer (9 months / 3 years). Feature branches (~1 month) are DEV-only.

## 4. The pieces, and why each exists

Read bottom-up; each layer needs the one below.

1. **GPU Operator** (platform). Makes GPUs usable by Kubernetes: driver, container toolkit, device plugin, monitoring.
   Lab: on the A100 the GPU worked in pods with no special runtime class.
2. **NIM Operator** (platform). Lets you describe a model with two objects instead of hand-writing Deployments:
   - **NIMCache:** "get these weights onto this storage". Phase B: 30 GB in 2.5 min from NGC; in an air gap it reads
     a pre-staged volume instead.
   - **NIMService:** "run the model from that cache on N GPUs". The operator writes the Deployment, Service and probes.
   This is why manual manifests are unnecessary: the operator already *is* the template.
3. **The NIM itself:** NVIDIA's container that serves the model (vLLM inside) with an OpenAI-compatible API.
   Model-specific NIMs bundle one model; the **model-free NIM** serves weights you point it at (NVIDIA's offered
   replacement for the retiring ones; not yet proven air-gapped, so the design treats it as "evaluating").
4. **Gateway (Bifrost)** (platform). The one front door: authentication (virtual keys), rate limits, routing, logging.
   Without it, any in-cluster client can call a model directly and nothing is metered.
5. **The catalogue** (`catalogue/services.yaml`, `catalogue/platform.yaml`). The single list of what runs where, per
   environment: image digest, profile, GPUs, weights revision, limits, owner, support dates. Everything else
   (NIMCache, NIMService, gateway config) is **generated** from it. This is the "model metadata" ticket done properly.
6. **The renderer** (`tools/render.py`). Turns the catalogue + templates + vendored Helm charts into the final YAML for
   each cluster, committed under `clusters/<env>/`. Why commit generated files: **the merge-request diff then shows
   exactly what changes in PROD**, and CI can check that what's committed is what the catalogue produces.
7. **Argo CD** (one per cluster). Applies `clusters/<env>/` and keeps the cluster matching it. Before Argo exists, a
   protected CI job does the applying from the same folders. The structure doesn't change when Argo arrives.
8. **SOPS + age.** Secrets are encrypted in git, one key per environment; only that environment can decrypt.
9. **Smoke tests.** After each deploy, real requests through the gateway: chat, streaming, tool calls, "unauthenticated
   is rejected", "rate limit triggers", and a real completion. These are the promotion gate.

## 5. How a change flows (the everyday loop)

**Promote a model version DEV → QA → PROD:**
1. MR edits `catalogue/services.yaml`: `envs.dev.image` = new digest (and profile, weights revision if they change).
2. CI renders all clusters. The diff shows only `clusters/dev/` changing (a rule enforces one environment per MR).
3. Merge → DEV deploys (auto) → smoke runs → its report records *(image, profile, weights)* passed DEV.
4. MR copies the `dev` block to `qa`, adding the DEV evidence. CI refuses a QA block without a DEV pass.
5. Merge → QA syncs (manual, in a window) → smoke → evidence.
6. MR copies `qa` to `prod`, with evidence; a PROD approver reviews the exact `clusters/prod/` diff; sync in a window.

**Roll back:** `git revert` the MR. Phase B proved this end to end. One catch from the lab: if a later change touched the
same generated files, the revert conflicts. Resolve by regenerating from the reverted catalogue, never by hand-merging.

**Upgrade a platform component:** same loop, on `catalogue/platform.yaml`. CRDs go first (their own folder and app),
then the operator.

**Retire a model:** set `deprecated.after` and `replacement`; users are told; after the date set `retired: true`.
The weights volume is deleted only by a separate, explicitly-labelled MR, because re-staging 1.5 TB is expensive.

## 6. Things that will bite (all found live, now built in as defaults)

| Gotcha | What happens | Default in the design |
|---|---|---|
| Read-only weights volume | NIM 2.1.7 refuses to start | mount read-write; protect with separate PVCs + Retain |
| Deny-all network policy | NIM Operator can't check readiness; model shows NotReady forever | allow the gateway **and** the operator |
| Bifrost and in-cluster models | Bifrost blocks private IPs by default (HTTP 502) | `allow_private_network` for in-cluster providers only |
| Tool calling | off by default; the documented env vars didn't reach the engine | `NIM_PASSTHROUGH_ARGS` with the model's parser |
| Bifrost virtual keys | empty `key_ids` = deny all | `key_ids` explicit |
| `/v1/models` as health | passes with the model down | smoke makes a real completion |
| Revision annotation in pods | every merge restarts PROD pods | no revision annotations |
| Failed post-sync test | Argo retries it on the old version and blocks the fix | PROD test retry 0; break-glass procedure |
| Secret change | pods don't restart | hash annotation on the pod |
| Hosted model retired | 410 overnight | lifecycle checklist; catalogue `support_ends` |

The meta-lesson: **schema-valid is not working.** Read-only cache and empty `key_ids` are both valid YAML that the
operator happily accepts. Only a real request proves it works. And from the reviews: the most common defect is a check
that passes when the thing is broken. So every gate has a test that proves it fails.

## 7. Why the design looks like it does (decisions and the alternative rejected)

| Decision | Rejected alternative | Why |
|---|---|---|
| One repo, two layers | separate platform/service repos | one small team; split later if teams split |
| Folders per env on `main` | branch per env | branches are what caused the current mess |
| Commit generated per-env YAML | let Argo render Helm/Kustomize live | the MR diff is the real PROD change; air-gap auditable; Argo's own version of this (Source Hydrator) is Beta and can't use OCI |
| Vendored Helm charts | pull charts at deploy time | air gap; reproducible render in offline CI |
| Per-environment blocks in the catalogue | one version per model | PROD stays on N while N+1 is tested |
| Evidence rule | "QA profile must equal PROD" | equality blocks every profile change; evidence proves what was tested |
| One Argo per cluster | one hub Argo | air gap; a DEV mistake can't reach PROD |
| Manual PROD sync in windows | auto-sync everywhere | single-replica large models: a sync is an outage |
| Model-specific NIMs by default, model-free "evaluating" | model-free by default | model-free is unproven air-gapped; prove it first |
| Monthly lifecycle checklist | scraper as a gate | NVIDIA has no feed; HTML diffs cry wolf; a person reads it |

## 8. Break-glass (the one exception)

In an incident someone may pause sync on one app and fix the live object. Within a working day they open an MR that
makes git match (or they revert the fix). A nightly job lists anything still paused or still different. Without a
written exception, people will hand-edit anyway and nobody will know.

## 9. Getting there from today (each step pays off alone)

| Step | Why it's worth it on its own |
|---|---|
| 0. Inventory + freeze | finally know what runs where |
| 0.5 Rotate every credential that was ever in a `.env` | the old branches are compromised history, whatever we do next |
| 1. One `main`, captured state | one place to look; done when the render diffs empty against each cluster |
| 2. Catalogue-lite + render + CI gates | models get a shared shape; typos caught before clusters |
| 3. Deploy from `main` by CI | no more manual applies; Ansible only bootstraps |
| 4. Argo per cluster | drift correction; same folders |
| 5. Gateway + evidence-gated promotion | metering, limits, real promotion gates |
| 6. Lifecycle routine | model-free proven; PB6 successor; first deprecation via the catalogue |

## 10. Likely pushback, and the answer

- **"Ansible works fine."** Ansible stays: it prepares nodes and installs Argo. It stops deploying apps because a
  playbook run doesn't tell you what *should* be running or catch drift.
- **"Generated files in git is weird."** It's what makes the MR show the exact PROD change. CI proves they match the
  catalogue. Argo's own built-in version of this exists (Beta).
- **"Too much process for three models."** Adopt in order (§9); stop at any step. Steps 0-3 are mostly moving files and
  one CI job.
- **"Why not just use NeMo Deployment Management?"** End of support 2026-10-01. Building on it means redoing it.
- **"Can't we keep env branches and be careful?"** That's what we have now.

## 11. What I still don't know (ask the team / NVIDIA)

Cluster layout per environment · GitLab tier (CE can't enforce approvals) · whether PROD reads from a mirror · NIM
Operator support window · PB6 successor · model-free NIM air-gapped with our weights · whether QA hardware equals PROD ·
the 750B model's real cold start · age-key custody.

## 12. Where to read more

- Design and its review triage: the spec (§15 lists every review finding and what changed).
- Lab proof: [Phase A findings](../raglab-phase-a-findings.md), [Phase B findings](../raglab-phase-b-findings.md).
- The ticket pages: [`docs/project-investigation/confluence/`](../project-investigation/confluence/README.md).
- Vendor lifecycle sources: NVIDIA AI Enterprise lifecycle policy, EOL notices, EOL branches (links in the research doc).
