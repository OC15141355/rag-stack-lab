# raglab Phase B session runbook (one rented A100, standalone cluster)

Spec: [`docs/superpowers/specs/2026-11-25-raglab-phase-b-gpu-design.md`](../../docs/superpowers/specs/2026-11-25-raglab-phase-b-gpu-design.md).
Everything runs from the repo root on the Mac unless a step says "on the VM". **Billing runs from `launch` until
`terminate`; terminate is the only stop.** The home lab is not touched.

## 0. Rules (read before every session)
- Never on the VM: the Lambda API key, the Phase A age key (`~/.sops/raglab-age-key.txt`), any home credential,
  kubeconfig or VPN client. No SSH agent forwarding. Only the session SSH key is used.
- Never in the repo, a PR, or a commit message: the VM's IP, the owner's home address, any key value. Session files
  (inventory, evidence, Argo CLI config) live in `~/.raglab-gpu/` (outside the repo, mode 700).
- Keys reach a process only through a pipe from `age -d` (never argv, never `export`, never echo). Check
  `fc -ln 1 | grep -c nvapi-` (zsh; bash: `history | grep -c nvapi-`) is 0 at the end.
- Failure injection and rollback go **through git** (Argo `selfHeal` reverts `kubectl` edits). Session PRs into
  `main` are **squash-merged** (one commit each), so a rollback is a plain `git revert <sha>`. The owner merges.
- The home lab VM stays **stopped** for the whole session: the rented cluster tracks `main`, and every merge to
  `main` would otherwise roll the home lab's dev Bifrost and rerun its smoke.
- Hard limits: **ABORT CHECKPOINT T+3:00** (NIMService not Ready: tear down, do not extend). **T+4:15 teardown
  starts regardless of state.** T+5:00 hard stop. Cap USD 15.

Shell setup for every terminal used in the session (bash or zsh):
```bash
cd ~/Projects/rag-stack-lab
export RG=$HOME/.raglab-gpu SK=$HOME/.sops/raglab-gpu-session
export KUBECONFIG=$PWD/lab/bootstrap/kubeconfig.gpu
export ARGOCD_OPTS="--core"        # talks to the cluster via kubeconfig.gpu; no login, no password, no token on disk
gssh() { ssh -i "$HOME/.ssh/raglab_gpu_ed25519" -o IdentitiesOnly=yes -o ForwardAgent=no "$@"; }
skey() { age -d -i "$SK/age-key.txt" "$SK/session-nvapi-key.age"; }      # pipe only: skey | <consumer>
IP=$(awk -F'ansible_host=' '/ansible_host/{split($2,a," "); print a[1]}' "$RG/inventory.ini" 2>/dev/null)
```

## 1. Pre-rent checklist (the day before; nothing here costs GPU time)
1. `main` contains the merged pre-rent PRs and CI is green on it: `gh run list --branch main --limit 1`.
2. Tools: `for t in age sops kubectl helm ansible-playbook argocd uv gh python3; do command -v $t >/dev/null || echo MISSING $t; done`
   prints nothing.
3. Session material present, private: `ls -l $SK ~/.ssh/raglab_gpu_ed25519` shows `age-key.txt`,
   `session-nvapi-key.age`, `lambda-api-key.age` (all `-rw-------`) and the SSH key (`-rw-------`).
4. The session key is accepted by the hosted API and the hosted model exists (2 small calls):
   `skey | python3 scripts/key_probe.py hosted --chat meta/llama-3.1-8b-instruct`
   Expect `model meta/llama-3.1-8b-instruct listed: True`, two `HTTP 200`, `ACCEPTED`. If `listed: False`, the hosted
   baseline needs a stand-in: see 3.8 note.
5. The session key can pull the pinned NIM, and the tag still points at the pinned digest:
   `skey | python3 scripts/key_probe.py nvcr --repo nim/meta/llama-3.1-8b-instruct --tag 2.1.7`
   Expect `ACCEPTED` and `digest: sha256:5ada92d1ca5c30069956e6e1322f0fbb250b4683b566aedb6547b10a64faf00b`. A different
   digest is fine (manifests are pinned by digest), but record it.
6. The committed secrets file decrypts with the session key and is intact (prints only OK lines):
   `SOPS_AGE_KEY_FILE=$SK/age-key.txt sops decrypt lab/gpu/secrets/gpu.sops.yaml | uv run -q --with pyyaml python3 scripts/make_gpu_sops.py verify`
   and the Phase A key cannot decrypt it:
   `err=$(SOPS_AGE_KEY_FILE=$HOME/.sops/raglab-age-key.txt sops decrypt lab/gpu/secrets/gpu.sops.yaml 2>&1 >/dev/null); rc=$?; if [ $rc -eq 0 ]; then echo LEAK; elif printf '%s' "$err" | grep -q -e 'no identity matched' -e '0 successful groups'; then echo ok-phase-a-key-cannot-decrypt; else echo "UNEXPECTED (not a no-identity error): $err" | head -3; fi`
   (a missing file, a bad path or a sops crash must not read as success: only sops' own no-matching-identity error passes)
7. The platform charts still render to the committed summaries (the Helm repo is mutable):
   `scripts/render-gpu-platform.sh --check` prints two `unchanged` lines.
8. Lambda: `python3 scripts/lambda.py instances` exits 0 (`live instances: 0  file systems: 0`) and
   `python3 scripts/lambda.py types` shows capacity for `gpu_1x_a100_sxm4` (us-east-1/us-west-2) or `gpu_1x_a100`
   (us-south-2). In the Lambda console: the account firewall allows TCP 22 and ICMP only from the current home
   address (if the home address changed, fix the rule before renting), SSH key `raglab-gpu-session` is registered. The account's billing profile (address and payment method) is valid: a
   bad billing address makes `launch` fail with `HTTP 403 global/invalid-address` (seen 2026-11-26).
9. Home lab VM stopped: `ssh hv-01 'qm status 101'` prints `status: stopped`.
10. Draft PR branches exist: `session/gpu-go` and `session/gpu-cutover` (built in plan Task 8).
11. Calendar alarms set relative to the planned start: T+3:00 checkpoint, T+4:15 teardown, T+4:45, T+5:00.
12. `mkdir -p -m 700 "$RG" "$RG/evidence" && cp lab/bootstrap/inventory.gpu.example.ini $RG/inventory.ini && chmod 600 $RG/inventory.ini`

## 2. Timeline
| Time | Step (section) | Gate |
|---|---|---|
| T+0:00 | Rent, SSH in, exposure probe (3.1) | `nvidia-smi` shows an A100; only 22 answers from outside |
| T+0:10 | Bootstrap 01 + 04 + tunnel + 02 + 03 (3.2) | node Ready; handover passes (operators, secrets, dev-gpu hosted smoke) |
| T+0:35 | GPU checks (3.3) | `nvidia.com/gpu: 1`; gpu-check Job prints the A100; no `nvidia` RuntimeClass |
| T+0:50 | **Go/no-go** (3.4) | `vllm-bf16-tp1-pp1` runnable, else **abort before any weights** (section 4) |
| T+0:55 | Go PR; NIMCache downloads (3.5) | NIMCache `Ready` |
| T+2:15 | Replicas PR; cold start (3.6) | NIMService `Ready`, cold start recorded |
| **T+3:00** | **ABORT CHECKPOINT** | NIMService not Ready: section 4, do not extend |
| T+3:00 | NetworkPolicy probes, cutover PR, smoke (3.7, 3.8) | smoke green on the SHA, `routing_info` = `nim-local` |
| T+3:40 | Failure injection, rollback, roll forward if time (3.9) | rollback smoke green on hosted; NIMCache kept |
| **T+4:15** | **Teardown begins regardless** (3.10 then section 5) | |
| T+4:30 | Terminated | `lambda.py instances` exit 0 |

## 3. Session

### 3.1 Rent and check the host (T+0:00)
1. `python3 scripts/lambda.py launch --type gpu_1x_a100_sxm4 --region us-east-1 --wait > $RG/evidence/launch.txt; rc=$?; cat $RG/evidence/launch.txt; echo exit=$rc`
   (or another type/region from step 1.8). Expect `exit=0`, `LAUNCHED <id> at <UTC>` then a line with `status=active ip=...`.
2. Put the IP into `$RG/inventory.ini` (replace the placeholder), then re-run the `IP=` line of the shell setup.
3. First SSH (accept the host key; there is no out-of-band fingerprint, trust on first use):
   `gssh ubuntu@$IP 'nvidia-smi --query-gpu=name,memory.total --format=csv,noheader; sudo -n true && echo SUDO_OK'`
   Expect `NVIDIA A100-SXM4-40GB, 40960 MiB` (or the PCIe name) and `SUDO_OK`.
   Then check for JupyterLab: `gssh ubuntu@$IP 'systemctl list-units --all --no-legend | grep -i jupyter || echo no-jupyter-unit; ss -ltn | grep -E ":8888|:8889" || echo no-jupyter-port'`.
   Playbook 01 stops and disables any jupyter unit; re-run this check after 01 and expect `no-jupyter-unit`.
4. Exposure probe from the Mac (criterion 7): `for p in 22 80 443 2379 6443 8080 10250; do nc -z -G 3 $IP $p >/dev/null 2>&1 && echo "OPEN $p" || echo "closed $p"; done | tee $RG/evidence/exposure.txt`
   Expect `OPEN 22` only. (ICMP from the home address is also allowed by the account firewall: recorded, accepted.)

### 3.2 Bootstrap (T+0:10)
```bash
scripts/gpu-ansible.sh playbooks/01-platform.yml      # wrapper: always the session inventory + -e gpu_session=true
scripts/gpu-ansible.sh playbooks/04-gpu-prep.yml
gssh -f -N -o ExitOnForwardFailure=yes -L 6443:127.0.0.1:6443 ubuntu@$IP     # API tunnel (k3s API is not exposed)
kubectl get nodes                                                             # one node Ready
scripts/gpu-ansible.sh playbooks/02-argocd.yml
scripts/gpu-ansible.sh playbooks/03-handover.yml
```
- 01: the GPU gate task prints the A100; "Verify secrets encryption" ok. 04: all gates ok; it writes
  `$RG/evidence/gpu-prep.txt` (containerd version, NRI socket, host toolkit, disk). If 04 fails on containerd or NRI,
  use section 9 (fallback) before 02.
- 02: the age-key task shows `censored due to no_log`. 03 waits up to ~20 min (GPU Operator operands, the dev-gpu
  smoke hook on the hosted provider). Its success is the **hosted baseline**:
  `kubectl -n raglab-dev-gpu logs job/smoke | tail -40 | tee $RG/evidence/smoke-hosted-baseline.txt`
  must show `0 failed`, `[PASS] auth-negative`, `[PASS] limit-429` and `revision=<main SHA>`.
- Argo CLI: no login. `ARGOCD_OPTS=--core` (shell setup) makes `argocd` use `kubeconfig.gpu` directly; run once
  `kubectl config set-context --current --namespace=argocd`. The admin password is never read.
- The playbooks refuse a mode mismatch (Phase A inventory/kubeconfig in GPU mode or the reverse) before touching anything.

### 3.3 GPU checks (T+0:35)
1. `kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}{"\n"}'` prints `1`.
2. `kubectl -n gpu-operator get pods` all `Running` or `Completed`; `kubectl get runtimeclass` lists no `nvidia` (NRI).
3. GPU through NRI/CDI with no runtimeClassName, and the NIM image pre-pull (several GB; up to ~15 min):
   ```bash
   kubectl apply --server-side -f lab/gpu/gonogo/gpu-check-job.yaml
   kubectl -n raglab-gpu wait --for=condition=complete job/gpu-check --timeout=30m
   kubectl -n raglab-gpu logs job/gpu-check | tee $RG/evidence/gpu-check.txt    # A100 name, memory, driver
   ```
4. No sync loop on the ClusterPolicy (spec open item 8): run
   `argocd app get raglab-gpu-operator -o json | python3 -c 'import json,sys;s=json.load(sys.stdin)["status"];print(len(s.get("history",[])),s["sync"]["status"])'`
   twice, 5 minutes apart. The history length must not grow and the status must be `Synced`. If it loops, record the
   diff (`argocd app diff raglab-gpu-operator`) and the field manager names
   (`kubectl get clusterpolicy cluster-policy --show-managed-fields -o yaml | grep manager:`); continue (it is a finding,
   not a blocker).

### 3.4 Go/no-go (T+0:50) — before any weights are downloaded
```bash
kubectl apply --server-side -f lab/gpu/gonogo/list-profiles-job.yaml
kubectl -n raglab-gpu wait --for=condition=complete job/list-model-profiles --timeout=20m
kubectl -n raglab-gpu logs job/list-model-profiles | tee $RG/evidence/list-model-profiles.txt
python3 - $RG/evidence/list-model-profiles.txt <<'PY'
import re, sys
t = open(sys.argv[1]).read()
parts = re.split(r"Compatible with system and runnable:?", t, maxsplit=1)
if len(parts) < 2:
    sys.exit("NO-GO? no 'Compatible with system and runnable' section: read the file by eye")
runnable = re.split(r"\n\s*-?\s*(?:Compilable|Incompatible)", parts[1], maxsplit=1)[0]
m = re.search(r"-\s*(\S+)\s*\(vllm-bf16-tp1-pp1\)", runnable) or re.search(r"-\s*(vllm-bf16-tp1-pp1)\b", runnable)
print(f"GO profile={m.group(1)}" if m else "NO-GO: vllm-bf16-tp1-pp1 is not runnable on this GPU")
sys.exit(0 if m else 1)
PY
```
- **GO** = `vllm-bf16-tp1-pp1` is listed as runnable. Pin exactly the ID the tool prints for it (`GO profile=<ID>`).
- **NO-GO** = not runnable (or the Job fails to pull/run): **abort, section 4.** Do not pick another profile live.
- Record whether the go/no-go pod and the gpu-check pod requested a GPU successfully, and the output format.

### 3.5 Go PR, NIMCache (T+0:55)
```bash
git fetch origin && git checkout session/gpu-go && git rebase origin/main
P='<ID from 3.4>'
sed -i '' "s/PENDING-GO-NO-GO/$P/" lab/gpu/nim/nimcache.yaml lab/gpu/nim/nimservice.yaml
uv run --with pytest --with pyyaml --with jsonschema pytest -q tests/test_gpu_argocd.py tests/test_gpu_manifests.py
git commit -am "gpu: pin NIM profile from go/no-go; add raglab-gpu-nim" && git push -f origin session/gpu-go
gh pr ready && gh pr checks --watch        # owner merges when gates is green
argocd app get raglab-gpu-root --hard-refresh >/dev/null
```
Then watch and record:
```bash
date -u +%FT%TZ | tee $RG/evidence/nimcache-start.txt
kubectl -n raglab-gpu get pods --show-labels | tee $RG/evidence/nimcache-pods.txt        # job pod labels (open item)
kubectl -n raglab-gpu get pods -o jsonpath='{range .items[*]}{.metadata.name}{" gpu="}{.spec.containers[0].resources.limits.nvidia\.com/gpu}{"\n"}{end}'
until [ "$(kubectl -n raglab-gpu get nimcache llama-8b -o jsonpath='{.status.state}')" = Ready ]; do sleep 30; done
date -u +%FT%TZ | tee $RG/evidence/nimcache-ready.txt
kubectl -n raglab-gpu get nimcache llama-8b -o jsonpath='{.status.profiles}{"\n"}' | tee -a $RG/evidence/nimcache-ready.txt
```
If the state becomes `Failed`: `kubectl -n raglab-gpu get pods` and `kubectl -n raglab-gpu logs <nimcache job pod> --tail=50`,
record, then decide against the clock (T+3:00 checkpoint).

### 3.6 NIMService up, cold start (T+2:15)
```bash
git fetch origin && git checkout -b session/gpu-replicas-1 origin/main
sed -i '' 's/^  replicas: 0$/  replicas: 1/' lab/gpu/nim/nimservice.yaml
uv run --with pytest --with pyyaml --with jsonschema pytest -q tests/test_gpu_manifests.py
git commit -am "gpu: NIMService replicas 1" && git push -u origin HEAD && gh pr create --fill && gh pr checks --watch
```
After the merge and sync:
```bash
kubectl -n raglab-gpu get nimservice llama-8b -w        # until STATUS Ready (Ctrl-C)
kubectl -n raglab-gpu get pods -l app.kubernetes.io/component=nim-llm -o json | python3 -c '
import json, sys, datetime as d
p = json.load(sys.stdin)["items"][0]; f = lambda s: d.datetime.fromisoformat(s.replace("Z", "+00:00"))
c = p["metadata"]["creationTimestamp"]; r = [x["lastTransitionTime"] for x in p["status"]["conditions"] if x["type"] == "Ready" and x["status"] == "True"]
print("pod", p["metadata"]["name"], "created", c, "ready", r[0] if r else None, "cold_start_s", (f(r[0]) - f(c)).total_seconds() if r else None,
      "restarts", sum(s.get("restartCount", 0) for s in p["status"].get("containerStatuses", [])))' | tee $RG/evidence/cold-start-empty.txt
```
If `-l app.kubernetes.io/component=nim-llm` finds no pod, the operator did not copy `spec.labels` to the pod: record the
pod's real labels (`kubectl -n raglab-gpu get pods --show-labels`) and fix the two NetworkPolicies by PR (open item).
Direct NIM check (port-forward bypasses NetworkPolicy; this tests the NIM, not the policy):
```bash
kubectl -n raglab-gpu port-forward svc/llama-8b 18000:8000 >/dev/null 2>&1 & PF=$!; sleep 3
curl -s -o /dev/null -w 'ready %{http_code}\n' http://127.0.0.1:18000/v1/health/ready
curl -s http://127.0.0.1:18000/v1/models | python3 -c 'import json,sys;print([m["id"] for m in json.load(sys.stdin)["data"]])'
curl -s http://127.0.0.1:18000/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"meta/llama-3.1-8b-instruct","messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":8}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["choices"][0]["message"]["content"])'
kill $PF
```
Expect `ready 200`, a model list containing `meta/llama-3.1-8b-instruct` (if the served name differs, the catalogue's
`chat/small.upstream` must change in the cutover PR), and a short answer.
**T+3:00: if the NIMService is not Ready, stop here: section 4.**

### 3.7 NetworkPolicy probes (criterion 9)
```bash
kubectl apply --server-side -f lab/gpu/probes/netpol-probes.yaml
sleep 30
for p in raglab-dev-gpu/probe-as-bifrost raglab-dev-gpu/probe-unlabelled default/probe-other-ns; do
  kubectl -n ${p%/*} logs ${p#*/}; done | tee $RG/evidence/netpol-probes.txt
kubectl delete -f lab/gpu/probes/netpol-probes.yaml
```
Expect `PROBE probe-as-bifrost status=200`, `PROBE probe-unlabelled BLOCKED (...)`, `PROBE probe-other-ns BLOCKED (...)`.
A `status=<any code>` (200, 503, ...) on either negative probe means the connection got through, so k3s is not enforcing the policy: record it as a finding. `ERROR (...)` is not a policy verdict (DNS or other): investigate.

### 3.8 Cutover (dev-gpu: hosted to nim-local)
```bash
git fetch origin && git checkout session/gpu-cutover && git rebase origin/main
uv run --with pyyaml python3 lab/catalogue/generate.py && git status --short     # only lab/gpu/envs/dev-gpu/generated changes
git diff --exit-code lab/envs                                                      # Phase A envs untouched
git commit -am "gpu: dev-gpu chat/small -> nim-local (cutover)" --allow-empty && git push -f origin session/gpu-cutover
gh pr ready && gh pr checks --watch      # owner merges; record the merge SHA as CUT
```
Stand-in note: if 1.4 showed the hosted model is not listed, the hosted baseline used a stand-in upstream; this PR then
also sets `chat/small.upstream` to `meta/llama-3.1-8b-instruct`, and the PR text must say the cutover is not like-for-like.

After the merge, Argo syncs dev-gpu (the ConfigMap hash rolls the pod) and the PostSync smoke runs:
```bash
argocd app wait raglab-apps/raglab-dev-gpu --operation --timeout 600
kubectl -n raglab-dev-gpu logs job/smoke | tail -40 | tee $RG/evidence/smoke-nim-local.txt
```
Expect `nim-local/chat/small` chat, stream, tools PASS, `[PASS] auth-negative`, `[PASS] limit-429`, `0 failed`,
`revision=<CUT>`. Then confirm Bifrost routed to the NIM:
```bash
kubectl -n raglab-dev-gpu port-forward svc/bifrost 18080:80 >/dev/null 2>&1 & PF=$!; sleep 3
VK=$(kubectl -n raglab-dev-gpu get secret bifrost-env -o jsonpath='{.data.BIFROST_VK}' | base64 -d)
printf 'header = "x-bf-vk: %s"\n' "$VK" | curl -s --config - -H 'Content-Type: application/json' \
  -d '{"model":"nim-local/chat/small","messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":8}' \
  http://127.0.0.1:18080/v1/chat/completions | python3 -c '
import json, sys
def find(o):
    if isinstance(o, dict):
        if "routing_info" in o: return o["routing_info"]
        o = list(o.values())
    for v in (o if isinstance(o, list) else []):
        r = find(v)
        if r is not None: return r
print(json.dumps(find(json.load(sys.stdin))))' | tee $RG/evidence/routing-info.txt
unset VK; kill $PF
```
Expect the provider `nim-local`. If the tools check fails on the NIM only, record it (tool-calling flag is an open
item); do not change NIM flags under the clock unless more than 45 min remain before T+4:15.

### 3.9 Failure injection, rollback, roll forward (T+3:40)
1. Failure injection PR: `git fetch origin && git checkout -b session/gpu-fail origin/main && sed -i '' 's/^  replicas: 1$/  replicas: 0/' lab/gpu/nim/nimservice.yaml`,
   commit, push, PR, merge. Then:
   ```bash
   kubectl -n raglab-gpu wait --for=delete pod -l app.kubernetes.io/component=nim-llm --timeout=5m
   argocd app sync raglab-apps/raglab-dev-gpu || true
   kubectl -n raglab-dev-gpu logs job/smoke | tail -40 | tee $RG/evidence/smoke-nim-down.txt
   ```
   Expect chat/stream/tools FAIL with an upstream/connection error and a non-zero exit: the gate detects a dead backend.
2. Rollback PR: `git fetch origin && git checkout -b session/gpu-rollback origin/main && git revert --no-edit <CUT>`,
   then `uv run --with pyyaml python3 lab/catalogue/generate.py --check` (exit 0), push, PR, merge. Then:
   ```bash
   argocd app wait raglab-apps/raglab-dev-gpu --operation --timeout 600
   kubectl -n raglab-dev-gpu logs job/smoke | tail -40 | tee $RG/evidence/smoke-rollback-hosted.txt   # nvidia-hosted/chat/small, 0 failed
   kubectl -n raglab-gpu get nimcache llama-8b -o jsonpath='{.status.state}{"\n"}'                      # Ready (cache survived)
   kubectl -n raglab-gpu get pvc                                                                       # Bound
   ```
3. Roll forward, only if it can finish before T+4:15: one PR that reverts the failure injection and the rollback
   (`git revert --no-edit <FAIL-merge> <ROLLBACK-merge>`), merge, then record the **warm-cache** cold start with the 3.6
   command (`| tee $RG/evidence/cold-start-warm.txt`) and the smoke tail (`smoke-rollforward.txt`).

### 3.10 Evidence and isolation probe (before terminating; 15 minutes at most, then section 5 regardless)
```bash
kubectl -n raglab-gpu get nimcache,nimservice -o yaml | python3 -c '
import sys, yaml
docs = yaml.safe_load(sys.stdin)
for d in docs["items"]:
    d["metadata"].pop("managedFields", None); (d["metadata"].get("annotations") or {}).pop("kubectl.kubernetes.io/last-applied-configuration", None)
yaml.safe_dump(docs, sys.stdout)' > $RG/evidence/nim-objects.yaml
argocd app list -o wide > $RG/evidence/argocd-apps.txt
kubectl -n argocd get secret sops-age-key -o jsonpath='{.data.keys\.txt}' | base64 -d | age-keygen -y | tee $RG/evidence/cmp-recipient.txt
kubectl get secrets -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,TYPE:.type --no-headers \
  | grep -v -e 'helm.sh/release' -e 'kubernetes.io/service-account-token' | tee $RG/evidence/secrets-inventory.txt
gssh ubuntu@$IP 'ip -br link | grep -Ei "tailscale|wg|tun|zt" || echo no-vpn-interface;
  for b in tailscale tailscaled wg openvpn zerotier-cli; do command -v $b; done; echo tools-checked;
  ls -a ~/.kube 2>/dev/null; sudo ls /root/.kube 2>/dev/null; echo kubeconfigs-checked' | tee $RG/evidence/isolation.txt
```
Expect: `cmp-recipient.txt` = exactly `age1lsw2ne59z5y02s074k2kmrqfda5tc363hvacn24v0g60x6n0hyqs5sd89v`;
the secrets inventory shows only Argo CD's own secrets, `sops-age-key`, `raglab-gpu/ngc-pull`, `raglab-gpu/ngc-api-key`,
`raglab-dev-gpu/bifrost-env`; `isolation.txt` shows `no-vpn-interface`, no tool paths, no kubeconfig listing.
Then go straight to section 5.

## 4. Abort (NO-GO, checkpoint missed, or anything unsafe)
1. Save whatever evidence exists (3.10 commands that still work; at least `list-model-profiles.txt`).
2. Section 5 immediately. Do not extend, do not try another profile, GPU type or image under the clock.
3. A second session may be scheduled from the findings; it starts again at section 1.

## 5. Teardown — TERMINATE FIRST
1. `python3 scripts/lambda.py terminate --yes --wait > $RG/evidence/terminate.txt; rc=$?; cat $RG/evidence/terminate.txt; echo exit=$rc` (expect `TERMINATED ... at <UTC>` and `exit=0`; any other exit: the console, NOW).
2. `python3 scripts/lambda.py instances > $RG/evidence/instances-after.txt; rc=$?; cat $RG/evidence/instances-after.txt; echo exit=$rc` (expect
   `live instances: 0  file systems: 0`, `exit=0`). Check the console too: no instance, no file system.
3. Kill the tunnel: `pkill -f 'L 6443:127.0.0.1:6443'`. The account firewall rule is a standing account setting and
   stays (it admits nothing without an instance); note it in the findings.
4. Billing has stopped. Everything below is after billing.

## 6. Key revocation and negative probes (same day, in this order)
1. **Session nvapi key:** revoke it in the NVIDIA/NGC console (revoke, not just expire). Then both must print `REJECTED`
   and exit 1 (exit 2 = inconclusive: retry later, it proves nothing):
   `skey | python3 scripts/key_probe.py hosted --chat meta/llama-3.1-8b-instruct; echo exit=$?` (without `--chat` the probe is INCONCLUSIVE by design: `/v1/models` answers without a key) and
   `skey | python3 scripts/key_probe.py nvcr --repo nim/meta/llama-3.1-8b-instruct --tag 2.1.7; echo exit=$?`
2. **Lambda API key:** delete the session key in the Lambda console, then
   `python3 scripts/lambda.py instances; echo exit=$?` must fail with `HTTP 401` (exit 3).
   Delete the `raglab-gpu-session` SSH key in the Lambda console.
3. **Delete session material** (this makes `lab/gpu/secrets/gpu.sops.yaml` permanently undecryptable):
   ```bash
   rm -f $SK/age-key.txt $SK/session-nvapi-key.age $SK/lambda-api-key.age && rmdir $SK
   rm -f ~/.ssh/raglab_gpu_ed25519 ~/.ssh/raglab_gpu_ed25519.pub
   ssh-keygen -R "$IP"; rm -f lab/bootstrap/kubeconfig.gpu $RG/inventory.ini; rm -rf $RG/argocd-config
   fc -ln 1 | grep -c -e nvapi- -e 'AGE-SECRET'     # 0 (zsh; bash: history | grep -c ...)
   ```
   Restart the home lab VM and run the Phase A regression (lab/README.md: session start, then the read-back).
   Keep `$RG/evidence/` until the findings are written (it holds no key), then `rm -rf $RG`.

## 7. Cleanup PRs (after billing has stopped)
Plan Task 19. Mandatory: remove the GPU rule from `.sops.yaml` and delete `lab/gpu/secrets/gpu.sops.yaml`. Default
(unless a second session is booked within two weeks): tag the last session commit `phase-b-session-1`, then revert the
shared files to Phase A and remove `lab/gpu/` and the Phase B scripts/tests.

## 8. Next-day bill check
1. Lambda console, Billing/Usage: the session's charge vs `(terminate time - launch time) x $1.99/h` from
   `launch.txt` and `terminate.txt`. Must be at most USD 15.
2. Console: no instance, no file system. Record both in the findings.

## 9. Fallback: GPU Operator without NRI (UNVERIFIED values; only if 04 fails on containerd/NRI)
Edit `lab/gpu/argocd/hand-applied/raglab-gpu-operator.yaml` locally: set `cdi: {enabled: true, nriPluginEnabled: false}`
and add under `toolkit`:
```yaml
toolkit:
  enabled: true
  env:
    - {name: CONTAINERD_CONFIG, value: /var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.tmpl}
    - {name: CONTAINERD_SOCKET, value: /run/k3s/containerd/containerd.sock}
    - {name: RUNTIME_CONFIG_SOURCE, value: "file=/var/lib/rancher/k3s/agent/etc/containerd/config.toml"}
```
add `{group: node.k8s.io, kind: RuntimeClass, name: nvidia}` to the `raglab-gpu-platform` whitelist, re-apply both files
with `kubectl apply --server-side -f`, and set `runtimeClassName: nvidia` on the NIMCache and NIMService in the go PR.
Commit the same change by PR afterwards (with `scripts/render-gpu-platform.sh` re-run). Record every value used.

## 10. Troubleshooting
- **kubectl: connection refused on 127.0.0.1:6443:** the SSH tunnel died; re-run the `gssh -f -N -L ...` line.
- **SSH times out:** the home address changed; fix the account firewall rule in the Lambda console (not from the VM).
- **Image pull `401` from nvcr.io:** `ngc-pull` missing or wrong: `kubectl -n raglab-gpu get secret ngc-pull` and the
  `raglab-gpu-secrets` app status; re-run pre-rent check 1.5.
- **`sops-kustomize: not permitted`:** only `raglab-apps_raglab-gpu-secrets` on `lab/gpu/secrets` may use the CMP.
- **NIM pod Pending with `Insufficient nvidia.com/gpu`:** another pod holds the GPU (gpu-check, list-model-profiles, or
  the NIMCache job): `kubectl -n raglab-gpu get pods`; delete the finished Jobs.
- **NIM startup probe kills the pod:** `failureThreshold 120 x 10 s` = 20 min; record the time and the logs.
- **Bifrost cannot reach the NIM but the probes pass:** check `lab/gpu/envs/dev-gpu/generated/config.json` base URL and
  `kubectl -n raglab-gpu get svc llama-8b`.
- **Bifrost rejects the nim-local key or the http base URL:** record the error; `custom_provider_config.is_key_less` is
  the alternative to test in a later session.
