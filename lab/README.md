# raglab operator runbook (Phase A)

Everything here is run from the repo root on the workstation unless a step says `hv-01`. Use only the lab kubeconfig:

```bash
export KUBECONFIG=$PWD/lab/bootstrap/kubeconfig     # gitignored; never use another context
export SOPS_AGE_KEY_FILE=$HOME/.sops/raglab-age-key.txt
```

The VM's LAN IP lives only in the gitignored `lab/bootstrap/inventory.ini`. Do not write it into any committed file or PR.
Argo CD's UI/API is reached with `argocd ... --port-forward --port-forward-namespace argocd --plaintext` (see 1.3).

> Status of this runbook: rebuild-tested on 2026-11-25 (VM destroyed and rebuilt from this file alone, about 16 min;
> the 9 defects found are fixed here). Fix any further missing step by PR.

## 1. Session start / stop

### Start
1. Precheck on hv-01 (read-only). Need root fs >= 20G free, `pve` VG free, PSI `some avg60` near 0:
   ```bash
   ssh hv-01 'df -h / | tail -1; vgs --noheadings -o vg_name,vg_free pve; cat /proc/pressure/io /proc/pressure/memory | head -2; qm list | grep -c running'
   ```
   Do not start the lab if the precheck is bad.
2. Start the VM and wait for k3s:
   ```bash
   ssh hv-01 'qm start 101'
   until kubectl get nodes 2>/dev/null | grep -q ' Ready'; do sleep 10; done
   ```
3. Log in to Argo CD (needs the lab `KUBECONFIG` exported at the top of this file; admin password is read into a shell variable, never printed):
   ```bash
   export ARGOCD_OPTS="--config $HOME/.config/argocd-raglab --port-forward --port-forward-namespace argocd --plaintext"
   PW=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)
   argocd login argocd-server --username admin --password "$PW"; unset PW
   ```
   Caveat: `--password` puts the password on this process's argv for the length of the command (visible to `ps` for any
   local user on the workstation). Acceptable on a single-user workstation; otherwise run `argocd login` without
   `--password` and type it at the prompt.
4. Check, hard refresh and sync each env app (smoke is a PostSync hook and only runs on sync; needs 1.3 done and
   `ARGOCD_OPTS` exported in this shell; the dev hook can take ~3 min, so `argocd app sync` may look hung). If an auto-sync is
   already running (a commit just landed), wait for it before syncing manually (`argocd app wait`), or the two
   operations collide:
   ```bash
   kubectl get applications -A
   for e in dev qa prod; do
     argocd app get raglab-apps/raglab-$e --hard-refresh >/dev/null
     argocd app wait raglab-apps/raglab-$e --operation --timeout 300
     argocd app sync raglab-apps/raglab-$e
   done
   for e in dev qa prod; do kubectl -n raglab-$e logs job/smoke | tail -20; done
   ```
   If `limit-429` fails with codes like `[200,200,200]` ("no 429 after request 2"), the probe key's 1-minute window rolled
   over mid-burst. Re-sync that env once before investigating.
5. Custom NIM health (kubectl does not show it; it lives in Argo's resource tree):
   ```bash
   for e in dev qa prod; do argocd app get raglab-apps/raglab-nim-$e -o json | python3 -c '
   import json,sys;a=json.load(sys.stdin)
   for r in a["status"]["resources"]:print(a["metadata"]["name"],r["name"],r.get("health"))'; done
   ```
   Expect `Healthy` / `scaled to zero (Phase A)`.

   **Every commit to a tracked branch restarts Bifrost and reruns smoke.** The revision annotation reaches the pod
   template, so every commit to `main` (dev), `env/qa` or `env/prod` rolls that env's Bifrost and reruns the smoke hook.
   That costs real NVIDIA calls per commit and can trip the probe key's limit within 60 s. Do not push a burst of
   commits to a tracked branch; batch them.
6. Before re-running any bootstrap playbook, review what changed since the last bootstrap (hand-applied files become
   live on re-run). Record the bootstrap SHA when you run it, then:
   ```bash
   git fetch origin && git diff <bootstrap-sha>..origin/main -- lab/argocd/hand-applied lab/argocd/argocd-values.yaml lab/bootstrap
   ```
7. Handover probe (no Secret may carry `last-applied-configuration`): re-run the check in
   `lab/bootstrap/playbooks/03-handover.yml` with `cd lab/bootstrap && ansible-playbook playbooks/03-handover.yml`.
8. Rate-limit read-back for all three envs (is the live value what the catalogue says? details in 4.1):
   ```bash
   for E in dev qa prod; do
     kubectl -n raglab-$E port-forward svc/bifrost 18080:80 >/dev/null 2>&1 & PF=$!; sleep 3
     BF_USER=$(kubectl -n raglab-$E get secret bifrost-env -o jsonpath='{.data.BIFROST_ADMIN_USER}' | base64 -d)
     BF_PASS=$(kubectl -n raglab-$E get secret bifrost-env -o jsonpath='{.data.BIFROST_ADMIN_PASSWORD}' | base64 -d)
     printf 'user = "%s:%s"\n' "$BF_USER" "$BF_PASS" | curl -s --config - http://127.0.0.1:18080/api/governance/rate-limits \
       | python3 -c 'import json,sys;[print(r["id"],r.get("request_max_limit")) for r in json.load(sys.stdin)["rate_limits"]]'
     unset BF_USER BF_PASS; kill $PF
   done
   ```
   Expect `rl-<env>` = the catalogue value (28) and `rl-<env>-probe` = 2.

### Stop rule
Stop the lab VM immediately if, during a session, any of these hold: host IO PSI `some avg60` > 10, k8s-ctrl CPU steal
> 10%, or any homelab etcd alarm or leader change.
```bash
ssh hv-01 'cat /proc/pressure/io /proc/pressure/memory'     # check every ~15 min
```

### Stop
1. `ssh hv-01 'qm shutdown 101 --timeout 90 || qm stop 101'` (the VM is `onboot: 0`; it stays off until you start it).
   The fallback covers a missing guest agent: with `agent: 1` and no qemu-guest-agent, `qm shutdown` fails after ~45 s
   with "VM quit/powerdown failed" and the VM keeps running.

## 2. Bootstrap from scratch

### 2.1 VM on hv-01 (OWNER, root on hv-01)
The VM is NOT cloned from template 9001 (its disk is 20G) and NOT on nested LVM (refused). It is built from the
Ubuntu 24.04 cloud image on dir storage backed by a dedicated ext4 LV.
1. Precheck: step 1.1 above.
2. Dedicated LV, formatted ext4, mounted via fstab (`nofail`), registered as dir storage restricted to hv-01:
   ```bash
   ssh hv-01 'set -e
   lvcreate -L 14G -n raglab pve
   mkfs.ext4 -m0 /dev/pve/raglab
   mkdir -p /mnt/raglab
   echo "/dev/pve/raglab /mnt/raglab ext4 defaults,nofail 0 2" >> /etc/fstab
   mount /mnt/raglab
   pvesm add dir raglab --path /mnt/raglab --is_mountpoint yes --content images,iso --nodes hv-01
   pvesm status | grep raglab'
   ```
3. Download the Ubuntu 24.04 cloud image and VERIFY its checksum against Canonical's `SHA256SUMS` before use. Keep the
   image off `/mnt/raglab` (14G). `sha256sum -c` must print `noble-server-cloudimg-amd64.img: OK`:
   ```bash
   ssh hv-01 'mkdir -p /root/raglab-img && cd /root/raglab-img &&
     curl -fsSLO https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img &&
     curl -fsSLO https://cloud-images.ubuntu.com/noble/current/SHA256SUMS &&
     sha256sum -c SHA256SUMS --ignore-missing'
   scp -O ~/.ssh/id_ed25519.pub hv-01:/root/raglab-img/pubkey    # --sshkeys needs the file on hv-01
   ```
4. Create the VM (2 vCPU, 5 GiB, no ballooning, low CPU weight, IO caps, not started on boot), import the image
   to `raglab` storage, size the disk to 13G, add a cloud-init drive on the same storage, set `ciuser=ubuntu`, your
   SSH public key, and `ipconfig0 ip=dhcp`:
   ```bash
   ssh hv-01 'set -e
   qm create 101 --name raglab --cores 2 --memory 5120 --balloon 0 --cpuunits 50 --onboot 0 \
     --net0 virtio,bridge=vmbr0 --scsihw virtio-scsi-pci --ostype l26 --agent 1
   qm importdisk 101 /root/raglab-img/noble-server-cloudimg-amd64.img raglab --format raw
   qm set 101 --scsi0 raglab:101/vm-101-disk-0.raw,mbps_wr=50,iops_wr=500 --boot order=scsi0
   qm resize 101 scsi0 13G
   qm set 101 --ide2 raglab:cloudinit --ciuser ubuntu --sshkeys /root/raglab-img/pubkey --ipconfig0 ip=dhcp
   qm config 101 | grep -E "^(cores|memory|cpuunits|onboot|scsi0|balloon)"'
   ```
   Adjust the bridge name to hv-01. Expect `cores: 2`, `memory: 5120`, `cpuunits: 50`, `agent: 1`, disk on `raglab:`
   with `mbps_wr=50,iops_wr=500`; `onboot` absent means 0 (the default is not printed).
   Do NOT add the VM to any vzdump backup job. Do NOT snapshot it. The cloud image has no qemu-guest-agent; with
   `--agent 1` the bootstrap (2.3 step 1) installs it. Until then `qm shutdown` fails (see Stop).
5. Start it and find its address (the guest agent is not running yet, so use the MAC; adjust the subnet):
   ```bash
   ssh hv-01 'qm start 101; qm config 101 | grep net0'      # note the MAC
   ssh hv-01 'for i in $(seq 1 254); do ping -c1 -W1 192.168.0.$i >/dev/null 2>&1 & done; wait; ip -4 neigh | grep -i <mac>'
   ssh-keygen -R <ip>      # drop any stale host key from a previous build
   ```
   Make the lease stable (DHCP reservation) if you can.

### 2.2 Workstation prerequisites
1. Lab age key present: `ls -l ~/.sops/raglab-age-key.txt` (mode 600, holds an `AGE-SECRET-KEY-` line). If lost, see
   the "Loss recovery" bullet in the spec Secrets section (new key, `sops rotate`, reissue secrets).
2. Clone, then install the hooks and verify them:
   ```bash
   scripts/install-hooks.sh && git config core.hooksPath     # must print .githooks
   ```
   Tools needed on the workstation: `python3`, `uv`, `gh`, `age` / `age-keygen`, `sops`, `gitleaks`, `kubectl`, `helm`,
   `ansible`, and the `argocd` CLI.
3. Inventory (gitignored): `cd lab/bootstrap && cp inventory.example.ini inventory.ini`, then replace
   `<LAN IP of the lab VM>` with the VM's IP. Verify `ssh ubuntu@<ip>` works first (accept the host key), then wait for
   first-boot cloud-init: `ssh ubuntu@<ip> 'cloud-init status --wait'` must print `status: done`. (sshd answers before
   cloud-init finishes; installing k3s too early fails with "D-Bus connection terminated". The playbook also waits, and
   re-running 01 is safe.)

### 2.3 Run the playbooks (run directory: `lab/bootstrap`)
`ansible.cfg` there points at `inventory.ini`, so always `cd lab/bootstrap` first.
1. k3s (pinned, checksum-verified, secrets encryption) and kubeconfig fetch (writes `lab/bootstrap/kubeconfig`, 0600):
   ```bash
   cd lab/bootstrap && ansible-playbook playbooks/01-platform.yml
   KUBECONFIG=$PWD/kubeconfig kubectl get nodes
   ```
   Expect one node `Ready` and "Verify secrets encryption" `ok`. The playbook also installs and enables
   `qemu-guest-agent` (so `qm shutdown` works once the VM is rebooted or the agent is started).
2. Namespaces, CMP plugin, repo-server egress policy, age-key Secret (created on the workstation, never logged),
   Argo CD (chart 10.18.3 = v3.6.2), locked `default` project, AppProjects, `raglab-system`, root app:
   ```bash
   ansible-playbook playbooks/02-argocd.yml
   ```
3. Handover (fails closed unless every required Application is Synced/Healthy, last operation Succeeded; waits ~20 min):
   ```bash
   ansible-playbook playbooks/03-handover.yml
   ```
   Until the NVIDIA key is real (section 3), the smoke hooks fail upstream with 401 and handover will report the env
   apps as not ready. Only then, and deliberately, allow them:
   `ansible-playbook playbooks/03-handover.yml -e '{"handover_allow_unhealthy":["raglab-apps/raglab-dev","raglab-apps/raglab-qa","raglab-apps/raglab-prod"]}'`
   (entries are `namespace/name`)
4. Do a session start (1.3 argocd login, then 1.4, with `ARGOCD_OPTS` exported) to sync and read smoke.

## 3. Adding the NVIDIA key (owner TODO)
Every env secret currently holds `NVIDIA_API_KEY=PENDING-...`. Use a Personal key scoped to the API catalog only, with the
shortest expiry that covers the lab (a separate key per env if quota allows).
1. Branch: `git checkout -b chore/nvidia-key main`
2. Edit (editor swap/undo off; never `export`/`echo` the key):
   ```bash
   for e in dev qa prod; do sops edit lab/secrets/$e.sops.yaml; done
   ```
3. `git add lab/secrets && git commit` (the pre-commit hook must pass), push, open a PR, wait for the `gates` check, merge.
4. `raglab-secrets` syncs (auto). Restart Bifrost so it reads the new value:
   ```bash
   for e in dev qa prod; do kubectl -n raglab-$e rollout restart deploy/bifrost; done
   ```
5. Sync each env (1.4) and read `kubectl -n raglab-<env> logs job/smoke | tail -20`. Expect `0 failed`,
   `[PASS] auth-negative`, `[PASS] limit-429`, `revision=<sha>`.
6. If chat returns 404 from upstream, set `providers.nvidia-hosted.base_url` in the catalogue to
   `https://integrate.api.nvidia.com/v1`, regenerate (`uv run --with pyyaml python3 lab/catalogue/generate.py`) and PR.
7. Done: `--expect-limit "rate limit violated for vk"` is Bifrost's governance message (verified live; `is_bifrost_error` is false on gateway 429s too, so it is not a usable marker). Former note: once a real
   gateway 429 confirms it.
8. Copy the lab age key into your password manager.

## 4. Promotion (dev -> qa -> prod)
Apps track: dev = `main`, qa = `env/qa`, prod = `env/prod`. Everything (base, catalogue, generated config) moves
together because it is the same commit.
1. Change on `main` by PR (example: `environments.dev.requests_per_minute` 30 -> 28 in the catalogue, regenerate). Merge.
2. Sync dev (1.4). Dev Bifrost rolls (it rolls on every commit, see 1.4). Evidence of a config change is that the
   `bifrost-config-<hash>` ConfigMap name changed (`kubectl -n raglab-dev get cm | grep bifrost-config`), plus the
   config read-back in section 4.1 below. Get the SHA:
   ```bash
   git fetch origin
   SHA=$(git rev-parse origin/main)
   kubectl -n raglab-dev logs job/smoke | tail -40       # must show revision=$SHA and 0 failed
   ```
3. PR `main` -> `env/qa`:
   ```bash
   gh pr create --base env/qa --head main --title "promote $SHA to qa" --body-file .github/pull_request_template.md
   ```
   Fill the template: the SHA, the redacted dev smoke tail (no IPs or hostnames), and tick the boxes. Merge with
   **"Create a merge commit"** (never squash, never rebase: a squash gives `env/qa` a new SHA, so the promoted SHA no
   longer matches the smoke evidence and the next promotion diverges). Sync qa.
4. Same again for `env/qa` -> `env/prod` using the QA smoke tail for the same SHA, again with "Create a merge commit".
   `env/*` branch protection has `strict: false` (keep the required `gates` check); with `strict: true` the second
   promotion blocks as "out of date".
5. This gate is attested, not enforced. A failed prod smoke means: revert PR on `env/prod`, re-sync.
6. "Healthy" in Argo is not evidence; only the smoke report with the matching `revision=` is.
7. Rate-limit changes DO propagate to the running governance rows when `source_of_truth` is `config.json` (verified live
   with the 30 -> 28 change). Still confirm with the read-back below after step 2.

### 4.1 Config read-back (is the live value what the catalogue says?)
Bifrost v2.6.0 management API (source: `transports/bifrost-http/handlers/governance.go` at ref `transports/v2.6.0`):
`GET /api/governance/rate-limits` (response `.rate_limits[]`, field `request_max_limit`) is VERIFIED live with admin
basic auth. `GET /api/governance/virtual-keys` returns `.virtual_keys[]`, each with `.rate_limit`;
`GET /api/governance/virtual-keys/{vk_id}` wraps its result in `{"virtual_key": {...}}`. If a call 404s, use the UI
(Governance -> Virtual Keys / Rate Limits) instead.
```bash
E=dev   # or qa / prod
kubectl -n raglab-$E port-forward svc/bifrost 18080:80 >/dev/null 2>&1 & PF=$!; sleep 3
BF_USER=$(kubectl -n raglab-$E get secret bifrost-env -o jsonpath='{.data.BIFROST_ADMIN_USER}' | base64 -d)
BF_PASS=$(kubectl -n raglab-$E get secret bifrost-env -o jsonpath='{.data.BIFROST_ADMIN_PASSWORD}' | base64 -d)
# curl reads the credential from stdin (--config -), so it never appears on argv or in output
printf 'user = "%s:%s"\n' "$BF_USER" "$BF_PASS" | curl -s --config - http://127.0.0.1:18080/api/governance/virtual-keys/vk-$E \
  | python3 -c 'import json,sys;v=json.load(sys.stdin)["virtual_key"];print(v.get("id"),(v.get("rate_limit") or {}).get("request_max_limit"))'
printf 'user = "%s:%s"\n' "$BF_USER" "$BF_PASS" | curl -s --config - http://127.0.0.1:18080/api/governance/rate-limits \
  | python3 -c 'import json,sys;[print(r["id"],r.get("request_max_limit")) for r in json.load(sys.stdin)["rate_limits"]]'
unset BF_USER BF_PASS; kill $PF
```
Compare `request_max_limit` with `lab/envs/$E/generated/config.json` (`rl-$E`).

## 5. NVIDIA key rotation
1. Create the new key at NVIDIA (same scope; shortest expiry).
2. `sops edit lab/secrets/<env>.sops.yaml` -> PR -> merge. `raglab-secrets` syncs.
3. `kubectl -n raglab-<env> rollout restart deploy/bifrost`, sync the env, smoke must PASS.
4. Revoke the OLD key at NVIDIA.
5. Negative probe with the old key read from a file, expecting failure (never put the key on argv):
   ```bash
   OLD=$(cat /path/to/old-key-file) python3 lab/smoke/smoke.py --base-url https://integrate.api.nvidia.com/v1 \
     --api-key-env OLD --model z-ai/glm-5.3-flash --skip stream --skip tools --skip models   # must FAIL
   ```
   Assert the failure is HTTP 401 or 403 specifically (the smoke output must show `401` or `403`), not a timeout, 429 or
   5xx: any other failure proves nothing about the key. Also, for a Bifrost virtual-key rotation, probe the old VK is refused:
   `python3 lab/smoke/smoke.py ... --header-env x-bf-vk=OLD_VK` expecting failure.

## 6. Age-key rotation and leak response
Committed ciphertext is public forever. `sops updatekeys` only changes who can unwrap the EXISTING data key; it does
not change the data key. So anyone holding the old age key plus the public git history can still decrypt the new
values if the data key was never rotated. The fix is `sops rotate` (generates a NEW data key and re-encrypts every value).
Verified with `sops 3.11.0`: `sops rotate --help` lists `--in-place/-i`, `--add-age` and `--rm-age`.

### Leak response (old key compromised)
Order matters. Do NOT enter new values until the data key has been rotated, or the new values are encrypted under a
data key the old-key holder can already unwrap.
1. Revoke the NVIDIA key at NVIDIA first.
2. Generate a new age key into a NEW file (never overwrite the old one):
   ```bash
   age-keygen -o ~/.sops/raglab-age-key-new.txt
   NEW=$(grep -o 'age1[a-z0-9]*' ~/.sops/raglab-age-key-new.txt | head -1)    # public key
   OLD=$(grep -o 'age1[a-z0-9]*' ~/.sops/raglab-age-key.txt | head -1)
   ```
3. Per env, rotate to a NEW data key and swap recipients (also update `.sops.yaml` to list only `$NEW`):
   ```bash
   for e in dev qa prod; do
     SOPS_AGE_KEY_FILE=$HOME/.sops/raglab-age-key.txt sops rotate -i --add-age "$NEW" --rm-age "$OLD" lab/secrets/$e.sops.yaml
   done
   ```
4. Only THEN enter the new values (new NVIDIA key, new Bifrost encryption key, admin credentials, VKs), decrypting
   with the new key:
   ```bash
   for e in dev qa prod; do SOPS_AGE_KEY_FILE=$HOME/.sops/raglab-age-key-new.txt sops edit lab/secrets/$e.sops.yaml; done
   ```
5. Swap the cluster `sops-age-key` Secret to the new key (delete and create from the file; the value is never printed
   and never passed on argv; the playbook only creates it if absent):
   ```bash
   kubectl -n argocd delete secret sops-age-key
   kubectl -n argocd create secret generic sops-age-key --from-file=keys.txt=$HOME/.sops/raglab-age-key-new.txt
   kubectl -n argocd rollout restart deploy/argocd-repo-server
   ```
6. PR and merge (hook and `gates` must pass), verify `raglab-secrets` and the env apps sync, then restart Bifrost so it
   reads the new Secret: `for e in dev qa prod; do kubectl -n raglab-$e rollout restart deploy/bifrost; done`. Smoke must PASS.
7. Replace `~/.sops/raglab-age-key.txt` with the new key, update the password manager, keep the offline backup in the
   owner's private location current, and run `scripts/safety-check.sh`; check GitHub secret-scanning alerts.

### Routine age-key rotation (old key NOT compromised)
Same mechanism, with a two-phase cluster cutover so the repo-server can decrypt at every step. Every file edit uses
`sops rotate -i` (new data key), not `updatekeys` alone.
1. Generate the new key into a new file (as above).
2. Phase 1, add the recipient and rotate the data key: add the new public key to `.sops.yaml`, then
   `for e in dev qa prod; do sops rotate -i --add-age "$NEW" lab/secrets/$e.sops.yaml; done`. PR and merge.
3. Put BOTH identities into the cluster Secret (delete first), combined in a private temp file:
   ```bash
   ( umask 077; f=$(mktemp); cat ~/.sops/raglab-age-key.txt ~/.sops/raglab-age-key-new.txt > "$f"
     kubectl -n argocd delete secret sops-age-key
     kubectl -n argocd create secret generic sops-age-key --from-file=keys.txt="$f"
     rm -f "$f" )
   kubectl -n argocd rollout restart deploy/argocd-repo-server
   ```
4. Verify: hard refresh and sync `raglab-secrets`; it must stay Synced/Healthy.
5. Phase 2, remove the old recipient: `sops rotate -i --rm-age "$OLD" lab/secrets/$e.sops.yaml` for each env, update
   `.sops.yaml`, PR, merge. Recreate the cluster Secret with only the new key, restart repo-server, verify sync.
6. Replace `~/.sops/raglab-age-key.txt` with the new key and update the password manager and the offline backup
   (owner's private location).

## 7. Teardown checklist (from the spec)
Delete Applications (with resource finalizers) or simply destroy the VM.
- **Proxmox:** remove the `raglab` storage definition and LV (see below).
- **Workstations:** remove kubeconfig contexts and known_hosts entries.
- **NVIDIA:** **revoke** the key(s). This is MANDATORY.
- **Age key:** retire the lab key (keep the backup only if the history should stay decryptable).
- **Phase B:** a standalone rented cluster; its teardown is lab/gpu/README.md sections 5-8 (no tailnet).

Proxmox detail (OWNER, hv-01):
1. `ssh hv-01 'qm stop 101; qm destroy 101 --purge'`
2. `ssh hv-01 'pvesm remove raglab'`
3. `ssh hv-01 'umount /mnt/raglab && sed -i "\#/dev/pve/raglab#d" /etc/fstab && lvremove -y pve/raglab'`
4. `ssh hv-01 'vgs pve; grep raglab /etc/fstab; pvesm status'`: confirm the 14G is back in the `pve` VG and no `raglab` line remains.
5. Workstation: `rm -f lab/bootstrap/kubeconfig`, `ssh-keygen -R <vm-ip>`, clear `inventory.ini`.

## 8. Troubleshooting (known issues)
- **Smoke chat/stream/tools fail with upstream 401:** the NVIDIA key is still `PENDING-...` (section 3). `limit-429` cannot be
  judged until requests 1 and 2 return 200.
- **Bifrost pods fail on missing `bifrost-env`:** `raglab-secrets` needs a destination namespace (fixed; keep it).
- **Bifrost denies every request:** virtual keys deny all upstream keys unless `key_ids: ["*"]` or explicit ids are set. A
  schema-valid config can still fail at runtime.
- **Bifrost CrashLoop / entrypoint loops forever:** never pass container `args`; unknown flags make `docker-entrypoint.sh`
  loop. Use `APP_*` env vars.
- **Bifrost logs prompt content:** `disable_content_logging` defaults to false; the catalogue must set it true.
- **A merged Application escaped its project:** Argo's built-in `default` project allows everything; it is locked by
  bootstrap (`--force-conflicts` is required to take it over). Child apps live in `raglab-apps`; only project `raglab`
  has `sourceNamespaces: [raglab-apps]`.
- **`sops-kustomize` "not permitted for ...":** the CMP guard only allows `raglab-apps_raglab-secrets` on path
  `lab/secrets`. With apps-in-any-namespace, `ARGOCD_APP_NAME` is `<ns>_<name>`.
- **`argocd` namespace missing/unlabelled:** it is created by `lab/argocd/hand-applied/namespaces.yaml` (PSS `restricted`).
- **NIMService shows `NotReady` in kubectl:** expected (replicas 0). Argo's custom health shows Healthy "scaled to zero
  (Phase A)"; read it from Argo (1.5), not kubectl.
- **NIM operator upgrades are outages** for single-replica NIMs (`maxSurge: 0`), the operator's default image is the
  floating `release-3.0` tag (pinned by digest here), and its ClusterRole can read every Secret: change operator values
  only by hand-apply, never via an auto-synced path.
- **`argocd` CLI says "not configured with SSO" / dial proxy refused:** use `--port-forward --port-forward-namespace argocd
  --plaintext` (the server serves plain HTTP behind the port-forward); `--core` fails here.
- **Env apps fail first sync (CRDs missing):** they use `SkipDryRunOnMissingResource` and retry; wait for `raglab-system`.
- **VM won't start after reboot of hv-01:** the fstab line is `nofail`; check `mount | grep raglab` and `pvesm status`.
- **`qm shutdown 101` fails ("VM quit/powerdown failed") after ~45 s:** `agent: 1` is set but qemu-guest-agent is not
  running in the guest. Use `qm shutdown 101 --timeout 90 || qm stop 101`; the bootstrap installs the agent.
- **`01-platform.yml` fails at "Install k3s server" with "D-Bus connection terminated":** first-boot cloud-init was still
  running. `ssh ubuntu@<ip> 'cloud-init status --wait'`, then re-run (safe).
- **`scp` to hv-01 fails with a protocol error from macOS:** use `scp -O`.
- **`install-hooks.sh` leaves an untracked `.githooks/`:** expected on a fresh clone (hooks path config is local).
- **`ansible-playbook` cannot find the inventory:** run from `lab/bootstrap` (relative `inventory.ini`).
