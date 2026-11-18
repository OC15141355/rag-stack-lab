# Current-state capture (template)

Copy this file somewhere **private** before filling it in. For every claim,
note the **evidence** (file path at commit, command output, or "per <role>,
<date>"). "Unknown" is a valid, useful answer. Leave it visible.

## 1. One-paragraph description

> How models are deployed today, in plain words: what gets applied, by what,
> from where, into which clusters.

## 2. Deployment path (per model)

| Item | Model A | Model B | Evidence |
|---|---|---|---|
| NIM image (repo:tag@digest) | | | |
| Deployed via (Helm chart / manifests / operator / other) | | | |
| Applied by (Ansible role / Argo app / CI job / manual) | | | |
| Source repo + path + branch | | | |
| Model profile (engine, precision, TP) and how it's chosen | | | |
| Weights source (NGC download / PVC / NFS / baked) | | | |
| Storage class, size, access mode | | | |
| Replicas, autoscaling | | | |
| GPUs per replica, GPU type | | | |
| Configured max context / concurrency | | | |
| Service name, port, exposed via | | | |
| Health/readiness probes | | | |
| Cold start time (measured) | | | |

## 3. Environments

| Item | DEV | QA | PROD | Evidence |
|---|---|---|---|---|
| Cluster / namespace | | | | |
| Kubernetes / VKS version | | | | |
| GPU Operator version | | | | |
| GPU type and count | | | | |
| Network zone / air-gap | | | | |
| Git branch (or path) that defines it | | | | |
| How changes arrive (merge, tag, manual) | | | | |
| Approvals needed | | | | |
| Models and versions running | | | | |

## 4. Operational dependencies

| Dependency | What exists | Owner | Gaps | Evidence |
|---|---|---|---|---|
| Image registry and mirroring (Harbor) | | | | |
| NGC access / API key handling | | | | |
| Storage for weights | | | | |
| Databases (Postgres?) | | | | |
| Object storage | | | | |
| Secrets delivery | | | | |
| Gateway (Bifrost) and its model config | | | | |
| Consumers that need model metadata | | | | |
| Monitoring / alerting for NIMs | | | | |
| Backup / DR | | | | |

## 5. How a model change happens today (step by step)

1. …
2. …

(Write the real sequence for "upgrade model A to a new NIM version" and "add a
new model", including every repo touched and every approval.)

## 6. Diagram

```
[Ansible / GitLab CI / Argo] ──applies──▶ [cluster: DEV]
                                        ▶ [cluster: QA]
                                        ▶ [cluster: PROD]
[Harbor] ──images──▶ …        [weights source] ──▶ …
[Gateway] ──routes──▶ [NIM svc A], [NIM svc B]
```

## 7. Unknowns and who to ask

| Unknown | Asked who | Date | Answer |
|---|---|---|---|
