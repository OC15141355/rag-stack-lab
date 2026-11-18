# Cutover and rollback runbook (template, per environment)

GPU capacity rarely allows running the old and new deployments side by side,
so each environment's move to operator-managed NIMs is a **cutover**: stop old,
start new, verify, and roll back if verification fails. Rehearse in DEV, then
QA; run PROD in a window.

Copy one per environment, privately.

```markdown
# Cutover: <env> — <model(s)> to NIM Operator

- Window: <date/time, duration>   - Change ref: <id>   - Lead: <name>   - Backup: <name>
- Comms: announce in <channel> at T-24h, T-1h, start, end

## Preconditions (all must be true; tick with evidence)
- [ ] Operator installed in <env>, version <x>; CRDs present (`kubectl get crd | grep apps.nvidia.com`)
- [ ] GPU Operator healthy; nodes show expected `nvidia.com/gpu` capacity
- [ ] Images mirrored: operator, NIM <repo:tag> (list) — `podman pull` from the cluster registry works
- [ ] NIMCache pre-staged and Ready for each model (`kubectl get nimcache -n <ns>`), PVC <size>
- [ ] Profiles pinned and match the previous deployment's (or the change is approved)
- [ ] Manifests merged to the <env> branch/path; GitOps app synced to "dry"/paused state, or Ansible ready
- [ ] NetworkPolicy prepared; gateway config points at the new Service names (or names unchanged)
- [ ] Smoke test passes against the *old* deployment (baseline report saved)
- [ ] Rollback artifacts ready: old manifests/values at <commit>; commands below tested in DEV
- [ ] Monitoring: dashboards for new pods ready; alerts muted/adjusted for the window

## Steps
| # | Step | Command / action | Expected | Done |
|---|---|---|---|---|
| 1 | Announce start | | | |
| 2 | Scale old model A to 0 (frees GPUs) | `kubectl scale deploy/<old> --replicas=0 -n <ns>` | Pods terminate, GPUs freed | |
| 3 | Apply/sync NIMService A | Argo sync / ansible-playbook … | NIMService Ready ≤ <N> min | |
| 4 | Smoke test A (direct + via gateway) | `smoke.py --base-url … --model A` | All PASS | |
| 5 | Repeat 2–4 for model B | | | |
| 6 | Apply NetworkPolicy | | Gateway reaches NIM; other pods blocked (negative probe) | |
| 7 | Watch for <15–30> min | Dashboards: TTFT, errors, waiting requests | Within baseline | |
| 8 | Remove old objects (after soak) | delete old Helm release/manifests via the delivery path | Only operator-managed objects remain | |
| 9 | Announce complete; attach smoke reports | | | |

## Rollback (decide by: <time> or on any failed verification)
| # | Step | Command | Expected |
|---|---|---|---|
| R1 | Scale NIMService to 0 / delete it | `kubectl patch nimservice <a> -n <ns> --type merge -p '{"spec":{"replicas":0}}'` (`spec.replicas` confirmed in operator v3.1.4 types) | GPUs freed |
| R2 | Restore old deployment | scale old back up / re-apply old values at <commit> | Old pods Ready |
| R3 | Smoke test old | `smoke.py …` | All PASS |
| R4 | Revert git change for <env> | MR revert | GitOps no longer applies new objects |
| R5 | Announce rollback; incident note | | |

Keep the NIMCache PVC on rollback: re-downloading a large model is slow.

## Post-cutover
- [ ] Old objects removed through the delivery path (not by hand only)
- [ ] Runbook updated with actual timings (cold start, Ready times)
- [ ] Ticket updated with evidence (smoke reports, screenshots)
```

## Notes

- **Upgrades of a single-replica model are outages.** In operator v3.1.4 the
  NIMService Deployment template hard-codes `RollingUpdate` with `maxSurge: 0`
  and `maxUnavailable: 25%` (`manifests/deployment.yaml` at tag v3.1.4), with
  no spec field to change it. With one 8-GPU replica, the old pod stops before
  the new one starts. Treat every NIM upgrade as a window, not a rolling change.

- **Measure in DEV first:** how long a NIMService takes to become Ready from
  a pre-staged cache. That number sets the window length.
- **Service names:** if the new Service names differ from the old ones, the
  gateway config change is part of the cutover. Keeping the names avoids it.
- **Two controllers:** don't leave the old Helm release and the operator both
  managing objects in the same namespace longer than the window.
