# raglab Phase B findings (rented A100, standalone cluster)

Status (2026-11-26): **session COMPLETE; instance terminated; billing stopped.** One Lambda `gpu_1x_a100_sxm4`
(A100 40GB SXM4, us-east-1), launched 19:30:53Z, terminated 22:44:40Z: **3 h 14 min, about USD 6.40** (cap 15).
After terminate: `live instances: 0  file systems: 0`. Home lab VM restarted; Phase A regression passed at `7f07242`
(9 apps Synced/Healthy, smoke 9/1/0 in dev/qa/prod, no GPU namespace or app on the home lab).

## OWNER TODOs (revocation, runbook section 6, after billing)

1. **Revoke the session NVIDIA key** in the NGC console. Then both probes must say `REJECTED` (exit 1):
   `skey | python3 scripts/key_probe.py hosted --chat z-ai/glm-5.3-flash` and
   `skey | python3 scripts/key_probe.py nvcr --repo nim/meta/llama-3.1-8b-instruct --tag 2.1.7`.
   (The runbook's `--chat meta/llama-3.1-8b-instruct` no longer works: that hosted model is retired, HTTP 410.)
2. **Delete the Lambda API key and the `raglab-gpu-session` SSH key** in the Lambda console; then
   `python3 scripts/lambda.py instances` must fail with HTTP 401.
3. Then delete the session material (runbook 6.3). This makes `lab/gpu/secrets/gpu.sops.yaml` permanently
   undecryptable, which is the intent. Claude can run 6.3 once 1-2 are done.
4. Copy the lab age key into the password manager (open from Phase A).

## Acceptance (Phase B)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | GPU through NRI/CDI, no `runtimeClassName`, no `nvidia` RuntimeClass | **PASS** | gpu-check Job: `NVIDIA A100-SXM4-40GB, 40960 MiB, 570.148.08`; `nvidia.com/gpu: 1` |
| 2 | Go/no-go before any weights | **PASS (GO)** | `092ed421…f90 (vllm-bf16-tp1-pp1-33.0)` runnable |
| 3 | NIMCache via Argo | **PASS** | Ready in 2 min 26 s (20:32:05 → 20:34:31), 30 GB on a 60Gi local-path PVC; job pod requests no GPU |
| 4 | NIMService Ready, cold start | **PASS** (after 2 fixes) | 129 s first start, 107 s warm restart, 0 restarts |
| 5 | Hosted baseline smoke | **NOT MET** (external) | NVIDIA hosted API answered in 150-260 s from the rented host vs 2-4 s from Australia; every run hit the 900 s Job deadline |
| 6 | Cutover through git, smoke green | **PASS** (after 2 fixes) | 6 passed / 0 failed at `4cedd91`; chat, stream (88 chunks in 1.1 s), tools 3/3, auth-negative, limit-429 |
| 7 | Only port 22 exposed | **PASS** | exposure probe: `OPEN 22`, everything else closed |
| 8 | Failure injection caught by the gate | **PASS** | NIM at 0 replicas: chat/stream/tools/limit FAIL `connection refused`, sync `Failed` |
| 9 | NetworkPolicy enforced | **PASS** | as-bifrost 200; unlabelled and other-namespace BLOCKED |
| 10 | Rollback through `git revert`; cache survives | **PASS** (smoke slow) | routed back to hosted (chat/stream PASS, tools hit the deadline: criterion 5); NIMCache Ready, PVC Bound |
| 11 | Roll forward | **PASS** | 6/0/0 at `7f07242` |
| 12 | Isolation | **PASS** | in-cluster decryption key = session recipient only; secrets = expected set; no VPN/kubeconfig on the VM; Phase A key cannot decrypt the GPU secrets |
| 13 | No ClusterPolicy sync loop | **PASS** | Argo history 1, Synced, across the session |

## Things that affect work (the Project investigation)

Each of these was hit live and fixed by a PR on `main` (numbers in brackets).

1. **A read-only weights PVC stops NIM 2.1.7 from starting.** `readOnly: true` on the NIMService cache (an obvious
   hardening for a shared, pre-populated PVC) crash-loops the NIM: "Cache directory /model-store is not accessible by
   the container user". File ownership was correct; the mount mode was the cause. (#35)
2. **Default-deny NetworkPolicies block the NIM Operator's own readiness check.** The operator calls the NIM's
   `/v1/models` to mark the NIMService Ready. With default-deny ingress the pod was 1/1 Ready but the NIMService stayed
   NotReady forever (operator log: `connection refused`). Any "only the gateway may reach the NIM" policy also needs the
   operator namespace. Argo health then reports the app as Progressing indefinitely. (#36)
3. **Bifrost v2.6 refuses in-cluster upstreams by default.** Its SSRF guard blocks RFC1918 addresses: HTTP 502
   "connection to private IP … is not allowed: set network_config.allow_private_network". Every self-hosted NIM behind
   Bifrost needs this per provider; keep it off for hosted providers. (#37)
4. **Tool calling is off by default on the NIM, and the documented env vars did not take effect.**
   `NIM_ENABLE_AUTO_TOOL_CHOICE` / `NIM_TOOL_CALL_PARSER` were present in the pod but absent from vLLM's arguments on
   this profile; requests with `tool_choice: auto` returned HTTP 400. `NIM_PASSTHROUGH_ARGS="--enable-auto-tool-choice
   --tool-call-parser llama3_json"` worked (3/3 well-formed tool calls). Agentic clients (Cline etc.) depend on this:
   smoke-test tools on every model, and check the engine's logged args, not just the pod env. (#38, #39)
5. **`/v1/models` through the gateway proves nothing about the backend.** With the NIM scaled to 0, Bifrost's model
   list still passed (it comes from config). Health gates need a real completion.
6. **Hosted-API latency depends heavily on where you call from.** The same request took 2-4 s from Australia and
   150-260 s from a US cloud host (`Nvcf-Status: fulfilled`, all latency upstream). A hosted fallback or baseline needs
   its own latency check from the place it will actually run.
7. **Hosted models are retired without notice.** `meta/llama-3.1-8b-instruct` went from listed to HTTP 410 between two
   days. Catalogues naming hosted upstreams need a scheduled check (list + one real call per model). (#31)
8. **A `git revert` rollback can conflict in generated files.** Reverting the cutover conflicted with a later change
   to the same generated Bifrost config. The fix is to resolve by regenerating from the reverted catalogue and running
   `generate.py --check`, never by hand-merging generated JSON. Rollback runbooks for catalogue-driven config should
   say so. (#41)
9. **Argo CD keeps retrying a failed PostSync smoke on the old revision and blocks newer syncs.** After a merge, the
   app stayed on a retrying operation for the previous revision until it was terminated. During an incident, terminate
   the stale operation first (`argocd app terminate-op`, or patch `status.operationState.phase: Terminating`), then
   sync the revision you want.
10. **YAML flow lists split on commas.** `command: [nvidia-smi, --query-gpu=name,memory.total, ...]` became separate
    arguments. Quote any argument containing a comma. (#33)
11. **NIM's profile names now carry a version suffix** (`vllm-bf16-tp1-pp1-33.0`). Our go/no-go parser would have
    reported a false NO-GO; any automation that matches profile names must allow the suffix. (#33)
12. **NIMCache downloads were fast** (8B bf16 profile, ~30 GB, in under 2.5 minutes from NGC on a cloud host). For the
    Project's air-gapped mirror the bottleneck will be the internal registry/storage, not NGC.

Earlier pre-session findings (still valid): checks that pass when broken were the dominant review defect; hand-typed
mode flags are a credential-leak path; cloud account readiness (billing profile) is its own gate.

## Runbook fixes still to make (not blocking; next session)

- 0 shell setup: `ARGOCD_OPTS=--core` alone still read the owner's home-lab Argo CLI config ("not configured with
  SSO"). Set `ARGOCD_CONFIG=$RG/argocd-config` as well.
- Port-forwards: replace `sleep 3` with a wait-until-listening loop (it failed twice on the first call).
- 3.8/3.9: add "terminate the stale operation, then sync the wanted revision" (finding 9), and "resolve a revert conflict
  by regenerating" (finding 8).
- 6.1: hosted revocation probe model must be a live hosted model (finding 7).
- The node name is the public IP: evidence copied into the repo must be redacted (it was here).

## Process notes

- Before the launch, a chained shell command kept going after a `git rebase` conflict and a text replacement hit the
  wrong model; caught before reaching the remote, reset, and rebuilt. Lesson: stop chains on conflict; edit structured
  files by key.
- A detached watchdog on the Mac (terminate at T+4:50, `caffeinate`) was armed for the whole rental and disarmed after
  the verified terminate.
