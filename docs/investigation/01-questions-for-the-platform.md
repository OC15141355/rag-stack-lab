# Questions for the existing platform

Grouped by area. Each question has **why it matters** (what changes in the
recommendation depending on the answer) and **who usually knows**. Ask in
batches by person, not one at a time. Write answers in your private copy of
[02](02-current-state-capture.md), with the source ("X said", "seen in
file Y", "kubectl output").

Rule: **prefer evidence over answers.** Where a question can be answered
read-only (a repo, `kubectl get`, a pipeline), answer it yourself first and ask
only to confirm or explain.

## A. Intent and scope (ask the ticket owner or lead first)

| # | Question | Why it matters | Who |
|---|---|---|---|
| A1 | What problem is moving to the NVIDIA operator approach meant to solve? (Repeatability? Upgrades? Multi-env consistency? NVIDIA support? A specific feature?) | Decides which option wins; a deprecated component can still be right if it solves the real problem | Lead / ticket author |
| A2 | Where did "NVIDIA-recommended" come from: a doc, an NVIDIA contact, a reference architecture? When? | NVIDIA's guidance changed in Oct–Nov 2026; the source may predate the sunset | Lead |
| A3 | Is the team aware NeMo Microservices was sunset (2026-10-01) and the operator's NeMo CRDs are deprecated? Has NVIDIA (account team) said anything? | May reshape the tickets | Lead / vendor contact |
| A4 | Which NeMo microservices are actually wanted: just model deployment, or also Customizer, Evaluator, Guardrails, Entity/Data Store? | Scope and prerequisites differ a lot | Lead / architect |
| A5 | Is fine-tuning (Customizer) on the roadmap? | Data Store and Entity Store mostly exist to serve customisation and evaluation workflows | Architect |
| A6 | What's the deadline, and is it fixed? Which environment has to be done first? | Phasing | Lead / PM |
| A7 | What does "done" look like for this investigation: a doc, a demo, a decision meeting? | Shapes 07 | Lead |

## B. Current model deployment (ask the platform engineer who deployed the NIMs)

| # | Question | Why it matters | Who |
|---|---|---|---|
| B1 | How are the NIMs deployed today: Helm (`nim-llm` chart?), raw manifests, NIM Operator already, or something custom? Which repo, which branch? | Baseline for every gap | Platform eng |
| B2 | Who or what applies it: Ansible playbook, Argo CD app, manual Helm, CI job? | Determines how a CRD-based approach slots in | Platform eng |
| B3 | Which NIM image tags/digests run in each env? Pinned by digest? | Reproducibility; promotion | Platform eng |
| B4 | Which model profile does each NIM use (engine, precision, TP size)? Pinned or auto-selected? | Auto-selection can differ per node type, so environments drift | Platform eng |
| B5 | Where do model weights come from at startup: NGC download, pre-staged PVC, NFS, object store, baked into the image? How long does a cold start take? | NIMCache design; air-gap | Platform eng |
| B6 | Storage: which storage class, size, access mode (RWO/RWX), backed by what (vSAN, NFS)? | NIMCache needs; multi-replica | Platform / storage |
| B7 | How many replicas per model per env? Any autoscaling? | Capacity; operator scaling config | Platform eng |
| B8 | What `max_model_len` / context and concurrency settings are configured? Where? | Model metadata item; gateway limits | Platform eng |
| B9 | How are NIM upgrades done today, and when was the last one? What broke? | Upgrade-path design; real risks | Platform eng |
| B10 | Is anything else model-related deployed: embedding/rerank NIMs, guardrails, NeMo services? | Scope | Platform eng |

## C. Environments (DEV / QA / PROD)

| # | Question | Why it matters | Who |
|---|---|---|---|
| C1 | Are DEV, QA and PROD separate clusters, separate namespaces in one cluster, or a mix? Which network zones? | Promotion design; operator install count | Platform eng |
| C2 | Do all three have the same GPUs (H200 vs H100 vs B200)? Same counts? | A model/profile that fits PROD may not fit DEV; gates on QA must match PROD hardware | Platform / infra |
| C3 | How does a change move between environments today: branch merge, tag, manual? Who approves? | Promotion item; maps to GitLab branches | Platform eng / lead |
| C4 | Are there change-management requirements for PROD (CAB, approvals, audit)? Where is the audit trail kept? | Promotion item ACs (who/when/what) | Lead / governance |
| C5 | Is QA expected to be production-like (same model versions, same gateway config)? | Validation-gate design | Lead |
| C6 | Is any environment air-gapped or restricted differently from the others? | Image and weight mirroring per env | Infra / security |

## D. Kubernetes platform and prerequisites

| # | Question | Why it matters | Who |
|---|---|---|---|
| D1 | Kubernetes version per cluster? VKS/Tanzu version? | Operator version compatibility | Platform eng |
| D2 | Is the NVIDIA GPU Operator installed? Which version, which components (driver, toolkit, device plugin, DCGM, MIG)? vGPU or passthrough? | Hard prerequisite for the NIM Operator | Platform eng |
| D3 | Can we install cluster-scoped things (CRDs, ClusterRoles, operators)? Who approves? | The NIM Operator needs cluster-scope RBAC | Platform lead / security |
| D4 | Are Pod Security Admission levels or policies (Kyverno/Gatekeeper) enforced? | Operator-created pods must pass them | Platform / security |
| D5 | Network policies in place? Can NIM pods be reached only via the gateway? | NIM has no client auth; isolation is the control | Platform / security |
| D6 | Is a LeaderWorkerSet or multi-node setup needed for any model? (A single 8-GPU node should be enough for an 8x H200 profile) | Operator multi-node support and prerequisites | Platform eng |

## E. Data, storage and databases

| # | Question | Why it matters | Who |
|---|---|---|---|
| E1 | Is there an existing Postgres service or operator (CloudNativePG, Crunchy, a managed VM DB)? Who runs it? | The Postgres item: provision new vs reuse | DBA / platform |
| E2 | Backup standard for databases (tooling, retention, restore tests)? | Postgres backup AC | DBA / platform |
| E3 | Is object storage (S3-compatible, e.g. MinIO) available? | Some NeMo/Helix components need it | Platform / storage |
| E4 | Is HA expected for operator-related state in PROD? What RPO/RTO? | Postgres HA scope | Lead / governance |

## F. Images, registries, secrets

| # | Question | Why it matters | Who |
|---|---|---|---|
| F1 | How do NGC images reach Harbor today (mirroring job, manual, proxy cache)? | Operator, NIM and NeMo images all need mirroring | Platform eng |
| F2 | Is there NGC access (API key, org) from any network zone? Who holds the key? | NIMCache download path vs pre-staging | Platform / vendor mgmt |
| F3 | How are secrets delivered today (plaintext `.env`, Ansible vars, CI variables, Kubernetes Secrets by hand)? | Operator needs NGC and pull secrets; Postgres creds; this is a risk item | Platform eng |
| F4 | Is there an agreed path for secret management going forward (ansible-vault, CI variables, External Secrets)? | Avoid adding new plaintext secrets with the migration | Lead / security |

## G. Consumers of models and metadata

| # | Question | Why it matters | Who |
|---|---|---|---|
| G1 | Who consumes model information today (the gateway, inference service, portal UI)? How do they learn model names and limits: hardcoded, config, `/v1/models`? | The metadata item: where metadata should live | App devs |
| G2 | Where are token/rate limits enforced today, if anywhere? | Token enforcement belongs in the gateway or NIM, not a metadata store; confirm the design intent | Gateway owner |
| G3 | When a model is added or retired, what has to change and in which repos? | Shows the real "model registration" workflow | Platform + app devs |
| G4 | Does anything need users or sessions stored (the item that mentions an entity store for "users, sessions")? What is it for? | NeMo Entity Store is not a user/session store; the requirement may belong to the portal | App devs / architect |

## H. Operations, ownership, support

| # | Question | Why it matters | Who |
|---|---|---|---|
| H1 | Who will own the operator and the CRDs after the change (on-call, upgrades)? | Operators add an upgrade stream | Lead |
| H2 | Is there NVIDIA AI Enterprise support / an account team? Has support been engaged on this? | Sunset guidance says "contact your account team" | Lead / vendor mgmt |
| H3 | What monitoring exists for NIMs (dashboards, alerts)? | Parity requirement during migration | Platform eng |
| H4 | What's the rollback expectation if a migrated environment misbehaves? | Phasing; dual-running | Lead |
| H5 | Maintenance windows for PROD? | Cutover planning | Lead / ops |

## Read-only evidence you can gather yourself

```sh
# what's deployed and how
kubectl get deploy,sts,svc -A | grep -i -E 'nim|nemo|llm'
kubectl get crd | grep -i -E 'nvidia|nim|nemo|apps.nvidia'
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{.spec.containers[*].image}{"\n"}{end}' | grep -i nim
kubectl get nodes -L nvidia.com/gpu.product,nvidia.com/gpu.count
kubectl get pods -n gpu-operator 2>/dev/null
helm list -A 2>/dev/null | grep -i -E 'nim|nemo|gpu'
kubectl get applications -n argocd 2>/dev/null
kubectl get pvc -A | grep -i -E 'nim|model|cache'
kubectl auth can-i --list | head -40       # what YOU can see

# how it gets there
git log --oneline --all -- '*nim*' '*nemo*' | head
rg -n -i 'nim|nemo|nvcr.io' --glob '*.yml' --glob '*.yaml' --glob '*.j2' | head -50
```

Record the outputs, redacted, in your private 02.
