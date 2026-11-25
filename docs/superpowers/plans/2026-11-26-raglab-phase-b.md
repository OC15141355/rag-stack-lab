# raglab Phase B Implementation Plan (one rented A100, standalone cluster, one real NIM)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Steps marked **[SESSION]** are run by the repo owner: they touch session keys, the Lambda account, NGC/NVIDIA
> consoles, or the rented VM, or they spend GPU money. Agents never perform, simulate or skip them; they stop and hand
> over. Agents open PRs; **only the owner merges**. Agents do not spawn subagents for this plan.

**Goal:** Rehearse the operator migration on real hardware: rent ONE Lambda A100 40GB for at most 5 hours, bootstrap a
standalone single-node k3s from this repo (same playbooks, `gpu_session=true`), run GPU Operator + NIM Operator, one
`NIMCache` and one `NIMService` (Llama 3.1 8B), cut the `dev-gpu` Bifrost from the hosted provider to the in-cluster NIM
and back, record cold start, then terminate and prove nothing is left running, billing or credentialed. The home lab
(dev/qa/prod) is untouched.

**Architecture:** Spec: [`docs/superpowers/specs/2026-11-25-raglab-phase-b-gpu-design.md`](../specs/2026-11-25-raglab-phase-b-gpu-design.md)
(rev 2) and its [fact-check](../specs/2026-11-25-raglab-phase-b-factcheck.md). All GPU material lives in new paths
(`lab/gpu/...`, new scripts/tests); the rented cluster's Argo root watches `lab/gpu/argocd/apps` only and the home lab's
root watches `lab/argocd/apps` only. Shared-file edits are minimal, CI-proven not to change Phase A (pinned sha256 of the
generated Phase A config, executed playbook runs in both modes), and reverted after the session. Order:
1. **Pre-rent (Tasks 1-8):** agents build, CI tests, owner merges to `main` **before** renting.
2. **Session (Tasks 9-20) [SESSION]:** rent, bootstrap, go/no-go, NIMCache, NIMService, cutover, rollback, cold start,
   terminate first, revoke, clean up, next-day bill check.
3. **Final (Task 21):** findings doc.

**Tech Stack:** Lambda Cloud on-demand (API v1) · k3s v1.37.2+k3s1 · Argo CD 3.6.2 (chart `argo-cd` 10.18.3) ·
NVIDIA GPU Operator v26.7.3 (NRI/CDI path) · NIM Operator 3.1.4 · NIM `meta/llama-3.1-8b-instruct` 2.1.7 ·
Bifrost v2.6.0 · sops 3.13.3 + age · kustomize · Ansible (ansible-core in CI) · Helm 4 (render checks) ·
Python 3.11+ stdlib/PyYAML (uv) · gitleaks 8.30.0 · GitHub Actions.

## Global Constraints

- **Provider:** Lambda on-demand **`gpu_1x_a100_sxm4`** (A100 40GB SXM4, USD 1.99/h; us-east-1 / us-west-2) or
  **`gpu_1x_a100`** (PCIe, us-south-2). Per-minute billing; **terminate is the only stop**. No file systems, ever.
- **Lambda API:** base `https://cloud.lambda.ai/api/v1/`, `Authorization: Bearer <key>`, a **non-Python User-Agent**
  (`raglab-lambda-helper/1.0`; Cloudflare 1010 blocks urllib's default). Key file
  `~/.sops/raglab-gpu-session/lambda-api-key.age`, decrypted with `age -d` **only into a local process**, never printed,
  never on argv, **never sent to the VM**.
- **Access:** the Lambda **account firewall already allows TCP 22 and ICMP only from the owner's home IP** (never write
  the IP to the repo, a PR or a commit). Session SSH key `~/.ssh/raglab_gpu_ed25519`, registered at Lambda as
  **`raglab-gpu-session`**; user `ubuntu`; no agent forwarding; the k3s API is reached through an SSH tunnel.
- **Session age key:** `~/.sops/raglab-gpu-session/age-key.txt`, public
  `age1lsw2ne59z5y02s074k2kmrqfda5tc363hvacn24v0g60x6n0hyqs5sd89v`. The **Phase A lab age key**
  (`~/.sops/raglab-age-key.txt`, `age14c2r6yt9qlvj2mdl7k4hdg2rfpcga8ehpt4dnahfx2l8dvkdm50syjrs65`) never leaves the Mac
  and is never used for GPU secrets.
- **Session nvapi key:** `~/.sops/raglab-gpu-session/session-nvapi-key.age` (age-encrypted to the session key). One key
  serves the hosted API (`NVIDIA_API_KEY`), `NGC_API_KEY` and the nvcr.io pull (`$oauthtoken`); it is entitled to the NIM.
- **NIM image:** `nvcr.io/nim/meta/llama-3.1-8b-instruct:2.1.7@sha256:5ada92d1ca5c30069956e6e1322f0fbb250b4683b566aedb6547b10a64faf00b`.
  Expected profile: `vllm-bf16-tp1-pp1` (pinned ID filled at the go/no-go).
- **NIM Operator** chart `k8s-nim-operator` **3.1.4** from `https://helm.ngc.nvidia.com/nvidia`, image
  `nvcr.io/nvidia/cloud-native/k8s-nim-operator:v3.1.4@sha256:3f84870acea8af063573898e6e2496379cc11c9e63046c073b1f8a6dc348f209`
  (values identical to Phase A's `raglab-system`).
- **GPU Operator** chart **`gpu-operator`** version **`v26.7.3`** from `https://helm.ngc.nvidia.com/nvidia`;
  `driver.enabled=false`, `toolkit.enabled=true`, `cdi.enabled=true`, `cdi.nriPluginEnabled=true`, NFD on, DCGM/DCGM
  exporter/MIG manager/node-status exporter off, **no k3s containerd variables, no `nvidia` RuntimeClass, no
  `runtimeClassName`** on NIM CRs.
- **Rendered-chart summaries** (Helm v4.1.4, `scripts/render-gpu-platform.sh`): gpu-operator v26.7.3 SHA256
  `cb54957d282abefb6bc6cd0d5e9b2358af77a82ba4d5f6a5537e688e4c0dd71b`; k8s-nim-operator 3.1.4 SHA256
  `8bc2cfc8ec6d1859425f1abe49425e964bcf63bd8f2e68cd2152d5b01f230615`.
- **k3s v1.37.2+k3s1** (same binary/`install.sh` checksums as Phase A). GPU mode adds `--disable traefik --disable servicelb`.
  Containerd must be 1.7.30+ (1.7 line) or 2.1+ and expose `/var/run/nri/nri.sock` (gated by `04-gpu-prep.yml`).
- **Argo CD** chart `argo-cd` **10.18.3** (v3.6.2) with the unchanged `lab/argocd/argocd-values.yaml`.
- **Bifrost** `maximhq/bifrost:v2.6.0@sha256:5968d007ba4f74ee01bc4ceb071decb9927a0b7bb43dbb9072208f75e2d522e3` (base unchanged).
  Probe pods use `python:3.12-slim@sha256:a0e2dd78cc679ddfffea960fe45ecfcff9ac2f68d67917a0edfcde5c2100151b` (the smoke image).
- **Names:** namespaces `gpu-operator` (PSS privileged), `raglab-system` (baseline), `raglab-gpu` (enforce baseline,
  warn/audit restricted), `raglab-dev-gpu` (restricted), `raglab-apps`, `argocd` (restricted). NIMCache/NIMService
  `llama-8b`, Service `llama-8b:8000` (`expose.service.name`). Secrets `raglab-gpu/ngc-pull`
  (`kubernetes.io/dockerconfigjson`), `raglab-gpu/ngc-api-key` (`NGC_API_KEY`), `raglab-dev-gpu/bifrost-env`.
  Projects `raglab-gpu`, `raglab-gpu-platform`, `raglab-gpu-root`; apps `raglab-gpu-root`, `raglab-gpu-operator`,
  `raglab-nim-operator`, `raglab-gpu-secrets`, `raglab-dev-gpu`, `raglab-gpu-nim` (added at go).
- **Phase A generated outputs are frozen** (sha256): dev/qa/prod `models.json` `102b320a…2e1c`; `config.json` dev
  `2c717f86…eb0`, qa `7c3c2e5b…11c`, prod `bc02c674…7a1` (full values in Task 4's test).
- **Budget:** session at most 5 h, hard cap USD 15 (expected about 10). **ABORT CHECKPOINT T+3:00**, **teardown starts
  T+4:15 regardless**, T+5:00 hard stop. Terminate before any tidy-up.
- **Session workspace** `~/.raglab-gpu/` (mode 700: inventory, evidence, Argo CLI config) is **outside the repo**.
- Public repo: no IPs, hostnames of the home environment, tokens, keys or employer data in any committed file or PR text.
- Never `Replace=true`. Every Secret-rendering Application uses `ServerSideApply=true`. The home lab VM stays stopped
  during the session (the rented cluster tracks `main`; session PRs are squash-merged).

---

## File map

```
.sops.yaml                                    + GPU rule FIRST (session recipient only)             [T1, reverted T19]
scripts/check_secrets.py                      + lab/gpu/secrets coverage, R7 recipients-follow-rule  [T1]
tests/test_check_secrets.py                   + 7 Phase B tests                                     [T1]
tests/test_sops_rules.py                      rule order / recipients                               [T1]
scripts/make_gpu_sops.py                      emit (age -d -> 3 Secrets -> stdout) / verify          [T2]
tests/test_make_gpu_sops.py                   fake-age tests, no real key                           [T2]
lab/gpu/secrets/kustomization.yaml            index of gpu.sops.yaml                                 [T2]
lab/gpu/secrets/gpu.sops.yaml                 [SESSION] encrypted to the session key only            [T2]
tests/fixtures/crds/apps.nvidia.com_nimcaches.yaml   vendored v3.1.4 CRD                             [T3]
lab/gpu/nim/{kustomization,nimcache,nimservice,networkpolicy}.yaml                                    [T3]
lab/gpu/gonogo/{list-profiles-job,gpu-check-job}.yaml   hand-applied Jobs                            [T3]
tests/test_gpu_manifests.py                   CRD validation, cache/service agreement, policies      [T3, +T5]
lab/catalogue/catalogue.yaml, generate.py     providers map, nim-local, chat/small, dev-gpu serving  [T4, reverted T19]
lab/gpu/envs/dev-gpu/generated/*.json         generated                                              [T4]
tests/test_generate.py                        + Phase A sha256 pins, dev-gpu tests                   [T4]
lab/README.md                                 catalogue key rename note                              [T4, T8]
scripts/helm_kinds.py, scripts/render-gpu-platform.sh   chart summaries for whitelists              [T5]
lab/gpu/argocd/hand-applied/*.yaml            namespaces, CMP, projects, operator apps, root         [T5]
lab/gpu/argocd/rendered/*.txt                 rendered-chart kind summaries + SHA256                 [T5]
lab/gpu/argocd/apps/{raglab-gpu-sops,raglab-dev-gpu}.yaml   child apps (raglab-gpu-nim at go)       [T5]
lab/gpu/envs/dev-gpu/{kustomization,networkpolicy-nim-egress}.yaml                                  [T5]
lab/gpu/probes/netpol-probes.yaml             hand-applied NetworkPolicy probes                       [T5]
tests/test_gpu_argocd.py                      bounds, whitelists == rendered, isolation               [T5]
lab/bootstrap/vars/{phase-a,gpu-session}.yml  mode values                                            [T6]
lab/bootstrap/playbooks/0{1,2,3}-*.yml        vars_files selector (Phase A behaviour pinned)         [T6, reverted T19]
lab/bootstrap/playbooks/04-gpu-prep.yml       GPU host gates + evidence                              [T6]
lab/bootstrap/inventory.gpu.example.ini       template, copied OUTSIDE the repo                       [T6]
lab/bootstrap/ansible.cfg                     drop empty `log_path =` (breaks pip ansible-core)       [T6, kept]
.github/workflows/ci.yml                      unit tests run with ansible-core                        [T6, reverted T19]
tests/test_playbooks.py                       values pinned + executed 02/03 runs in both modes       [T6]
scripts/lambda.py, scripts/key_probe.py       Mac-only helpers (stdlib)                               [T7]
tests/test_lambda_helper.py, tests/test_key_probe.py   mock-server tests                             [T7]
lab/gpu/README.md                             session runbook                                         [T8]
docs/raglab-phase-b-findings.md               findings                                                [T21]
```

Every pre-rent task starts on a fresh branch: `git fetch origin && git checkout -b <branch> origin/main` (branch names
are in each task's commit step). Tasks 1-8 merge in order; later tasks rely on earlier ones being on `main`.

---

### Task 1: SOPS rule for `lab/gpu/secrets` + structural-check coverage

**Files:**
- Modify: `.sops.yaml`, `scripts/check_secrets.py`, `tests/test_check_secrets.py`
- Create: `tests/test_sops_rules.py`

**Interfaces:**
- Produces: `.sops.yaml` rule 1 `^lab/gpu/secrets/[a-z0-9-]+\.sops\.yaml$` → session recipient only (placed before the
  Phase A rule); `check_secrets.py` treats `lab/gpu/secrets/` like `lab/secrets/` (R1-R3, R6) and adds **R7**: each
  secrets file's age recipients equal those of the first matching `.sops.yaml` rule.
- Consumed by: Task 2 (`sops encrypt --filename-override lab/gpu/secrets/gpu.sops.yaml`), CI `gates`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sops_rules.py`:
```python
"""The .sops.yaml rule order is a security boundary: the first matching rule wins."""
import re
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
PHASE_A = "age14c2r6yt9qlvj2mdl7k4hdg2rfpcga8ehpt4dnahfx2l8dvkdm50syjrs65"
SESSION = "age1lsw2ne59z5y02s074k2kmrqfda5tc363hvacn24v0g60x6n0hyqs5sd89v"
RULES = yaml.safe_load((ROOT / ".sops.yaml").read_text())["creation_rules"]

def first_match(path):
    return next((r for r in RULES if re.search(r["path_regex"], path)), None)

def test_gpu_secrets_go_to_session_key_only():
    r = first_match("lab/gpu/secrets/gpu.sops.yaml")
    assert r is RULES[0], "GPU rule must be placed before the Phase A rule"
    assert r["age"] == SESSION and PHASE_A not in r["age"]
    assert r["encrypted_regex"] == "^(data|stringData)$"

def test_phase_a_secrets_unchanged():
    for env in ("dev", "qa", "prod"):
        r = first_match(f"lab/secrets/{env}.sops.yaml")
        assert r["age"] == PHASE_A and SESSION not in r["age"]
        assert r["path_regex"] == r"^lab/secrets/[a-z0-9-]+\.sops\.yaml$"

def test_no_rule_matches_outside_secret_dirs():
    for p in ["lab/gpu/nim/nimcache.yaml", "lab/gpu/secrets/kustomization.yaml",
              "lab/secrets/kustomization.yaml", "lab/gpu/secrets/sub/x.sops.yaml", "x/lab/secrets/a.sops.yaml"]:
        assert first_match(p) is None, p

def test_exactly_two_rules():
    assert len(RULES) == 2
```

Append to `tests/test_check_secrets.py`:
```python
# ---- Phase B: lab/gpu/secrets coverage + recipients follow .sops.yaml (R7) ----
SESSION = "age1lsw2ne59z5y02s074k2kmrqfda5tc363hvacn24v0g60x6n0hyqs5sd89v"
PHASE_A = "age14c2r6yt9qlvj2mdl7k4hdg2rfpcga8ehpt4dnahfx2l8dvkdm50syjrs65"
SOPS_CFG = f"""\
creation_rules:
  - path_regex: ^lab/gpu/secrets/[a-z0-9-]+\\.sops\\.yaml$
    age: {SESSION}
  - path_regex: ^lab/secrets/[a-z0-9-]+\\.sops\\.yaml$
    age: {PHASE_A}
"""

def enc_for(recipient):
    return ENC_OK.replace("age1xyz", recipient)

def test_gpu_plaintext_value_fails(tmp_path):
    body = ENC_OK.replace("ENC[AES256_GCM,data:abc,iv:x,tag:y,type:str]", "hunter2")
    r = run(tmp_path, w(tmp_path, "lab/gpu/secrets/gpu.sops.yaml", body))
    assert r.returncode == 1 and "not ENC[" in r.stdout

def test_gpu_wrong_filename_fails(tmp_path):
    r = run(tmp_path, w(tmp_path, "lab/gpu/secrets/gpu.yaml", ENC_OK))
    assert r.returncode == 1 and "lab/gpu/secrets/ must be *.sops.yaml" in r.stdout

def test_gpu_kustomization_index_allowed(tmp_path):
    k = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: [gpu.sops.yaml]\n"
    assert run(tmp_path, w(tmp_path, "lab/gpu/secrets/kustomization.yaml", k)).returncode == 0
    bad = k + "patches: []\n"
    assert run(tmp_path, w(tmp_path, "lab/gpu/secrets/kustomization.yaml", bad)).returncode == 1

def test_recipients_follow_first_matching_rule(tmp_path):
    w(tmp_path, ".sops.yaml", SOPS_CFG)
    assert run(tmp_path, w(tmp_path, "lab/gpu/secrets/gpu.sops.yaml", enc_for(SESSION))).returncode == 0
    assert run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", enc_for(PHASE_A))).returncode == 0

def test_gpu_file_encrypted_to_phase_a_key_fails(tmp_path):
    w(tmp_path, ".sops.yaml", SOPS_CFG)
    r = run(tmp_path, w(tmp_path, "lab/gpu/secrets/gpu.sops.yaml", enc_for(PHASE_A)))
    assert r.returncode == 1 and "recipients do not match" in r.stdout

def test_phase_a_file_with_session_key_fails(tmp_path):
    w(tmp_path, ".sops.yaml", SOPS_CFG)
    both = ENC_OK.replace("age: [{recipient: age1xyz}]", f"age: [{{recipient: {PHASE_A}}}, {{recipient: {SESSION}}}]")
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", both))
    assert r.returncode == 1 and "recipients do not match" in r.stdout

def test_multi_document_gpu_file_checks_every_document(tmp_path):
    w(tmp_path, ".sops.yaml", SOPS_CFG)
    good = enc_for(SESSION)
    assert run(tmp_path, w(tmp_path, "lab/gpu/secrets/gpu.sops.yaml", good + "---\n" + good)).returncode == 0
    bad = good + "---\n" + enc_for(PHASE_A)
    assert run(tmp_path, w(tmp_path, "lab/gpu/secrets/gpu.sops.yaml", bad)).returncode == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --with pytest --with pyyaml pytest -q tests/test_sops_rules.py tests/test_check_secrets.py`
Expected: FAIL (`test_gpu_secrets_go_to_session_key_only`, `test_exactly_two_rules`, `test_gpu_wrong_filename_fails`,
`test_gpu_file_encrypted_to_phase_a_key_fails`, ... fail; the 28 existing tests pass).

- [ ] **Step 3: Implement**

`.sops.yaml` (whole file):
```yaml
# First matching rule wins (sops semantics), so the GPU-session rule MUST stay first.
# Rule 1 (Phase B, temporary): lab/gpu/secrets/*.sops.yaml -> GPU-session age key ONLY. Removed by the
#   teardown revert PR; the session private key is deleted at teardown, which makes that ciphertext dead.
# Rule 2 (Phase A): lab/secrets/*.sops.yaml -> lab-only age key (never the homelab key).
creation_rules:
  - path_regex: ^lab/gpu/secrets/[a-z0-9-]+\.sops\.yaml$
    encrypted_regex: ^(data|stringData)$
    age: age1lsw2ne59z5y02s074k2kmrqfda5tc363hvacn24v0g60x6n0hyqs5sd89v
  - path_regex: ^lab/secrets/[a-z0-9-]+\.sops\.yaml$
    encrypted_regex: ^(data|stringData)$
    age: age14c2r6yt9qlvj2mdl7k4hdg2rfpcga8ehpt4dnahfx2l8dvkdm50syjrs65
```

`scripts/check_secrets.py` (whole file):
```python
#!/usr/bin/env python3
"""Structural secrets checks for this repo (stdlib + PyYAML).

Rules:
  R1 every file under a secrets dir (lab/secrets/, lab/gpu/secrets/) is named *.sops.yaml
     (paths are normalised first); the only exception is that dir's kustomization.yaml index
  R2 every file has >=1 YAML document, each with a top-level `sops:` block whose `mac` is ENC[...]
     and whose keys are all known sops keys
  R3 every leaf outside `sops:` is ENC[...], except apiVersion, kind, type,
     metadata.name and metadata.namespace; at least one ENC leaf must exist
  R4 generated Bifrost files (lab/envs/*/generated/*) contain no literal nvapi-/sk-bf- values
  R5 no age private key or PEM private-key header anywhere in scanned text files
  R6 undecodable files under a secrets dir and explicit paths that do not exist are findings
  R7 the age recipients of every secrets file equal those of the FIRST .sops.yaml creation rule whose
     path_regex matches it (sops semantics), so a GPU-session file can never carry the Phase A key
     and vice versa (skipped when --root has no .sops.yaml)
Exit 0 clean, 1 findings, 2 usage.
"""
from __future__ import annotations
import argparse, posixpath, re, subprocess, sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("check_secrets: PyYAML required (uv run --with pyyaml ...)", file=sys.stderr); sys.exit(2)

AGE_PRIV = re.compile(r"(?i)AGE-SECRET-KE[Y]-[A-Z0-9-]*1[A-Z0-9]{20,}")
PEM_PRIV = re.compile(r"-{4,5} ?BEGIN [A-Z0-9 _-]*PRIVATE KEY")
LITERAL = re.compile(r"(nvapi-[A-Za-z0-9_-]{20,}|sk-bf-[A-Za-z0-9_-]{8,})")
ENC = re.compile(r"^ENC\[[A-Z0-9_]+,data:.*\]$")

SOPS_KEYS = {"kms", "gcp_kms", "azure_kv", "hc_vault", "age", "pgp", "lastmodified", "mac",
             "unencrypted_suffix", "encrypted_suffix", "unencrypted_regex", "encrypted_regex",
             "unencrypted_comment_regex", "encrypted_comment_regex", "mac_only_encrypted",
             "version", "shamir_threshold", "key_groups"}
PLAIN_OK = {("apiVersion",), ("kind",), ("type",), ("metadata", "name"), ("metadata", "namespace")}
SECRET_DIRS = ("lab/secrets/", "lab/gpu/secrets/")

def secrets_dir(rel: str) -> str | None:
    return next((d for d in SECRET_DIRS if rel.startswith(d)), None)

def sops_rules(root: Path) -> list[tuple[re.Pattern, set[str]]] | None:
    f = root / ".sops.yaml"
    if not f.is_file():
        return None
    rules = []
    for r in (yaml.safe_load(f.read_text()) or {}).get("creation_rules") or []:
        ages = r.get("age") or ""
        ages = ages if isinstance(ages, list) else [a.strip() for a in ages.split(",")]
        rules.append((re.compile(r.get("path_regex", "")), {a for a in ages if a}))
    return rules

def check_recipients(rel: str, text: str, rules) -> list[str]:
    want = next((ages for rx, ages in rules if rx.search(rel)), None)
    if want is None:
        return [f"{rel}: no .sops.yaml creation rule matches this path"]
    try:
        docs = [d for d in yaml.safe_load_all(text) if isinstance(d, dict) and isinstance(d.get("sops"), dict)]
    except yaml.YAMLError:
        return []   # already reported by check_secret_file
    out = []
    for d in docs:
        got = {a.get("recipient") for a in d["sops"].get("age") or [] if isinstance(a, dict)}
        if got != want:
            out.append(f"{rel}: sops age recipients do not match the first matching .sops.yaml rule")
    return out

def leaves(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items(): yield from leaves(v, path + (str(k),))
    elif isinstance(node, list):
        for v in node: yield from leaves(v, path)
    else:
        yield path, node

def is_secrets_kustomization(rel: str, text: str) -> list[str] | None:
    """The one non-sops file allowed under lab/secrets: a pure index of *.sops.yaml names.
    Returns None if rel isn't that file, else a (possibly empty) list of findings."""
    if rel not in {d + "kustomization.yaml" for d in SECRET_DIRS}:
        return None
    class Strict(yaml.SafeLoader):
        pass
    def no_dups(loader, node, deep=False):
        keys = [loader.construct_object(k, deep=True) for k, _ in node.value]
        if len(keys) != len(set(keys)):
            raise yaml.YAMLError("duplicate key")
        return yaml.SafeLoader.construct_mapping(loader, node, deep)
    Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, no_dups)
    try:
        d = yaml.load(text, Loader=Strict)
    except yaml.YAMLError:
        return [f"{rel}: unparseable YAML or duplicate keys"]
    ok = (isinstance(d, dict) and set(d) == {"apiVersion", "kind", "resources"}
          and d["apiVersion"] == "kustomize.config.k8s.io/v1beta1"
          and d["kind"] == "Kustomization" and isinstance(d["resources"], list)
          and all(isinstance(r, str) and re.fullmatch(r"[A-Za-z0-9_-]+\.sops\.yaml", r) for r in d["resources"]))
    return [] if ok else [f"{rel}: must contain only apiVersion, kind and a resources list of bare *.sops.yaml names"]

def check_secret_file(rel: str, text: str) -> list[str]:
    k = is_secrets_kustomization(rel, text)
    if k is not None:
        return k
    out = []
    if not rel.endswith(".sops.yaml"):
        out.append(f"{rel}: files under {secrets_dir(rel) or 'lab/secrets/'} must be *.sops.yaml")
    try:
        docs = [d for d in yaml.safe_load_all(text) if d is not None]
    except yaml.YAMLError as e:
        return out + [f"{rel}: unparseable YAML ({e.__class__.__name__})"]
    if not docs:
        out.append(f"{rel}: no YAML documents (empty or comment-only)")
    for d in docs:
        if not isinstance(d, dict) or not isinstance(d.get("sops"), dict):
            out.append(f"{rel}: no sops metadata block"); continue
        mac = d["sops"].get("mac")
        if not (isinstance(mac, str) and ENC.match(mac)):
            out.append(f"{rel}: sops.mac missing or not ENC[...] (file not produced by sops?)")
        for k in d["sops"]:
            if k not in SOPS_KEYS:
                out.append(f"{rel}: unknown key in sops block: {k}")
        body = {k: v for k, v in d.items() if k != "sops"}
        enc = 0
        bad = False
        for path, v in leaves(body):
            if isinstance(v, str) and ENC.match(v):
                enc += 1
            elif path not in PLAIN_OK:
                bad = True
        if bad:
            out.append(f"{rel}: value outside sops block is not ENC[...]")
        if enc == 0:
            out.append(f"{rel}: sops block present but nothing encrypted")
    return out

def check_text(rel: str, text: str) -> list[str]:
    out = []
    if AGE_PRIV.search(text): out.append(f"{rel}: age private key material")
    if PEM_PRIV.search(text): out.append(f"{rel}: PEM private key header")
    if "/generated/" in rel and LITERAL.search(text):
        out.append(f"{rel}: literal secret value in generated config (use env.VAR)")
    return out

def tracked_files(root: Path) -> list[str]:
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"check_secrets: git ls-files failed: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return [l for l in r.stdout.splitlines() if l]

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args()
    root = Path(a.root)
    rules = sops_rules(root)
    paths = a.paths or tracked_files(root)
    findings = []
    for raw in paths:
        rel = posixpath.normpath(raw)
        p = root / rel
        in_secrets = secrets_dir(rel) is not None
        if not p.is_file():
            findings.append(f"{rel}: path does not exist or is not a file")
            continue
        data = p.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            if in_secrets:
                findings.append(f"{rel}: undecodable (non-UTF-8) file under {secrets_dir(rel)}")
                continue
            text = data.decode("utf-8", errors="replace")
        if in_secrets:
            findings += check_secret_file(rel, text)
            if rules is not None and not rel.endswith("/kustomization.yaml"):
                findings += check_recipients(rel, text, rules)
        findings += check_text(rel, text)
    for f in findings: print(f"FINDING {f}")
    return 1 if findings else 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests and the repo check**

Run: `uv run --with pytest --with pyyaml pytest -q tests/test_sops_rules.py tests/test_check_secrets.py && uv run --with pyyaml python3 scripts/check_secrets.py; echo rc=$?`
Expected: `39 passed`, then `rc=0` (the Phase A files' recipient matches rule 2, so R7 passes on the real tree).

- [ ] **Step 5: Commit and PR**

```bash
scripts/safety-check.sh
git branch --show-current     # feat/gpu-sops-rule (created at the start of the task)
git add .sops.yaml scripts/check_secrets.py tests/test_check_secrets.py tests/test_sops_rules.py
git commit -m "feat(gpu): sops rule for lab/gpu/secrets (session key only, first rule); check_secrets covers it (R7)"
git push -u origin feat/gpu-sops-rule && gh pr create --fill
```
Expected: `PASSED`; CI `gates` green. **[SESSION] owner merges.**

---

### Task 2: The session secrets file `lab/gpu/secrets/gpu.sops.yaml`

**Files:**
- Create: `scripts/make_gpu_sops.py`, `tests/test_make_gpu_sops.py`, `lab/gpu/secrets/kustomization.yaml`
- Create **[SESSION]**: `lab/gpu/secrets/gpu.sops.yaml`

**Interfaces:**
- Consumes: Task 1's `.sops.yaml` rule; `~/.sops/raglab-gpu-session/{age-key.txt,session-nvapi-key.age}`.
- Produces: `make_gpu_sops.py emit` (three Secret manifests on stdout, refuses a TTY) and `verify` (reads decrypted YAML
  on stdin; prints only `OK`/`FAIL` lines; compares the key with the one on disk). The encrypted file holds:
  `raglab-gpu/ngc-pull` (dockerconfigjson for `nvcr.io`, user `$oauthtoken`), `raglab-gpu/ngc-api-key` (`NGC_API_KEY`),
  `raglab-dev-gpu/bifrost-env` (`NVIDIA_API_KEY`, `NIM_LOCAL_API_KEY`=non-secret placeholder, fresh
  `BIFROST_ENCRYPTION_KEY`, `BIFROST_ADMIN_USER`, `BIFROST_ADMIN_PASSWORD`, `BIFROST_VK`, `BIFROST_VK_PROBE`).
- Consumed by: Task 5 (`raglab-gpu-secrets` app), Task 3 manifests (secret names).

- [ ] **Step 1: Write the failing tests**

`tests/test_make_gpu_sops.py`:
```python
"""make_gpu_sops.py with a fake `age` binary: no real key is ever used in tests."""
import os, pty, subprocess, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_gpu_sops.py"
FAKE_KEY = "nvapi-" + "T" * 40          # built at runtime so gitleaks never sees a literal

def setup(tmp_path, key=FAKE_KEY, age_rc=0):
    d = tmp_path / "session"; d.mkdir()
    (d / "age-key.txt").write_text("identity-placeholder\n")
    (d / "session-nvapi-key.age").write_text("ciphertext-placeholder\n")
    fake = tmp_path / "fake-age"
    fake.write_text(f"#!/bin/sh\nprintf '%s\\n' '{key}'\nexit {age_rc}\n"); fake.chmod(0o755)
    return {**os.environ, "RAGLAB_GPU_DIR": str(d), "RAGLAB_AGE_BIN": str(fake)}

def run(env, *args, stdin=None, stdout=subprocess.PIPE):
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, input=stdin,
                          stdout=stdout, stderr=subprocess.PIPE, text=True)

def test_emit_builds_three_secrets(tmp_path):
    r = run(setup(tmp_path), "emit")
    assert r.returncode == 0, r.stderr
    docs = list(yaml.safe_load_all(r.stdout))
    assert [(d["metadata"]["namespace"], d["metadata"]["name"], d["type"]) for d in docs] == [
        ("raglab-gpu", "ngc-pull", "kubernetes.io/dockerconfigjson"),
        ("raglab-gpu", "ngc-api-key", "Opaque"),
        ("raglab-dev-gpu", "bifrost-env", "Opaque")]
    assert FAKE_KEY not in r.stderr

def test_emit_then_verify_passes(tmp_path):
    env = setup(tmp_path)
    out = run(env, "emit").stdout
    v = run(env, "verify", stdin=out)
    assert v.returncode == 0, v.stdout
    assert "FAIL" not in v.stdout and FAKE_KEY not in v.stdout + v.stderr
    assert "OK   key equals the session key on disk (decode probe)" in v.stdout

def test_two_emits_generate_fresh_bifrost_values(tmp_path):
    env = setup(tmp_path)
    a, b = (list(yaml.safe_load_all(run(env, "emit").stdout))[2]["stringData"] for _ in range(2))
    assert a["BIFROST_VK"] != b["BIFROST_VK"] and a["BIFROST_ENCRYPTION_KEY"] != b["BIFROST_ENCRYPTION_KEY"]

def test_verify_detects_tampering(tmp_path):
    env = setup(tmp_path)
    docs = list(yaml.safe_load_all(run(env, "emit").stdout))
    docs[2]["stringData"]["NVIDIA_API_KEY"] = "nvapi-" + "X" * 40
    v = run(env, "verify", stdin=yaml.safe_dump_all(docs))
    assert v.returncode == 1 and "FAIL bifrost NVIDIA_API_KEY equals NGC_API_KEY" in v.stdout
    assert "X" * 40 not in v.stdout

def test_verify_detects_wrong_source_key(tmp_path):
    out = run(setup(tmp_path), "emit").stdout
    o = tmp_path / "o"; o.mkdir()
    other = setup(o, key="nvapi-" + "Z" * 40)
    v = run(other, "verify", stdin=out)
    assert v.returncode == 1 and "FAIL key equals the session key on disk" in v.stdout

def test_verify_rejects_still_encrypted_input(tmp_path):
    env = setup(tmp_path)
    docs = list(yaml.safe_load_all(run(env, "emit").stdout))
    for d in docs: d["sops"] = {"version": "3.13.3"}
    v = run(env, "verify", "--no-source", stdin=yaml.safe_dump_all(docs))
    assert v.returncode == 1 and "FAIL no sops block" in v.stdout

def test_age_failure_is_reported_without_output(tmp_path):
    r = run(setup(tmp_path, age_rc=1), "emit")
    assert r.returncode == 2 and r.stdout == "" and FAKE_KEY not in r.stderr

def test_non_nvapi_key_rejected_without_echo(tmp_path):
    r = run(setup(tmp_path, key="sk-not-a-nvidia-key-1234567890"), "emit")
    assert r.returncode == 2 and r.stdout == "" and "sk-not-a-nvidia" not in r.stderr

def test_emit_refuses_a_terminal(tmp_path):
    master, slave = pty.openpty()
    try:
        r = subprocess.run([sys.executable, str(SCRIPT), "emit"], env=setup(tmp_path),
                           stdout=slave, stderr=subprocess.PIPE, text=True)
    finally:
        os.close(slave)
        os.close(master)
    assert r.returncode == 2 and "refusing to write secrets to a terminal" in r.stderr


def test_gpu_secrets_kustomization_lists_only_gpu_file():
    k = yaml.safe_load((ROOT / "lab/gpu/secrets/kustomization.yaml").read_text())
    assert k == {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": ["gpu.sops.yaml"]}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --with pytest --with pyyaml pytest -q tests/test_make_gpu_sops.py`
Expected: FAIL (script and kustomization missing).

- [ ] **Step 3: Implement**

`scripts/make_gpu_sops.py`:
```python
#!/usr/bin/env python3
"""Build (emit) or check (verify) the plaintext for lab/gpu/secrets/gpu.sops.yaml. Never prints a value.

  emit    reads the session nvapi- key with `age -d` (into this process only), generates fresh Bifrost
          values, and writes three Secret manifests to stdout. Refuses to write to a terminal: stdout
          must be a pipe into `sops encrypt`.
  verify  reads the DECRYPTED file on stdin (from `sops decrypt`), checks its structure and that the
          key inside equals the session key on disk; prints only OK/FAIL lines.

Session files (override the directory with RAGLAB_GPU_DIR, the age binary with RAGLAB_AGE_BIN):
  age-key.txt              session age identity (decrypts the .age file)
  session-nvapi-key.age    the session nvapi- key (hosted API + nvcr.io pull), age-encrypted
Exit 0 ok, 1 verify failure, 2 usage/input error.
"""
from __future__ import annotations
import argparse, base64, json, os, re, secrets, subprocess, sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("make_gpu_sops: PyYAML required (uv run --with pyyaml ...)", file=sys.stderr); sys.exit(2)

GPU_NS, DEV_GPU_NS = "raglab-gpu", "raglab-dev-gpu"
NIM_LOCAL_PLACEHOLDER = "not-a-secret-nim-local"   # the NIM ignores the bearer; Bifrost needs a value
KEY_RE = re.compile(r"^nvapi-[A-Za-z0-9_-]{20,}$")
BIFROST_KEYS = {"NVIDIA_API_KEY", "NIM_LOCAL_API_KEY", "BIFROST_ENCRYPTION_KEY", "BIFROST_ADMIN_USER",
                "BIFROST_ADMIN_PASSWORD", "BIFROST_VK", "BIFROST_VK_PROBE"}


def die(msg: str, code: int = 2):
    print(f"make_gpu_sops: {msg}", file=sys.stderr); sys.exit(code)


def session_dir() -> Path:
    return Path(os.environ.get("RAGLAB_GPU_DIR", str(Path.home() / ".sops" / "raglab-gpu-session")))


def read_session_key() -> str:
    d = session_dir()
    ident, enc = d / "age-key.txt", d / "session-nvapi-key.age"
    for f in (ident, enc):
        if not f.is_file():
            die(f"missing {f}")
    r = subprocess.run([os.environ.get("RAGLAB_AGE_BIN", "age"), "-d", "-i", str(ident), str(enc)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die("age -d failed (output suppressed)")
    key = r.stdout.strip()
    if not KEY_RE.match(key):
        die("decrypted session key does not look like an nvapi- key (value not shown)")
    return key


def dockerconfig(key: str) -> str:
    auth = base64.b64encode(f"$oauthtoken:{key}".encode()).decode()
    return json.dumps({"auths": {"nvcr.io": {"username": "$oauthtoken", "password": key, "auth": auth}}},
                      sort_keys=True)


def secret(name: str, ns: str, data: dict, typ: str = "Opaque") -> dict:
    return {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name, "namespace": ns},
            "type": typ, "stringData": data}


def build(key: str) -> list[dict]:
    return [
        secret("ngc-pull", GPU_NS, {".dockerconfigjson": dockerconfig(key)}, "kubernetes.io/dockerconfigjson"),
        secret("ngc-api-key", GPU_NS, {"NGC_API_KEY": key}),
        secret("bifrost-env", DEV_GPU_NS, {
            "NVIDIA_API_KEY": key,
            "NIM_LOCAL_API_KEY": NIM_LOCAL_PLACEHOLDER,
            "BIFROST_ENCRYPTION_KEY": secrets.token_urlsafe(32),
            "BIFROST_ADMIN_USER": "raglab-admin",
            "BIFROST_ADMIN_PASSWORD": secrets.token_urlsafe(24),
            "BIFROST_VK": "sk-bf-" + secrets.token_urlsafe(24),
            "BIFROST_VK_PROBE": "sk-bf-" + secrets.token_urlsafe(24),
        }),
    ]


def emit() -> int:
    if sys.stdout.isatty():
        die("refusing to write secrets to a terminal; pipe into `sops encrypt`")
    sys.stdout.write(yaml.safe_dump_all(build(read_session_key()), sort_keys=False, default_flow_style=False))
    return 0


def verify(text: str, source_key: str | None) -> int:
    ok = True

    def check(name: str, cond: bool):
        nonlocal ok
        print(f"{'OK  ' if cond else 'FAIL'} {name}")
        ok = ok and cond

    try:
        docs = [d for d in yaml.safe_load_all(text) if d]
    except yaml.YAMLError:
        print("FAIL parse"); return 1
    by = {(d.get("metadata", {}).get("namespace"), d.get("metadata", {}).get("name")): d
          for d in docs if isinstance(d, dict)}
    check("three documents", len(docs) == 3)
    check("no sops block (input must be decrypted)", all("sops" not in d for d in docs if isinstance(d, dict)))
    pull = by.get((GPU_NS, "ngc-pull"), {})
    api = by.get((GPU_NS, "ngc-api-key"), {})
    bif = by.get((DEV_GPU_NS, "bifrost-env"), {})
    check("ngc-pull type dockerconfigjson", pull.get("type") == "kubernetes.io/dockerconfigjson")
    check("ngc-api-key type Opaque", api.get("type") == "Opaque")
    check("bifrost-env type Opaque", bif.get("type") == "Opaque")
    key = (api.get("stringData") or {}).get("NGC_API_KEY", "")
    check("NGC_API_KEY is an nvapi- key", bool(KEY_RE.match(key)))
    try:
        auths = json.loads((pull.get("stringData") or {}).get(".dockerconfigjson", "{}"))["auths"]
        ent = auths.get("nvcr.io", {})
        check("dockerconfigjson has only nvcr.io", set(auths) == {"nvcr.io"})
        check("nvcr.io username is $oauthtoken", ent.get("username") == "$oauthtoken")
        check("nvcr.io password equals NGC_API_KEY", ent.get("password") == key)
        check("nvcr.io auth decodes to $oauthtoken:<key>",
              base64.b64decode(ent.get("auth", "")).decode() == f"$oauthtoken:{key}")
    except (ValueError, KeyError, TypeError, AttributeError):
        check("dockerconfigjson parses", False)
    sd = bif.get("stringData") or {}
    check("bifrost-env has exactly the expected keys", set(sd) == BIFROST_KEYS)
    check("bifrost NVIDIA_API_KEY equals NGC_API_KEY", sd.get("NVIDIA_API_KEY") == key)
    check("NIM_LOCAL_API_KEY is the placeholder", sd.get("NIM_LOCAL_API_KEY") == NIM_LOCAL_PLACEHOLDER)
    check("virtual keys are sk-bf- and distinct",
          all(str(sd.get(k, "")).startswith("sk-bf-") for k in ("BIFROST_VK", "BIFROST_VK_PROBE"))
          and sd.get("BIFROST_VK") != sd.get("BIFROST_VK_PROBE"))
    check("generated values are long enough",
          all(len(str(sd.get(k, ""))) >= 30 for k in ("BIFROST_ENCRYPTION_KEY", "BIFROST_ADMIN_PASSWORD")))
    if source_key is not None:
        check("key equals the session key on disk (decode probe)", key == source_key)
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("emit")
    v = sub.add_parser("verify")
    v.add_argument("--no-source", action="store_true", help="skip the comparison with the key on disk")
    a = ap.parse_args()
    if a.cmd == "emit":
        return emit()
    return verify(sys.stdin.read(), None if a.no_source else read_session_key())


if __name__ == "__main__":
    sys.exit(main())
```

`lab/gpu/secrets/kustomization.yaml`:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: [gpu.sops.yaml]
```

- [ ] **Step 4: Run the tests**

Run: `chmod +x scripts/make_gpu_sops.py && uv run --with pytest --with pyyaml pytest -q tests/test_make_gpu_sops.py`
Expected: `10 passed`.

- [ ] **Step 5: Commit, push the branch (no PR yet)**

```bash
git branch --show-current     # feat/gpu-secrets (created at the start of the task)
git add scripts/make_gpu_sops.py tests/test_make_gpu_sops.py lab/gpu/secrets/kustomization.yaml
git commit -m "feat(gpu): make_gpu_sops (emit/verify) for the session secrets file" && git push -u origin feat/gpu-secrets
```
Agent stops here and hands over.

- [ ] **Step 6: [SESSION] Encrypt (the plaintext exists only in the pipe; nothing is printed)**

```bash
git checkout feat/gpu-secrets && git pull
set -o pipefail
uv run -q --with pyyaml python3 scripts/make_gpu_sops.py emit \
  | sops encrypt --filename-override lab/gpu/secrets/gpu.sops.yaml --input-type yaml --output-type yaml /dev/stdin \
  > lab/gpu/secrets/gpu.sops.yaml
echo rc=$?
```
Expected: `rc=0`, no other output. If `sops` rejects multi-document input, stop and report (fallback: three files
`ngc-pull.sops.yaml`, `ngc-api-key.sops.yaml`, `bifrost-env.sops.yaml` listed in the kustomization; same pipe per doc).

- [ ] **Step 7: [SESSION] Structural check, decode probe, negative probe**

```bash
uv run --with pyyaml python3 scripts/check_secrets.py lab/gpu/secrets/gpu.sops.yaml lab/gpu/secrets/kustomization.yaml; echo structural=$?
grep -c 'nvapi-' lab/gpu/secrets/gpu.sops.yaml
SOPS_AGE_KEY_FILE=$HOME/.sops/raglab-gpu-session/age-key.txt sops decrypt lab/gpu/secrets/gpu.sops.yaml \
  | uv run -q --with pyyaml python3 scripts/make_gpu_sops.py verify; echo verify=$?
SOPS_AGE_KEY_FILE=$HOME/.sops/raglab-age-key.txt sops decrypt lab/gpu/secrets/gpu.sops.yaml >/dev/null 2>&1 \
  && echo LEAK-phase-a-key-decrypts || echo ok-phase-a-key-cannot-decrypt
```
Expected: `structural=0`; `0`; 16 `OK   ...` lines ending `OK   key equals the session key on disk (decode probe)` and
`verify=0`; `ok-phase-a-key-cannot-decrypt`.

- [ ] **Step 8: [SESSION] Commit and PR**

```bash
scripts/safety-check.sh
git add lab/gpu/secrets/gpu.sops.yaml && git commit -m "feat(gpu): session secrets (encrypted to the session key only)"
git push && gh pr create --fill
```
Expected: hook passes; CI `gates` green (R7 proves the recipient). **[SESSION] owner merges.**

---

### Task 3: Vendor the NIMCache CRD; NIM manifests validated against both CRDs

**Files:**
- Create: `tests/fixtures/crds/apps.nvidia.com_nimcaches.yaml`, `lab/gpu/nim/kustomization.yaml`,
  `lab/gpu/nim/nimcache.yaml`, `lab/gpu/nim/nimservice.yaml`, `lab/gpu/nim/networkpolicy.yaml`,
  `lab/gpu/gonogo/list-profiles-job.yaml`, `lab/gpu/gonogo/gpu-check-job.yaml`, `tests/test_gpu_manifests.py`

**Interfaces:**
- Produces: `kubectl kustomize lab/gpu/nim` → NIMCache `llama-8b` (wave 0, `Prune=false,Delete=false`), NIMService
  `llama-8b` (wave 1, `replicas: 0`, Service `llama-8b:8000`, label `app.kubernetes.io/component: nim-llm`), three
  NetworkPolicies; profile placeholder `PENDING-GO-NO-GO` in both CRs. Two hand-applied Jobs (`gpu-check`,
  `list-model-profiles`) using the pinned image.
- Consumed by: Task 5 (catalogue/policy agreement, the `raglab-gpu-nim` app at go), Tasks 11-14.

- [ ] **Step 1: Vendor the CRD and prove it comes from the same source as the NIMService fixture**

```bash
base=https://raw.githubusercontent.com/NVIDIA/k8s-nim-operator/v3.1.4/config/crd/bases
curl -fsSL "$base/apps.nvidia.com_nimservices.yaml" | cmp - tests/fixtures/crds/apps.nvidia.com_nimservices.yaml && echo same-source
curl -fsSL -o tests/fixtures/crds/apps.nvidia.com_nimcaches.yaml "$base/apps.nvidia.com_nimcaches.yaml"
shasum -a 256 tests/fixtures/crds/apps.nvidia.com_nimcaches.yaml
```
Expected: `same-source`; `9936c51bb2b06b15888af7f7e36c49bd4cec7ef61484f5a55c23ddd097fa3685` (855 lines). The NIMCache
v3.1.4 spec fields are `certConfig, env, groupID, initContainers, nodeSelector, proxy, resources (cpu, memory only),
runtimeClassName, source, storage, tolerations, userID`; it has **no** `labels` field (job pod labels are the operator's).

- [ ] **Step 2: Write the failing tests**

`tests/test_gpu_manifests.py`:
```python
"""Phase B: lab/gpu kustomizations build, match the vendored v3.1.4 CRDs, and agree with the catalogue."""
import shutil, subprocess
from pathlib import Path
from urllib.parse import urlparse
import pytest, yaml

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl needed")
jsonschema = pytest.importorskip("jsonschema")
NIM_IMAGE = ("nvcr.io/nim/meta/llama-3.1-8b-instruct:2.1.7"
             "@sha256:5ada92d1ca5c30069956e6e1322f0fbb250b4683b566aedb6547b10a64faf00b")
PRIVATE = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"}

def build(path):
    out = subprocess.run(["kubectl", "kustomize", str(ROOT / path)], capture_output=True, text=True, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]

def by(docs, kind, name=None):
    return [d for d in docs if d["kind"] == kind and (name is None or d["metadata"]["name"] == name)]

def crd_spec_schema(plural):
    crd = yaml.safe_load((ROOT / f"tests/fixtures/crds/apps.nvidia.com_{plural}.yaml").read_text())
    ver = next(v for v in crd["spec"]["versions"] if v["name"] == "v1alpha1")
    return ver["schema"]["openAPIV3Schema"]["properties"]["spec"]

def test_nim_kustomization_validates_against_both_crds():
    docs = build("lab/gpu/nim")
    assert sorted(d["kind"] for d in docs) == ["NIMCache", "NIMService", "NetworkPolicy", "NetworkPolicy", "NetworkPolicy"]
    for d in docs:
        assert d["metadata"]["namespace"] == "raglab-gpu"
    (cache,) = by(docs, "NIMCache"); (svc,) = by(docs, "NIMService")
    jsonschema.validate(cache["spec"], crd_spec_schema("nimcaches"))
    jsonschema.validate(svc["spec"], crd_spec_schema("nimservices"))

def test_cache_and_service_agree():
    docs = build("lab/gpu/nim")
    (cache,) = by(docs, "NIMCache"); (svc,) = by(docs, "NIMService")
    ngc = cache["spec"]["source"]["ngc"]
    assert ngc["modelPuller"] == NIM_IMAGE
    assert f'{svc["spec"]["image"]["repository"]}:{svc["spec"]["image"]["tag"]}' == NIM_IMAGE
    assert ngc["model"]["profiles"] == [svc["spec"]["storage"]["nimCache"]["profile"]], "profile pinned in BOTH places"
    assert svc["spec"]["storage"]["nimCache"]["name"] == cache["metadata"]["name"] == "llama-8b"
    assert ngc["pullSecret"] == "ngc-pull" and svc["spec"]["image"]["pullSecrets"] == ["ngc-pull"]
    assert ngc["authSecret"] == svc["spec"]["authSecret"] == "ngc-api-key"
    assert cache["metadata"]["annotations"]["argocd.argoproj.io/sync-options"] == "Prune=false,Delete=false"
    assert cache["spec"]["storage"]["pvc"]["storageClass"] == "local-path"
    for d in (cache, svc):
        assert "runtimeClassName" not in d["spec"], "NRI path: leave runtimeClassName unset"
    assert svc["spec"]["replicas"] in (0, 1)
    assert svc["spec"]["resources"]["limits"]["nvidia.com/gpu"] == 1

def test_nim_network_policies():
    docs = build("lab/gpu/nim")
    deny = by(docs, "NetworkPolicy", "default-deny-ingress")[0]["spec"]
    assert deny == {"podSelector": {}, "policyTypes": ["Ingress"]}
    allow = by(docs, "NetworkPolicy", "nim-from-bifrost")[0]["spec"]
    assert allow["podSelector"] == {"matchLabels": {"app.kubernetes.io/component": "nim-llm"}}
    assert allow["ingress"] == [{"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "raglab-dev-gpu"}},
                                           "podSelector": {"matchLabels": {"app": "bifrost"}}}],
                                 "ports": [{"port": 8000, "protocol": "TCP"}]}]
    eg = by(docs, "NetworkPolicy", "egress-dns-and-public-443")[0]["spec"]
    assert eg["podSelector"] == {} and eg["policyTypes"] == ["Egress"]
    blk = eg["egress"][1]["to"][0]["ipBlock"]
    assert blk["cidr"] == "0.0.0.0/0" and set(blk["except"]) == PRIVATE and eg["egress"][1]["ports"] == [{"port": 443}]
    (svc,) = by(docs, "NIMService")
    assert svc["spec"]["labels"]["app.kubernetes.io/component"] == "nim-llm"

def test_gonogo_job_uses_the_pinned_image_and_a_gpu():
    (job,) = [d for d in yaml.safe_load_all((ROOT / "lab/gpu/gonogo/list-profiles-job.yaml").read_text()) if d]
    assert job["kind"] == "Job" and job["metadata"]["namespace"] == "raglab-gpu"
    c = job["spec"]["template"]["spec"]["containers"][0]
    assert c["image"] == NIM_IMAGE and c["command"] == ["list-model-profiles"]
    assert c["resources"]["limits"]["nvidia.com/gpu"] == 1
    assert job["spec"]["template"]["spec"]["imagePullSecrets"] == [{"name": "ngc-pull"}]
    assert c["env"][0]["valueFrom"]["secretKeyRef"] == {"name": "ngc-api-key", "key": "NGC_API_KEY"}
    for k in (ROOT / "lab/gpu").rglob("kustomization.yaml"):
        assert "gonogo" not in k.read_text(), "the go/no-go Job is applied by hand only"

def test_gpu_check_job_pinned_and_unprivileged():
    (job,) = [d for d in yaml.safe_load_all((ROOT / "lab/gpu/gonogo/gpu-check-job.yaml").read_text()) if d]
    s = job["spec"]["template"]["spec"]; c = s["containers"][0]
    assert c["image"] == NIM_IMAGE and c["command"][0] == "nvidia-smi"
    assert c["resources"]["limits"]["nvidia.com/gpu"] == 1 and "runtimeClassName" not in s
    assert s["securityContext"]["runAsNonRoot"] is True and c["securityContext"]["allowPrivilegeEscalation"] is False
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run --with pytest --with pyyaml --with jsonschema pytest -q tests/test_gpu_manifests.py`
Expected: FAIL (`lab/gpu/nim` does not exist).

- [ ] **Step 4: Write the manifests**

`lab/gpu/nim/kustomization.yaml`:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: raglab-gpu
resources: [networkpolicy.yaml, nimcache.yaml, nimservice.yaml]
```
`lab/gpu/nim/nimcache.yaml`:
```yaml
# Phase B (rented GPU cluster only). Field names checked against the vendored v3.1.4 CRD in CI.
# The profile is filled by the go/no-go PR from `list-model-profiles` on the real A100 (lab/gpu/README.md).
apiVersion: apps.nvidia.com/v1alpha1
kind: NIMCache
metadata:
  name: llama-8b
  annotations:
    argocd.argoproj.io/sync-wave: "0"
    argocd.argoproj.io/sync-options: Prune=false,Delete=false
spec:
  source:
    ngc:
      modelPuller: nvcr.io/nim/meta/llama-3.1-8b-instruct:2.1.7@sha256:5ada92d1ca5c30069956e6e1322f0fbb250b4683b566aedb6547b10a64faf00b
      pullSecret: ngc-pull
      authSecret: ngc-api-key
      model:
        profiles: ["PENDING-GO-NO-GO"]
  storage:
    pvc: {create: true, storageClass: local-path, size: 60Gi, volumeAccessMode: ReadWriteOnce}
  tolerations: []          # single node, no GPU taint
  resources: {cpu: "2", memory: 8Gi}
  userID: 1000
  groupID: 2000
  # runtimeClassName: intentionally unset (NRI path: no 'nvidia' RuntimeClass)
```
`lab/gpu/nim/nimservice.yaml`:
```yaml
# Phase B (rented GPU cluster only). replicas 0 until the NIMCache is Ready, then 1 by PR.
apiVersion: apps.nvidia.com/v1alpha1
kind: NIMService
metadata:
  name: llama-8b
  annotations: {argocd.argoproj.io/sync-wave: "1"}
spec:
  image:
    repository: nvcr.io/nim/meta/llama-3.1-8b-instruct
    tag: "2.1.7@sha256:5ada92d1ca5c30069956e6e1322f0fbb250b4683b566aedb6547b10a64faf00b"
    pullPolicy: IfNotPresent
    pullSecrets: [ngc-pull]
  authSecret: ngc-api-key
  storage:
    nimCache: {name: llama-8b, profile: "PENDING-GO-NO-GO"}
    readOnly: true
    sharedMemorySizeLimit: 8Gi
  labels: {app.kubernetes.io/component: nim-llm}
  resources:
    requests: {cpu: "4", memory: 24Gi, nvidia.com/gpu: 1}
    limits: {memory: 24Gi, nvidia.com/gpu: 1}
  # runtimeClassName: intentionally unset (NRI path: no 'nvidia' RuntimeClass)
  replicas: 0
  userID: 1000
  groupID: 2000
  startupProbe:
    enabled: true
    probe:
      httpGet: {path: /v1/health/ready, port: 8000}
      initialDelaySeconds: 60
      periodSeconds: 10
      timeoutSeconds: 5
      failureThreshold: 120
  # Service name pinned so the catalogue's nim-local base_url is known before the session.
  expose: {service: {name: llama-8b, type: ClusterIP, port: 8000}}
```
`lab/gpu/nim/networkpolicy.yaml`:
```yaml
# raglab-gpu: nothing reaches the NIM except Bifrost in raglab-dev-gpu; pods may only resolve DNS
# and reach PUBLIC 443 (NGC / nvcr.io for the NIMCache job and the NIM).
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: default-deny-ingress}
spec:
  podSelector: {}
  policyTypes: [Ingress]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: nim-from-bifrost}
spec:
  podSelector: {matchLabels: {app.kubernetes.io/component: nim-llm}}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: raglab-dev-gpu}}
          podSelector: {matchLabels: {app: bifrost}}
      ports: [{port: 8000, protocol: TCP}]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: egress-dns-and-public-443}
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to: [{namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}, podSelector: {matchLabels: {k8s-app: kube-dns}}}]
      ports: [{port: 53, protocol: UDP}, {port: 53, protocol: TCP}]
    - to: [{ipBlock: {cidr: 0.0.0.0/0, except: [10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10, 169.254.0.0/16]}}]
      ports: [{port: 443}]
```
`lab/gpu/gonogo/list-profiles-job.yaml`:
```yaml
# GO/NO-GO (lab/gpu/README.md): applied BY HAND with kubectl, never by Argo (not in any kustomization).
# Runs the NIM's own profile selector on the real A100 before any weights are downloaded.
apiVersion: batch/v1
kind: Job
metadata: {name: list-model-profiles, namespace: raglab-gpu}
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 1200
  ttlSecondsAfterFinished: 3600
  template:
    metadata: {labels: {app: list-model-profiles}}
    spec:
      restartPolicy: Never
      imagePullSecrets: [{name: ngc-pull}]
      securityContext: {runAsNonRoot: true, runAsUser: 1000, runAsGroup: 2000, fsGroup: 2000, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: list
          image: nvcr.io/nim/meta/llama-3.1-8b-instruct:2.1.7@sha256:5ada92d1ca5c30069956e6e1322f0fbb250b4683b566aedb6547b10a64faf00b
          command: [list-model-profiles]
          env:
            - name: NGC_API_KEY
              valueFrom: {secretKeyRef: {name: ngc-api-key, key: NGC_API_KEY}}
          resources:
            requests: {cpu: "1", memory: 4Gi, nvidia.com/gpu: 1}
            limits: {memory: 8Gi, nvidia.com/gpu: 1}
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
```
`lab/gpu/gonogo/gpu-check-job.yaml`:
```yaml
# Applied BY HAND (lab/gpu/README.md, T+0:35). Proves a pod gets the GPU through the NRI/CDI path with no
# runtimeClassName, and pre-pulls the pinned NIM image (reused by the go/no-go Job, NIMCache and NIMService).
apiVersion: batch/v1
kind: Job
metadata: {name: gpu-check, namespace: raglab-gpu}
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 1800
  ttlSecondsAfterFinished: 3600
  template:
    metadata: {labels: {app: gpu-check}}
    spec:
      restartPolicy: Never
      imagePullSecrets: [{name: ngc-pull}]
      securityContext: {runAsNonRoot: true, runAsUser: 1000, runAsGroup: 2000, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: nvidia-smi
          image: nvcr.io/nim/meta/llama-3.1-8b-instruct:2.1.7@sha256:5ada92d1ca5c30069956e6e1322f0fbb250b4683b566aedb6547b10a64faf00b
          command: [nvidia-smi, --query-gpu=name,memory.total,driver_version, --format=csv,noheader]
          resources:
            requests: {cpu: 100m, memory: 256Mi, nvidia.com/gpu: 1}
            limits: {memory: 512Mi, nvidia.com/gpu: 1}
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
```

- [ ] **Step 5: Run the tests**

Run: `uv run --with pytest --with pyyaml --with jsonschema pytest -q tests/test_gpu_manifests.py`
Expected: `5 passed`.

- [ ] **Step 6: Commit and PR**

```bash
scripts/safety-check.sh
git branch --show-current     # feat/gpu-nim (created at the start of the task)
git add tests/fixtures/crds/apps.nvidia.com_nimcaches.yaml lab/gpu/nim lab/gpu/gonogo tests/test_gpu_manifests.py
git commit -m "feat(gpu): NIMCache+NIMService (llama 3.1 8B, replicas 0, profile pinned at go/no-go), CRD-validated"
git push -u origin feat/gpu-nim && gh pr create --fill
```
Expected: CI green. **[SESSION] owner merges.**

---

### Task 4: Generator: `nim-local` provider, per-env `serving`, `dev-gpu` env

**Files:**
- Modify: `lab/catalogue/catalogue.yaml`, `lab/catalogue/generate.py`, `tests/test_generate.py`, `lab/README.md`
- Create (generated): `lab/gpu/envs/dev-gpu/generated/config.json`, `lab/gpu/envs/dev-gpu/generated/models.json`

**Interfaces:**
- Produces: catalogue keys `default_provider`, `providers.<name>.{base_url,timeout_seconds,key_name,key_env}`, model
  `envs: [...]` restriction, env `dir` and `serving: {alias: provider}`. An env without `serving` serves every
  unrestricted model from `default_provider` (Phase A, **byte-identical**). `config.json` holds only referenced
  providers; VK `allowed_models`/`key_ids` per referenced provider; `models.json` ids `<provider>/<alias>`.
  `generate.py [--check] [--out ROOT] [--catalogue FILE]`; exit 2 + `CATALOGUE ERROR:` on a bad serving map.
- Consumed by: Task 5 (dev-gpu overlay `configMapGenerator`), Task 15 (cutover = one-line `serving` change).

- [ ] **Step 1: Record the Phase A hashes before any change**

Run: `shasum -a 256 lab/envs/{dev,qa,prod}/generated/*.json`
Expected (these are pinned in the test below; stop if they differ):
```
2c717f86ff378bbf4b97c21ae810d960b2ac879aa4e52b4b18df0850f1dc1eb0  lab/envs/dev/generated/config.json
102b320a7943c2d5e89c637705a636b6a204e0bdce257ade86b18bd9706b2e1c  lab/envs/dev/generated/models.json
7c3c2e5b3bc4a97a47211724430ca40c5f27b00784178f65b931e9c6a61b111c  lab/envs/qa/generated/config.json
102b320a7943c2d5e89c637705a636b6a204e0bdce257ade86b18bd9706b2e1c  lab/envs/qa/generated/models.json
bc02c6749fa3e199727c61393a00383813c1bf47281cd8d113d9451a5a3247a1  lab/envs/prod/generated/config.json
102b320a7943c2d5e89c637705a636b6a204e0bdce257ade86b18bd9706b2e1c  lab/envs/prod/generated/models.json
```

- [ ] **Step 2: Write the failing tests**

In `tests/test_generate.py`, replace in `test_provider_network_and_allowed_requests`:
```python
    up = CAT["upstream"]
```
with:
```python
    up = CAT["providers"]["nvidia-hosted"]
```
Replace `test_committed_outputs_have_no_drift` with (outputs now live in per-env dirs, so no `--out`):
```python
def test_committed_outputs_have_no_drift():
    r = subprocess.run([sys.executable, str(GEN), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
```
Append:
```python
# ---- Phase B: dev-gpu env, nim-local provider, per-env serving ----
import hashlib

# sha256 of the committed Phase A outputs BEFORE the Phase B generator change. Must never change.
PHASE_A_SHA256 = {
    "dev/generated/config.json": "2c717f86ff378bbf4b97c21ae810d960b2ac879aa4e52b4b18df0850f1dc1eb0",
    "qa/generated/config.json": "7c3c2e5b3bc4a97a47211724430ca40c5f27b00784178f65b931e9c6a61b111c",
    "prod/generated/config.json": "bc02c6749fa3e199727c61393a00383813c1bf47281cd8d113d9451a5a3247a1",
    "dev/generated/models.json": "102b320a7943c2d5e89c637705a636b6a204e0bdce257ade86b18bd9706b2e1c",
    "qa/generated/models.json": "102b320a7943c2d5e89c637705a636b6a204e0bdce257ade86b18bd9706b2e1c",
    "prod/generated/models.json": "102b320a7943c2d5e89c637705a636b6a204e0bdce257ade86b18bd9706b2e1c",
}

def test_phase_a_outputs_byte_identical(out):
    for rel, want in PHASE_A_SHA256.items():
        assert hashlib.sha256((out / rel).read_bytes()).hexdigest() == want, rel
        assert hashlib.sha256((ROOT / "lab/envs" / rel).read_bytes()).hexdigest() == want, rel

def test_phase_a_envs_have_no_serving_and_no_gpu_models():
    for env in ENVS:
        assert "serving" not in CAT["environments"][env] and "dir" not in CAT["environments"][env]
    small = next(m for m in CAT["models"] if m["alias"] == "chat/small")
    assert small["envs"] == ["dev-gpu"]

def test_dev_gpu_written_under_lab_gpu():
    d = ROOT / "lab/gpu/envs/dev-gpu/generated"
    assert (d / "config.json").exists() and (d / "models.json").exists()
    assert not (ROOT / "lab/envs/dev-gpu").exists()

def write_cat(tmp_path, mutate):
    cat = yaml.safe_load((ROOT / "lab/catalogue/catalogue.yaml").read_text())
    mutate(cat)
    p = tmp_path / "cat.yaml"; p.write_text(yaml.safe_dump(cat)); return p

def test_dev_gpu_serving_is_hosted_or_nim_local():
    assert CAT["environments"]["dev-gpu"]["serving"] in ({"chat/small": "nvidia-hosted"}, {"chat/small": "nim-local"})

def test_dev_gpu_hosted_baseline(tmp_path):
    def hosted(c): c["environments"]["dev-gpu"]["serving"]["chat/small"] = "nvidia-hosted"
    o = tmp_path / "o"
    gen_ok(o, "--catalogue", str(write_cat(tmp_path, hosted)))
    c = cfg(o, "dev-gpu")
    jsonschema.validate(c, SCHEMA)
    assert set(c["providers"]) == {"nvidia-hosted"}
    key = c["providers"]["nvidia-hosted"]["keys"][0]
    assert key["name"] == "nvidia-dev-gpu" and key["value"] == "env.NVIDIA_API_KEY"
    assert key["aliases"] == {"chat/small": "meta/llama-3.1-8b-instruct"}
    for vk in c["governance"]["virtual_keys"]:
        assert vk["provider_configs"] == [{"provider": "nvidia-hosted", "weight": 1,
                                           "allowed_models": ["chat/small"], "key_ids": ["*"]}]
    m = json.loads((o / "dev-gpu/generated/models.json").read_text())["models"]
    assert [x["id"] for x in m] == ["nvidia-hosted/chat/small"]
    assert m[0]["capabilities"] == ["chat", "stream", "tools"]

def test_dev_gpu_cutover_to_nim_local(tmp_path):
    def cut(c): c["environments"]["dev-gpu"]["serving"]["chat/small"] = "nim-local"
    o = tmp_path / "o"
    gen_ok(o, "--catalogue", str(write_cat(tmp_path, cut)))
    c = cfg(o, "dev-gpu")
    jsonschema.validate(c, SCHEMA)
    assert set(c["providers"]) == {"nim-local"}, "only referenced providers are emitted"
    p = c["providers"]["nim-local"]
    assert p["network_config"]["base_url"] == "http://llama-8b.raglab-gpu.svc.cluster.local:8000"
    assert p["keys"][0]["value"] == "env.NIM_LOCAL_API_KEY" and p["keys"][0]["name"] == "nim-local-dev-gpu"
    for vk in c["governance"]["virtual_keys"]:
        assert vk["provider_configs"] == [{"provider": "nim-local", "weight": 1,
                                           "allowed_models": ["chat/small"], "key_ids": ["*"]}]
    m = json.loads((o / "dev-gpu/generated/models.json").read_text())["models"]
    assert [x["id"] for x in m] == ["nim-local/chat/small"]
    for rel, want in PHASE_A_SHA256.items():   # the cutover never touches Phase A envs
        assert hashlib.sha256((o / rel).read_bytes()).hexdigest() == want, rel

@pytest.mark.parametrize("mutate,msg", [
    (lambda c: c["environments"]["dev-gpu"]["serving"].update({"chat/small": "nope"}), "unknown provider"),
    (lambda c: c["environments"]["dev-gpu"]["serving"].update({"chat/missing": "nim-local"}), "unknown model"),
    (lambda c: c["environments"]["dev"].update({"serving": {"chat/small": "nim-local"}}), "restricted to"),
    (lambda c: c["environments"]["dev-gpu"].update({"serving": {}}), "serving is empty"),
])
def test_bad_serving_rejected(tmp_path, mutate, msg):
    r = gen(tmp_path / "o", "--catalogue", str(write_cat(tmp_path, mutate)))
    assert r.returncode == 2 and msg in r.stderr, r.stderr
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run --with pytest --with pyyaml --with jsonschema pytest -q tests/test_generate.py`
Expected: FAIL (`KeyError: 'providers'`, no `dev-gpu`, unknown `--catalogue`).

- [ ] **Step 4: Implement**

`lab/catalogue/catalogue.yaml` (whole file; `upstream:` becomes `default_provider` + `providers`):
```yaml
# lab/catalogue/catalogue.yaml — source of truth for models, providers and per-env limits.
# Limits are per env only (no shared defaults), so a limit change is always an env-scoped change.
# An env without `serving` serves every model that has no `envs` list, from default_provider (Phase A).
default_provider: nvidia-hosted
providers:
  nvidia-hosted:
    base_url: https://integrate.api.nvidia.com
    timeout_seconds: 300
    key_name: nvidia            # Bifrost key name = <key_name>-<env>
    key_env: NVIDIA_API_KEY     # key in the env's bifrost-env Secret
  # Phase B, rented GPU cluster only: the in-cluster NIMService (Service name pinned by
  # expose.service.name in lab/gpu/nim/nimservice.yaml). Plain HTTP inside the cluster. The NIM does
  # not check the bearer, so NIM_LOCAL_API_KEY holds a non-secret placeholder.
  nim-local:
    base_url: http://llama-8b.raglab-gpu.svc.cluster.local:8000
    timeout_seconds: 300
    key_name: nim-local
    key_env: NIM_LOCAL_API_KEY
models:
  - alias: chat/glm
    upstream: z-ai/glm-5.3-flash
    context_window: 131072
    max_output_tokens: 8192
    capabilities: [chat, stream, tools]
  - alias: chat/nemotron
    upstream: nvidia/nemotron-3.5-lightning-30b-a3b
    context_window: 131072
    max_output_tokens: 8192
    capabilities: [chat, stream]
  - alias: chat/small
    upstream: meta/llama-3.1-8b-instruct   # same served name on hosted and on the NIM
    context_window: 131072
    max_output_tokens: 4096
    capabilities: [chat, stream, tools]
    envs: [dev-gpu]
# requests_per_minute: main virtual key (generous; normal smoke uses ~12 requests).
# probe_requests_per_minute: a second, tiny virtual key used ONLY by the limit-429 check, so the 429 is
# provably Bifrost's (only 2 calls ever reach upstream), never NVIDIA's own rate limit.
environments:
  dev:  {requests_per_minute: 28, tokens_per_minute: 60000, probe_requests_per_minute: 2, log_retention_days: 3}
  qa:   {requests_per_minute: 28, tokens_per_minute: 60000, probe_requests_per_minute: 2, log_retention_days: 3}
  prod: {requests_per_minute: 28, tokens_per_minute: 60000, probe_requests_per_minute: 2, log_retention_days: 7}
  # Phase B: exists only on the rented GPU cluster (lab/gpu). Cutover = change chat/small's provider.
  dev-gpu:
    dir: gpu/envs/dev-gpu
    serving: {chat/small: nvidia-hosted}
    requests_per_minute: 28
    tokens_per_minute: 60000
    probe_requests_per_minute: 2
    log_retention_days: 1
```

`lab/catalogue/generate.py` (whole file):
```python
#!/usr/bin/env python3
"""Generate per-env Bifrost config.json + models.json from catalogue.yaml.

Secrets are never written: every credential is an `env.VAR` reference resolved by Bifrost at startup
from the bifrost-env Secret. Output is validated in CI against the vendored Bifrost schema.

Serving rule:
  - an env WITHOUT `serving` serves every model that has no `envs` restriction, all from
    `default_provider` (the Phase A shape; its output must stay byte-identical);
  - an env WITH `serving: {alias: provider}` serves exactly those aliases, each from the named provider.
config.json holds only the providers an env references; models.json ids are `<provider>/<alias>`.
Output dir: `<lab>/<env.dir or envs/<env>>/generated`, or `<--out>/<env>/generated` when --out is given.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
LAB = HERE.parent


class CatalogueError(ValueError):
    pass


def serving(cat: dict, env: str) -> dict[str, str]:
    """alias -> provider for one env (validated)."""
    e = cat["environments"][env]
    models = {m["alias"]: m for m in cat["models"]}
    if "serving" not in e:
        prov = cat["default_provider"]
        if prov not in cat["providers"]:
            raise CatalogueError(f"default_provider {prov!r} is not in providers")
        return {a: prov for a, m in models.items() if "envs" not in m}
    out = {}
    for alias, prov in e["serving"].items():
        if alias not in models:
            raise CatalogueError(f"{env}: serving references unknown model {alias!r}")
        if prov not in cat["providers"]:
            raise CatalogueError(f"{env}: serving references unknown provider {prov!r}")
        allowed = models[alias].get("envs")
        if allowed is not None and env not in allowed:
            raise CatalogueError(f"{env}: model {alias!r} is restricted to {allowed}")
        out[alias] = prov
    if not out:
        raise CatalogueError(f"{env}: serving is empty")
    return out


def by_provider(cat: dict, env: str) -> dict[str, dict[str, str]]:
    """provider -> {alias: upstream model name} for one env."""
    up = {m["alias"]: m["upstream"] for m in cat["models"]}
    out: dict[str, dict[str, str]] = {}
    for alias, prov in serving(cat, env).items():
        out.setdefault(prov, {})[alias] = up[alias]
    return out


def provider_block(cat: dict, env: str, prov: str, aliases: dict[str, str]) -> dict:
    p = cat["providers"][prov]
    return {
        "keys": [{
            "name": f"{p['key_name']}-{env}",
            "value": f"env.{p['key_env']}",
            "weight": 1,
            "models": sorted(aliases),
            "aliases": aliases,
        }],
        "network_config": {
            "base_url": p["base_url"],
            "default_request_timeout_in_seconds": p["timeout_seconds"],
            "stream_idle_timeout_in_seconds": p["timeout_seconds"],
        },
        "custom_provider_config": {
            "base_provider_type": "openai",
            "allowed_requests": {
                "list_models": True, "chat_completion": True, "chat_completion_stream": True,
            },
        },
        "store_raw_request_response": False,
    }


def build_config(cat: dict, env: str) -> dict:
    lim = cat["environments"][env]
    provs = by_provider(cat, env)
    rl_id, vk_id = f"rl-{env}", f"vk-{env}"

    def pcs():
        return [{"provider": p, "weight": 1, "allowed_models": sorted(provs[p]), "key_ids": ["*"]}
                for p in sorted(provs)]

    return {
        "version": 2,
        "source_of_truth": "config.json",
        "encryption_key": "env.BIFROST_ENCRYPTION_KEY",
        "client": {
            "enforce_auth_on_inference": True,
            "enable_logging": True,
            "disable_content_logging": True,
            "log_retention_days": lim["log_retention_days"],
        },
        "config_store": {"enabled": True, "type": "sqlite", "config": {"path": "/app/data/config.db"}},
        "logs_store": {"enabled": True, "type": "sqlite", "config": {"path": "/app/data/logs.db"}},
        "providers": {p: provider_block(cat, env, p, provs[p]) for p in sorted(provs)},
        "governance": {
            "auth_config": {
                "is_enabled": True,
                "admin_username": "env.BIFROST_ADMIN_USER",
                "admin_password": "env.BIFROST_ADMIN_PASSWORD",
            },
            "rate_limits": [
                {"id": rl_id,
                 "request_max_limit": lim["requests_per_minute"], "request_reset_duration": "1m",
                 "token_max_limit": lim["tokens_per_minute"], "token_reset_duration": "1m"},
                {"id": f"{rl_id}-probe",
                 "request_max_limit": lim["probe_requests_per_minute"], "request_reset_duration": "1m"},
            ],
            "virtual_keys": [
                {"id": vk_id, "name": vk_id, "value": "env.BIFROST_VK", "is_active": True,
                 "rate_limit_id": rl_id, "provider_configs": pcs()},
                {"id": f"{vk_id}-probe", "name": f"{vk_id}-probe", "value": "env.BIFROST_VK_PROBE",
                 "is_active": True, "rate_limit_id": f"{rl_id}-probe", "provider_configs": pcs()},
            ],
        },
    }


def build_models(cat: dict, env: str) -> dict:
    serv = serving(cat, env)
    # id = "<provider>/<alias>": the routed request string (verified live in Phase A).
    return {"models": [{"id": f"{serv[m['alias']]}/{m['alias']}", "provider": serv[m["alias"]],
                        "alias": m["alias"], "upstream": m["upstream"],
                        "context_window": m["context_window"], "max_output_tokens": m["max_output_tokens"],
                        "capabilities": m["capabilities"]}
                       for m in cat["models"] if m["alias"] in serv]}


def render(obj: dict) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def out_dir(cat: dict, env: str, root: Path | None) -> Path:
    if root is not None:
        return root / env / "generated"
    return LAB / cat["environments"][env].get("dir", f"envs/{env}") / "generated"


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path, default=None,
                    help="root dir holding <env>/generated (default: per-env dir under lab/)")
    ap.add_argument("--catalogue", type=Path, default=HERE / "catalogue.yaml")
    a = ap.parse_args()
    cat = yaml.safe_load(a.catalogue.read_text())
    drift = 0
    try:
        for env in cat["environments"]:
            out = out_dir(cat, env, a.out)
            for name, obj in (("config.json", build_config(cat, env)), ("models.json", build_models(cat, env))):
                p, want = out / name, render(obj)
                if a.check:
                    if not p.exists() or p.read_text() != want:
                        print(f"DRIFT: {p} differs from catalogue"); drift = 1
                else:
                    out.mkdir(parents=True, exist_ok=True); p.write_text(want); print(f"wrote {p}")
    except CatalogueError as e:
        print(f"CATALOGUE ERROR: {e}", file=sys.stderr)
        return 2
    return drift


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Generate and prove Phase A unchanged**

Run:
```bash
uv run --with pyyaml python3 lab/catalogue/generate.py
git status --short lab/envs lab/gpu
uv run --with pyyaml python3 lab/catalogue/generate.py --check; echo check=$?
uv run --with pytest --with pyyaml --with jsonschema pytest -q tests/test_generate.py
```
Expected: `wrote ...` for 8 files; `git status` shows only an untracked `lab/gpu/envs/` entry (nothing under
`lab/envs`); `check=0`; `24 passed`. `lab/gpu/envs/dev-gpu/generated/models.json` has the single id
`nvidia-hosted/chat/small`.

- [ ] **Step 6: Runbook key rename**

In `lab/README.md` section 3 step 6, replace ``set `upstream.base_url` in the catalogue`` with
``set `providers.nvidia-hosted.base_url` in the catalogue``.

- [ ] **Step 7: Commit and PR**

```bash
scripts/safety-check.sh
git branch --show-current     # feat/gpu-catalogue (created at the start of the task)
git add lab/catalogue lab/gpu/envs/dev-gpu/generated tests/test_generate.py lab/README.md
git commit -m "feat(catalogue): providers map, nim-local, per-env serving, dev-gpu env (Phase A outputs byte-identical)"
git push -u origin feat/gpu-catalogue && gh pr create --fill
```
Expected: CI `catalogue drift` and unit tests green. **[SESSION] owner merges.**

---

### Task 5: `lab/gpu` Argo CD, operators, namespaces, dev-gpu overlay, probes

**Files:**
- Create: `scripts/helm_kinds.py`, `scripts/render-gpu-platform.sh`,
  `lab/gpu/argocd/hand-applied/{namespaces,cmp-plugin,repo-server-egress,appproject-default-locked,appproject-raglab-gpu,appproject-raglab-gpu-platform,raglab-gpu-operator,raglab-nim-operator,root-app}.yaml`,
  `lab/gpu/argocd/rendered/{gpu-operator-v26.7.3,k8s-nim-operator-3.1.4}.txt`,
  `lab/gpu/argocd/apps/{raglab-gpu-sops,raglab-dev-gpu}.yaml`,
  `lab/gpu/envs/dev-gpu/{kustomization,networkpolicy-nim-egress}.yaml`, `lab/gpu/probes/netpol-probes.yaml`,
  `tests/test_gpu_argocd.py`
- Modify: `tests/test_gpu_manifests.py` (append)

**Interfaces:**
- Consumes: Task 2 secrets, Task 3 NIM manifests, Task 4 generated dev-gpu config.
- Produces: hand-applied set for the rented cluster (applied by `02-argocd.yml` in GPU mode, Task 6); root
  `raglab-gpu-root` → `lab/gpu/argocd/apps`; AppProject whitelists **equal** the committed rendered summaries (CI);
  `scripts/render-gpu-platform.sh [--check]`.
- Phase A isolation: nothing under `lab/argocd` references `lab/gpu`; GPU apps never point at Phase A paths (CI).

- [ ] **Step 1: Write the failing tests**

`tests/test_gpu_argocd.py`:
```python
"""Phase B: static bounds for the rented-GPU-cluster Argo CD files, and Phase A isolation. No cluster needed."""
from pathlib import Path
import pytest, yaml

ROOT = Path(__file__).resolve().parents[1]
GPU = ROOT / "lab" / "gpu" / "argocd"
HA = GPU / "hand-applied"
GPU_NS = {"raglab-gpu", "raglab-dev-gpu"}
REPO = "https://github.com/OC15141355/rag-stack-lab.git"
PLACEHOLDER = "PENDING-GO-NO-GO"

def load(p):
    return [d for d in yaml.safe_load_all(Path(p).read_text()) if d]

def one(p):
    (d,) = load(p); return d

def gpu_apps():
    files = sorted((GPU / "apps").glob("*.yaml"))
    assert files
    return [(f, d) for f in files for d in load(f)]

def rendered(name):
    lines = (GPU / "rendered" / name).read_text().splitlines()
    cluster = {tuple(l.split(None, 1)[1].split("/", 2)) for l in lines if l.startswith("CLUSTER ")}
    ns = {tuple(l.split(None, 1)[1].split("/", 1)) for l in lines if l.startswith("NS ")}
    assert not [l for l in lines if l.startswith("UNKNOWN ")], f"{name}: unknown-scope kinds need a decision"
    return cluster, ns

def test_gpu_apps_bounded():
    for f, d in gpu_apps():
        s = d["spec"]
        assert d["kind"] == "Application" and d["metadata"]["namespace"] == "raglab-apps", f
        assert s["project"] == "raglab-gpu", f
        assert s["destination"]["namespace"] in GPU_NS, f
        assert s["source"]["repoURL"] == REPO and s["source"]["targetRevision"] == "main", f
        assert s["source"]["path"].startswith("lab/gpu/"), f
        opts = s.get("syncPolicy", {}).get("syncOptions", [])
        assert not any(o.startswith("CreateNamespace") for o in opts), f

def test_only_secrets_app_uses_the_cmp():
    users = [d["metadata"]["name"] for _, d in gpu_apps() if "plugin" in d["spec"]["source"]]
    assert users == ["raglab-gpu-secrets"]
    (app,) = [d for _, d in gpu_apps() if d["metadata"]["name"] == "raglab-gpu-secrets"]
    assert app["spec"]["source"]["path"] == "lab/gpu/secrets"
    assert "ServerSideApply=true" in app["spec"]["syncPolicy"]["syncOptions"]

def test_gpu_cmp_guard():
    script = one(HA / "cmp-plugin.yaml")["data"]["sops-kustomize.yaml"]
    assert '[ "$ARGOCD_APP_NAME" = raglab-apps_raglab-gpu-secrets ]' in script
    assert '[ "$ARGOCD_APP_SOURCE_PATH" = lab/gpu/secrets ]' in script
    assert script.index("ARGOCD_APP_NAME") < script.index("sops --decrypt")

def test_raglab_gpu_project_bounds():
    s = one(HA / "appproject-raglab-gpu.yaml")["spec"]
    assert s["sourceNamespaces"] == ["raglab-apps"] and s["sourceRepos"] == [REPO]
    assert {d["namespace"] for d in s["destinations"]} == GPU_NS
    assert s["clusterResourceWhitelist"] == []
    assert {(r["group"], r["kind"]) for r in s["namespaceResourceWhitelist"]} == {
        ("", "ConfigMap"), ("", "Secret"), ("", "Service"), ("", "PersistentVolumeClaim"), ("apps", "Deployment"),
        ("batch", "Job"), ("networking.k8s.io", "NetworkPolicy"), ("apps.nvidia.com", "NIMService"),
        ("apps.nvidia.com", "NIMCache")}

def test_platform_project_matches_rendered_charts_exactly():
    s = one(HA / "appproject-raglab-gpu-platform.yaml")["spec"]
    assert s["sourceRepos"] == ["https://helm.ngc.nvidia.com/nvidia"]
    assert not s.get("sourceNamespaces")
    assert {d["namespace"] for d in s["destinations"]} == {"gpu-operator", "raglab-system"}
    gc, gn = rendered("gpu-operator-v26.7.3.txt")
    nc, nn = rendered("k8s-nim-operator-3.1.4.txt")
    want = set(gc) | {t for t in nc if not (t[1] == "CustomResourceDefinition" and t[2].endswith(".apps.nvidia.com"))}
    want.add(("apiextensions.k8s.io", "CustomResourceDefinition", "*.apps.nvidia.com"))
    got = {(e["group"], e["kind"], e["name"]) for e in s["clusterResourceWhitelist"]}
    assert got == want
    assert {(e["group"], e["kind"]) for e in s["namespaceResourceWhitelist"]} == gn | nn
    assert not any(k == "RuntimeClass" for _, k, _ in got), "NRI path: no RuntimeClass (spec section 6)"

def test_gpu_operator_app():
    a = one(HA / "raglab-gpu-operator.yaml"); s = a["spec"]; src = s["source"]
    assert s["project"] == "raglab-gpu-platform" and a["metadata"]["namespace"] == "argocd"
    assert (src["repoURL"], src["chart"], src["targetRevision"]) == ("https://helm.ngc.nvidia.com/nvidia", "gpu-operator", "v26.7.3")
    v = src["helm"]["valuesObject"]
    assert v["driver"]["enabled"] is False
    assert v["cdi"] == {"enabled": True, "nriPluginEnabled": True}
    assert v["dcgmExporter"]["enabled"] is False and v["migManager"]["enabled"] is False
    flat = yaml.safe_dump(v)
    assert "CONTAINERD_CONFIG" not in flat and "CONTAINERD_SOCKET" not in flat, "NRI path: no k3s containerd vars"
    assert s["destination"]["namespace"] == "gpu-operator"
    assert {"ServerSideApply=true", "RespectIgnoreDifferences=true"} <= set(s["syncPolicy"]["syncOptions"])
    assert [(i["group"], i["kind"]) for i in s["ignoreDifferences"]] == [("nvidia.com", "ClusterPolicy")]

def test_nim_operator_app_equals_phase_a_values():
    a = one(HA / "raglab-nim-operator.yaml")["spec"]
    p = one(ROOT / "lab/argocd/hand-applied/raglab-system.yaml")["spec"]
    assert a["project"] == "raglab-gpu-platform" and a["destination"]["namespace"] == "raglab-system"
    for k in ("repoURL", "chart", "targetRevision"):
        assert a["source"][k] == p["source"][k]
    assert a["source"]["helm"]["valuesObject"] == p["source"]["helm"]["valuesObject"]

def test_gpu_root_only_creates_applications():
    docs = load(HA / "root-app.yaml")
    (proj,) = [d for d in docs if d["kind"] == "AppProject"]
    (app,) = [d for d in docs if d["kind"] == "Application"]
    assert app["metadata"]["name"] == "raglab-gpu-root" and app["spec"]["project"] == "raglab-gpu-root"
    assert app["spec"]["source"]["path"] == "lab/gpu/argocd/apps"
    assert proj["spec"]["namespaceResourceWhitelist"] == [{"group": "argoproj.io", "kind": "Application"}]
    assert proj["spec"]["clusterResourceWhitelist"] == []
    assert [d["namespace"] for d in proj["spec"]["destinations"]] == ["raglab-apps"]

def test_gpu_namespaces_pod_security():
    ns = {d["metadata"]["name"]: d["metadata"]["labels"] for d in load(HA / "namespaces.yaml")}
    enforce = {k: v["pod-security.kubernetes.io/enforce"] for k, v in ns.items()}
    assert enforce == {"argocd": "restricted", "raglab-apps": "restricted", "raglab-system": "baseline",
                       "gpu-operator": "privileged", "raglab-gpu": "baseline", "raglab-dev-gpu": "restricted"}
    assert ns["raglab-gpu"]["pod-security.kubernetes.io/warn"] == "restricted"

def test_copied_hand_applied_files_identical_to_phase_a():
    for n in ("appproject-default-locked.yaml", "repo-server-egress.yaml"):
        assert (HA / n).read_text() == (ROOT / "lab/argocd/hand-applied" / n).read_text(), n

def test_phase_a_never_sees_gpu_paths():
    (root,) = [d for d in load(ROOT / "lab/argocd/hand-applied/root-app.yaml") if d["kind"] == "Application"]
    assert root["spec"]["source"]["path"] == "lab/argocd/apps"
    for f in (ROOT / "lab/argocd").rglob("*.yaml"):
        assert "lab/gpu" not in f.read_text(), f
    for f, d in gpu_apps():
        p = d["spec"]["source"]["path"]
        assert p != "lab/secrets" and not p.startswith("lab/envs/") and not p.startswith("lab/nim/"), f

def test_nim_app_only_after_go_no_go():
    """raglab-gpu-nim is added by the go/no-go PR; from then on no placeholder may remain."""
    nim_app = GPU / "apps" / "raglab-gpu-nim.yaml"
    texts = [(ROOT / "lab/gpu/nim" / f).read_text() for f in ("nimcache.yaml", "nimservice.yaml")]
    if nim_app.exists():
        assert all(PLACEHOLDER not in t for t in texts), "go/no-go PR must fill the profile"
        d = one(nim_app)
        assert d["spec"]["source"]["path"] == "lab/gpu/nim" and d["spec"]["destination"]["namespace"] == "raglab-gpu"
    else:
        assert all(PLACEHOLDER in t for t in texts)
```

Append to `tests/test_gpu_manifests.py`:
```python
# ---- Task 5: dev-gpu overlay, catalogue agreement, NetworkPolicy probes ----
def test_service_name_and_port_match_catalogue():
    (svc,) = by(build("lab/gpu/nim"), "NIMService")
    cat = yaml.safe_load((ROOT / "lab/catalogue/catalogue.yaml").read_text())
    u = urlparse(cat["providers"]["nim-local"]["base_url"])
    e = svc["spec"]["expose"]["service"]
    assert u.hostname == f'{e["name"]}.raglab-gpu.svc.cluster.local' and u.port == e["port"] == 8000

def test_dev_gpu_overlay():
    docs = build("lab/gpu/envs/dev-gpu")
    for d in docs:
        assert d["metadata"]["namespace"] == "raglab-dev-gpu", d["metadata"]["name"]
    assert not by(docs, "IngressRoute"), "no Traefik on the rented cluster"
    assert [d for d in by(docs, "ConfigMap") if d["metadata"]["name"].startswith("bifrost-config-")]
    base = by(build("lab/envs/dev"), "NetworkPolicy", "bifrost")[0]["spec"]
    assert by(docs, "NetworkPolicy", "bifrost")[0]["spec"] == base, "Phase A base policy reused unchanged"
    nim = by(docs, "NetworkPolicy", "bifrost-to-nim")[0]["spec"]
    assert nim == {"podSelector": {"matchLabels": {"app": "bifrost"}}, "policyTypes": ["Egress"],
                   "egress": [{"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "raglab-gpu"}},
                                       "podSelector": {"matchLabels": {"app.kubernetes.io/component": "nim-llm"}}}],
                               "ports": [{"port": 8000, "protocol": "TCP"}]}]}
    for d in by(docs, "Deployment") + by(docs, "Job"):
        s = d["spec"]["template"]["spec"]
        assert s["securityContext"]["runAsNonRoot"] is True and s["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"

def test_netpol_probes():
    docs = [d for d in yaml.safe_load_all((ROOT / "lab/gpu/probes/netpol-probes.yaml").read_text()) if d]
    pods = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Pod"}
    assert {(n, p["metadata"]["namespace"], p["metadata"]["labels"]["app"]) for n, p in pods.items()} == {
        ("probe-as-bifrost", "raglab-dev-gpu", "bifrost"), ("probe-unlabelled", "raglab-dev-gpu", "probe"),
        ("probe-other-ns", "default", "bifrost")}
    for p in pods.values():
        c = p["spec"]["containers"][0]
        assert "@sha256:" in c["image"] and p["spec"]["securityContext"]["runAsNonRoot"] is True
        assert c["securityContext"]["capabilities"]["drop"] == ["ALL"]
    cms = [d for d in docs if d["kind"] == "ConfigMap"]
    assert {d["metadata"]["namespace"] for d in cms} == {"raglab-dev-gpu", "default"}
    assert all("llama-8b.raglab-gpu.svc.cluster.local:8000/v1/health/ready" in d["data"]["probe.py"] for d in cms)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --with pytest --with pyyaml --with jsonschema pytest -q tests/test_gpu_argocd.py tests/test_gpu_manifests.py`
Expected: FAIL (`lab/gpu/argocd` and `lab/gpu/envs/dev-gpu/kustomization.yaml` missing).

- [ ] **Step 3: Chart summary tooling**

`scripts/helm_kinds.py`:
```python
#!/usr/bin/env python3
"""Summarise `helm template --include-crds` output (stdin) for an AppProject whitelist review.

Prints, sorted and de-duplicated:
  CLUSTER <group>/<kind>/<name>     cluster-scoped objects (each must be name-whitelisted)
  NS      <group>/<kind>            namespaced kinds (namespaceResourceWhitelist)
  HOOK    <hook>  <group>/<kind>/<name>   Helm hooks (Argo maps them to its own phases)
  UNKNOWN <group>/<kind>/<name>     kinds whose scope this script does not know: decide by hand
followed by `SHA256 <hex>` of the raw rendered input (the Helm repo is mutable; record it).
"""
from __future__ import annotations
import hashlib, sys
import yaml

CLUSTER_KINDS = {
    ("", "Namespace"), ("", "PersistentVolume"), ("", "Node"),
    ("apiextensions.k8s.io", "CustomResourceDefinition"),
    ("rbac.authorization.k8s.io", "ClusterRole"), ("rbac.authorization.k8s.io", "ClusterRoleBinding"),
    ("scheduling.k8s.io", "PriorityClass"), ("node.k8s.io", "RuntimeClass"),
    ("storage.k8s.io", "StorageClass"), ("storage.k8s.io", "CSIDriver"),
    ("admissionregistration.k8s.io", "ValidatingWebhookConfiguration"),
    ("admissionregistration.k8s.io", "MutatingWebhookConfiguration"),
    ("admissionregistration.k8s.io", "ValidatingAdmissionPolicy"),
    ("admissionregistration.k8s.io", "ValidatingAdmissionPolicyBinding"),
    ("apiregistration.k8s.io", "APIService"),
    ("nvidia.com", "ClusterPolicy"), ("nfd.k8s-sigs.io", "NodeFeatureRule"),
}
NS_KINDS = {
    ("", "ServiceAccount"), ("", "Service"), ("", "ConfigMap"), ("", "Secret"), ("", "Pod"),
    ("", "PersistentVolumeClaim"), ("apps", "Deployment"), ("apps", "DaemonSet"), ("apps", "StatefulSet"),
    ("batch", "Job"), ("batch", "CronJob"), ("rbac.authorization.k8s.io", "Role"),
    ("rbac.authorization.k8s.io", "RoleBinding"), ("networking.k8s.io", "NetworkPolicy"),
    ("policy", "PodDisruptionBudget"), ("monitoring.coreos.com", "ServiceMonitor"),
    ("monitoring.coreos.com", "PrometheusRule"), ("nfd.k8s-sigs.io", "NodeFeature"),
    ("nfd.k8s-sigs.io", "NodeFeatureGroup"),
}


def main() -> int:
    raw = sys.stdin.read()
    lines = set()
    for d in yaml.safe_load_all(raw):
        if not isinstance(d, dict) or "kind" not in d:
            continue
        api = d.get("apiVersion", "")
        group = api.split("/")[0] if "/" in api else ""
        kind, name = d["kind"], (d.get("metadata") or {}).get("name", "?")
        hook = ((d.get("metadata") or {}).get("annotations") or {}).get("helm.sh/hook")
        if hook:
            lines.add(f"HOOK    {hook}  {group}/{kind}/{name}")
        if (group, kind) in CLUSTER_KINDS:
            lines.add(f"CLUSTER {group}/{kind}/{name}")
        elif (group, kind) in NS_KINDS:
            lines.add(f"NS      {group}/{kind}")
        else:
            lines.add(f"UNKNOWN {group}/{kind}/{name}")
    for l in sorted(lines):
        print(l)
    print(f"SHA256 {hashlib.sha256(raw.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/render-gpu-platform.sh`:
```bash
#!/usr/bin/env bash
# Render the two hand-applied GPU-platform charts with the EXACT inline values from their Applications and
# summarise them (scripts/helm_kinds.py). Default: write lab/gpu/argocd/rendered/*.txt.
# --check: diff against the committed files instead (exit 1 on any difference, e.g. a mutated Helm repo).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
out=lab/gpu/argocd/rendered; tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
check=0; [[ "${1:-}" == --check ]] && check=1
rc=0
render() {  # <application file> <namespace> <output name>
  uv run -q --with pyyaml python3 - "$1" "$tmp/values.yaml" > "$tmp/src" <<'PY'
import sys, yaml
s = yaml.safe_load(open(sys.argv[1]))["spec"]["source"]
yaml.safe_dump(s["helm"]["valuesObject"], open(sys.argv[2], "w"))
print(s["helm"]["releaseName"], s["chart"], s["targetRevision"], s["repoURL"])
PY
  read -r release chart ver repo < "$tmp/src"
  helm template "$release" "$chart" --repo "$repo" --version "$ver" -n "$2" --include-crds -f "$tmp/values.yaml" \
    | uv run -q --with pyyaml python3 scripts/helm_kinds.py > "$tmp/$3"
  if [[ $check == 1 ]]; then
    diff -u "$out/$3" "$tmp/$3" && echo "unchanged $out/$3" || rc=1
  else
    cp "$tmp/$3" "$out/$3"; echo "wrote $out/$3"
  fi
}
render lab/gpu/argocd/hand-applied/raglab-gpu-operator.yaml gpu-operator gpu-operator-v26.7.3.txt
render lab/gpu/argocd/hand-applied/raglab-nim-operator.yaml raglab-system k8s-nim-operator-3.1.4.txt
exit $rc
```

- [ ] **Step 4: Hand-applied files (rented cluster only)**

Copy the two Phase A files that apply unchanged:
```bash
mkdir -p lab/gpu/argocd/hand-applied lab/gpu/argocd/apps lab/gpu/argocd/rendered
cp lab/argocd/hand-applied/appproject-default-locked.yaml lab/argocd/hand-applied/repo-server-egress.yaml lab/gpu/argocd/hand-applied/
```

`lab/gpu/argocd/hand-applied/namespaces.yaml`:
```yaml
# HAND-APPLIED on the rented GPU cluster only. Namespaces are created here, never by Argo CD apps.
apiVersion: v1
kind: Namespace
metadata: {name: argocd, labels: {pod-security.kubernetes.io/enforce: restricted}}
---
# Holds only Application objects (apps-in-any-namespace), created by raglab-gpu-root.
apiVersion: v1
kind: Namespace
metadata: {name: raglab-apps, labels: {pod-security.kubernetes.io/enforce: restricted}}
---
# NIM Operator (same chart and values as Phase A's raglab-system).
apiVersion: v1
kind: Namespace
metadata: {name: raglab-system, labels: {pod-security.kubernetes.io/enforce: baseline}}
---
# GPU Operator operands need host access (driver checks, toolkit, device plugin, NFD).
apiVersion: v1
kind: Namespace
metadata: {name: gpu-operator, labels: {pod-security.kubernetes.io/enforce: privileged}}
---
# NIMCache jobs and the NIMService: operator-rendered pods carry no seccomp profile in v3.1.4, so
# `restricted` cannot pass (spec D7). Enforce baseline; warn/audit restricted to keep the gap visible.
apiVersion: v1
kind: Namespace
metadata:
  name: raglab-gpu
  labels:
    pod-security.kubernetes.io/enforce: baseline
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/audit: restricted
---
apiVersion: v1
kind: Namespace
metadata: {name: raglab-dev-gpu, labels: {pod-security.kubernetes.io/enforce: restricted}}
```
`lab/gpu/argocd/hand-applied/cmp-plugin.yaml`:
```yaml
# HAND-APPLIED on the rented GPU cluster only (same ConfigMap name and key as Phase A, so the shared
# lab/argocd/argocd-values.yaml mounts it unchanged). The guard admits only raglab-gpu-secrets.
apiVersion: v1
kind: ConfigMap
metadata: {name: cmp-plugin, namespace: argocd}
data:
  sops-kustomize.yaml: |
    apiVersion: argoproj.io/v1alpha1
    kind: ConfigManagementPlugin
    metadata: {name: sops-kustomize}
    spec:
      allowConcurrency: true
      generate:
        command:
          - sh
          - -c
          - |
            # Only raglab-gpu-secrets may use this plugin (it holds the session age key).
            [ "$ARGOCD_APP_NAME" = raglab-apps_raglab-gpu-secrets ] && [ "$ARGOCD_APP_SOURCE_PATH" = lab/gpu/secrets ] || { echo "sops-kustomize: not permitted for $ARGOCD_APP_NAME" >&2; exit 1; }
            # Fail closed: a decrypt failure fails the render.
            for f in $(find . -type f -name "*.sops.yaml"); do
              if ! err=$(sops --decrypt --in-place "$f" 2>&1); then
                echo "sops decrypt FAILED for $f: $err" >&2; exit 1
              fi
            done
            kustomize build .
      lockRepo: false
```
`lab/gpu/argocd/hand-applied/appproject-raglab-gpu.yaml`:
```yaml
# HAND-APPLIED on the rented GPU cluster only. Not under lab/gpu/argocd/apps, so a merge cannot widen it.
# GPU env apps only: no cluster-scoped kinds, no RBAC, no ServiceAccounts.
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata: {name: raglab-gpu, namespace: argocd}
spec:
  sourceNamespaces: [raglab-apps]
  sourceRepos: [https://github.com/OC15141355/rag-stack-lab.git]
  destinations:
    - {server: https://kubernetes.default.svc, namespace: raglab-gpu}
    - {server: https://kubernetes.default.svc, namespace: raglab-dev-gpu}
  clusterResourceWhitelist: []
  namespaceResourceWhitelist:
    - {group: "", kind: ConfigMap}
    - {group: "", kind: Secret}
    - {group: "", kind: Service}
    - {group: "", kind: PersistentVolumeClaim}
    - {group: apps, kind: Deployment}
    - {group: batch, kind: Job}
    - {group: networking.k8s.io, kind: NetworkPolicy}
    - {group: apps.nvidia.com, kind: NIMService}
    - {group: apps.nvidia.com, kind: NIMCache}
```
`lab/gpu/argocd/hand-applied/appproject-raglab-gpu-platform.yaml`:
```yaml
# HAND-APPLIED on the rented GPU cluster only. Only the GPU Operator (v26.7.3) and NIM Operator (3.1.4),
# only what their charts render with the inline values: lab/gpu/argocd/rendered/*.txt (CI-enforced).
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata: {name: raglab-gpu-platform, namespace: argocd}
spec:
  sourceRepos: [https://helm.ngc.nvidia.com/nvidia]
  destinations:
    - {server: https://kubernetes.default.svc, namespace: gpu-operator}
    - {server: https://kubernetes.default.svc, namespace: raglab-system}
  clusterResourceWhitelist:
    # GPU Operator v26.7.3
    - {group: apiextensions.k8s.io, kind: CustomResourceDefinition, name: clusterpolicies.nvidia.com}
    - {group: apiextensions.k8s.io, kind: CustomResourceDefinition, name: computedomaincliques.resource.nvidia.com}
    - {group: apiextensions.k8s.io, kind: CustomResourceDefinition, name: computedomains.resource.nvidia.com}
    - {group: apiextensions.k8s.io, kind: CustomResourceDefinition, name: gpuclusters.nvidia.com}
    - {group: apiextensions.k8s.io, kind: CustomResourceDefinition, name: nodefeaturegroups.nfd.k8s-sigs.io}
    - {group: apiextensions.k8s.io, kind: CustomResourceDefinition, name: nodefeaturerules.nfd.k8s-sigs.io}
    - {group: apiextensions.k8s.io, kind: CustomResourceDefinition, name: nodefeatures.nfd.k8s-sigs.io}
    - {group: apiextensions.k8s.io, kind: CustomResourceDefinition, name: nvidiadrivers.nvidia.com}
    - {group: nvidia.com, kind: ClusterPolicy, name: cluster-policy}
    - {group: rbac.authorization.k8s.io, kind: ClusterRole, name: gpu-operator}
    - {group: rbac.authorization.k8s.io, kind: ClusterRole, name: gpu-operator-node-feature-discovery}
    - {group: rbac.authorization.k8s.io, kind: ClusterRole, name: gpu-operator-node-feature-discovery-gc}
    - {group: rbac.authorization.k8s.io, kind: ClusterRole, name: gpu-operator-node-feature-discovery-prune}
    - {group: rbac.authorization.k8s.io, kind: ClusterRole, name: gpu-operator-upgrade-crd-hook-role}
    - {group: rbac.authorization.k8s.io, kind: ClusterRoleBinding, name: gpu-operator}
    - {group: rbac.authorization.k8s.io, kind: ClusterRoleBinding, name: gpu-operator-node-feature-discovery}
    - {group: rbac.authorization.k8s.io, kind: ClusterRoleBinding, name: gpu-operator-node-feature-discovery-gc}
    - {group: rbac.authorization.k8s.io, kind: ClusterRoleBinding, name: gpu-operator-node-feature-discovery-prune}
    - {group: rbac.authorization.k8s.io, kind: ClusterRoleBinding, name: gpu-operator-upgrade-crd-hook-binding}
    # NIM Operator 3.1.4 (same names as Phase A's raglab-platform)
    - {group: apiextensions.k8s.io, kind: CustomResourceDefinition, name: "*.apps.nvidia.com"}
    - {group: rbac.authorization.k8s.io, kind: ClusterRole, name: k8s-nim-operator-role}
    - {group: rbac.authorization.k8s.io, kind: ClusterRole, name: k8s-nim-operator-metrics-reader}
    - {group: rbac.authorization.k8s.io, kind: ClusterRole, name: nim-operator-upgrade-crd-hook-role}
    - {group: rbac.authorization.k8s.io, kind: ClusterRoleBinding, name: k8s-nim-operator-rolebinding}
    - {group: rbac.authorization.k8s.io, kind: ClusterRoleBinding, name: nim-operator-upgrade-crd-hook-binding}
  namespaceResourceWhitelist:
    - {group: "", kind: ConfigMap}
    - {group: "", kind: ServiceAccount}
    - {group: "", kind: Service}
    - {group: apps, kind: DaemonSet}
    - {group: apps, kind: Deployment}
    - {group: batch, kind: Job}
    - {group: rbac.authorization.k8s.io, kind: Role}
    - {group: rbac.authorization.k8s.io, kind: RoleBinding}
```
`lab/gpu/argocd/hand-applied/raglab-gpu-operator.yaml`:
```yaml
# HAND-APPLIED on the rented GPU cluster only (project raglab-gpu-platform). Values are inline so a merge
# cannot change them. If you change valuesObject, re-render lab/gpu/argocd/rendered/gpu-operator-v26.7.3.txt.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: raglab-gpu-operator
  namespace: argocd
  finalizers: [resources-finalizer.argocd.argoproj.io]
spec:
  project: raglab-gpu-platform
  source:
    repoURL: https://helm.ngc.nvidia.com/nvidia
    chart: gpu-operator
    targetRevision: v26.7.3
    helm:
      releaseName: gpu-operator
      valuesObject:
        driver: {enabled: false}             # Lambda Stack ships the driver; gate: nvidia-smi passes first
        toolkit: {enabled: true}             # operator-managed toolkit + CDI spec (see lab/gpu/README.md, NRI)
        cdi: {enabled: true, nriPluginEnabled: true}   # NRI: no k3s containerd vars, no 'nvidia' RuntimeClass
        nfd: {enabled: true}
        dcgm: {enabled: false}
        dcgmExporter: {enabled: false, serviceMonitor: {enabled: false}}
        migManager: {enabled: false}
        nodeStatusExporter: {enabled: false}
  destination: {server: https://kubernetes.default.svc, namespace: gpu-operator}
  # The operator mutates ClusterPolicy defaults/status; ignore the fields its own manager owns.
  ignoreDifferences:
    - {group: nvidia.com, kind: ClusterPolicy, managedFieldsManagers: [gpu-operator]}
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [ServerSideApply=true, RespectIgnoreDifferences=true]
    retry: {limit: 5, backoff: {duration: 30s, factor: 2, maxDuration: 5m}}
```
`lab/gpu/argocd/hand-applied/raglab-nim-operator.yaml`:
```yaml
# HAND-APPLIED on the rented GPU cluster only (project raglab-gpu-platform). Same chart, version and
# values as Phase A's lab/argocd/hand-applied/raglab-system.yaml (CI asserts they are equal).
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: raglab-nim-operator
  namespace: argocd
  finalizers: [resources-finalizer.argocd.argoproj.io]
spec:
  project: raglab-gpu-platform
  source:
    repoURL: https://helm.ngc.nvidia.com/nvidia
    chart: k8s-nim-operator
    targetRevision: 3.1.4
    helm:
      releaseName: raglab-nim-operator
      valuesObject:
        operator:
          replicas: 1
          upgradeCRD: true
          image:
            repository: nvcr.io/nvidia/cloud-native/k8s-nim-operator
            tag: v3.1.4@sha256:3f84870acea8af063573898e6e2496379cc11c9e63046c073b1f8a6dc348f209
            pullPolicy: IfNotPresent
          resources:
            requests: {cpu: 100m, memory: 128Mi}
            limits: {memory: 256Mi}
          admissionController: {enabled: false}
  destination: {server: https://kubernetes.default.svc, namespace: raglab-system}
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [ServerSideApply=true]
    retry: {limit: 5, backoff: {duration: 30s, factor: 2, maxDuration: 5m}}
```
`lab/gpu/argocd/hand-applied/root-app.yaml`:
```yaml
# HAND-APPLIED on the rented GPU cluster only. Syncs only lab/gpu/argocd/apps (Applications in project
# raglab-gpu). The home lab's root watches lab/argocd/apps and never sees this path.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: raglab-gpu-root, namespace: argocd}
spec:
  project: raglab-gpu-root
  source: {repoURL: https://github.com/OC15141355/rag-stack-lab.git, targetRevision: main, path: lab/gpu/argocd/apps}
  destination: {server: https://kubernetes.default.svc, namespace: raglab-apps}
  syncPolicy: {automated: {prune: true, selfHeal: true}}
---
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata: {name: raglab-gpu-root, namespace: argocd}
spec:
  sourceRepos: [https://github.com/OC15141355/rag-stack-lab.git]
  destinations: [{server: https://kubernetes.default.svc, namespace: raglab-apps}]
  clusterResourceWhitelist: []
  namespaceResourceWhitelist: [{group: argoproj.io, kind: Application}]
```

Helm hooks in the render (Argo maps them to its own phases): `pre-upgrade` CRD-upgrade Jobs for both charts (run as
PreSync on every sync; their ClusterRole/Binding are whitelisted above), gpu-operator `pre-delete`
`gpu-operator-cleanup-gpucluster` and `post-delete` NFD prune hooks (deletion only; never exercised, the VM is
terminated instead of deleting the app).

- [ ] **Step 5: Render the chart summaries (needs `helm` and network; read-only)**

Run: `chmod +x scripts/render-gpu-platform.sh && scripts/render-gpu-platform.sh && cat lab/gpu/argocd/rendered/gpu-operator-v26.7.3.txt`
Expected: two `wrote ...` lines and exactly:
```
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/clusterpolicies.nvidia.com
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/computedomaincliques.resource.nvidia.com
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/computedomains.resource.nvidia.com
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/gpuclusters.nvidia.com
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/nodefeaturegroups.nfd.k8s-sigs.io
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/nodefeaturerules.nfd.k8s-sigs.io
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/nodefeatures.nfd.k8s-sigs.io
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/nvidiadrivers.nvidia.com
CLUSTER nvidia.com/ClusterPolicy/cluster-policy
CLUSTER rbac.authorization.k8s.io/ClusterRole/gpu-operator
CLUSTER rbac.authorization.k8s.io/ClusterRole/gpu-operator-node-feature-discovery
CLUSTER rbac.authorization.k8s.io/ClusterRole/gpu-operator-node-feature-discovery-gc
CLUSTER rbac.authorization.k8s.io/ClusterRole/gpu-operator-node-feature-discovery-prune
CLUSTER rbac.authorization.k8s.io/ClusterRole/gpu-operator-upgrade-crd-hook-role
CLUSTER rbac.authorization.k8s.io/ClusterRoleBinding/gpu-operator
CLUSTER rbac.authorization.k8s.io/ClusterRoleBinding/gpu-operator-node-feature-discovery
CLUSTER rbac.authorization.k8s.io/ClusterRoleBinding/gpu-operator-node-feature-discovery-gc
CLUSTER rbac.authorization.k8s.io/ClusterRoleBinding/gpu-operator-node-feature-discovery-prune
CLUSTER rbac.authorization.k8s.io/ClusterRoleBinding/gpu-operator-upgrade-crd-hook-binding
HOOK    post-delete  /ServiceAccount/gpu-operator-node-feature-discovery-prune
HOOK    post-delete  batch/Job/gpu-operator-node-feature-discovery-prune
HOOK    post-delete  rbac.authorization.k8s.io/ClusterRole/gpu-operator-node-feature-discovery-prune
HOOK    post-delete  rbac.authorization.k8s.io/ClusterRoleBinding/gpu-operator-node-feature-discovery-prune
HOOK    pre-delete  batch/Job/gpu-operator-cleanup-gpucluster
HOOK    pre-upgrade  /ServiceAccount/gpu-operator-upgrade-crd-hook-sa
HOOK    pre-upgrade  batch/Job/gpu-operator-upgrade-crd
HOOK    pre-upgrade  rbac.authorization.k8s.io/ClusterRole/gpu-operator-upgrade-crd-hook-role
HOOK    pre-upgrade  rbac.authorization.k8s.io/ClusterRoleBinding/gpu-operator-upgrade-crd-hook-binding
NS      /ConfigMap
NS      /ServiceAccount
NS      apps/DaemonSet
NS      apps/Deployment
NS      batch/Job
NS      rbac.authorization.k8s.io/Role
NS      rbac.authorization.k8s.io/RoleBinding
SHA256 cb54957d282abefb6bc6cd0d5e9b2358af77a82ba4d5f6a5537e688e4c0dd71b
```
and `lab/gpu/argocd/rendered/k8s-nim-operator-3.1.4.txt`:
```
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/nemocustomizers.apps.nvidia.com
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/nemodatastores.apps.nvidia.com
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/nemoentitystores.apps.nvidia.com
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/nemoevaluators.apps.nvidia.com
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/nemoguardrails.apps.nvidia.com
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/nimbuilds.apps.nvidia.com
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/nimcaches.apps.nvidia.com
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/nimpipelines.apps.nvidia.com
CLUSTER apiextensions.k8s.io/CustomResourceDefinition/nimservices.apps.nvidia.com
CLUSTER rbac.authorization.k8s.io/ClusterRole/k8s-nim-operator-metrics-reader
CLUSTER rbac.authorization.k8s.io/ClusterRole/k8s-nim-operator-role
CLUSTER rbac.authorization.k8s.io/ClusterRole/nim-operator-upgrade-crd-hook-role
CLUSTER rbac.authorization.k8s.io/ClusterRoleBinding/k8s-nim-operator-rolebinding
CLUSTER rbac.authorization.k8s.io/ClusterRoleBinding/nim-operator-upgrade-crd-hook-binding
HOOK    pre-upgrade  /ServiceAccount/nim-operator-upgrade-crd-hook-sa
HOOK    pre-upgrade  batch/Job/nim-operator-upgrade-crd
HOOK    pre-upgrade  rbac.authorization.k8s.io/ClusterRole/nim-operator-upgrade-crd-hook-role
HOOK    pre-upgrade  rbac.authorization.k8s.io/ClusterRoleBinding/nim-operator-upgrade-crd-hook-binding
NS      /Service
NS      /ServiceAccount
NS      apps/Deployment
NS      batch/Job
NS      rbac.authorization.k8s.io/Role
NS      rbac.authorization.k8s.io/RoleBinding
SHA256 8bc2cfc8ec6d1859425f1abe49425e964bcf63bd8f2e68cd2152d5b01f230615
```
If either differs (new chart content in the mutable repo, or another Helm version), do **not** edit the test: update the
`raglab-gpu-platform` whitelist to the new CLUSTER/NS lines only after reviewing each new name, and say so in the PR.

- [ ] **Step 6: Child apps, dev-gpu overlay, probes**

`lab/gpu/argocd/apps/raglab-gpu-sops.yaml` (the file name avoids `.gitignore`'s `*secret*`):
```yaml
# File name avoids "secret" (.gitignore `*secret*`); the Application is raglab-gpu-secrets (CMP guard name).
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: raglab-gpu-secrets, namespace: raglab-apps, finalizers: [resources-finalizer.argocd.argoproj.io]}
spec:
  project: raglab-gpu
  source:
    repoURL: https://github.com/OC15141355/rag-stack-lab.git
    targetRevision: main
    path: lab/gpu/secrets
    plugin: {name: sops-kustomize}
  # Manifests carry their own namespaces (raglab-gpu, raglab-dev-gpu); each is still checked by the project.
  destination: {server: https://kubernetes.default.svc, namespace: raglab-gpu}
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [ServerSideApply=true]
    retry: {limit: 10, backoff: {duration: 30s, factor: 2, maxDuration: 5m}}
```
`lab/gpu/argocd/apps/raglab-dev-gpu.yaml`:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: raglab-dev-gpu, namespace: raglab-apps, finalizers: [resources-finalizer.argocd.argoproj.io]}
spec:
  project: raglab-gpu
  source:
    repoURL: https://github.com/OC15141355/rag-stack-lab.git
    targetRevision: main
    path: lab/gpu/envs/dev-gpu
    kustomize:
      commonAnnotations: {raglab/revision: "${ARGOCD_APP_REVISION}"}
      commonAnnotationsEnvsubst: true
  destination: {server: https://kubernetes.default.svc, namespace: raglab-dev-gpu}
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [SkipDryRunOnMissingResource=true]
    retry: {limit: 5, backoff: {duration: 30s, factor: 2, maxDuration: 5m}}
```
`lab/gpu/envs/dev-gpu/kustomization.yaml`:
```yaml
# Phase B (rented GPU cluster only): Bifrost for dev-gpu, reusing the Phase A base unchanged.
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: raglab-dev-gpu
resources: [../../../envs/base, networkpolicy-nim-egress.yaml]
configMapGenerator:
  - name: bifrost-config
    files: [config.json=generated/config.json, models.json=generated/models.json]
commonAnnotations:
  raglab/env: dev-gpu
patches:
  # k3s on the rented VM runs without Traefik: nothing is published, Bifrost is reached by port-forward.
  - patch: |-
      $patch: delete
      apiVersion: traefik.io/v1alpha1
      kind: IngressRoute
      metadata:
        name: bifrost-v1
```
`lab/gpu/envs/dev-gpu/networkpolicy-nim-egress.yaml`:
```yaml
# Additive to the base `bifrost` policy (which excludes RFC1918): Bifrost may also reach the in-cluster NIM.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: bifrost-to-nim}
spec:
  podSelector: {matchLabels: {app: bifrost}}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: raglab-gpu}}
          podSelector: {matchLabels: {app.kubernetes.io/component: nim-llm}}
      ports: [{port: 8000, protocol: TCP}]
```
`lab/gpu/probes/netpol-probes.yaml`:
```yaml
# Applied BY HAND after the NIMService is Ready (lab/gpu/README.md, NetworkPolicy probes). Each pod makes one
# HTTP GET to the NIM's /v1/health/ready and prints PROBE <name> status=<code> or PROBE <name> BLOCKED.
#   probe-as-bifrost  raglab-dev-gpu, label app=bifrost  -> expect status=200 (allowed path)
#   probe-unlabelled  raglab-dev-gpu, label app=probe    -> expect BLOCKED (NIM ingress policy)
#   probe-other-ns    default,        label app=bifrost  -> expect BLOCKED (namespaceSelector)
apiVersion: v1
kind: ConfigMap
metadata: {name: netpol-probe, namespace: raglab-dev-gpu}
data:
  probe.py: |
    import os, urllib.request
    n, u = os.environ["PROBE"], "http://llama-8b.raglab-gpu.svc.cluster.local:8000/v1/health/ready"
    try:
        print(f"PROBE {n} status={urllib.request.urlopen(u, timeout=8).status}")
    except Exception as e:
        print(f"PROBE {n} BLOCKED ({e.__class__.__name__})")
---
apiVersion: v1
kind: ConfigMap
metadata: {name: netpol-probe, namespace: default}
data:
  probe.py: |
    import os, urllib.request
    n, u = os.environ["PROBE"], "http://llama-8b.raglab-gpu.svc.cluster.local:8000/v1/health/ready"
    try:
        print(f"PROBE {n} status={urllib.request.urlopen(u, timeout=8).status}")
    except Exception as e:
        print(f"PROBE {n} BLOCKED ({e.__class__.__name__})")
---
apiVersion: v1
kind: Pod
metadata: {name: probe-as-bifrost, namespace: raglab-dev-gpu, labels: {app: bifrost, raglab/probe: "true"}}
spec:
  restartPolicy: Never
  securityContext: {runAsNonRoot: true, runAsUser: 1000, seccompProfile: {type: RuntimeDefault}}
  containers:
    - name: probe
      image: python:3.12-slim@sha256:a0e2dd78cc679ddfffea960fe45ecfcff9ac2f68d67917a0edfcde5c2100151b
      command: [python3, /probe/probe.py]
      env: [{name: PROBE, valueFrom: {fieldRef: {fieldPath: metadata.name}}}]
      resources: {requests: {cpu: 10m, memory: 32Mi}, limits: {memory: 64Mi}}
      securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
      volumeMounts: [{name: probe, mountPath: /probe}]
  volumes: [{name: probe, configMap: {name: netpol-probe}}]
---
apiVersion: v1
kind: Pod
metadata: {name: probe-unlabelled, namespace: raglab-dev-gpu, labels: {app: probe, raglab/probe: "true"}}
spec:
  restartPolicy: Never
  securityContext: {runAsNonRoot: true, runAsUser: 1000, seccompProfile: {type: RuntimeDefault}}
  containers:
    - name: probe
      image: python:3.12-slim@sha256:a0e2dd78cc679ddfffea960fe45ecfcff9ac2f68d67917a0edfcde5c2100151b
      command: [python3, /probe/probe.py]
      env: [{name: PROBE, valueFrom: {fieldRef: {fieldPath: metadata.name}}}]
      resources: {requests: {cpu: 10m, memory: 32Mi}, limits: {memory: 64Mi}}
      securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
      volumeMounts: [{name: probe, mountPath: /probe}]
  volumes: [{name: probe, configMap: {name: netpol-probe}}]
---
apiVersion: v1
kind: Pod
metadata: {name: probe-other-ns, namespace: default, labels: {app: bifrost, raglab/probe: "true"}}
spec:
  restartPolicy: Never
  securityContext: {runAsNonRoot: true, runAsUser: 1000, seccompProfile: {type: RuntimeDefault}}
  containers:
    - name: probe
      image: python:3.12-slim@sha256:a0e2dd78cc679ddfffea960fe45ecfcff9ac2f68d67917a0edfcde5c2100151b
      command: [python3, /probe/probe.py]
      env: [{name: PROBE, valueFrom: {fieldRef: {fieldPath: metadata.name}}}]
      resources: {requests: {cpu: 10m, memory: 32Mi}, limits: {memory: 64Mi}}
      securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
      volumeMounts: [{name: probe, mountPath: /probe}]
  volumes: [{name: probe, configMap: {name: netpol-probe}}]
```

- [ ] **Step 7: Run the tests and the existing suites**

Run: `uv run --with pytest --with pyyaml --with jsonschema pytest -q tests/test_gpu_argocd.py tests/test_gpu_manifests.py tests/test_argocd_bounds.py tests/test_manifests.py && git check-ignore lab/gpu/argocd/apps/*.yaml; echo ignored=$?`
Expected: all pass (`12` + `8` new; Phase A bounds/manifests unchanged) and `ignored=1` (no file ignored).

- [ ] **Step 8: Commit and PR**

```bash
scripts/safety-check.sh
git branch --show-current     # feat/gpu-argocd (created at the start of the task)
git add scripts/helm_kinds.py scripts/render-gpu-platform.sh lab/gpu/argocd lab/gpu/envs/dev-gpu lab/gpu/probes tests/test_gpu_argocd.py tests/test_gpu_manifests.py
git commit -m "feat(gpu): rented-cluster Argo CD set (GPU Operator v26.7.3 NRI, NIM Operator 3.1.4), dev-gpu overlay, probes"
git push -u origin feat/gpu-argocd && gh pr create --fill
```
Expected: CI green. **[SESSION] owner merges.** The home lab's Argo is unaffected (its root watches `lab/argocd/apps`).

---

### Task 6: Playbook GPU-session mode (Phase A path pinned)

**Files:**
- Create: `lab/bootstrap/vars/phase-a.yml`, `lab/bootstrap/vars/gpu-session.yml`, `lab/bootstrap/playbooks/04-gpu-prep.yml`,
  `lab/bootstrap/inventory.gpu.example.ini`, `tests/test_playbooks.py`
- Modify: `lab/bootstrap/playbooks/01-platform.yml`, `02-argocd.yml`, `03-handover.yml`, `lab/bootstrap/ansible.cfg`,
  `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `-e gpu_session=true` selects `vars/gpu-session.yml` in every play that needs mode values; unset/false
  selects `vars/phase-a.yml`, whose values are exactly the previous literals. GPU mode: kubeconfig
  `lab/bootstrap/kubeconfig.gpu` (server stays `127.0.0.1`, reached by SSH tunnel), k3s without Traefik/servicelb,
  nvidia-smi gate and host Docker/containerd stopped before k3s, session age key, `lab/gpu/argocd/hand-applied`,
  operators applied by 02, GPU `required_apps` in 03. `04-gpu-prep.yml` gates containerd/NRI/disk and writes
  `~/.raglab-gpu/evidence/gpu-prep.txt`.
- Consumed by: Task 11.

- [ ] **Step 1: Write the failing tests**

`tests/test_playbooks.py`:
```python
"""Bootstrap playbooks: Phase A behaviour pinned, GPU-session mode isolated.

The mode-dependent values live in lab/bootstrap/vars/{phase-a,gpu-session}.yml. 02/03 are executed for real
(both modes) against fake kubectl/helm/stat on PATH, recording every command they run.
"""
import json, os, shutil, subprocess
from pathlib import Path
import pytest, yaml

ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT / "lab" / "bootstrap"
SELECTOR = "../vars/{{ 'gpu-session' if (gpu_session | default(false) | bool) else 'phase-a' }}.yml"
HAVE_ANSIBLE = shutil.which("ansible-playbook") is not None
if os.environ.get("CI") and not HAVE_ANSIBLE:
    def test_ansible_present_in_ci():
        pytest.fail("CI is set but ansible-playbook is not installed (uv run --with ansible-core)")
needs_ansible = pytest.mark.skipif(not HAVE_ANSIBLE, reason="ansible-playbook not installed")

PHASE_A_REQUIRED = ["argocd/raglab-root", "argocd/raglab-system", "raglab-apps/raglab-secrets",
                    "raglab-apps/raglab-dev", "raglab-apps/raglab-qa", "raglab-apps/raglab-prod",
                    "raglab-apps/raglab-nim-dev", "raglab-apps/raglab-nim-qa", "raglab-apps/raglab-nim-prod"]
GPU_REQUIRED = ["argocd/raglab-gpu-root", "argocd/raglab-gpu-operator", "argocd/raglab-nim-operator",
                "raglab-apps/raglab-gpu-secrets", "raglab-apps/raglab-dev-gpu"]

def mode_vars(name):
    return yaml.safe_load((BOOT / "vars" / f"{name}.yml").read_text())

def test_phase_a_values_pinned():
    assert mode_vars("phase-a") == {
        "kubeconfig_name": "kubeconfig", "rewrite_kubeconfig_server": True, "install_guest_agent": True,
        "gpu_host_prep": False, "k3s_exec": "server --secrets-encryption --write-kubeconfig-mode 0600",
        "hand_applied_dir": "argocd/hand-applied", "age_key_relpath": ".sops/raglab-age-key.txt",
        "app_projects": ["appproject-raglab.yaml", "appproject-raglab-platform.yaml"],
        "platform_apps": ["raglab-system.yaml"], "required_apps": PHASE_A_REQUIRED}

def test_gpu_values():
    v = mode_vars("gpu-session")
    assert set(v) == set(mode_vars("phase-a")), "both modes define the same variables"
    assert v["age_key_relpath"] == ".sops/raglab-gpu-session/age-key.txt"
    assert v["kubeconfig_name"] == "kubeconfig.gpu" and v["rewrite_kubeconfig_server"] is False
    assert "--disable traefik" in v["k3s_exec"] and "--secrets-encryption" in v["k3s_exec"]
    assert v["hand_applied_dir"] == "gpu/argocd/hand-applied" and v["required_apps"] == GPU_REQUIRED
    for f in v["app_projects"] + v["platform_apps"] + ["root-app.yaml", "namespaces.yaml", "cmp-plugin.yaml"]:
        assert (ROOT / "lab" / v["hand_applied_dir"] / f).is_file(), f

def test_every_play_that_needs_mode_vars_loads_them():
    for name, plays in (("01-platform.yml", [1, 2]), ("02-argocd.yml", [0]), ("03-handover.yml", [0])):
        doc = yaml.safe_load((BOOT / "playbooks" / name).read_text())
        for i in plays:
            assert doc[i]["vars_files"] == [SELECTOR], (name, i)

@needs_ansible
@pytest.mark.parametrize("mode", ["false", "true"])
@pytest.mark.parametrize("pb", ["01-platform.yml", "02-argocd.yml", "03-handover.yml", "04-gpu-prep.yml"])
def test_syntax_both_modes(mode, pb):
    r = subprocess.run(["ansible-playbook", "-i", "inventory.example.ini", "--syntax-check", "-e", f"gpu_session={mode}",
                        f"playbooks/{pb}"], cwd=BOOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def fake_env(tmp_path, apps):
    b = tmp_path / "bin"; b.mkdir()
    log = tmp_path / "log"; appsf = tmp_path / "apps.json"
    appsf.write_text(json.dumps({"items": [
        {"metadata": {"namespace": a.split("/")[0], "name": a.split("/")[1]},
         "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"},
                    "operationState": {"phase": "Succeeded"}}} for a in apps]}))
    (b / "kubectl").write_text(
        '#!/bin/sh\necho "$KUBECONFIG|$*" >> "$FAKE_LOG"\n'
        'case "$*" in\n'
        '  "get applications -A -o json") cat "$FAKE_APPS" ;;\n'
        '  "get secrets -A -o json") echo \'{"items": []}\' ;;\n'
        '  "-n argocd get secret sops-age-key") exit 1 ;;\n'
        'esac\nexit 0\n')
    (b / "helm").write_text('#!/bin/sh\necho "helm|$*" >> "$FAKE_LOG"\nexit 0\n')
    (b / "stat").write_text("#!/bin/sh\necho 600\n")
    for f in b.iterdir(): f.chmod(0o755)
    home = tmp_path / "home"
    for rel in (".sops/raglab-age-key.txt", ".sops/raglab-gpu-session/age-key.txt"):
        k = home / rel; k.parent.mkdir(parents=True, exist_ok=True)
        k.write_text("AGE-SECRET-" + "KEY-1" + "Q" * 58 + "\n"); k.chmod(0o600)   # fake, built at runtime
    env = {**os.environ, "PATH": f"{b}:{os.environ['PATH']}", "HOME": str(home), "FAKE_LOG": str(log),
           "FAKE_APPS": str(appsf), "ANSIBLE_LOCAL_TEMP": str(tmp_path / "ans"), "ANSIBLE_NOCOLOR": "1"}
    return env, log

def play(pb, mode, env):
    return subprocess.run(["ansible-playbook", "-i", "localhost,", "-c", "local", "-e", f"gpu_session={mode}",
                           "-e", "ansible_python_interpreter={{ ansible_playbook_python }}", f"playbooks/{pb}"],
                          cwd=BOOT, env=env, capture_output=True, text=True)

def logged(log):
    return [l.split("|", 1) for l in log.read_text().splitlines()]

@needs_ansible
@pytest.mark.parametrize("mode,apps,kc", [("false", PHASE_A_REQUIRED, "kubeconfig"), ("true", GPU_REQUIRED, "kubeconfig.gpu")])
def test_handover_runs_against_the_right_cluster_and_apps(tmp_path, mode, apps, kc):
    env, log = fake_env(tmp_path, apps)
    r = play("03-handover.yml", mode, env)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    calls = logged(log)
    assert calls and all(Path(k).resolve() == (BOOT / kc).resolve() for k, _ in calls)

def expected_02(ha, key):
    return ([f"apply --server-side -f {ha}/namespaces.yaml", f"apply --server-side -f {ha}/cmp-plugin.yaml",
             f"apply --server-side -f {ha}/repo-server-egress.yaml", "-n argocd get secret sops-age-key",
             f"-n argocd create secret generic sops-age-key --from-file=keys.txt={key}"])

@needs_ansible
def test_argocd_phase_a_sequence_unchanged(tmp_path):
    env, log = fake_env(tmp_path, [])
    r = play("02-argocd.yml", "false", env)
    assert r.returncode == 0, r.stdout[-3000:]
    ha = (BOOT / "playbooks/../../argocd/hand-applied")
    got = [c for k, c in logged(log)]
    key = f"{env['HOME']}/.sops/raglab-age-key.txt"
    assert [c.replace(str(BOOT / "playbooks/../.."), "LAB") for c in got] == [
        c.replace(str(BOOT / "playbooks/../.."), "LAB") for c in expected_02(str(ha), key)] + [
        "upgrade --install argocd argo-cd --repo https://argoproj.github.io/argo-helm --version 10.18.3 -n argocd "
        "-f LAB/argocd/argocd-values.yaml --wait --timeout 10m",
        "apply --server-side --force-conflicts -f LAB/argocd/hand-applied/appproject-default-locked.yaml",
        "apply --server-side -f LAB/argocd/hand-applied/appproject-raglab.yaml",
        "apply --server-side -f LAB/argocd/hand-applied/appproject-raglab-platform.yaml",
        "apply --server-side -f LAB/argocd/hand-applied/raglab-system.yaml",
        "apply --server-side -f LAB/argocd/hand-applied/root-app.yaml"]
    assert all(Path(k).name == "kubeconfig" for k, c in logged(log) if k != "helm")
    assert "gpu" not in log.read_text()

@needs_ansible
def test_argocd_gpu_sequence(tmp_path):
    env, log = fake_env(tmp_path, [])
    r = play("02-argocd.yml", "true", env)
    assert r.returncode == 0, r.stdout[-3000:]
    got = [c.replace(str(BOOT / "playbooks/../.."), "LAB") for k, c in logged(log)]
    assert got[:5] == [c.replace(str(BOOT / "playbooks/../.."), "LAB") for c in expected_02(
        str(BOOT / "playbooks/../../gpu/argocd/hand-applied"), f"{env['HOME']}/.sops/raglab-gpu-session/age-key.txt")]
    assert got[6:] == [
        "apply --server-side --force-conflicts -f LAB/gpu/argocd/hand-applied/appproject-default-locked.yaml",
        "apply --server-side -f LAB/gpu/argocd/hand-applied/appproject-raglab-gpu.yaml",
        "apply --server-side -f LAB/gpu/argocd/hand-applied/appproject-raglab-gpu-platform.yaml",
        "apply --server-side -f LAB/gpu/argocd/hand-applied/raglab-gpu-operator.yaml",
        "apply --server-side -f LAB/gpu/argocd/hand-applied/raglab-nim-operator.yaml",
        "apply --server-side -f LAB/gpu/argocd/hand-applied/root-app.yaml"]
    assert all(Path(k).name == "kubeconfig.gpu" for k, c in logged(log) if k != "helm")
    assert "raglab-age-key.txt" not in log.read_text(), "the Phase A age key is never used in GPU mode"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --with pytest --with pyyaml --with ansible-core pytest -q tests/test_playbooks.py`
Expected: FAIL (no `vars/`; and every ansible run fails with `ERROR: [Errno 21] Is a directory: '.../lab/bootstrap'`:
the empty `log_path =` in `ansible.cfg` breaks pip-installed ansible-core, fixed in Step 3).

- [ ] **Step 3: Implement**

`lab/bootstrap/ansible.cfg`: delete the line `log_path =` (an empty value is read as the current directory by
ansible-core from PyPI; without the line, no log file is written, which is what the empty value meant). Result:
```ini
[defaults]
inventory = inventory.ini
host_key_checking = True
stdout_callback = default
no_target_syslog = True
```

`lab/bootstrap/vars/phase-a.yml`:
```yaml
# Phase A (home lab VM): the values the playbooks had before Phase B. Selected when gpu_session is unset/false.
# tests/test_playbooks.py pins every value; changing one changes Phase A.
kubeconfig_name: kubeconfig
rewrite_kubeconfig_server: true
install_guest_agent: true
gpu_host_prep: false
k3s_exec: server --secrets-encryption --write-kubeconfig-mode 0600
hand_applied_dir: argocd/hand-applied
age_key_relpath: .sops/raglab-age-key.txt
app_projects: [appproject-raglab.yaml, appproject-raglab-platform.yaml]
platform_apps: [raglab-system.yaml]
required_apps:
  - argocd/raglab-root
  - argocd/raglab-system
  - raglab-apps/raglab-secrets
  - raglab-apps/raglab-dev
  - raglab-apps/raglab-qa
  - raglab-apps/raglab-prod
  - raglab-apps/raglab-nim-dev
  - raglab-apps/raglab-nim-qa
  - raglab-apps/raglab-nim-prod
```
`lab/bootstrap/vars/gpu-session.yml`:
```yaml
# Phase B (rented GPU VM, standalone): selected with -e gpu_session=true. Never used for the home lab.
kubeconfig_name: kubeconfig.gpu          # gitignored (kubeconfig.*); server stays https://127.0.0.1:6443
rewrite_kubeconfig_server: false         # the API is reached only through an SSH tunnel (lab/gpu/README.md)
install_guest_agent: false               # not a Proxmox VM
gpu_host_prep: true
k3s_exec: server --secrets-encryption --write-kubeconfig-mode 0600 --disable traefik --disable servicelb
hand_applied_dir: gpu/argocd/hand-applied
age_key_relpath: .sops/raglab-gpu-session/age-key.txt   # session key; the Phase A key never leaves the Mac
app_projects: [appproject-raglab-gpu.yaml, appproject-raglab-gpu-platform.yaml]
platform_apps: [raglab-gpu-operator.yaml, raglab-nim-operator.yaml]
required_apps:
  - argocd/raglab-gpu-root
  - argocd/raglab-gpu-operator
  - argocd/raglab-nim-operator
  - raglab-apps/raglab-gpu-secrets
  - raglab-apps/raglab-dev-gpu
```
`lab/bootstrap/inventory.gpu.example.ini`:
```ini
# Phase B: copy OUTSIDE the repo (~/.raglab-gpu/inventory.ini) and fill in the instance IP from
# `scripts/lambda.py status`. Never commit the address. Session-only SSH key, no agent forwarding.
[raglab]
raglab-vm ansible_host=<public IP of the Lambda instance> ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/raglab_gpu_ed25519 ansible_ssh_common_args='-o IdentitiesOnly=yes -o ForwardAgent=no'
```
`lab/bootstrap/playbooks/01-platform.yml` (whole file):
```yaml
# FRESH INSTALL ONLY: no upgrade handling. The k3s install is skipped when
# /etc/systemd/system/k3s.service exists; bumping k3s_version needs a manual upgrade.
# Mode: Phase A by default; -e gpu_session=true selects ../vars/gpu-session.yml (rented GPU VM).
- hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - name: Inventory group raglab must not be empty
      ansible.builtin.assert:
        that: groups['raglab'] | default([]) | length > 0
        fail_msg: "inventory.ini has no hosts in [raglab] (copy inventory.example.ini)"

- hosts: raglab
  become: true
  vars:
    k3s_version: v1.37.2+k3s1
  vars_files:
    - "../vars/{{ 'gpu-session' if (gpu_session | default(false) | bool) else 'phase-a' }}.yml"
  tasks:
    - name: Wait for first-boot cloud-init (sshd answers before it finishes; k3s install races it otherwise)
      ansible.builtin.command: cloud-init status --wait
      changed_when: false
      when: not (gpu_host_prep | bool)
    - name: "GPU: wait for cloud-init if the image has it (exit 2 = finished with recoverable errors)"
      ansible.builtin.shell: |
        command -v cloud-init >/dev/null 2>&1 || exit 0
        cloud-init status --wait >/dev/null; rc=$?; [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ]
      changed_when: false
      when: gpu_host_prep | bool
    - name: "GPU: gate - the driver works and the GPU is an A100 (spec D6: nvidia-smi passes first)"
      ansible.builtin.command: nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
      register: smi
      changed_when: false
      failed_when: smi.rc != 0 or 'A100' not in smi.stdout
      when: gpu_host_prep | bool
    - name: "GPU: stop the image's own Docker/containerd so k3s's containerd is the only runtime (NRI)"
      ansible.builtin.shell: |
        for u in docker.socket docker.service containerd.service; do
          if systemctl list-unit-files "$u" --no-legend 2>/dev/null | grep -q "^$u"; then
            systemctl disable --now "$u"; echo "stopped $u"
          fi
        done
      register: hostrt
      changed_when: "'stopped' in hostrt.stdout"
      when: gpu_host_prep | bool
    - name: Install and enable qemu-guest-agent (the cloud image lacks it; needed for qm shutdown with agent=1)
      ansible.builtin.apt:
        name: qemu-guest-agent
        state: present
        update_cache: true
      when: install_guest_agent | bool
    - name: Ensure qemu-guest-agent is running
      ansible.builtin.systemd:
        name: qemu-guest-agent
        state: started
        enabled: true
      when: install_guest_agent | bool
    - name: Download k3s binary at the pinned version (checksum-verified)
      ansible.builtin.get_url:
        url: "https://github.com/k3s-io/k3s/releases/download/{{ k3s_version | urlencode }}/k3s"
        dest: /usr/local/bin/k3s
        mode: "0755"
        checksum: "sha256:https://github.com/k3s-io/k3s/releases/download/{{ k3s_version | urlencode }}/sha256sum-amd64.txt"
    - name: Download install script at the same tag
      ansible.builtin.get_url:
        url: "https://raw.githubusercontent.com/k3s-io/k3s/{{ k3s_version | urlencode }}/install.sh"
        dest: /root/k3s-install.sh
        mode: "0700"
        checksum: "sha256:ed01f89fd977bf20ac1516bbebf8370bf3ddbaa55dac8aba610956a4c78cc00b"  # install.sh at v1.37.2+k3s1; recompute on bump
    - name: Install k3s server (binary already present)
      ansible.builtin.command:
        cmd: /root/k3s-install.sh
        creates: /etc/systemd/system/k3s.service
      environment:
        INSTALL_K3S_SKIP_DOWNLOAD: "true"
        INSTALL_K3S_EXEC: "{{ k3s_exec }}"
    - name: Verify secrets encryption is on (retry while the API server starts)
      ansible.builtin.command: k3s secrets-encrypt status
      register: enc
      changed_when: false
      retries: 20
      delay: 6
      until: enc.rc == 0
      failed_when: enc.rc != 0 or 'Enabled' not in enc.stdout
    - name: Pre-create the kubeconfig destination as 0600 (before it holds credentials)
      become: false
      delegate_to: localhost
      ansible.builtin.file:
        path: "{{ playbook_dir }}/../{{ kubeconfig_name }}"
        state: touch
        mode: "0600"
        modification_time: preserve
        access_time: preserve
    - name: Fetch kubeconfig to the workstation (gitignored path)
      ansible.builtin.fetch:
        src: /etc/rancher/k3s/k3s.yaml
        dest: "{{ playbook_dir }}/../{{ kubeconfig_name }}"
        flat: true

- hosts: localhost
  connection: local
  gather_facts: false
  vars:
    vm_ip: "{{ hostvars['raglab-vm'].ansible_host }}"
  vars_files:
    - "../vars/{{ 'gpu-session' if (gpu_session | default(false) | bool) else 'phase-a' }}.yml"
  tasks:
    - name: Point the kubeconfig at the VM instead of 127.0.0.1
      ansible.builtin.replace:
        path: "{{ playbook_dir }}/../{{ kubeconfig_name }}"
        regexp: '127\.0\.0\.1'
        replace: "{{ vm_ip }}"
        mode: "0600"
      when: rewrite_kubeconfig_server | bool
```
`lab/bootstrap/playbooks/02-argocd.yml` (whole file; the Phase A apply order is unchanged: projects, then
`raglab-system`, then root):
```yaml
# Age key rotation: the Secret is created only if absent, so to rotate delete it first
# (kubectl -n argocd delete secret sops-age-key) and re-run, then restart repo-server.
# Order matters: AppProject/Application CRDs only exist after the helm install.
# Mode: Phase A by default; -e gpu_session=true selects ../vars/gpu-session.yml (rented GPU VM).
- hosts: localhost
  connection: local
  gather_facts: false
  vars_files:
    - "../vars/{{ 'gpu-session' if (gpu_session | default(false) | bool) else 'phase-a' }}.yml"
  environment: {KUBECONFIG: "{{ playbook_dir }}/../{{ kubeconfig_name }}"}
  vars:
    ha: "{{ playbook_dir }}/../../{{ hand_applied_dir }}"
    values: "{{ playbook_dir }}/../../argocd/argocd-values.yaml"
  tasks:
    - name: Hand-applied namespaces
      ansible.builtin.command: kubectl apply --server-side -f {{ ha }}/namespaces.yaml
      changed_when: true
    - name: CMP plugin ConfigMap and repo-server egress policy
      ansible.builtin.command: kubectl apply --server-side -f {{ item }}
      loop: ["{{ ha }}/cmp-plugin.yaml", "{{ ha }}/repo-server-egress.yaml"]
      changed_when: true
    - name: age key file preflight (exists, mode 0600, holds an AGE-SECRET-KEY line; output discarded)
      no_log: true
      ansible.builtin.shell: |
        f="$HOME/{{ age_key_relpath }}"
        [ -f "$f" ] && [ "$(stat -f %Lp "$f" 2>/dev/null || stat -c %a "$f")" = 600 ] \
          && grep -q '^AGE-SECRET-KEY-' "$f" >/dev/null 2>&1
      changed_when: false
      register: agepre
      failed_when: false
    - name: Fail with a fixed message if the age key preflight failed
      ansible.builtin.assert:
        that: agepre.rc == 0
        fail_msg: "age key file ~/{{ age_key_relpath }} missing, not mode 0600, or no AGE-SECRET-KEY- line"
    - name: age key Secret (created on the workstation, never copied, never logged)
      no_log: true
      ansible.builtin.shell: |
        kubectl -n argocd get secret sops-age-key >/dev/null 2>&1 || \
        kubectl -n argocd create secret generic sops-age-key --from-file=keys.txt="$HOME/{{ age_key_relpath }}"
      changed_when: true
    - name: Argo CD (chart 10.18.3 = v3.6.2)
      ansible.builtin.command: >
        helm upgrade --install argocd argo-cd --repo https://argoproj.github.io/argo-helm
        --version 10.18.3 -n argocd -f {{ values }} --wait --timeout 10m
      changed_when: true
    - name: Default project lockdown (argocd-server auto-creates it; take over its fields deliberately)
      ansible.builtin.command: kubectl apply --server-side --force-conflicts -f {{ ha }}/appproject-default-locked.yaml
      changed_when: true
    - name: AppProjects
      ansible.builtin.command: kubectl apply --server-side -f {{ ha }}/{{ item }}
      loop: "{{ app_projects }}"
      changed_when: true
    - name: Platform Applications (operators; hand-applied, inline values)
      ansible.builtin.command: kubectl apply --server-side -f {{ ha }}/{{ item }}
      loop: "{{ platform_apps }}"
      changed_when: true
    - name: Root app
      ansible.builtin.command: kubectl apply --server-side -f {{ ha }}/root-app.yaml
      changed_when: true
```
`lab/bootstrap/playbooks/03-handover.yml`: replace the header and play head down to the end of `required_apps:` with
the block below (the tasks are unchanged; `required_apps` moves to the vars files):
```yaml
# Fail closed: every required Application must exist and be Synced/Healthy with a
# Succeeded (or no) last operation, unless named in handover_allow_unhealthy
# (entries are namespace/name, e.g. raglab-apps/raglab-dev).
# Mode: Phase A by default; -e gpu_session=true selects ../vars/gpu-session.yml (required_apps, kubeconfig).
- hosts: localhost
  connection: local
  gather_facts: false
  vars_files:
    - "../vars/{{ 'gpu-session' if (gpu_session | default(false) | bool) else 'phase-a' }}.yml"
  environment: {KUBECONFIG: "{{ playbook_dir }}/../{{ kubeconfig_name }}"}
  vars:
    handover_allow_unhealthy: []   # deliberate exceptions, e.g. -e '{"handover_allow_unhealthy":["raglab-apps/raglab-dev"]}'
```
`lab/bootstrap/playbooks/04-gpu-prep.yml`:
```yaml
# Phase B only (run after 01 with -e gpu_session=true). Records what the rented VM provides and gates the
# NRI path (spec D6). Writes ~/.raglab-gpu/evidence/gpu-prep.txt on the workstation (outside the repo).
- hosts: raglab
  become: true
  gather_facts: false
  vars_files:
    - "../vars/{{ 'gpu-session' if (gpu_session | default(false) | bool) else 'phase-a' }}.yml"
  tasks:
    - name: Refuse to run outside GPU-session mode
      ansible.builtin.assert:
        that: gpu_host_prep | bool
        fail_msg: "04-gpu-prep.yml is for the rented GPU VM only (-e gpu_session=true)"
    - name: GPU, driver, memory
      ansible.builtin.command: nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
      register: smi
      changed_when: false
      failed_when: smi.rc != 0 or 'A100' not in smi.stdout
    - name: k3s containerd version
      ansible.builtin.shell: k3s ctr version | awk '/^Server:/{s=1} s && /Version:/{print $2; exit}'
      register: ctrv
      changed_when: false
      failed_when: ctrv.rc != 0 or ctrv.stdout == ''
    - name: Gate - containerd supports the NRI plugin path (1.7.30+ on 1.7, or 2.1+)
      ansible.builtin.assert:
        that: >-
          (ctrv.stdout | regex_replace('^v', '') | regex_replace('[-+].*$', '')) is version('2.1.0', '>=') or
          ((ctrv.stdout | regex_replace('^v', '') | regex_replace('[-+].*$', '')) is version('1.7.30', '>=') and
           (ctrv.stdout | regex_replace('^v', '') | regex_replace('[-+].*$', '')) is version('1.8.0', '<'))
        fail_msg: "containerd {{ ctrv.stdout }} cannot use the NRI path: use the fallback in lab/gpu/README.md"
    - name: NRI socket present (k3s's containerd has NRI enabled)
      ansible.builtin.stat: {path: /var/run/nri/nri.sock}
      register: nri
    - name: Host NVIDIA container toolkit (recorded, not required)
      ansible.builtin.shell: command -v nvidia-ctk >/dev/null && nvidia-ctk --version | head -1 || echo absent
      register: ctk
      changed_when: false
    - name: Host Docker/containerd services (recorded; 01 stops them in GPU mode)
      ansible.builtin.shell: for u in docker containerd; do printf '%s=%s ' "$u" "$(systemctl is-active $u 2>/dev/null)"; done
      register: hostrt
      changed_when: false
    - name: Free disk for images, weights and the NIMCache PVC
      ansible.builtin.shell: df -BG --output=avail /var/lib/rancher | tail -1 | tr -dc 0-9
      register: disk
      changed_when: false
      failed_when: disk.stdout | int < 120
    - name: Evidence directory on the workstation (outside the repo)
      become: false
      delegate_to: localhost
      ansible.builtin.file: {path: "{{ lookup('env', 'HOME') }}/.raglab-gpu/evidence", state: directory, mode: "0700"}
    - name: Record evidence on the workstation (outside the repo)
      become: false
      delegate_to: localhost
      ansible.builtin.copy:
        dest: "{{ lookup('env', 'HOME') }}/.raglab-gpu/evidence/gpu-prep.txt"
        mode: "0600"
        content: |
          gpu: {{ smi.stdout }}
          containerd: {{ ctrv.stdout }}
          nri_socket: {{ nri.stat.exists }}
          host_toolkit: {{ ctk.stdout }}
          host_runtimes: {{ hostrt.stdout }}
          disk_free_gb: {{ disk.stdout }}
    - name: Gate - NRI socket must exist for cdi.nriPluginEnabled=true
      ansible.builtin.assert:
        that: nri.stat.exists
        fail_msg: "no /var/run/nri/nri.sock: k3s's containerd has NRI disabled; use the fallback in lab/gpu/README.md"
```
`.github/workflows/ci.yml`, step `unit tests`:
```yaml
      - name: unit tests
        run: uv run --with pytest --with pyyaml --with jsonschema --with ansible-core pytest -q
```

- [ ] **Step 4: Run the tests**

Run: `uv run --with pytest --with pyyaml --with jsonschema --with ansible-core pytest -q tests/test_playbooks.py`
Expected: `15 passed` (values pinned; syntax-check of 01-04 in both modes; 03 executed in both modes against fake
kubectl; 02 executed in both modes with the exact Phase A command sequence asserted, and the Phase A age key never
touched in GPU mode).

- [ ] **Step 5: Full suite**

Run: `uv run --with pytest --with pyyaml --with jsonschema --with ansible-core pytest -q`
Expected: all pass (about 180 at this point; 197 after Task 7).

- [ ] **Step 6: Commit and PR**

```bash
scripts/safety-check.sh
git branch --show-current     # feat/gpu-bootstrap-mode (created at the start of the task)
git add lab/bootstrap/vars lab/bootstrap/playbooks lab/bootstrap/inventory.gpu.example.ini lab/bootstrap/ansible.cfg .github/workflows/ci.yml tests/test_playbooks.py
git commit -m "feat(bootstrap): gpu_session mode via vars files (Phase A sequence pinned by executed tests); 04-gpu-prep"
git push -u origin feat/gpu-bootstrap-mode && gh pr create --fill
```
Expected: CI green (the unit-test step now has ansible-core, so the executed-playbook tests run in CI).
**[SESSION] owner merges.**

---

### Task 7: Mac-only helpers: `scripts/lambda.py` and `scripts/key_probe.py`

**Files:**
- Create: `scripts/lambda.py`, `scripts/key_probe.py`, `tests/test_lambda_helper.py`, `tests/test_key_probe.py`

**Interfaces:**
- `python3 scripts/lambda.py types [--all] | launch --type T --region R [--name raglab-gpu-...] [--wait] | status [--id] | instances | terminate --yes [--id] [--wait]`.
  Exit 0 ok, 1 condition not met (instances exist, no capacity, wait timeout), 2 usage/local error, 3 API error.
  `launch` refuses types other than the two A100 SKUs, refuses when any live instance exists, sends
  `file_system_names: []`, `ssh_key_names: ["raglab-gpu-session"]`, `quantity: 1`. `terminate` only targets
  `raglab-gpu*` instances (or one `--id`). Never prints the key or `jupyter_*` fields.
- `<key on stdin> | python3 scripts/key_probe.py hosted [--chat MODEL] | nvcr --repo R --tag T`: exit 0 accepted,
  1 REJECTED (401/403), 2 inconclusive. Used pre-rent (expect 0) and after revocation (expect 1).
- No real endpoint is called in CI (local mock servers).

- [ ] **Step 1: Write the failing tests**

`tests/test_lambda_helper.py`:
```python
"""scripts/lambda.py against a local mock of the Lambda Cloud API. No real API call is ever made."""
import json, os, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "lambda.py"
FAKE_KEY = "secret_" + "lambdakey" * 4          # built at runtime

TYPES = {
    "gpu_1x_a100_sxm4": {"instance_type": {"name": "gpu_1x_a100_sxm4", "description": "1x A100 (40 GB SXM4)",
                                           "price_cents_per_hour": 199,
                                           "specs": {"vcpus": 30, "memory_gib": 200, "storage_gib": 512, "gpus": 1}},
                         "regions_with_capacity_available": [{"name": "us-east-1"}]},
    "gpu_8x_h100_sxm5": {"instance_type": {"name": "gpu_8x_h100_sxm5", "price_cents_per_hour": 2392, "specs": {}},
                         "regions_with_capacity_available": [{"name": "us-east-1"}]},
}

def inst(i, name="raglab-gpu-session", status="active"):
    return {"id": i, "name": name, "status": status, "ip": "198.51.100.7", "jupyter_token": "JUPYTERTOKEN",
            "jupyter_url": "https://jupyter.example", "instance_type": {"name": "gpu_1x_a100_sxm4"},
            "region": {"name": "us-east-1"}}

class Mock:
    def __init__(self):
        self.instances, self.fss, self.calls, self.error = [], [], [], None

    def handle(self, h, method):
        n = int(h.headers.get("Content-Length") or 0)
        body = json.loads(h.rfile.read(n)) if n else None
        self.calls.append({"method": method, "path": h.path, "headers": dict(h.headers), "body": body})
        if self.error:
            return 400, {"error": {"code": "global/invalid-parameters", "message": "bad " + FAKE_KEY}}
        p = h.path.split("/api/v1/", 1)[-1]
        if method == "GET" and p == "instance-types": return 200, {"data": TYPES}
        if method == "GET" and p == "instances": return 200, {"data": self.instances}
        if method == "GET" and p.startswith("instances/"):
            return 200, {"data": next(i for i in self.instances if i["id"] == p.split("/")[1])}
        if method == "GET" and p == "file-systems": return 200, {"data": self.fss}
        if method == "POST" and p == "instance-operations/launch":
            self.instances.append(inst("i-new")); return 200, {"data": {"instance_ids": ["i-new"]}}
        if method == "POST" and p == "instance-operations/terminate":
            ids = body["instance_ids"]
            self.instances = [i for i in self.instances if i["id"] not in ids]
            return 200, {"data": {"terminated_instances": [{"id": i} for i in ids]}}
        return 404, {"error": {"code": "not-found", "message": p}}

@pytest.fixture
def api(tmp_path):
    m = Mock()
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _do(self, method):
            code, obj = m.handle(self, method)
            data = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        def do_GET(self): self._do("GET")
        def do_POST(self): self._do("POST")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = tmp_path / "session"; d.mkdir()
    (d / "age-key.txt").write_text("identity\n"); (d / "lambda-api-key.age").write_text("ct\n")
    fake = tmp_path / "fake-age"; fake.write_text(f"#!/bin/sh\nprintf '%s\\n' '{FAKE_KEY}'\n"); fake.chmod(0o755)
    m.env = {**os.environ, "RAGLAB_GPU_DIR": str(d), "RAGLAB_AGE_BIN": str(fake), "LAMBDA_POLL_SECONDS": "0.05",
             "LAMBDA_API_BASE": f"http://127.0.0.1:{srv.server_address[1]}/api/v1/"}
    yield m
    srv.shutdown()

def run(m, *args, env=None):
    r = subprocess.run([sys.executable, str(SCRIPT), *args], env=env or m.env, capture_output=True, text=True)
    assert FAKE_KEY not in r.stdout + r.stderr, "API key leaked to output"
    return r

def test_auth_and_user_agent(api):
    assert run(api, "types").returncode == 0
    h = api.calls[0]["headers"]
    assert h["Authorization"] == f"Bearer {FAKE_KEY}"
    assert "python" not in h["User-Agent"].lower() and h["User-Agent"].startswith("raglab-lambda-helper/")

def test_types_shows_a100_only_by_default(api):
    out = run(api, "types").stdout
    assert "gpu_1x_a100_sxm4  $1.99/h" in out and "capacity=us-east-1" in out and "h100" not in out
    assert "gpu_8x_h100_sxm5" in run(api, "types", "--all").stdout

def test_launch_posts_exact_body_and_waits(api):
    r = run(api, "launch", "--type", "gpu_1x_a100_sxm4", "--region", "us-east-1", "--wait")
    assert r.returncode == 0, r.stderr
    post = [c for c in api.calls if c["method"] == "POST"]
    assert len(post) == 1 and post[0]["body"] == {
        "region_name": "us-east-1", "instance_type_name": "gpu_1x_a100_sxm4",
        "ssh_key_names": ["raglab-gpu-session"], "file_system_names": [], "quantity": 1,
        "name": "raglab-gpu-session"}
    assert "LAUNCHED i-new" in r.stdout and "status=active" in r.stdout and "198.51.100.7" in r.stdout

def test_launch_refuses_other_types_without_calling_api(api):
    r = run(api, "launch", "--type", "gpu_8x_h100_sxm5", "--region", "us-east-1")
    assert r.returncode == 2 and not api.calls

def test_launch_refuses_when_an_instance_exists(api):
    api.instances.append(inst("i-old", name="something-else"))
    r = run(api, "launch", "--type", "gpu_1x_a100_sxm4", "--region", "us-east-1")
    assert r.returncode == 1 and "already has a live instance" in r.stderr
    assert not [c for c in api.calls if c["method"] == "POST"]

def test_launch_refuses_region_without_capacity(api):
    r = run(api, "launch", "--type", "gpu_1x_a100_sxm4", "--region", "us-west-2")
    assert r.returncode == 1 and "no capacity" in r.stderr
    assert not [c for c in api.calls if c["method"] == "POST"]

def test_status_never_prints_jupyter_fields(api):
    api.instances.append(inst("i-1"))
    out = run(api, "status").stdout
    assert "i-1" in out and "JUPYTERTOKEN" not in out and "jupyter" not in out

def test_terminate_requires_yes(api):
    api.instances.append(inst("i-1"))
    r = run(api, "terminate")
    assert r.returncode == 2 and not api.calls

def test_terminate_only_raglab_instances_and_waits(api):
    api.instances += [inst("i-1"), inst("i-2", name="not-ours")]
    r = run(api, "terminate", "--yes", "--wait")
    assert r.returncode == 0 and "TERMINATED" in r.stdout
    post = [c for c in api.calls if c["method"] == "POST"]
    assert post[0]["body"] == {"instance_ids": ["i-1"]}
    assert [i["id"] for i in api.instances] == ["i-2"]

def test_instances_exit_code_is_teardown_evidence(api):
    assert run(api, "instances").returncode == 0
    api.fss.append({"id": "fs-1", "name": "x", "region": {"name": "us-east-1"}})
    r = run(api, "instances")
    assert r.returncode == 1 and "file systems: 1" in r.stdout
    api.fss.clear(); api.instances.append(inst("i-1", status="booting"))
    assert run(api, "instances").returncode == 1

def test_api_error_is_reported_and_scrubbed(api):
    api.error = True
    r = run(api, "types")
    assert r.returncode == 3 and "global/invalid-parameters" in r.stderr and "***" in r.stderr

def test_plain_http_to_remote_refused(api):
    r = run(api, "types", env={**api.env, "LAMBDA_API_BASE": "http://example.com/api/v1/"})
    assert r.returncode == 2 and "must be https" in r.stderr
```

`tests/test_key_probe.py`:
```python
"""scripts/key_probe.py against a local mock (hosted API + registry). No real endpoint is called."""
import base64, json, os, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "key_probe.py"
GOOD = "nvapi-" + "G" * 40
BAD = "nvapi-" + "B" * 40
DIGEST = "sha256:" + "ab" * 32

@pytest.fixture
def srv():
    state = {"rate_limited": False}
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def reply(self, code, obj=None, headers=()):
            data = json.dumps(obj).encode() if obj is not None else b""
            self.send_response(code)
            for k, v in headers: self.send_header(k, v)
            self.send_header("Content-Length", str(len(data))); self.end_headers()
            if self.command != "HEAD": self.wfile.write(data)
        def authed(self):
            return self.headers.get("Authorization") == f"Bearer {GOOD}"
        def route(self):
            p = self.path
            if state["rate_limited"]: return self.reply(429)
            if p == "/v1/models":
                return self.reply(200, {"data": [{"id": "meta/llama-3.1-8b-instruct"}]}) if self.authed() else self.reply(401)
            if p == "/v1/chat/completions":
                return self.reply(200, {"choices": []}) if self.authed() else self.reply(401)
            if p.startswith("/v2/nim/meta/x/manifests/"):
                if self.headers.get("Authorization") == "Bearer REGTOKEN":
                    return self.reply(200, headers=[("Docker-Content-Digest", DIGEST)])
                port = self.server.server_address[1]
                return self.reply(401, headers=[("WWW-Authenticate",
                    f'Bearer realm="http://127.0.0.1:{port}/token",scope="repository:nim/meta/x:pull"')])
            if p.startswith("/token"):
                want = "Basic " + base64.b64encode(f"$oauthtoken:{GOOD}".encode()).decode()
                return self.reply(200, {"token": "REGTOKEN"}) if self.headers.get("Authorization") == want else self.reply(401)
            return self.reply(404)
        do_GET = do_POST = do_HEAD = route
    s = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{s.server_address[1]}"
    yield {"env": {**os.environ, "KEY_PROBE_HOSTED": base, "KEY_PROBE_REGISTRY": base}, "state": state}
    s.shutdown()

def run(srv, key, *args):
    r = subprocess.run([sys.executable, str(SCRIPT), *args], input=key + "\n", env=srv["env"],
                       capture_output=True, text=True)
    assert key not in r.stdout + r.stderr
    return r

def test_hosted_accepted_with_chat(srv):
    r = run(srv, GOOD, "hosted", "--chat", "meta/llama-3.1-8b-instruct")
    assert r.returncode == 0 and "listed: True" in r.stdout and r.stdout.strip().endswith("ACCEPTED")

def test_hosted_rejected_is_exit_1(srv):
    r = run(srv, BAD, "hosted")
    assert r.returncode == 1 and "HTTP 401" in r.stdout and "REJECTED" in r.stdout

def test_rate_limit_is_inconclusive_not_rejected(srv):
    srv["state"]["rate_limited"] = True
    r = run(srv, BAD, "hosted")
    assert r.returncode == 2 and "INCONCLUSIVE" in r.stdout

def test_nvcr_accepted_prints_digest(srv):
    r = run(srv, GOOD, "nvcr", "--repo", "nim/meta/x", "--tag", "2.1.7")
    assert r.returncode == 0 and f"digest: {DIGEST}" in r.stdout

def test_nvcr_rejected(srv):
    r = run(srv, BAD, "nvcr", "--repo", "nim/meta/x", "--tag", "2.1.7")
    assert r.returncode == 1 and "registry token: HTTP 401" in r.stdout
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --with pytest pytest -q tests/test_lambda_helper.py tests/test_key_probe.py`
Expected: FAIL (scripts missing).

- [ ] **Step 3: Implement**

`scripts/lambda.py`:
```python
#!/usr/bin/env python3
"""Lambda Cloud helper for the raglab Phase B GPU session. Mac only; stdlib only. Prints no secrets.

  types [--all]                                  instance types, price, regions with capacity (A100 1x by default)
  launch --type T --region R [--name N] [--wait] rent ONE instance (refuses if any instance already exists)
  status [--id ID]                               raglab-gpu* instances (or one id): id, name, status, ip, type, region
  instances                                      every instance + file system on the account; exit 0 only if none
  terminate --yes [--id ID] [--wait]             terminate raglab-gpu* instances (or one id); billing stops here

The API key is read with `age -d` from ~/.sops/raglab-gpu-session/lambda-api-key.age (identity age-key.txt in
the same dir; override the dir with RAGLAB_GPU_DIR, the binary with RAGLAB_AGE_BIN) into this process only.
It is never printed, never put on argv, never written to disk, and never sent anywhere but the API base
(LAMBDA_API_BASE, default https://cloud.lambda.ai/api/v1/; plain http is refused except for 127.0.0.1 tests).
Exit: 0 ok, 1 condition not met (instances exist / wait timed out), 2 usage or local error, 3 API error.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BASE = "https://cloud.lambda.ai/api/v1/"
USER_AGENT = "raglab-lambda-helper/1.0"      # urllib's default UA is blocked by Cloudflare (error 1010)
ALLOWED_TYPES = ("gpu_1x_a100_sxm4", "gpu_1x_a100")   # spec D2: one A100 40GB, nothing bigger
SSH_KEY_NAME = "raglab-gpu-session"
NAME_PREFIX = "raglab-gpu"
LIVE_EXCLUDED = {"terminated"}
SHOWN_FIELDS = ("id", "name", "status", "ip", "instance_type", "region")   # never jupyter_token/url

_KEY: str | None = None


class ApiError(Exception):
    pass


def die(msg: str, code: int = 2):
    print(f"lambda: {msg}", file=sys.stderr); sys.exit(code)


def scrub(text: str) -> str:
    return text.replace(_KEY, "***") if _KEY else text


def api_base() -> str:
    base = os.environ.get("LAMBDA_API_BASE", DEFAULT_BASE)
    u = urllib.parse.urlparse(base)
    if not (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost"))):
        die("LAMBDA_API_BASE must be https (plain http only for 127.0.0.1)")
    return base if base.endswith("/") else base + "/"


def api_key() -> str:
    global _KEY
    if _KEY is None:
        d = Path(os.environ.get("RAGLAB_GPU_DIR", str(Path.home() / ".sops" / "raglab-gpu-session")))
        ident, enc = d / "age-key.txt", d / "lambda-api-key.age"
        for f in (ident, enc):
            if not f.is_file():
                die(f"missing {f}")
        r = subprocess.run([os.environ.get("RAGLAB_AGE_BIN", "age"), "-d", "-i", str(ident), str(enc)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            die("age -d failed for the Lambda API key (output suppressed)")
        _KEY = r.stdout.strip()
    return _KEY


def api(method: str, path: str, body: dict | None = None):
    url = urllib.parse.urljoin(api_base(), path)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {api_key()}", "User-Agent": USER_AGENT,
        "Accept": "application/json", **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}").get("data")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode()).get("error", {})
            msg = f"{err.get('code', '?')}: {err.get('message', '')} {err.get('suggestion') or ''}".strip()
        except (ValueError, AttributeError):
            msg = "(no JSON error body)"
        raise ApiError(scrub(f"HTTP {e.code} {method} {path}: {msg}"[:400]))
    except urllib.error.URLError as e:
        raise ApiError(scrub(f"{method} {path}: {e.reason}"))


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def show(i: dict) -> str:
    t = (i.get("instance_type") or {}).get("name", "?")
    reg = (i.get("region") or {}).get("name", "?")
    return f"{i.get('id')}  name={i.get('name')}  status={i.get('status')}  ip={i.get('ip') or '-'}  type={t}  region={reg}"


def live(instances: list[dict]) -> list[dict]:
    return [i for i in instances if i.get("status") not in LIVE_EXCLUDED]


def ours(instances: list[dict]) -> list[dict]:
    return [i for i in live(instances) if str(i.get("name") or "").startswith(NAME_PREFIX)]


def poll() -> float:
    return float(os.environ.get("LAMBDA_POLL_SECONDS", "10"))


def cmd_types(a) -> int:
    for name, v in sorted((api("GET", "instance-types") or {}).items()):
        if not a.all and name not in ALLOWED_TYPES:
            continue
        it, regions = v.get("instance_type", {}), [r.get("name") for r in v.get("regions_with_capacity_available", [])]
        s = it.get("specs", {})
        print(f"{name}  ${it.get('price_cents_per_hour', 0) / 100:.2f}/h  gpus={s.get('gpus')}  vcpus={s.get('vcpus')}"
              f"  mem={s.get('memory_gib')}GiB  disk={s.get('storage_gib')}GiB"
              f"  capacity={','.join(regions) if regions else 'NONE'}  ({it.get('description', '')})")
    return 0


def cmd_launch(a) -> int:
    if a.type not in ALLOWED_TYPES:
        die(f"type {a.type} not allowed (spec D2: one of {', '.join(ALLOWED_TYPES)})")
    if not a.name.startswith(NAME_PREFIX):
        die(f"--name must start with {NAME_PREFIX} (terminate and status find instances by that prefix)")
    existing = live(api("GET", "instances") or [])
    if existing:
        for i in existing: print(show(i))
        die("refusing to launch: the account already has a live instance (one session = one instance)", 1)
    t = (api("GET", "instance-types") or {}).get(a.type)
    regions = [r.get("name") for r in (t or {}).get("regions_with_capacity_available", [])]
    if a.region not in regions:
        die(f"no capacity for {a.type} in {a.region} (capacity now: {','.join(regions) or 'NONE'})", 1)
    d = api("POST", "instance-operations/launch", {
        "region_name": a.region, "instance_type_name": a.type, "ssh_key_names": [SSH_KEY_NAME],
        "file_system_names": [], "quantity": 1, "name": a.name})
    ids = (d or {}).get("instance_ids") or []
    print(f"LAUNCHED {' '.join(ids)} at {now()}  -- BILLING HAS STARTED; terminate is the only stop")
    if not a.wait or not ids:
        return 0 if ids else 3
    deadline = time.time() + a.timeout
    while time.time() < deadline:
        i = api("GET", f"instances/{ids[0]}") or {}
        if i.get("status") == "active" and i.get("ip"):
            print(show(i)); return 0
        time.sleep(poll())
    print(f"TIMEOUT waiting for {ids[0]} to be active (it is still billing)", file=sys.stderr)
    return 1


def cmd_status(a) -> int:
    rows = [api("GET", f"instances/{a.id}") or {}] if a.id else ours(api("GET", "instances") or [])
    for i in rows: print(show(i))
    if not rows: print("no raglab-gpu instances")
    return 0


def cmd_instances(a) -> int:
    inst = live(api("GET", "instances") or [])
    fss = api("GET", "file-systems") or []
    print(f"{now()}  live instances: {len(inst)}  file systems: {len(fss)}")
    for i in inst: print("  instance " + show(i))
    for f in fss: print(f"  file-system {f.get('id')} name={f.get('name')} region={(f.get('region') or {}).get('name')}")
    return 0 if not inst and not fss else 1


def cmd_terminate(a) -> int:
    if not a.yes:
        die("terminate needs --yes")
    targets = [a.id] if a.id else [i["id"] for i in ours(api("GET", "instances") or [])]
    if not targets:
        print("nothing to terminate (no live raglab-gpu instances)"); return 0
    d = api("POST", "instance-operations/terminate", {"instance_ids": targets}) or {}
    done = [i.get("id") for i in d.get("terminated_instances", [])]
    print(f"TERMINATE requested at {now()}: {' '.join(done) or ' '.join(targets)}")
    if not a.wait:
        return 0
    deadline = time.time() + a.timeout
    while time.time() < deadline:
        left = [i for i in live(api("GET", "instances") or []) if i.get("id") in targets]
        if not left:
            print(f"TERMINATED (no longer listed as live) at {now()}"); return 0
        time.sleep(poll())
    print("TIMEOUT: instance still listed as live; check the console NOW", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lambda.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("types"); t.add_argument("--all", action="store_true")
    l = sub.add_parser("launch")
    l.add_argument("--type", required=True); l.add_argument("--region", required=True)
    l.add_argument("--name", default=f"{NAME_PREFIX}-session")
    l.add_argument("--wait", action="store_true"); l.add_argument("--timeout", type=float, default=1200)
    s = sub.add_parser("status"); s.add_argument("--id")
    sub.add_parser("instances")
    x = sub.add_parser("terminate")
    x.add_argument("--yes", action="store_true"); x.add_argument("--id")
    x.add_argument("--wait", action="store_true"); x.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args(argv)
    try:
        return {"types": cmd_types, "launch": cmd_launch, "status": cmd_status,
                "instances": cmd_instances, "terminate": cmd_terminate}[a.cmd](a)
    except ApiError as e:
        print(f"lambda: API error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/key_probe.py`:
```python
#!/usr/bin/env python3
"""Probe whether an NVIDIA key works, reading the key from STDIN only. Prints status codes, never the key.

  hosted [--chat MODEL]          GET <hosted>/v1/models (and one 4-token chat call if --chat)
  nvcr --repo R --tag T          registry token for R (Basic $oauthtoken:<key>), then the manifest of R:T;
                                 prints the manifest digest
Exit: 0 = key accepted (all calls 200), 1 = key REJECTED (a 401/403 anywhere), 2 = anything else
(network error, 404, 429, 5xx): proves nothing about the key.
Usage:  age -d -i <identity> <key.age> | python3 scripts/key_probe.py hosted --chat meta/llama-3.1-8b-instruct
Endpoints can be overridden for tests: KEY_PROBE_HOSTED (default https://integrate.api.nvidia.com),
KEY_PROBE_REGISTRY (default https://nvcr.io).
"""
from __future__ import annotations
import argparse, base64, json, os, re, sys, urllib.error, urllib.parse, urllib.request

UA = "raglab-key-probe/1.0"
MANIFEST_TYPES = ", ".join([
    "application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"])


class Rejected(Exception):
    pass


class Inconclusive(Exception):
    pass


def call(url: str, headers: dict, body: dict | None = None, method: str | None = None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, method=method,
                                 headers={"User-Agent": UA, **headers,
                                          **({"Content-Type": "application/json"} if body else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), b""
    except urllib.error.URLError as e:
        raise Inconclusive(f"network error: {e.reason}")


def expect_ok(what: str, code: int):
    print(f"{what}: HTTP {code}")
    if code in (401, 403):
        raise Rejected(what)
    if code != 200:
        raise Inconclusive(what)


def hosted(key: str, chat: str | None):
    base = os.environ.get("KEY_PROBE_HOSTED", "https://integrate.api.nvidia.com").rstrip("/")
    auth = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    code, _, body = call(f"{base}/v1/models", auth)
    expect_ok("GET /v1/models", code)
    if chat:
        ids = {m.get("id") for m in json.loads(body or b"{}").get("data", [])}
        print(f"model {chat} listed: {chat in ids}")
        code, _, _ = call(f"{base}/v1/chat/completions", auth, {
            "model": chat, "max_tokens": 4, "messages": [{"role": "user", "content": "Reply with OK."}]})
        expect_ok(f"POST /v1/chat/completions ({chat})", code)


def nvcr(key: str, repo: str, tag: str):
    reg = os.environ.get("KEY_PROBE_REGISTRY", "https://nvcr.io").rstrip("/")
    murl = f"{reg}/v2/{repo}/manifests/{tag}"
    code, hdrs, _ = call(murl, {"Accept": MANIFEST_TYPES})
    chal = next((v for k, v in hdrs.items() if k.lower() == "www-authenticate"), "")
    params = dict(re.findall(r'(\w+)="([^"]*)"', chal))
    if code != 401 or "realm" not in params:
        raise Inconclusive(f"unexpected anonymous response HTTP {code}")
    q = {k: v for k, v in params.items() if k in ("service", "scope")}
    q.setdefault("scope", f"repository:{repo}:pull")
    basic = base64.b64encode(f"$oauthtoken:{key}".encode()).decode()
    code, _, body = call(f"{params['realm']}?{urllib.parse.urlencode(q)}", {"Authorization": f"Basic {basic}"})
    expect_ok("registry token", code)
    token = json.loads(body).get("token") or json.loads(body).get("access_token")
    code, hdrs, _ = call(murl, {"Authorization": f"Bearer {token}", "Accept": MANIFEST_TYPES}, method="HEAD")
    expect_ok(f"manifest {repo}:{tag}", code)
    print("digest:", next((v for k, v in hdrs.items() if k.lower() == "docker-content-digest"), "(none)"))


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hosted"); h.add_argument("--chat")
    n = sub.add_parser("nvcr"); n.add_argument("--repo", required=True); n.add_argument("--tag", required=True)
    a = ap.parse_args()
    if sys.stdin.isatty():
        print("key_probe: pipe the key on stdin (never type or paste it)", file=sys.stderr); return 2
    key = sys.stdin.read().strip()
    if not key:
        print("key_probe: empty key on stdin", file=sys.stderr); return 2
    try:
        hosted(key, a.chat) if a.cmd == "hosted" else nvcr(key, a.repo, a.tag)
    except Rejected as e:
        print(f"REJECTED ({e})"); return 1
    except Inconclusive as e:
        print(f"INCONCLUSIVE ({e}): proves nothing about the key"); return 2
    print("ACCEPTED"); return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `chmod +x scripts/lambda.py scripts/key_probe.py && uv run --with pytest pytest -q tests/test_lambda_helper.py tests/test_key_probe.py`
Expected: `17 passed`.

- [ ] **Step 5: Full suite and gitleaks**

Run: `uv run --with pytest --with pyyaml --with jsonschema --with ansible-core pytest -q && scripts/safety-check.sh`
Expected: `197 passed` (114 before Phase B); `PASSED`.

- [ ] **Step 6: Commit and PR**

```bash
git branch --show-current     # feat/gpu-helpers (created at the start of the task)
git add scripts/lambda.py scripts/key_probe.py tests/test_lambda_helper.py tests/test_key_probe.py
git commit -m "feat(gpu): Mac-only Lambda helper and key probe (stdlib, age -d, no secrets printed)"
git push -u origin feat/gpu-helpers && gh pr create --fill
```
**[SESSION] owner merges.**

---

### Task 8: Session runbook `lab/gpu/README.md` + draft session PRs

**Files:**
- Create: `lab/gpu/README.md`, branch `session/gpu-go` (adds `lab/gpu/argocd/apps/raglab-gpu-nim.yaml`), branch
  `session/gpu-cutover` (catalogue `serving` change)
- Modify: `lab/README.md` (teardown pointer)

**Interfaces:**
- Produces: the only document the owner needs during the session (timeline, go/no-go, abort checkpoint, teardown with
  terminate FIRST, revocation, next-day bill check). Draft PR `session/gpu-go` is **red by design** until the profile is
  filled (`test_nim_app_only_after_go_no_go`).

- [ ] **Step 1: Write the runbook**

`lab/gpu/README.md`:
````markdown
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
  `history | grep -c nvapi-` is 0 at the end.
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
export ARGOCD_OPTS="--config $RG/argocd-config --port-forward --port-forward-namespace argocd --plaintext"
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
   `SOPS_AGE_KEY_FILE=$HOME/.sops/raglab-age-key.txt sops decrypt lab/gpu/secrets/gpu.sops.yaml >/dev/null 2>&1 && echo LEAK || echo ok-phase-a-key-cannot-decrypt`
7. The platform charts still render to the committed summaries (the Helm repo is mutable):
   `scripts/render-gpu-platform.sh --check` prints two `unchanged` lines.
8. Lambda: `python3 scripts/lambda.py instances` exits 0 (`live instances: 0  file systems: 0`) and
   `python3 scripts/lambda.py types` shows capacity for `gpu_1x_a100_sxm4` (us-east-1/us-west-2) or `gpu_1x_a100`
   (us-south-2). In the Lambda console: the account firewall allows TCP 22 and ICMP only from the current home
   address (if the home address changed, fix the rule before renting), SSH key `raglab-gpu-session` is registered.
9. Home lab VM stopped: `ssh hv-01 'qm status 101'` prints `status: stopped`.
10. Draft PR branches exist: `session/gpu-go` and `session/gpu-cutover` (built in plan Task 8).
11. Calendar alarms set relative to the planned start: T+3:00 checkpoint, T+4:15 teardown, T+4:45, T+5:00.
12. `mkdir -p -m 700 $RG/evidence && cp lab/bootstrap/inventory.gpu.example.ini $RG/inventory.ini && chmod 600 $RG/inventory.ini`

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
1. `python3 scripts/lambda.py launch --type gpu_1x_a100_sxm4 --region us-east-1 --wait | tee $RG/evidence/launch.txt`
   (or another type/region from step 1.8). Expect `LAUNCHED <id> at <UTC>` then a line with `status=active ip=...`.
2. Put the IP into `$RG/inventory.ini` (replace the placeholder), then re-run the `IP=` line of the shell setup.
3. First SSH (accept the host key; there is no out-of-band fingerprint, trust on first use):
   `gssh ubuntu@$IP 'nvidia-smi --query-gpu=name,memory.total --format=csv,noheader; sudo -n true && echo SUDO_OK'`
   Expect `NVIDIA A100-SXM4-40GB, 40960 MiB` (or the PCIe name) and `SUDO_OK`.
4. Exposure probe from the Mac (criterion 7): `for p in 22 80 443 2379 6443 8080 10250; do nc -z -G 3 $IP $p >/dev/null 2>&1 && echo "OPEN $p" || echo "closed $p"; done | tee $RG/evidence/exposure.txt`
   Expect `OPEN 22` only. (ICMP from the home address is also allowed by the account firewall: recorded, accepted.)

### 3.2 Bootstrap (T+0:10)
```bash
cd lab/bootstrap
ansible-playbook -i $RG/inventory.ini -e gpu_session=true playbooks/01-platform.yml
ansible-playbook -i $RG/inventory.ini -e gpu_session=true playbooks/04-gpu-prep.yml
cd ../..
gssh -f -N -o ExitOnForwardFailure=yes -L 6443:127.0.0.1:6443 ubuntu@$IP     # API tunnel (k3s API is not exposed)
kubectl get nodes                                                             # one node Ready
cd lab/bootstrap
ansible-playbook -i $RG/inventory.ini -e gpu_session=true playbooks/02-argocd.yml
ansible-playbook -i $RG/inventory.ini -e gpu_session=true playbooks/03-handover.yml
cd ../..
```
- 01: the GPU gate task prints the A100; "Verify secrets encryption" ok. 04: all gates ok; it writes
  `$RG/evidence/gpu-prep.txt` (containerd version, NRI socket, host toolkit, disk). If 04 fails on containerd or NRI,
  use section 9 (fallback) before 02.
- 02: the age-key task shows `censored due to no_log`. 03 waits up to ~20 min (GPU Operator operands, the dev-gpu
  smoke hook on the hosted provider). Its success is the **hosted baseline**:
  `kubectl -n raglab-dev-gpu logs job/smoke | tail -40 | tee $RG/evidence/smoke-hosted-baseline.txt`
  must show `0 failed`, `[PASS] auth-negative`, `[PASS] limit-429` and `revision=<main SHA>`.
- Argo CLI login (password read into a variable, never printed):
  `PW=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d); argocd login argocd-server --username admin --password "$PW"; unset PW`

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
A `status=200` on either negative probe means k3s is not enforcing the policy: record it as a finding.

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

### 3.10 Evidence and isolation probe (before terminating)
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
1. `python3 scripts/lambda.py terminate --yes --wait | tee $RG/evidence/terminate.txt` (expect `TERMINATED ... at <UTC>`).
2. `python3 scripts/lambda.py instances | tee $RG/evidence/instances-after.txt; echo exit=$?` (expect
   `live instances: 0  file systems: 0`, `exit=0`). Check the console too: no instance, no file system.
3. Kill the tunnel: `pkill -f 'L 6443:127.0.0.1:6443'`. The account firewall rule is a standing account setting and
   stays (it admits nothing without an instance); note it in the findings.
4. Billing has stopped. Everything below is after billing.

## 6. Key revocation and negative probes (same day, in this order)
1. **Session nvapi key:** revoke it in the NVIDIA/NGC console (revoke, not just expire). Then both must print `REJECTED`
   and exit 1 (exit 2 = inconclusive: retry later, it proves nothing):
   `skey | python3 scripts/key_probe.py hosted; echo exit=$?` and
   `skey | python3 scripts/key_probe.py nvcr --repo nim/meta/llama-3.1-8b-instruct --tag 2.1.7; echo exit=$?`
2. **Lambda API key:** delete the session key in the Lambda console, then
   `python3 scripts/lambda.py instances; echo exit=$?` must fail with `HTTP 401` (exit 3).
   Delete the `raglab-gpu-session` SSH key in the Lambda console.
3. **Delete session material** (this makes `lab/gpu/secrets/gpu.sops.yaml` permanently undecryptable):
   ```bash
   rm -f $SK/age-key.txt $SK/session-nvapi-key.age $SK/lambda-api-key.age && rmdir $SK
   rm -f ~/.ssh/raglab_gpu_ed25519 ~/.ssh/raglab_gpu_ed25519.pub
   ssh-keygen -R "$IP"; rm -f lab/bootstrap/kubeconfig.gpu $RG/inventory.ini; rm -rf $RG/argocd-config
   history | grep -c -e nvapi- -e 'AGE-SECRET'     # 0
   ```
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
````

- [ ] **Step 2: Phase A runbook pointer**

In `lab/README.md` section 7, replace the bullet `- **Phase B only:** tailnet device and auth key.` with
`- **Phase B:** a standalone rented cluster; its teardown is lab/gpu/README.md sections 5-8 (no tailnet).`

- [ ] **Step 3: Commit and PR the runbook**

```bash
scripts/safety-check.sh
git branch --show-current     # docs/gpu-runbook (created at the start of the task)
git add lab/gpu/README.md lab/README.md && git commit -m "docs(gpu): Phase B session runbook" && git push -u origin docs/gpu-runbook && gh pr create --fill
```
**[SESSION] owner merges.**

- [ ] **Step 4: Draft PR `session/gpu-go` (opened as draft, merged only at the go/no-go)**

```bash
git fetch origin && git checkout -b session/gpu-go origin/main
cat > lab/gpu/argocd/apps/raglab-gpu-nim.yaml <<'EOF'
# Added by the go/no-go PR only (lab/gpu/README.md 3.5). CI fails while the profile placeholder remains.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: raglab-gpu-nim, namespace: raglab-apps, finalizers: [resources-finalizer.argocd.argoproj.io]}
spec:
  project: raglab-gpu
  source: {repoURL: https://github.com/OC15141355/rag-stack-lab.git, targetRevision: main, path: lab/gpu/nim}
  destination: {server: https://kubernetes.default.svc, namespace: raglab-gpu}
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [SkipDryRunOnMissingResource=true]
    retry: {limit: 5, backoff: {duration: 30s, factor: 2, maxDuration: 5m}}
EOF
git add lab/gpu/argocd/apps/raglab-gpu-nim.yaml
git commit -m "gpu: add raglab-gpu-nim (profile filled at go/no-go)" && git push -u origin session/gpu-go
gh pr create --draft --title "gpu: go - pin NIM profile, add raglab-gpu-nim" --body "Merged only after the go/no-go (lab/gpu/README.md 3.4). CI is red until the profile placeholder is replaced."
uv run --with pytest --with pyyaml --with jsonschema pytest -q tests/test_gpu_argocd.py
```
Expected: `1 failed, 11 passed` (`test_nim_app_only_after_go_no_go`: the intended guard).

- [ ] **Step 5: Draft PR `session/gpu-cutover`**

```bash
git fetch origin && git checkout -b session/gpu-cutover origin/main
sed -i '' 's#serving: {chat/small: nvidia-hosted}#serving: {chat/small: nim-local}#' lab/catalogue/catalogue.yaml
uv run --with pyyaml python3 lab/catalogue/generate.py && git status --short
uv run --with pytest --with pyyaml --with jsonschema pytest -q tests/test_generate.py tests/test_gpu_manifests.py
git commit -am "gpu: dev-gpu chat/small -> nim-local (cutover)" && git push -u origin session/gpu-cutover
gh pr create --draft --title "gpu: cutover dev-gpu chat/small to nim-local" --body "Merged at session step 3.8 only. Client-visible id changes: nvidia-hosted/chat/small -> nim-local/chat/small."
```
Expected: `git status` shows only `lab/catalogue/catalogue.yaml` and the two `lab/gpu/envs/dev-gpu/generated` files;
`32 passed`. Agent work ends here; hand over to the owner.

---

## Session tasks (all **[SESSION]**: owner only; follow `lab/gpu/README.md`, which holds every command)

Before Task 9: shell setup from README section 0 in every terminal. Record every timestamp and result in
`~/.raglab-gpu/evidence/` (outside the repo). Nothing from the evidence directory is committed verbatim; Task 21 distils it.

### Task 9: [SESSION] Pre-rent gate (the day before, and again at T-30 min)

- [ ] **Step 1:** README section 1 items 1-12, in order. Every item must give its expected output. Any failure stops
  the session before renting (nothing has been spent).
- [ ] **Step 2:** Record the planned start time T and set the four calendar alarms (T+3:00, T+4:15, T+4:45, T+5:00).
- [ ] **Step 3:** Confirm `lab/gpu/secrets/gpu.sops.yaml` on `main` passes the decode probe (README 1.6) and the
  draft PRs `session/gpu-go` and `session/gpu-cutover` exist (`gh pr list --draft`).

### Task 10: [SESSION] Rent and check the host (T+0:00)

- [ ] **Step 1:** README 3.1 steps 1-2. Expected: `LAUNCHED <id> at <UTC>  -- BILLING HAS STARTED`, then
  `status=active ip=...`. **Billing clock starts: note T.**
- [ ] **Step 2:** README 3.1 step 3. Expected: an `A100` line and `SUDO_OK`. Anything else: Task 17 now (abort).
- [ ] **Step 3:** README 3.1 step 4. Expected: `OPEN 22` and `closed` for every other port (criterion 7).

### Task 11: [SESSION] Bootstrap (T+0:10 to T+0:35)

- [ ] **Step 1:** README 3.2: `01-platform.yml` then `04-gpu-prep.yml` (gates: A100, containerd version, NRI socket,
  disk ≥ 120 GB). If 04 fails on containerd/NRI: README section 9 fallback, or abort if past T+0:45.
- [ ] **Step 2:** SSH tunnel; `kubectl get nodes` shows one `Ready` node.
- [ ] **Step 3:** `02-argocd.yml` (age-key task `censored`), `03-handover.yml` (passes: 5 apps Synced/Healthy, no
  `last-applied` Secret). Save the hosted-baseline smoke tail (README 3.2): `0 failed`, `[PASS] auth-negative`,
  `[PASS] limit-429`, `revision=<sha>`.
- [ ] **Step 4:** README 3.3: allocatable `nvidia.com/gpu` = `1`; no `nvidia` RuntimeClass; `gpu-check` Job prints the
  A100 (GPU via NRI/CDI with no runtimeClassName); ClusterPolicy has no sync loop (history length stable over 5 min).

### Task 12: [SESSION] Go/no-go (T+0:50)

- [ ] **Step 1:** README 3.4. Expected: `GO profile=<ID>` with `vllm-bf16-tp1-pp1` runnable on this A100.
- [ ] **Step 2:** `NO-GO` (or the Job cannot pull/run): README section 4 → Task 17. No weights have been downloaded.

### Task 13: [SESSION] Go PR and NIMCache (T+0:55 to about T+2:15)

- [ ] **Step 1:** README 3.5: fill the profile on `session/gpu-go`, tests pass locally (`20 passed`), mark ready, CI
  green, squash-merge, hard-refresh `raglab-gpu-root`.
- [ ] **Step 2:** Record the NIMCache start time, the job pod labels and whether the job requested a GPU (open items).
- [ ] **Step 3:** Wait for `status.state` = `Ready`; record the time and `status.profiles` (must contain the pinned ID).

### Task 14: [SESSION] NIMService up, cold start, ABORT CHECKPOINT

- [ ] **Step 1:** README 3.6 replicas PR (`replicas: 0` → `1`), squash-merge.
- [ ] **Step 2:** NIMService `Ready`; record `cold_start_s` (empty cache) and `restarts` = 0 (criterion 1, 4). If the
  `nim-llm` label selector finds no pod, record the real labels and fix the two NetworkPolicies by PR.
- [ ] **Step 3:** Direct NIM check: `ready 200`, model list contains the served name, a chat answer.
- [ ] **Step 4:** **T+3:00: NIMService not Ready → README section 4 → Task 17. Do not extend.**

### Task 15: [SESSION] NetworkPolicy probes and cutover

- [ ] **Step 1:** README 3.7. Expected `status=200` for `probe-as-bifrost`, `BLOCKED` for the other two (criterion 9).
- [ ] **Step 2:** README 3.8: rebase `session/gpu-cutover`, `git diff --exit-code lab/envs` (Phase A untouched), ready,
  CI green, squash-merge; record the merge SHA as CUT.
- [ ] **Step 3:** Smoke tail on `nim-local/chat/small`: chat, stream, tools PASS, auth-negative PASS, limit-429
  `[200, 200, 429]` with the gateway marker, `0 failed`, `revision=<CUT>` (criterion 2). `routing_info` shows
  `nim-local`.

### Task 16: [SESSION] Failure injection, rollback, roll forward (T+3:40)

- [ ] **Step 1:** README 3.9.1: replicas `1` → `0` PR; after the NIM pod is gone, sync dev-gpu; smoke **fails** with an
  upstream/connection error (the gate detects a dead backend).
- [ ] **Step 2:** README 3.9.2: `git revert <CUT>` PR; smoke passes on `nvidia-hosted/chat/small`; NIMCache `Ready`, PVC
  `Bound` (criterion 3).
- [ ] **Step 3:** Only if it finishes before T+4:15: README 3.9.3 roll forward and the warm-cache cold start.
- [ ] **Step 4:** **T+4:15: stop whatever is running and go to Task 17.**

### Task 17: [SESSION] Evidence, isolation probe, TERMINATE FIRST (T+4:15 to T+4:30)

- [ ] **Step 1:** README 3.10 (skip what no longer works after an abort). Expected: CMP recipient = the session public
  key only; secrets inventory = Argo's own + `sops-age-key` + the three session Secrets; `no-vpn-interface`, no VPN
  tools, no kubeconfig listing (criterion 6).
- [ ] **Step 2:** README 5.1-5.2: `terminate --yes --wait` → `TERMINATED`; `instances` → `live instances: 0  file systems: 0`,
  exit 0; console shows nothing. **Billing has stopped: note the time.**
- [ ] **Step 3:** README 5.3: kill the tunnel; record that the account firewall rule stays (standing account setting).

### Task 18: [SESSION] Revoke keys, negative probes, delete session material

- [ ] **Step 1:** README 6.1: revoke the session nvapi key in the console; both `key_probe.py` calls print `REJECTED`
  and exit 1 (criterion 10). Exit 2 is inconclusive: retry later; do not tick.
- [ ] **Step 2:** README 6.2: before deleting anything, run `python3 scripts/lambda.py instances` one last time (exit 0);
  then delete the Lambda API key and the `raglab-gpu-session` SSH key in the Lambda console; the helper now exits 3
  with `HTTP 401`.
- [ ] **Step 3:** README 6.3: delete the session age key, `.age` files, SSH keypair, `kubeconfig.gpu`, inventory, Argo CLI
  config, known_hosts entry; `history | grep -c -e nvapi- -e AGE-SECRET` = `0`.

### Task 19: [SESSION] Cleanup PRs (after billing has stopped)

**Files:** `.sops.yaml`, `lab/gpu/secrets/gpu.sops.yaml` (mandatory); by default also every Phase B shared-file change and
new path.

- [ ] **Step 1: Tag the session state**

```bash
git fetch origin && git tag -a phase-b-session-1 origin/main -m "raglab Phase B session 1 (lab/gpu, scripts, tests)" && git push origin phase-b-session-1
```

- [ ] **Step 2: PR-T1 (mandatory, same day): dead ciphertext and the session sops rule**

`PHASE_A_BASE` = the `main` commit before Task 1 merged (`git log --oneline -- .sops.yaml`, the commit before the
GPU-rule commit). Verified in a scratch copy while writing this plan.
```bash
git checkout -b chore/gpu-teardown-secrets origin/main
B=<PHASE_A_BASE>
git rm -q lab/gpu/secrets/gpu.sops.yaml lab/gpu/secrets/kustomization.yaml lab/gpu/argocd/apps/raglab-gpu-sops.yaml tests/test_sops_rules.py
git show $B:.sops.yaml > .sops.yaml
python3 - <<'PY'
import re
for f, names in {"tests/test_gpu_argocd.py": ["test_only_secrets_app_uses_the_cmp"],
                 "tests/test_make_gpu_sops.py": ["test_gpu_secrets_kustomization_lists_only_gpu_file"]}.items():
    s = open(f).read()
    for n in names:
        s = re.sub(r"\ndef " + n + r"\(.*?(?=\ndef |\Z)", "\n", s, flags=re.S)
    open(f, "w").write(s)
PY
git diff --exit-code $B -- .sops.yaml && echo sops-yaml-restored
uv run --with pytest --with pyyaml --with jsonschema --with ansible-core pytest -q
uv run --with pyyaml python3 scripts/check_secrets.py; echo structural=$?
scripts/safety-check.sh
git add -A && git commit -m "chore(gpu): teardown - remove the session sops rule and the undecryptable session secrets"
git push -u origin HEAD && gh pr create --fill
```
Expected: `sops-yaml-restored`; `191 passed`; `structural=0`; `PASSED`. Owner merges.

- [ ] **Step 3: PR-T2 (default; skip only if a second session is booked within two weeks): back to Phase A**

```bash
git checkout -b chore/gpu-teardown-revert origin/main
B=<PHASE_A_BASE>
git checkout $B -- lab/catalogue scripts/check_secrets.py tests/test_check_secrets.py tests/test_generate.py \
  lab/bootstrap/playbooks .github/workflows/ci.yml lab/README.md
git rm -r -q lab/gpu lab/bootstrap/vars lab/bootstrap/playbooks/04-gpu-prep.yml lab/bootstrap/inventory.gpu.example.ini \
  scripts/make_gpu_sops.py scripts/lambda.py scripts/key_probe.py scripts/helm_kinds.py scripts/render-gpu-platform.sh \
  tests/test_make_gpu_sops.py tests/test_gpu_manifests.py tests/test_gpu_argocd.py tests/test_playbooks.py \
  tests/test_lambda_helper.py tests/test_key_probe.py tests/fixtures/crds/apps.nvidia.com_nimcaches.yaml
uv run --with pyyaml python3 lab/catalogue/generate.py --check && uv run --with pytest --with pyyaml --with jsonschema pytest -q
git diff --stat $B -- . ':!docs'
```
Expected: `--check` exit 0; `114 passed`; the final `git diff --stat` lists **only** `lab/bootstrap/ansible.cfg` (the
`log_path` fix is kept on purpose). Commit, `scripts/safety-check.sh`, PR, owner merges. Tag `phase-b-session-1` keeps
the whole Phase B tree for a later session (verified in a scratch copy while writing this plan).

### Task 20: [SESSION] Next-day bill check and Phase A regression

- [ ] **Step 1:** README section 8: charge vs `(terminate - launch) x 1.99`; at most USD 15 (criterion 5); console shows
  no instance and no file system.
- [ ] **Step 2:** Next time the home lab runs: README (Phase A) 1.1-1.4, then `cd lab/bootstrap && ansible-playbook playbooks/03-handover.yml`
  passes and `uv run --with pyyaml python3 lab/catalogue/generate.py --check` exits 0 (criterion 8).
- [ ] **Step 3:** Hygiene (criterion 11): `git log -p --all | grep -c -E 'nvapi-[A-Za-z0-9_-]{20,}'` = `0`; `gitleaks git . --config .gitleaks.toml --redact`
  clean; `git grep -n -E '([0-9]{1,3}\.){3}[0-9]{1,3}' -- lab docs/raglab-phase-b-findings.md` shows no home or VM address.

---

### Task 21: Findings doc `docs/raglab-phase-b-findings.md`

**Files:**
- Create: `docs/raglab-phase-b-findings.md`
- Modify: `docs/raglab-phase-a-findings.md` (one line linking Phase B)

- [ ] **Step 1: Write the findings from `~/.raglab-gpu/evidence/`** (numbers and outcomes only: no IPs, no instance id,
  no key, no raw logs with addresses). Template:

````markdown
# raglab Phase B — session findings (<date>)

Status: <COMPLETE | ABORTED at <step> (reason)>. Spec: `docs/superpowers/specs/2026-11-25-raglab-phase-b-gpu-design.md`.
Session: Lambda `<gpu_1x_a100_sxm4|gpu_1x_a100>` in `<region>`, launched <UTC>, terminated <UTC>, billed <h:mm> =
USD <x.xx> (bill checked <date>).

## Numbers this lab exists to produce
| Measure | Value | Evidence file |
|---|---|---|
| NIM image pull (gpu-check Job) | <min> | gpu-check |
| NIMCache download, start to Ready | <min> | nimcache-start/ready |
| NIMService cold start, empty cache (pod created to Ready) | <s> | cold-start-empty |
| NIMService cold start, warm cache | <s or "not reached"> | cold-start-warm |
| Bootstrap 01+02+03 wall time | <min> | |
| Total session (launch to terminate) | <h:mm> | launch/terminate |

## Success criteria (spec section 12)
| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | NIM Ready, pinned profile identical in cache/service = go/no-go, 0 restarts, NIMCache Ready | | |
| 2 | Smoke via dev-gpu on nim-local (chat, stream, tools, auth-negative, limit-429), routing_info nim-local | | |
| 3 | Injected outage fails smoke; rollback passes on hosted; NIMCache survived | | |
| 4 | Cold start recorded | | |
| 5 | Spend at or under USD 15, reconciled with the bill | | |
| 6 | No home credentials/VPN on the VM; CMP key = session key only; only the 3 session Secrets | | |
| 7 | Only SSH answers from outside (ICMP from home allowed by the account firewall: noted) | | |
| 8 | Phase A isolated: home Argo never saw lab/gpu; generate --check clean; Phase A apps Synced/Healthy | | |
| 9 | NetworkPolicy: Bifrost 200, unlabelled pod and other namespace blocked | | |
| 10 | Teardown: terminated, 0 instances/file systems, nvapi + Lambda keys REJECTED | | |
| 11 | Hygiene: no key or address in git; gitleaks clean | | |
| 12 | This document | | |

## UNVERIFIED items resolved (spec section 14, fact-check "Remaining UNKNOWNs")
| Item | Finding |
|---|---|
| Lambda: sudo, disk size, Docker/toolkit preinstalled, firewall model | |
| k3s v1.37.2 containerd version; NRI socket present | |
| GPU Operator: NRI path worked with toolkit.enabled=true; ClusterPolicy selfHeal loop? field manager name | |
| NIM: list-model-profiles output format; runnable profiles on A100 40GB; pinned ID | |
| NIMCache job: GPU request? pod labels | |
| NIMService: spec.labels reach the pod? Service name from expose.service.name | |
| NIM served model name; tool calling without flags | |
| Bifrost: plain-HTTP base_url and env placeholder key for a custom provider | |
| k3s embedded NetworkPolicy enforcement (same node) | |
| Hosted `meta/llama-3.1-8b-instruct` callable (like-for-like cutover?) | |

## Things that affect work (the Project investigation)
- <one bullet per finding that changes how the Project should run GPU Operator / NIM Operator / Bifrost cutovers>

## Deviations from the plan
- <each step done differently, and why>

## Teardown record
| Step | Done (UTC) | Evidence |
|---|---|---|
| Terminate; 0 instances, 0 file systems | | |
| Session nvapi key revoked; hosted + nvcr probes REJECTED | | |
| Lambda API key and session SSH key deleted; helper 401 | | |
| Session age key, .age files, SSH keypair, kubeconfig.gpu, inventory deleted | | |
| PR-T1 merged (sops rule, ciphertext) | | |
| PR-T2 merged or deferred (reason) | | |
| Next-day bill check | | |
````

- [ ] **Step 2:** In `docs/raglab-phase-a-findings.md`, under the status line, add:
  `Phase B (rented GPU, standalone): see [raglab-phase-b-findings.md](raglab-phase-b-findings.md).`
- [ ] **Step 3:** `scripts/safety-check.sh`, branch `docs/gpu-findings`, commit, PR. **[SESSION] owner merges.** Then
  `rm -rf ~/.raglab-gpu`.

---

## Self-review against the spec (done)

**Coverage (spec section → task):**
- §1 purpose 1-4: rent (T10), bootstrap with the same playbooks + GPU variables (T6, T11), cutover and back (T15, T16),
  terminate and prove nothing left (T17, T18, T20).
- §3 decisions: D1 standalone (T5 root path, T6 tunnel, no VPN anywhere); D2 Lambda A100 40GB per-minute,
  terminate-only, no file systems (T7 `file_system_names: []`, `instances` exit code); D3 5 h / USD 15 (Global
  Constraints, README timeline, T14/T16 checkpoints, T20 bill); D4 SSH from home only, nothing else exposed, no Lambda
  key on the VM (account firewall, T10 exposure probe, T7 helper on the Mac); D5 8B NIM, tag + digest pinned (T3, T9
  nvcr digest probe); D6 GPU Operator v26.7.3 NRI path, `driver.enabled=false` (T5, T6 04 gates, README §9 fallback);
  D7 PSS baseline/privileged/restricted (T5 namespaces); D8/D9 session key, revoked at teardown (T2, T18); D10 session-only
  age key, separate file, Phase A key never used (T1 R7, T2 negative probe, T6 test); D11 new paths, separate root,
  GPU-mode-only application (T5, T6); D12 dev-gpu only (T4).
- §4.2 bootstrap: `gpu_session=true`, uncommitted inventory outside the repo, k3s pinned, Traefik/servicelb off,
  session age key, GPU root (T6); unset = Phase A behaviour, proven by executed runs in CI (T6); `04-gpu-prep.yml` (T6).
- §5 layout and isolation: `lab/gpu/...`, secrets outside `lab/secrets`, rule first (T1, T2, T5); generator keeps
  Phase A byte-identical (T4 sha256 pins).
- §6 operators: separate `raglab-gpu-platform`, whitelists enumerated from `helm template --include-crds` and enforced
  equal by CI, rendered hash recorded, SSA + `ignoreDifferences` on ClusterPolicy, hooks listed (T5); no RuntimeClass /
  `runtimeClassName` (T3, T5 tests); success signal `nvidia.com/gpu: 1` + nvidia-smi pod (T11).
- §7 go/no-go before any download (T12), NIMCache/NIMService fields CRD-validated in CI (T3), profile in both places
  equal (T3 test), cold start (T14), PSS (T5), NetworkPolicy both sides + positive/negative probes (T3, T5, T15).
- §8 secrets: what exists on the VM (T17 inventory probe), built without printing (T2 emit/verify), revocation (T18).
- §9 Bifrost: `nim-local`, `chat/small`, per-env serving, only referenced providers, VK `allowed_models`/`key_ids`,
  client-visible id change, egress policy in the overlay, changes through git, smoke + `routing_info` (T4, T5, T15).
- §9.1 cutover/injection/rollback/roll-forward (T15, T16). §10 preparation, timeline, alarms, cost controls (T9, README).
- §11 teardown order with terminate first, evidence before it, revert PRs after billing, next-day bill (T17-T20).
- §12 criteria 1-12: mapped in the Task 21 table; each has a step that produces its evidence.

**Spec ambiguities resolved here (also listed in the hand-off):**
1. Pre-rent PRs are **merged before renting** (owner instruction), not held as the spec's §10.1 says; only the go and
   cutover PRs are drafts. Safe because the home lab never reads `lab/gpu`, and Phase A outputs are pinned.
2. **One session nvapi key** serves the hosted API, `NGC_API_KEY` and the nvcr.io pull (resolved fact), instead of the
   spec's separate NGC key (D8) and hosted key (D9). Revocation covers both uses at once. No gitleaks change is needed
   (the existing `nvapi-` rule covers it); the spec's "NGC key pattern" CI change is dropped.
3. Secret name **`ngc-api-key`** (spec §7.2/§8.3), not `ngc-api` (brief wording).
4. **Account-level Lambda firewall** (22 + ICMP from home) already exists and is kept after teardown; criterion 7 is
   "only TCP 22 answers"; ICMP from the home address is allowed and recorded.
5. k3s API is **not** bound to loopback (that would break in-cluster API access); it is unreachable from outside by the
   account firewall and reached from the Mac through an SSH tunnel; the kubeconfig keeps `127.0.0.1`.
6. `nim-local` key: an `env.NIM_LOCAL_API_KEY` reference with a non-secret placeholder in `bifrost-env`, not a literal
   in `config.json`, to keep the Phase A invariant that every generated credential is `env.*`.
7. Service name is **pinned** with `expose.service.name: llama-8b` (field exists in v3.1.4), so the catalogue URL is
   known pre-rent instead of "confirm live".
8. `toolkit.enabled: true` by default (operator-managed toolkit/CDI spec with NRI); the spec's "false if preinstalled"
   cannot be verified pre-rent.
9. Startup probe uses port `8000`, not the port name `api` (name unverified). NIMService tag is `2.1.7@sha256:...`
   (digest-pinned like the operator image).
10. The GPU root app lives at `lab/gpu/argocd/hand-applied/root-app.yaml` (with the other hand-applied files the playbook
    switches on), not `lab/gpu/argocd/root-app.yaml`. The secrets Application file is `raglab-gpu-sops.yaml` because
    `.gitignore` ignores `*secret*` (the Application name stays `raglab-gpu-secrets`).
11. Go criterion is concrete: `vllm-bf16-tp1-pp1` listed as runnable; anything else is NO-GO (no live profile shopping).
    The `raglab-gpu-nim` app enters git only with the go PR, so the NIMCache cannot start before the go/no-go.
12. In GPU mode `01-platform.yml` stops the image's own Docker/containerd so k3s's containerd is the only (NRI) runtime.
13. dev-gpu runs without Traefik, so the overlay deletes the base IngressRoute.
14. Hosted model missing contingency: the cutover PR also changes `chat/small.upstream` and says "not like-for-like".
15. Branch: the rented cluster tracks `main` (spec default); the home lab VM stays stopped so session merges cannot roll
    it; session PRs are squash-merged so rollback is a single `git revert`.
16. Teardown: the owner's "revert" rule is honoured by PR-T2 (shared files back to the pre-Phase-B commit; Phase B tree
    preserved by tag `phase-b-session-1`); PR-T1 (sops rule + ciphertext) is mandatory regardless. Exception kept on
    purpose: the `ansible.cfg` `log_path` fix (a latent Phase A bug with PyPI ansible-core).
17. The Lambda API key and the registered SSH key are deleted at teardown (the spec only covered NGC/hosted keys): the
    Lambda key file becomes undecryptable once the session age key is deleted anyway.
18. CI gains `ansible-core` in the unit-test step (needed for the "render/lint both modes" regression check); reverted
    in PR-T2.

**Placeholders (runtime values with exact commands, not unspecified design):** the profile ID (filled by README 3.4 →
3.5), the VM IP (only in `~/.raglab-gpu/inventory.ini`), `<CUT>`/merge SHAs and `<PHASE_A_BASE>` (from `git log`), and
evidence values in Task 21.

**Verified while writing this plan (2026-11-26, read-only):** every code block in Tasks 1-7 was run in a scratch copy of
the repo: 197 tests pass (114 before), `check_secrets.py` and `generate.py --check` exit 0, the Phase A hashes are
unchanged, gitleaks finds nothing in the new files, both charts render to the summaries above with Helm v4.1.4, and the
cutover branch changes only `lab/gpu/envs/dev-gpu/generated/*`.

**Still UNVERIFIED (resolved only on hardware; each has a recording step):** NRI with k3s's embedded containerd, the
`list-model-profiles` output format, NIMCache job GPU request and labels, `spec.labels` reaching the NIM pod, tool calling
without flags, Bifrost accepting plain HTTP + placeholder key for a custom provider, k3s NetworkPolicy enforcement, the
ClusterPolicy field-manager name used by `ignoreDifferences`, whether `sops` encrypts the three-document file as one.
