# raglab operator runbook (Phase A)

Everything here is run from the repo root on the workstation unless a step says `hv-01`. Use only the lab kubeconfig:

```bash
export KUBECONFIG=$PWD/lab/bootstrap/kubeconfig     # gitignored; never use another context
export SOPS_AGE_KEY_FILE=$HOME/.sops/raglab-age-key.txt
```

The VM's LAN IP lives only in the gitignored `lab/bootstrap/inventory.ini`. Do not write it into any committed file or PR.
Argo CD's UI/API is reached with `argocd ... --port-forward --port-forward-namespace argocd --plaintext` (see 1.4).

> Status of this runbook: the Proxmox VM steps (section 2) were reconstructed from the run notes in
> `docs/raglab-phase-a-findings.md`, not replayed. The rebuild test (Task 11 Step 8) is still owed; fix any
> missing step by PR.

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
3. Log in to Argo CD (admin password is read into a shell variable, never printed):
   ```bash
   export ARGOCD_OPTS="--config $HOME/.config/argocd-raglab --port-forward --port-forward-namespace argocd --plaintext"
   PW=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)
   argocd login argocd-server --username admin --password "$PW"; unset PW
   ```
4. Check, hard refresh and sync each env app (smoke is a PostSync hook and only runs on sync):
   ```bash
   kubectl get applications -A
   for e in dev qa prod; do
     argocd app get raglab-apps/raglab-$e --hard-refresh >/dev/null
     argocd app sync raglab-apps/raglab-$e
   done
   for e in dev qa prod; do kubectl -n raglab-$e logs job/smoke | tail -20; done
   ```
5. Custom NIM health (kubectl does not show it; it lives in Argo's resource tree):
   ```bash
   for e in dev qa prod; do argocd app get raglab-apps/raglab-nim-$e -o json | python3 -c '
   import json,sys;a=json.load(sys.stdin)
   for r in a["status"]["resources"]:print(a["metadata"]["name"],r["name"],r.get("health"))'; done
   ```
   Expect `Healthy` / `scaled to zero (Phase A)`.
6. Handover probe (no Secret may carry `last-applied-configuration`): re-run the check in
   `lab/bootstrap/playbooks/03-handover.yml` with `cd lab/bootstrap && ansible-playbook playbooks/03-handover.yml`.

### Stop rule
Stop the lab VM immediately if, during a session, any of these hold: host IO PSI `some avg60` > 10, k8s-ctrl CPU steal
> 10%, or any homelab etcd alarm or leader change.
```bash
ssh hv-01 'cat /proc/pressure/io /proc/pressure/memory'     # check every ~15 min
```

### Stop
1. `ssh hv-01 'qm shutdown 101'` (the VM is `onboot: 0`; it stays off until you start it).

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
   pvesm add dir raglab --path /mnt/raglab --content images,iso --nodes hv-01
   pvesm status | grep raglab'
   ```
3. Download the Ubuntu 24.04 cloud image and VERIFY its checksum against Canonical's `SHA256SUMS` before use
   (the original build used a verified image; fetch both from cloud-images.ubuntu.com, `sha256sum -c`).
4. Create the VM (2 vCPU, 5 GiB, no ballooning, low CPU weight, IO caps, not started on boot), import the image
   to `raglab` storage, size the disk to 13G, add a cloud-init drive on the same storage, set `ciuser=ubuntu`, your
   SSH public key, and `ipconfig0 ip=dhcp`:
   ```bash
   ssh hv-01 'set -e
   qm create 101 --name raglab --cores 2 --memory 5120 --balloon 0 --cpuunits 50 --onboot 0 \
     --net0 virtio,bridge=vmbr0 --scsihw virtio-scsi-pci --ostype l26
   qm importdisk 101 /path/to/noble-server-cloudimg-amd64.img raglab
   qm set 101 --scsi0 raglab:101/vm-101-disk-0.raw,mbps_wr=50,iops_wr=500 --boot order=scsi0
   qm resize 101 scsi0 13G
   qm set 101 --ide2 raglab:cloudinit --ciuser ubuntu --sshkeys /path/to/pubkey --ipconfig0 ip=dhcp
   qm config 101 | grep -E "^(cores|memory|cpuunits|onboot|scsi0|balloon)"'
   ```
   Adjust the bridge name and image/key paths to hv-01. Expect `cores: 2`, `memory: 5120`, `cpuunits: 50`,
   `onboot: 0`, disk on `raglab:` with `mbps_wr=50,iops_wr=500`.
   Do NOT add the VM to any vzdump backup job. Do NOT snapshot it. The cloud image has no qemu-guest-agent.
5. Start it and find its address from your DHCP server's lease table (no guest agent):
   ```bash
   ssh hv-01 'qm start 101'
   ```
   Make the lease stable (DHCP reservation) if you can.

### 2.2 Workstation prerequisites
1. Lab age key present: `ls -l ~/.sops/raglab-age-key.txt` (mode 600, holds an `AGE-SECRET-KEY-` line). If lost, see
   the "Loss recovery" bullet in the spec Secrets section (new key, `sops updatekeys`, reissue secrets).
2. Tools: `ansible`, `kubectl`, `helm`, `sops`, `argocd`.
3. Inventory (gitignored): `cd lab/bootstrap && cp inventory.example.ini inventory.ini`, then replace
   `<LAN IP of the lab VM>` with the VM's IP. Verify `ssh ubuntu@<ip>` works first (accept the host key).

### 2.3 Run the playbooks (run directory: `lab/bootstrap`)
`ansible.cfg` there points at `inventory.ini`, so always `cd lab/bootstrap` first.
1. k3s (pinned, checksum-verified, secrets encryption) and kubeconfig fetch (writes `lab/bootstrap/kubeconfig`, 0600):
   ```bash
   cd lab/bootstrap && ansible-playbook playbooks/01-platform.yml
   KUBECONFIG=$PWD/kubeconfig kubectl get nodes
   ```
   Expect one node `Ready` and "Verify secrets encryption" `ok`.
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
   `ansible-playbook playbooks/03-handover.yml -e '{"handover_allow_unhealthy":["raglab-dev","raglab-qa","raglab-prod"]}'`
4. Do a session start (1.4) to sync and read smoke.

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
6. If chat returns 404 from upstream, set `upstream.base_url` in the catalogue to
   `https://integrate.api.nvidia.com/v1`, regenerate (`lab/catalogue/generate.py`) and PR.
7. Open item: replace `--expect-limit "rate limit"` with the Bifrost-specific marker `"is_bifrost_error":true` once a real
   gateway 429 confirms it.
8. Copy the lab age key into your password manager.

## 4. Promotion (dev -> qa -> prod)
Apps track: dev = `main`, qa = `env/qa`, prod = `env/prod`. Everything (base, catalogue, generated config) moves
together because it is the same commit.
1. Change on `main` by PR (example: `environments.dev.requests_per_minute` 30 -> 28 in the catalogue, regenerate). Merge.
2. Sync dev (1.4). Dev Bifrost rolls (new ReplicaSet, new ConfigMap hash). Get evidence and the SHA:
   ```bash
   SHA=$(git rev-parse origin/main)
   kubectl -n raglab-dev logs job/smoke | tail -40       # must show revision=$SHA and 0 failed
   ```
3. PR `main` -> `env/qa`:
   ```bash
   gh pr create --base env/qa --head main --title "promote $SHA to qa" --body-file .github/pull_request_template.md
   ```
   Fill the template: the SHA, the redacted dev smoke tail (no IPs or hostnames), and tick the boxes. Merge; sync qa.
4. Same again for `env/qa` -> `env/prod` using the QA smoke tail for the same SHA.
5. This gate is attested, not enforced. A failed prod smoke means: revert PR on `env/prod`, re-sync.
6. "Healthy" in Argo is not evidence; only the smoke report with the matching `revision=` is.
7. Known open question: whether a rate-limit change propagates to existing Bifrost limit rows (rows are runtime-owned).
   Check `config read-back` after step 2.

## 5. NVIDIA key rotation
1. Create the new key at NVIDIA (same scope; shortest expiry).
2. `sops edit lab/secrets/<env>.sops.yaml` -> PR -> merge. `raglab-secrets` syncs.
3. `kubectl -n raglab-<env> rollout restart deploy/bifrost`, sync the env, smoke must PASS.
4. Revoke the OLD key at NVIDIA.
5. Negative probe with the old key read from a file, expecting failure (never put the key on argv):
   ```bash
   OLD=$(cat /path/to/old-key-file) python3 lab/smoke/smoke.py --base-url https://integrate.api.nvidia.com/v1 \
     --api-key-env OLD --model z-ai/glm-5.3-flash --skip stream --skip tools --skip models   # must FAIL (401/403)
   ```
   Also, for a Bifrost virtual-key rotation, probe the old VK is refused:
   `python3 lab/smoke/smoke.py ... --header-env x-bf-vk=OLD_VK` expecting failure.

## 6. Age-key rotation (two-phase) and leak response
Committed ciphertext is public forever. A compromised age key means rotating EVERY secret ever encrypted to it
(NVIDIA key, Bifrost keys, admin passwords), not just the key.

### Leak response (revoke first)
1. Revoke the NVIDIA key at NVIDIA. Rotate every Bifrost secret value. Then do the rotation below.
2. Scan: `scripts/safety-check.sh`; check GitHub secret-scanning alerts.

### Two-phase rotation
1. Generate the new key: `age-keygen -o ~/.sops/raglab-age-key-new.txt` (do not overwrite the old one).
2. Phase 1, add recipient: add the new public key to the recipients in `.sops.yaml`, then
   `for e in dev qa prod; do sops updatekeys -y lab/secrets/$e.sops.yaml; done`. PR and merge.
3. Put BOTH identities into the cluster Secret (the playbook creates `sops-age-key` only if absent, so delete first),
   concatenating both key files into one `keys.txt`:
   ```bash
   cat ~/.sops/raglab-age-key.txt ~/.sops/raglab-age-key-new.txt > /private/tmp/raglab-both.txt   # chmod 600; delete after
   kubectl -n argocd delete secret sops-age-key
   kubectl -n argocd create secret generic sops-age-key --from-file=keys.txt=/private/tmp/raglab-both.txt
   kubectl -n argocd rollout restart deploy/argocd-repo-server
   rm -P /private/tmp/raglab-both.txt
   ```
4. Verify: hard refresh and sync `raglab-secrets`; it must stay Synced/Healthy.
5. Phase 2, remove the old recipient: edit `.sops.yaml`, `sops updatekeys -y` for each env file, PR, merge. Recreate
   the cluster Secret with only the new key (as in step 3 with the new file alone), restart repo-server, verify sync.
6. Replace `~/.sops/raglab-age-key.txt` with the new key, update the password manager and the core-01 backup
   (`~/.homelab-backup/`). In a leak case, also reissue all secret values (history stays decryptable with the old key).

## 7. Teardown checklist (from the spec)
Delete Applications (with resource finalizers) or simply destroy the VM.
- **Proxmox:** remove the `raglab` storage definition and LV (see below).
- **Workstations:** remove kubeconfig contexts and known_hosts entries.
- **NVIDIA:** **revoke** the key(s). This is MANDATORY.
- **Age key:** retire the lab key (keep the backup only if the history should stay decryptable).
- **Phase B only:** tailnet device and auth key.

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
- **`ansible-playbook` cannot find the inventory:** run from `lab/bootstrap` (relative `inventory.ini`).
