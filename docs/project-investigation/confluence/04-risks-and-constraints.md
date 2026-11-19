# 4. Risks and constraints

> **[MACRO: Page Properties]**
> | Status | DRAFT |
> | Owner | <you> |
> | Last updated | <date> |
> | Parent | Model deployment: move to NVIDIA operator approach |

**Purpose:** risks of making the change (and of not making it), and constraints to plan around.


| Risk | L | I | Mitigation |
|---|---|---|---|
| Building on deprecated NeMo CRDs / sunset product | H | H | Don't adopt without a decision record and NVIDIA's written position (N13) |
| Tickets assume features NVIDIA doesn't have | H | M | Re-scope as in 5.3 |
| Upgrades are outages for single-replica 8-GPU models (`maxSurge: 0`, hard-coded) | H | M | Treat upgrades as windows; consider replicas where GPUs allow |
| QA validates RC images, not PROD's artefact | M | H | Digest pinning + MR promotion |
| Manual weight staging is not reproducible | H | M | Automate (N4) |
| Large-model cache size/cold start (~750 GB) | H | M | Pre-stage; size PVC; measure cold start in DEV |
| Cluster-scope approval delays | M | H | Raise early (N2) |
| GPU capacity prevents side-by-side cutover | H | M | Per-env cutover windows; rollback plan; keep PVCs |
| Argo pruning a `NIMCache` deletes weights | M | H | Prune/Delete protection annotations |
| NIM endpoints reachable bypassing Bifrost | M | H | NetworkPolicy (N7) |
| New secrets added in plaintext | H | H | Agree a secret path first (N8) |
| ASR NIM support under the operator unknown | M | M | Verify (N12) |
| Operator adds an upgrade stream | M | M | Pin versions; upgrade runbook |

**Constraints:** fixed GPU hardware per env; restricted networking and Harbor mirroring; existing
Ansible + GitLab branch delivery; PROD change approvals; team capacity.

## Risk of not changing
- QA keeps validating release-candidate images rather than PROD's artefact.
- Weight staging stays manual and unrepeatable.
- No limits/metadata in front of the models until Bifrost lands.
