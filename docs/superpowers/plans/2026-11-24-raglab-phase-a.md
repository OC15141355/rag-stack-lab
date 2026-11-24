# raglab Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Steps marked **[OWNER]** are run by the repo owner (they touch keys, GitHub settings, or hv-01 as root). Agents
> never perform, simulate or skip them; they stop and hand over. Agents open PRs; **only the owner merges**.

**Goal:** Build the Phase A raglab: an on-demand k3s VM on hv-01, with its own bounded Argo CD fed from the public
`rag-stack-lab/lab/`. It runs the NIM Operator, plus Bifrost in dev/qa/prod configured from a git catalogue and
calling NVIDIA's hosted API, with smoke-test evidence and branch-based promotion. Repo secret gates go in first.

**Architecture:** Spec: [`docs/superpowers/specs/2026-11-24-raglab-gitops-lab-design.md`](../specs/2026-11-24-raglab-gitops-lab-design.md)
(rev 2), with its fact-check alongside. Order:
1. Repo gates.
2. Catalogue and generator (schema-tested).
3. Smoke tooling.
4. Manifests.
5. Argo CD.
6. VM.
7. Bootstrap.
8. Bring-up and acceptance.
9. Promotion branches.

**Tech Stack:** k3s v1.37.2+k3s1 · Argo CD 3.6.2 (chart `argo-cd` 10.18.3) · NIM Operator 3.1.4 · Bifrost v2.6.0 ·
sops 3.13.3 + age · kustomize (bundled in Argo CD) · Ansible · Python 3.11+ (uv) · gitleaks 8.30.0 · GitHub Actions.

## Global Constraints

- Argo CD chart `argo-cd` **10.18.3** (appVersion **v3.6.2**, ≥ 3.3.9 fixes CVE-2026-42880). Plugin sidecar image `quay.io/argoproj/argocd:v3.6.2@sha256:bbcc3b6e79c5963439bdc5170f6e20a52365b41878133fac5ce8d6810d2641dc`.
- k3s **v1.37.2+k3s1**, started with `--secrets-encryption`.
- NIM Operator chart `k8s-nim-operator` **3.1.4** from `https://helm.ngc.nvidia.com/nvidia`; image `nvcr.io/nvidia/cloud-native/k8s-nim-operator:v3.1.4@sha256:3f84870acea8af063573898e6e2496379cc11c9e63046c073b1f8a6dc348f209`, `pullPolicy: IfNotPresent`, admission webhook **off**.
- Bifrost image `maximhq/bifrost:v2.6.0@sha256:5968d007ba4f74ee01bc4ceb071decb9927a0b7bb43dbb9072208f75e2d522e3`; config validated against `transports/config.schema.json` at tag `transports/v2.6.0`.
- sops image `ghcr.io/getsops/sops:v3.13.3-alpine@sha256:ae501277bf742f1662e0f881f43dd8fd6798b489a8058e921dbf6cda597140ea`.
- gitleaks image `ghcr.io/gitleaks/gitleaks@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9` (v8.30.0, same pin as homelab-k8s).
- Hosted upstream: `https://integrate.api.nvidia.com` (OpenAI-compatible). Stand-in models: `z-ai/glm-5.3-flash`, `nvidia/nemotron-3.5-lightning-30b-a3b`; aliases `chat/glm`, `chat/nemotron`.
- Namespaces: `raglab-system`, `raglab-dev`, `raglab-qa`, `raglab-prod`. Argo CD in `argocd`.
- VM: hv-01, 2 vCPU, 5 GiB, 14 GiB raw disk on a dedicated thick LV `raglab` (VG `pve`), `cpuunits 50`, no `cpulimit`, `mbps_wr=50,iops_wr=500`, `onboot 0`, **no tailnet**, never in a vzdump job.
- Lab age key file: `~/.sops/raglab-age-key.txt` on the MacBook (never `~/.config/sops/age/keys.txt`, never `~/.sops/age-key.txt`).
- Public repo: no IPs, tailnet names, tokens, keys or employer data in any committed file or PR text.
- Never `Replace=true`. Every Secret-rendering Application uses `ServerSideApply=true`.

---

## File map

```
.gitignore                                  secret/key/kubeconfig/inventory ignores
.gitleaks.toml                              gitleaks rules (defaults + age key + PEM header + nvapi)
.sops.yaml                                  single rule for lab/secrets/*.sops.yaml
.github/workflows/ci.yml                    gates + tests (pull_request only)
.github/pull_request_template.md            promotion evidence checklist
scripts/check_secrets.py                    structural secrets checker (stdlib)
scripts/safety-check.sh                     gitleaks + structural check, worktree and index
scripts/pre-commit.sh                       git hook entrypoint
scripts/install-hooks.sh                    sets core.hooksPath
tests/test_check_secrets.py                 pytest for check_secrets.py
lab/catalogue/catalogue.yaml                models + per-env limits
lab/catalogue/generate.py                   → lab/envs/<env>/generated/{config.json,models.json}
lab/catalogue/bifrost-config.schema.json    vendored schema (transports/v2.6.0)
tests/test_generate.py                      pytest: schema-valid, no literal secrets, check mode
lab/smoke/smoke.py                          smoke tests (copy of examples/smoke/smoke.py + new options)
lab/smoke/mock_llm.py                       mock incl. Bifrost-style 401 body and 429
tests/test_smoke.py                         pytest: runs smoke.py against the mock
lab/envs/base/*.yaml                        Bifrost Deployment/Service/PVC/NetworkPolicy/IngressRoute/smoke Job
lab/envs/{dev,qa,prod}/kustomization.yaml   overlays (configMapGenerator from generated/)
lab/nim/base/*.yaml + lab/nim/{dev,qa,prod}/kustomization.yaml
lab/platform/nim-operator/values.yaml
lab/argocd/argocd-values.yaml               Helm values (slim, CMP sidecar, health Lua, netpol)
lab/argocd/cmp-plugin.yaml                  ConfigMap with the fail-closed sops CMP
lab/argocd/appproject-raglab.yaml           hand-applied
lab/argocd/root-app.yaml                    hand-applied
lab/argocd/apps/*.yaml                      child Applications
tests/health/                               NIMService fixtures + expected health
lab/bootstrap/{ansible.cfg,inventory.example.ini,playbooks/*.yml}
lab/secrets/{dev,qa,prod}.sops.yaml         [OWNER] created with sops edit
lab/README.md                               runbook (sessions, bootstrap, promotion, rotation, teardown)
```

---

### Task 1: Repo secret gates (before any secret exists)

**Files:**
- Create: `.gitignore`, `.gitleaks.toml`, `scripts/check_secrets.py`, `scripts/safety-check.sh`, `scripts/pre-commit.sh`, `scripts/install-hooks.sh`, `tests/test_check_secrets.py`, `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `python3 scripts/check_secrets.py [--paths P...]` → exit 0 clean, 1 findings (prints `FINDING <path>: <reason>`); `scripts/safety-check.sh` → exit 0 = PASSED; CI job `gates`.

- [ ] **Step 1: Write the failing tests for the structural checker**

```python
# tests/test_check_secrets.py
import subprocess, sys, textwrap
from pathlib import Path

CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"

def run(root: Path, *paths: str):
    return subprocess.run([sys.executable, str(CHECK), "--root", str(root), *paths],
                          capture_output=True, text=True)

def w(root: Path, rel: str, body: str):
    p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(textwrap.dedent(body)); return rel

ENC_OK = """\
apiVersion: v1
kind: Secret
metadata: {name: s}
stringData:
  NVIDIA_API_KEY: ENC[AES256_GCM,data:abc,iv:x,tag:y,type:str]
sops:
  age: [{recipient: age1xyz}]
  version: 3.13.3
"""

def test_encrypted_secret_passes(tmp_path):
    assert run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", ENC_OK)).returncode == 0

def test_plaintext_value_under_secrets_fails(tmp_path):
    body = ENC_OK.replace("ENC[AES256_GCM,data:abc,iv:x,tag:y,type:str]", "hunter2")
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
    assert r.returncode == 1 and "not ENC[" in r.stdout

def test_missing_sops_block_fails(tmp_path):
    body = ENC_OK.split("sops:")[0]
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
    assert r.returncode == 1 and "no sops metadata" in r.stdout

def test_sops_block_but_nothing_encrypted_fails(tmp_path):
    # FC 9: sops writes a sops: block even when encrypted_regex matched nothing
    body = "apiVersion: v1\nkind: ConfigMap\ndata:\n  x: hunter2\nsops:\n  version: 3.13.3\n"
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.sops.yaml", body))
    assert r.returncode == 1

def test_wrong_filename_under_secrets_fails(tmp_path):
    r = run(tmp_path, w(tmp_path, "lab/secrets/dev.yaml", ENC_OK))
    assert r.returncode == 1 and "must be *.sops.yaml" in r.stdout

def test_generated_config_with_literal_key_fails(tmp_path):
    r = run(tmp_path, w(tmp_path, "lab/envs/dev/generated/config.json",
                        '{"providers": {"x": {"keys": [{"value": "nvapi-' + "A"*50 + '"}]}}}'))
    assert r.returncode == 1 and "literal secret" in r.stdout

def test_generated_config_with_env_ref_passes(tmp_path):
    r = run(tmp_path, w(tmp_path, "lab/envs/dev/generated/config.json",
                        '{"providers": {"x": {"keys": [{"value": "env.NVIDIA_API_KEY"}]}}}'))
    assert r.returncode == 0

def test_private_age_key_anywhere_fails(tmp_path):
    r = run(tmp_path, w(tmp_path, "lab/notes.txt", "AGE-SECRET-KE" + "Y-1" + "Q"*58 + "\n"))
    assert r.returncode == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest --with pyyaml pytest tests/test_check_secrets.py -q`
Expected: FAIL (`check_secrets.py` does not exist; non-zero exit for every test).

- [ ] **Step 3: Implement the checker**

```python
#!/usr/bin/env python3
"""Structural secrets checks for this repo (stdlib + PyYAML).

Rules:
  R1 every file under lab/secrets/ is named *.sops.yaml
  R2 every lab/secrets file has a top-level `sops:` block
  R3 every leaf under data/stringData of those files is ENC[...]; there must be at least one such leaf
  R4 generated Bifrost files (lab/envs/*/generated/*) contain no literal nvapi-/sk-bf- values
  R5 no age private key or PEM private-key header anywhere in scanned text files
Exit 0 clean, 1 findings, 2 usage.
"""
from __future__ import annotations
import argparse, re, subprocess, sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("check_secrets: PyYAML required (uv run --with pyyaml ...)", file=sys.stderr); sys.exit(2)

AGE_PRIV = re.compile(r"(?i)AGE-SECRET-KE[Y]-[A-Z0-9-]*1[A-Z0-9]{20,}")
PEM_PRIV = re.compile(r"-{4,5} ?BEGIN [A-Z0-9 _-]*PRIVATE KEY")
LITERAL = re.compile(r"(nvapi-[A-Za-z0-9_-]{20,}|sk-bf-[A-Za-z0-9_-]{8,})")
ENC = re.compile(r"^ENC\[[A-Z0-9_]+,data:.*\]$")

def leaves(node):
    if isinstance(node, dict):
        for v in node.values(): yield from leaves(v)
    elif isinstance(node, list):
        for v in node: yield from leaves(v)
    else:
        yield node

def check_secret_file(rel: str, text: str) -> list[str]:
    out = []
    if not rel.endswith(".sops.yaml"):
        out.append(f"{rel}: files under lab/secrets must be *.sops.yaml")
    try:
        docs = [d for d in yaml.safe_load_all(text) if d is not None]
    except yaml.YAMLError as e:
        return out + [f"{rel}: unparseable YAML ({e.__class__.__name__})"]
    for d in docs:
        if not isinstance(d, dict) or "sops" not in d:
            out.append(f"{rel}: no sops metadata block"); continue
        vals = [v for k in ("data", "stringData") for v in leaves(d.get(k) or {})]
        if not vals:
            out.append(f"{rel}: sops block present but no data/stringData values (nothing encrypted)")
        for v in vals:
            if not (isinstance(v, str) and ENC.match(v)):
                out.append(f"{rel}: value under data/stringData is not ENC[...]")
                break
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
    return [l for l in r.stdout.splitlines() if l]

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args()
    root = Path(a.root)
    paths = a.paths or tracked_files(root)
    findings = []
    for rel in paths:
        p = root / rel
        if not p.is_file(): continue
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            continue
        if rel.startswith("lab/secrets/"):
            findings += check_secret_file(rel, text)
        findings += check_text(rel, text)
    for f in findings: print(f"FINDING {f}")
    return 1 if findings else 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest --with pyyaml pytest tests/test_check_secrets.py -q`
Expected: `8 passed`.

- [ ] **Step 5: Add .gitignore, .gitleaks.toml, safety-check, hooks**

`.gitignore` (comments on their own lines only; a trailing comment disables a pattern):
```gitignore
# Private keys and key material
*.key
*.pem
*.p12
age-key*.txt
raglab-age-key*.txt
*.age
# Environment and credential files
.env
.env.*
*.kubeconfig
kubeconfig
kubeconfig.*
k3s.yaml
# Bootstrap inventory with real hosts
lab/bootstrap/inventory.ini
# Decrypted / plaintext working copies
*.dec
*.dec.*
*.plain.*
# Anything named secret, except encrypted sops files
*secret*
!**/secrets/
!**/secrets/*.sops.yaml
!scripts/check_secrets.py
!lab/argocd/apps/raglab-secrets.yaml
!tests/test_check_secrets.py
# Editor swap/backup
*.swp
*.swo
*~
.#*
# Python
__pycache__/
.pytest_cache/
.venv/
```

`.gitleaks.toml`:
```toml
title = "rag-stack-lab"

[extend]
useDefault = true

# key prefix written KE[Y] so this file never matches itself
[[rules]]
id = "age-secret-key"
description = "age secret key incl. PQ hybrid / lower-case variants"
regex = '''(?i)AGE-SECRET-KE[Y]-[A-Z0-9-]*1[A-Z0-9]{20,}'''
keywords = ["age-secret-key-"]

[[rules]]
id = "private-key-header"
description = "PEM / ssh.com private-key header, no END marker required"
regex = '''-{4,5} ?BEGIN [A-Z0-9 _-]*PRIVATE KEY'''
keywords = ["private key"]

[[rules]]
id = "nvidia-api-key"
description = "NVIDIA API / NGC personal key"
regex = '''nvapi-[A-Za-z0-9_-]{20,}'''
keywords = ["nvapi-"]

[[rules]]
id = "bifrost-virtual-key"
description = "Bifrost virtual key"
regex = '''sk-bf-[A-Za-z0-9_-]{8,}'''
keywords = ["sk-bf-"]

[allowlist]
description = "age PUBLIC keys are not secrets; test fixtures build fake keys at runtime"
regexes = ['''^age1[a-z0-9]{58}$''']
```

`scripts/safety-check.sh`:
```bash
#!/usr/bin/env bash
# Run before `git add`. Exit 0 = PASSED. Scans worktree (tracked + untracked, not ignored) and the index.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
GITLEAKS_IMAGE="ghcr.io/gitleaks/gitleaks@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9"
fail=0
uv run --quiet --with pyyaml python3 scripts/check_secrets.py || fail=1
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks dir . --config .gitleaks.toml --no-banner --redact || fail=1
  gitleaks git . --config .gitleaks.toml --no-banner --redact --staged || fail=1
elif command -v docker >/dev/null 2>&1; then
  docker run --rm -v "$PWD:/repo" -w /repo "$GITLEAKS_IMAGE" dir /repo --config /repo/.gitleaks.toml --no-banner --redact || fail=1
else
  echo "safety-check: neither gitleaks nor docker available; structural check only (NOT a pass)" >&2
  exit 2
fi
[[ $fail -eq 0 ]] && echo "PASSED" || { echo "FAILED"; exit 1; }
```

`scripts/pre-commit.sh`:
```bash
#!/usr/bin/env bash
# git pre-commit hook: structural check on staged files + gitleaks on the staged diff.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# bash 3.2 compatible (macOS /bin/bash): no mapfile
staged=()
while IFS= read -r f; do staged+=("$f"); done < <(git diff --cached --name-only --diff-filter=ACMR)
[[ ${#staged[@]} -eq 0 ]] && exit 0
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
for f in "${staged[@]}"; do mkdir -p "$tmp/$(dirname "$f")"; git show ":$f" > "$tmp/$f" 2>/dev/null || true; done
uv run --quiet --with pyyaml python3 scripts/check_secrets.py --root "$tmp" "${staged[@]}"
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks git . --config .gitleaks.toml --no-banner --redact --staged
else
  command -v docker >/dev/null 2>&1 || { echo "pre-commit: need gitleaks or docker; refusing commit" >&2; exit 1; }
  docker run --rm -v "$tmp:/scan:ro" -v "$PWD/.gitleaks.toml:/cfg.toml:ro" \
    ghcr.io/gitleaks/gitleaks@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9 \
    dir /scan --config /cfg.toml --no-banner --redact \
  || { echo "pre-commit: gitleaks found secrets; refusing commit" >&2; exit 1; }
fi
```

`scripts/install-hooks.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
mkdir -p .githooks
ln -sf ../scripts/pre-commit.sh .githooks/pre-commit
chmod +x scripts/pre-commit.sh scripts/safety-check.sh
git config core.hooksPath .githooks
echo "hooks installed (core.hooksPath=.githooks)"
```

Run: `chmod +x scripts/*.sh && scripts/install-hooks.sh`
Expected: `hooks installed (core.hooksPath=.githooks)`

- [ ] **Step 6: Add CI**

`.github/workflows/ci.yml`:
```yaml
name: ci
on:
  pull_request:
  push:
    branches: [main, env/qa, env/prod]
permissions:
  contents: read
jobs:
  gates:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - name: gitleaks (tree + full history)
        run: |
          docker run --rm -v "$PWD:/repo" -w /repo \
            ghcr.io/gitleaks/gitleaks@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9 \
            git /repo --config /repo/.gitleaks.toml --no-banner --redact
      - uses: astral-sh/setup-uv@v6
      - name: structural secrets check
        run: uv run --with pyyaml python3 scripts/check_secrets.py
      - name: unit tests
        run: uv run --with pytest --with pyyaml --with jsonschema pytest -q
```

- [ ] **Step 7: Prove the gates block a fake key (negative test)**

```bash
printf 'token = "nvapi-%s"\n' "$(python3 -c 'print("A"*48)')" > /tmp/raglab-fake.txt
cp /tmp/raglab-fake.txt lab-fake-key.txt
git add lab-fake-key.txt && git commit -m "test: must be blocked"; echo "exit=$?"
git reset -q HEAD lab-fake-key.txt; rm -f lab-fake-key.txt /tmp/raglab-fake.txt
```
Expected: the commit is refused (non-zero `exit=`), output names `nvidia-api-key`. If it commits, STOP: the hook is not wired.

- [ ] **Step 8: Commit (via the hook)**

```bash
scripts/safety-check.sh
git checkout -b feat/repo-gates
git add .gitignore .gitleaks.toml scripts/ tests/test_check_secrets.py .github/workflows/ci.yml
git commit -m "feat(gates): secret gates before any lab secret (gitleaks, structural check, hooks, CI)"
git push -u origin feat/repo-gates && gh pr create --fill
```
Expected: `PASSED`; PR opened; CI `gates` green. **[OWNER] merges.**

---

### Task 2: GitHub protections + history scan **[OWNER]**

**Files:** none (repository settings).

- [ ] **Step 1: Turn on secret scanning + push protection**

```bash
gh api -X PATCH repos/OC15141355/rag-stack-lab \
  -f 'security_and_analysis[secret_scanning][status]=enabled' \
  -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
gh api repos/OC15141355/rag-stack-lab --jq '.security_and_analysis | {ss:.secret_scanning.status, pp:.secret_scanning_push_protection.status}'
```
Expected: `{"ss":"enabled","pp":"enabled"}`.

- [ ] **Step 2: Protect main (PR + CI required, no force-push)**

```bash
gh api -X PUT repos/OC15141355/rag-stack-lab/branches/main/protection --input - <<'JSON'
{"required_status_checks":{"strict":true,"contexts":["gates"]},
 "enforce_admins":false,
 "required_pull_request_reviews":{"required_approving_review_count":0},
 "restrictions":null,"allow_force_pushes":false,"allow_deletions":false}
JSON
gh api repos/OC15141355/rag-stack-lab/branches/main/protection --jq '.required_status_checks.contexts'
```
Expected: `["gates"]`. (`enforce_admins:false` keeps owner break-glass; agents still go through PRs by rule.)

- [ ] **Step 3: Full-history scan**

Run: `docker run --rm -v "$PWD:/repo" ghcr.io/gitleaks/gitleaks@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9 git /repo --config /repo/.gitleaks.toml --no-banner --redact; echo exit=$?`
Expected: `no leaks found`, `exit=0`. Any finding: stop, assess, rotate (never "fix" by history rewrite alone).

---

### Task 3: Lab age key + SOPS config + env secrets **[OWNER for key and values]**

**Files:**
- Create: `.sops.yaml`, `lab/secrets/{dev,qa,prod}.sops.yaml` (owner), `lab/.envrc`

**Interfaces:**
- Produces: Secret manifests `bifrost-env` in each `raglab-<env>` with keys `NVIDIA_API_KEY`, `BIFROST_ENCRYPTION_KEY`, `BIFROST_ADMIN_USER`, `BIFROST_ADMIN_PASSWORD`, `BIFROST_VK`, `BIFROST_VK_PROBE`; Secret `sops-age-key` (bootstrap, never in git).

- [ ] **Step 1: [OWNER] Generate the lab key into its own file**

```bash
test ! -e ~/.sops/raglab-age-key.txt || { echo "EXISTS: refusing to overwrite"; exit 1; }
mkdir -p ~/.sops && (umask 077 && age-keygen -o ~/.sops/raglab-age-key.txt)
grep '^# public key:' ~/.sops/raglab-age-key.txt
```
Expected: `# public key: age1...`. Copy only that public value into the next step. Back up the file to the password manager now.

- [ ] **Step 2: Root `.sops.yaml` (agent may write; public key only)**

```yaml
# Single rule. Only Kubernetes Secret manifests under lab/secrets/*.sops.yaml are encrypted.
creation_rules:
  - path_regex: ^lab/secrets/[a-z0-9-]+\.sops\.yaml$
    encrypted_regex: ^(data|stringData)$
    age: age1REPLACE_WITH_OWNER_PUBLIC_KEY_FROM_STEP_1
```
The `age:` value is the owner's public key printed in Step 1, pasted verbatim (public keys are not secrets).

`lab/.envrc`:
```bash
export SOPS_AGE_KEY_FILE="$HOME/.sops/raglab-age-key.txt"
```

- [ ] **Step 3: [OWNER] Create each env secret with `sops edit` (no plaintext on disk)**

```bash
cd "$(git rev-parse --show-toplevel)"
export SOPS_AGE_KEY_FILE=~/.sops/raglab-age-key.txt
EDITOR='vim -n -i NONE -c "set noundofile nobackup nowritebackup"' sops edit lab/secrets/dev.sops.yaml
```
Replace the template with (values typed/pasted in the editor only):
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: bifrost-env
  namespace: raglab-dev
type: Opaque
stringData:
  NVIDIA_API_KEY: <paste the dev NVIDIA personal key>
  BIFROST_ENCRYPTION_KEY: <output of: openssl rand -hex 32>
  BIFROST_ADMIN_USER: raglab-admin
  BIFROST_ADMIN_PASSWORD: <output of: openssl rand -base64 24>
  BIFROST_VK: sk-bf-<output of: openssl rand -hex 24>
  BIFROST_VK_PROBE: sk-bf-<output of: openssl rand -hex 24>
```
Repeat for `qa` and `prod` (namespace `raglab-qa`/`raglab-prod`; separate generated values; separate NVIDIA keys if quota allows). NVIDIA key: Personal key, service "Public API Endpoints" only, shortest expiry covering the lab.

- [ ] **Step 4: Verify encryption structurally and by test-decrypt (stdout only)**

```bash
uv run --with pyyaml python3 scripts/check_secrets.py lab/secrets/dev.sops.yaml lab/secrets/qa.sops.yaml lab/secrets/prod.sops.yaml; echo exit=$?
sops -d lab/secrets/dev.sops.yaml | grep -c '^  [A-Z_]*:'
```
Expected: `exit=0`; `6`. Then prove the password-manager backup decrypts: `SOPS_AGE_KEY_FILE=<backup copy> sops -d lab/secrets/dev.sops.yaml >/dev/null && echo backup-ok`.

- [ ] **Step 5: Commit through the hook**

```bash
git checkout -b feat/lab-secrets
git add .sops.yaml lab/.envrc lab/secrets/*.sops.yaml
git commit -m "feat(lab): sops config and encrypted env secrets"
git push -u origin feat/lab-secrets && gh pr create --fill
```
Expected: hook passes; CI green. **[OWNER] merges.**

---

### Task 4: Catalogue + schema-valid Bifrost config generator

**Files:**
- Create: `lab/catalogue/catalogue.yaml`, `lab/catalogue/generate.py`, `lab/catalogue/bifrost-config.schema.json`, `tests/test_generate.py`
- Output (committed): `lab/envs/{dev,qa,prod}/generated/{config.json,models.json}`

**Interfaces:**
- Produces: `uv run --with pyyaml python3 lab/catalogue/generate.py [--check]` writes/compares `lab/envs/<env>/generated/config.json` (Bifrost config) and `models.json` (`{"models":[{"id","alias","upstream","context_window","max_output_tokens","capabilities":[...]}]}`). Consumed by Task 6 (configMapGenerator) and Task 5 (smoke reads `models.json`).

- [ ] **Step 1: Vendor the schema**

```bash
gh api -H 'Accept: application/vnd.github.raw' \
  'repos/maximhq/bifrost/contents/transports/config.schema.json?ref=transports/v2.6.0' \
  > lab/catalogue/bifrost-config.schema.json
python3 -c "import json;print(len(json.load(open('lab/catalogue/bifrost-config.schema.json'))['properties']))"
```
Expected: a number ≥ 30.

- [ ] **Step 2: Write the catalogue**

```yaml
# lab/catalogue/catalogue.yaml — source of truth for models and per-env limits.
# Limits are per env only (no shared defaults), so a limit change is always an env-scoped change.
upstream:
  provider: nvidia-hosted
  base_url: https://integrate.api.nvidia.com
  timeout_seconds: 300
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
# requests_per_minute: main virtual key (generous; normal smoke uses ~12 requests).
# probe_requests_per_minute: a second, tiny virtual key used ONLY by the limit-429 check, so the 429 is
# provably Bifrost's (only 2 calls ever reach upstream), never NVIDIA's own rate limit.
environments:
  dev:  {requests_per_minute: 30, tokens_per_minute: 60000, probe_requests_per_minute: 2, log_retention_days: 3}
  qa:   {requests_per_minute: 30, tokens_per_minute: 60000, probe_requests_per_minute: 2, log_retention_days: 3}
  prod: {requests_per_minute: 30, tokens_per_minute: 60000, probe_requests_per_minute: 2, log_retention_days: 7}
```
(`capabilities` drives smoke `--skip tools`; Nemotron Lightning tool support is unconfirmed, so it's off until proven.)

- [ ] **Step 3: Write failing tests**

```python
# tests/test_generate.py
import json, subprocess, sys
from pathlib import Path
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "lab/catalogue/generate.py"
SCHEMA = json.loads((ROOT / "lab/catalogue/bifrost-config.schema.json").read_text())

def gen(*args):
    return subprocess.run([sys.executable, str(GEN), *args], capture_output=True, text=True, cwd=ROOT)

def cfg(env):
    return json.loads((ROOT / f"lab/envs/{env}/generated/config.json").read_text())

def test_generate_writes_all_envs():
    r = gen(); assert r.returncode == 0, r.stderr
    for env in ("dev", "qa", "prod"):
        assert (ROOT / f"lab/envs/{env}/generated/config.json").exists()
        assert (ROOT / f"lab/envs/{env}/generated/models.json").exists()

def test_config_is_valid_against_bifrost_schema():
    gen()
    for env in ("dev", "qa", "prod"):
        jsonschema.validate(cfg(env), SCHEMA)

def test_security_settings():
    gen(); c = cfg("prod")
    assert c["source_of_truth"] == "config.json"
    assert c["client"]["enforce_auth_on_inference"] is True
    assert c["client"]["disable_content_logging"] is True
    assert c["governance"]["auth_config"]["is_enabled"] is True
    assert c["encryption_key"] == "env.BIFROST_ENCRYPTION_KEY"

def test_no_literal_secrets_only_env_refs():
    gen(); text = json.dumps(cfg("dev"))
    assert "nvapi-" not in text and "sk-bf-" not in text
    assert '"env.NVIDIA_API_KEY"' in text and '"env.BIFROST_VK"' in text

def test_limits_are_per_env_and_probe_key_exists():
    gen(); g = cfg("dev")["governance"]
    rl = {r["id"]: r for r in g["rate_limits"]}
    assert rl["rl-dev"]["request_max_limit"] == 30 and rl["rl-dev-probe"]["request_max_limit"] == 2
    vks = {v["id"]: v for v in g["virtual_keys"]}
    assert vks["vk-dev"]["value"] == "env.BIFROST_VK" and vks["vk-dev-probe"]["value"] == "env.BIFROST_VK_PROBE"
    assert vks["vk-dev-probe"]["rate_limit_id"] == "rl-dev-probe"

def test_aliases_map_to_upstream():
    gen(); key = cfg("dev")["providers"]["nvidia-hosted"]["keys"][0]
    assert key["aliases"]["chat/glm"] == "z-ai/glm-5.3-flash"
    assert set(key["models"]) == {"chat/glm", "chat/nemotron"}

def test_check_mode_detects_drift(tmp_path):
    gen()
    p = ROOT / "lab/envs/qa/generated/config.json"; orig = p.read_text()
    try:
        p.write_text(orig.replace('"request_max_limit": 30', '"request_max_limit": 99'))
        assert gen("--check").returncode == 1
    finally:
        p.write_text(orig)
    assert gen("--check").returncode == 0
```

Run: `uv run --with pytest --with pyyaml --with jsonschema pytest tests/test_generate.py -q`
Expected: FAIL (generator missing).

- [ ] **Step 4: Implement the generator**

```python
#!/usr/bin/env python3
"""Generate per-env Bifrost config.json + models.json from catalogue.yaml.

Secrets are never written: every credential is an `env.VAR` reference resolved by Bifrost at startup
from the bifrost-env Secret. Output is validated in CI against the vendored Bifrost schema.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
ENVS = ("dev", "qa", "prod")

def build_config(cat: dict, env: str) -> dict:
    up, models, lim = cat["upstream"], cat["models"], cat["environments"][env]
    prov = up["provider"]
    aliases = {m["alias"]: m["upstream"] for m in models}
    rl_id, vk_id = f"rl-{env}", f"vk-{env}"
    return {
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
        "providers": {
            prov: {
                "keys": [{
                    "name": f"nvidia-{env}",
                    "value": "env.NVIDIA_API_KEY",
                    "weight": 1,
                    "models": sorted(aliases),
                    "aliases": aliases,
                }],
                "network_config": {
                    "base_url": up["base_url"],
                    "default_request_timeout_in_seconds": up["timeout_seconds"],
                    "stream_idle_timeout_in_seconds": up["timeout_seconds"],
                },
                "custom_provider_config": {
                    "base_provider_type": "openai",
                    "allowed_requests": {
                        "list_models": True, "chat_completion": True, "chat_completion_stream": True,
                    },
                },
                "store_raw_request_response": False,
            }
        },
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
                 "rate_limit_id": rl_id,
                 "provider_configs": [{"provider": prov, "weight": 1, "allowed_models": sorted(aliases)}]},
                {"id": f"{vk_id}-probe", "name": f"{vk_id}-probe", "value": "env.BIFROST_VK_PROBE",
                 "is_active": True, "rate_limit_id": f"{rl_id}-probe",
                 "provider_configs": [{"provider": prov, "weight": 1, "allowed_models": sorted(aliases)}]},
            ],
        },
    }

def build_models(cat: dict) -> dict:
    return {"models": [{"id": m["alias"], "alias": m["alias"], "upstream": m["upstream"],
                        "context_window": m["context_window"], "max_output_tokens": m["max_output_tokens"],
                        "capabilities": m["capabilities"]} for m in cat["models"]]}

def render(obj: dict) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--check", action="store_true"); a = ap.parse_args()
    cat = yaml.safe_load((HERE / "catalogue.yaml").read_text())
    drift = 0
    for env in ENVS:
        out = LAB / "envs" / env / "generated"
        for name, obj in (("config.json", build_config(cat, env)), ("models.json", build_models(cat))):
            p, want = out / name, render(obj)
            if a.check:
                if not p.exists() or p.read_text() != want:
                    print(f"DRIFT: {p.relative_to(LAB.parent)} differs from catalogue"); drift = 1
            else:
                out.mkdir(parents=True, exist_ok=True); p.write_text(want); print(f"wrote {p.relative_to(LAB.parent)}")
    return drift

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --with pytest --with pyyaml --with jsonschema pytest tests/test_generate.py -q`
Expected: `7 passed`. If schema validation fails, read the reported path, fix the field against `bifrost-config.schema.json`, re-run. Do not loosen the test.

- [ ] **Step 6: Add generator drift check to CI and commit**

Append to `.github/workflows/ci.yml` `gates.steps`:
```yaml
      - name: catalogue drift
        run: uv run --with pyyaml python3 lab/catalogue/generate.py --check
```
```bash
scripts/safety-check.sh
git checkout -b feat/catalogue && git add lab/catalogue lab/envs/*/generated tests/test_generate.py .github/workflows/ci.yml
git commit -m "feat(lab): model catalogue + schema-valid Bifrost config generator" && git push -u origin feat/catalogue && gh pr create --fill
```

---

### Task 5: Smoke tooling for Bifrost

**Files:**
- Create: `lab/smoke/smoke.py` (from `examples/smoke/smoke.py` + changes below), `lab/smoke/mock_llm.py` (from `examples/smoke/mock_llm.py` + changes), `tests/test_smoke.py`
- Modify: `.github/workflows/ci.yml` (drift check `examples/smoke` vs `lab/smoke` is **not** used; `lab/smoke` is now canonical and `examples/smoke/README` points to it)

**Interfaces:**
- Consumes: `lab/envs/<env>/generated/models.json` (Task 4).
- Produces: `python3 lab/smoke/smoke.py --base-url URL --models-file models.json --header-env x-bf-vk=BIFROST_VK [--expect-auth BODY_SUBSTRING] [--limit-burst N --limit-header-env x-bf-vk=BIFROST_VK_PROBE] --json-report P`, exit 0 pass / 1 fail.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_smoke.py
import json, os, socket, subprocess, sys, time
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SMOKE, MOCK = ROOT / "lab/smoke/smoke.py", ROOT / "lab/smoke/mock_llm.py"

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

@pytest.fixture
def mock(tmp_path):
    procs = []
    def start(mode="good", rpm=1000, probe_rpm=2):
        port = free_port()
        p = subprocess.Popen([sys.executable, str(MOCK)], env={**os.environ, "MOCK_MODE": mode, "PORT": str(port),
                             "MOCK_RPM": str(rpm), "MOCK_VK": "sk-bf-test", "MOCK_VK_PROBE": "sk-bf-probe",
                             "MOCK_PROBE_RPM": str(probe_rpm)})
        procs.append(p); time.sleep(0.6); return f"http://127.0.0.1:{port}/v1"
    yield start
    for p in procs: p.kill()

def models_file(tmp_path, tools=True):
    f = tmp_path / "models.json"
    f.write_text(json.dumps({"models": [{"id": "test-model", "capabilities": ["chat", "stream"] + (["tools"] if tools else [])}]}))
    return str(f)

def run(url, tmp_path, *extra):
    env = {**os.environ, "BIFROST_VK": "sk-bf-test", "BIFROST_VK_PROBE": "sk-bf-probe"}
    return subprocess.run([sys.executable, str(SMOKE), "--base-url", url, "--models-file", models_file(tmp_path),
                           "--header-env", "x-bf-vk=BIFROST_VK", *extra], capture_output=True, text=True, env=env)

def test_good_passes_and_key_not_in_argv(mock, tmp_path):
    r = run(mock(), tmp_path, "--expect-auth", "virtual key")
    assert r.returncode == 0, r.stdout
    assert "sk-bf-test" not in r.stdout

def test_auth_negative_requires_bifrost_body(mock, tmp_path):
    r = run(mock(mode="generic401"), tmp_path, "--expect-auth", "virtual key")
    assert r.returncode == 1 and "auth-negative" in r.stdout

def test_limit_burst_expects_429_from_probe_key(mock, tmp_path):
    lim = ("--limit-burst", "3", "--limit-header-env", "x-bf-vk=BIFROST_VK_PROBE")
    assert run(mock(probe_rpm=2), tmp_path, *lim).returncode == 0
    assert run(mock(probe_rpm=1000), tmp_path, *lim).returncode == 1

def test_skips_tools_when_capability_absent(mock, tmp_path):
    env = {**os.environ, "BIFROST_VK": "sk-bf-test"}
    r = subprocess.run([sys.executable, str(SMOKE), "--base-url", mock(mode="notools"), "--models-file",
                        models_file(tmp_path, tools=False), "--header-env", "x-bf-vk=BIFROST_VK"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "[SKIP] tools" in r.stdout

def test_backoff_on_upstream_429(mock, tmp_path):
    assert run(mock(mode="flaky429"), tmp_path).returncode == 0
```

Run: `uv run --with pytest pytest tests/test_smoke.py -q`
Expected: FAIL (files missing).

- [ ] **Step 2: Create `lab/smoke/mock_llm.py`**

Copy `examples/smoke/mock_llm.py`, then make these changes (complete file):
```python
"""Fake Bifrost/OpenAI endpoint for smoke tests.
MOCK_MODE: good | buffered | notools | generic401 | flaky429 ; MOCK_RPM: main-key requests/min before 429 ;
MOCK_VK: main key ; MOCK_VK_PROBE: probe key limited to MOCK_PROBE_RPM (default 2)."""
import json, os, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODE = os.environ.get("MOCK_MODE", "good")
VK = os.environ.get("MOCK_VK", "sk-bf-test")
RPM = int(os.environ.get("MOCK_RPM", "1000"))
VK_PROBE = os.environ.get("MOCK_VK_PROBE", "sk-bf-probe")
PROBE_RPM = int(os.environ.get("MOCK_PROBE_RPM", "2"))
_lock, _hits, _probe_hits, _flaky = threading.Lock(), [], [], {"n": 0}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _gate(self):
        if self.headers.get("x-bf-vk") == VK_PROBE:
            with _lock:
                now = time.time(); _probe_hits[:] = [t for t in _probe_hits if now - t < 60]; _probe_hits.append(now)
                if len(_probe_hits) > PROBE_RPM:
                    self._json(429, {"error": {"message": "rate limit exceeded", "type": "rate_limited"}}); return False
            return True
        if self.headers.get("x-bf-vk") != VK:
            if MODE == "generic401": self._json(401, {"error": "unauthorized"})
            else: self._json(401, {"error": {"message": "virtual key is required", "type": "virtual_key_required"}})
            return False
        with _lock:
            now = time.time(); _hits[:] = [t for t in _hits if now - t < 60]; _hits.append(now)
            if len(_hits) > RPM:
                self._json(429, {"error": {"message": "rate limit exceeded", "type": "rate_limited"}}); return False
        if MODE == "flaky429":
            with _lock:
                _flaky["n"] += 1
                if _flaky["n"] % 3 == 1:
                    self.send_response(429); self.send_header("Retry-After", "1"); self.end_headers(); return False
        return True
    def do_GET(self):
        if not self._gate(): return
        self._json(200, {"data": [{"id": "test-model"}]})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if not self._gate(): return
        if body.get("stream"):
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            chunks = [f"data: {json.dumps({'choices': [{'delta': {'content': str(i) + ','}}]})}\n\n" for i in range(1, 31)]
            if MODE == "buffered":
                time.sleep(1.5); self.wfile.write("".join(chunks).encode())
            else:
                for ch in chunks: self.wfile.write(ch.encode()); self.wfile.flush(); time.sleep(0.05)
            self.wfile.write(b"data: [DONE]\n\n"); return
        if body.get("tools"):
            msg = ({"role": "assistant", "content": '<tool_call>{"name":"get_weather"}</tool_call>'} if MODE == "notools"
                   else {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function",
                         "function": {"name": "get_weather", "arguments": json.dumps({"city": "Sydney"})}}]})
            return self._json(200, {"choices": [{"message": msg, "finish_reason": "tool_calls"}]})
        n = len(body["messages"][0]["content"].split())
        self._json(200, {"choices": [{"message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": n, "completion_tokens": 1}})

ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "18080"))), H).serve_forever()
```

- [ ] **Step 3: Create `lab/smoke/smoke.py`**

Copy `examples/smoke/smoke.py`, then apply these changes:

(a) In `Client.__init__`, add `self.retries = 3` and replace `call` with a version that retries 429 with `Retry-After` (default 2 s):
```python
    def call(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> tuple[int, dict | str]:
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(self._req(method, path, body, auth), timeout=self.timeout, context=self.ctx) as r:
                    raw = r.read().decode()
                    try: return r.status, json.loads(raw)
                    except json.JSONDecodeError: return r.status, raw
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < self.retries and not getattr(self, "no_retry", False):
                    time.sleep(float(e.headers.get("Retry-After") or 2)); continue
                return e.code, e.read().decode(errors="replace")[:500]
        return 429, "retries exhausted"
```
(b) Add options and env-sourced headers in `main()` (replace the header-parsing block):
```python
    p.add_argument("--header-env", action="append", default=[],
                   help="header from env var: 'Header-Name=ENV_VAR' (value never on argv)")
    p.add_argument("--models-file", help="models.json from the catalogue; runs checks per model")
    p.add_argument("--expect-auth", metavar="BODY_SUBSTRING",
                   help="assert unauthenticated requests are rejected 401/403 with this substring in the body")
    p.add_argument("--limit-burst", type=int, default=0,
                   help="send N quick 1-token chats without retry using --limit-header-env; pass only if one gets 429")
    p.add_argument("--limit-header-env", default="",
                   help="'Header-Name=ENV_VAR' for the low-limit probe key (separate from the main key)")
```
```python
    headers = {}
    for h in a.header:
        k, v = h.split(":", 1); headers[k.strip()] = v.strip()
    for h in a.header_env:
        k, var = h.split("=", 1)
        if var not in os.environ: p.error(f"--header-env: ${var} not set")
        headers[k.strip()] = os.environ[var]
```
Make `--model` optional (`required=False`) and, when `--models-file` is given, loop:
```python
    models = ([{"id": a.model, "capabilities": ["chat", "stream", "tools"]}] if a.model
              else json.load(open(a.models_file))["models"])
    for m in models:
        mid = m.get("id") or m["alias"]
        print(f"--- model {mid}")
        for name, fn in (("models", lambda: check_models(c, mid)), ("chat", lambda: check_chat(c, mid, a.max_tokens)),
                         ("stream", lambda: check_stream(c, mid, a.max_ttft)), ("tools", lambda: check_tools(c, mid, a.tool_attempts))):
            if name in a.skip or (name == "tools" and "tools" not in m.get("capabilities", [])):
                record(name, None, "skipped"); continue
            try: fn()
            except Exception as e: record(name, False, f"error: {e}")
    if a.expect_auth: check_auth(c, models[0].get("id") or models[0]["alias"], a.expect_auth)
    if a.limit_burst:
        k, var = a.limit_header_env.split("=", 1)
        if var not in os.environ: p.error(f"--limit-header-env: ${var} not set")
        check_limit(c, models[0].get("id") or models[0]["alias"], a.limit_burst, {k.strip(): os.environ[var]})
```
(c) Replace `check_auth` and add `check_limit`:
```python
def check_auth(c: Client, model: str, body_substring: str) -> None:
    code, body = c.call("POST", "/chat/completions", {"model": model, "max_tokens": 4,
                        "messages": [{"role": "user", "content": "hi"}]}, auth=False)
    text = json.dumps(body) if not isinstance(body, str) else body
    ok = code in (401, 403) and body_substring.lower() in text.lower()
    record("auth-negative", ok, f"unauthenticated -> HTTP {code}; gateway body {'matched' if ok else 'NOT matched'} ({body_substring!r})")

def check_limit(c: Client, model: str, n: int, probe_headers: dict) -> None:
    saved, c.headers, c.no_retry, codes = c.headers, {**c.headers, **probe_headers}, True, []
    try:
        for _ in range(n):
            code, _ = c.call("POST", "/chat/completions", {"model": model, "max_tokens": 1,
                             "messages": [{"role": "user", "content": "hi"}]})
            codes.append(code)
    finally:
        c.headers, c.no_retry = saved, False
    # probe key allows 2/min, so request 3 must be refused by the gateway; earlier ones may succeed
    record("limit-429", 429 in codes[2:], f"{n} rapid probe-key requests -> codes {codes} (expect 429 from request 3)")
```
(d) The unauthenticated request must send **no** gateway headers: in `_req`, `h.update(self.headers if auth else {})` already does this. Keep it.
(e) Print the synced revision when present: at the end of `main()`, `print(f"revision={os.environ.get('SYNC_REVISION','unknown')}")` and include `"revision"` in the JSON report.

- [ ] **Step 4: Run tests**

Run: `uv run --with pytest pytest tests/test_smoke.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
printf '# Moved\nThe maintained smoke tooling is in `lab/smoke/`.\n' > examples/smoke/README.md
scripts/safety-check.sh
git checkout -b feat/smoke && git add lab/smoke tests/test_smoke.py examples/smoke/README.md
git commit -m "feat(lab): smoke tooling with env-sourced keys, gateway auth body, limit-429 and backoff"
git push -u origin feat/smoke && gh pr create --fill
```

---

### Task 6: Kustomize manifests (Bifrost envs + NIM CRs)

**Files:**
- Create: `lab/envs/base/{kustomization.yaml,deployment.yaml,service.yaml,pvc.yaml,networkpolicy.yaml,ingressroute.yaml,smoke-job.yaml,prune-canary.yaml}`, `lab/envs/{dev,qa,prod}/kustomization.yaml`, `lab/nim/base/{kustomization.yaml,nimservice-glm.yaml,nimservice-nemotron.yaml}`, `lab/nim/{dev,qa,prod}/kustomization.yaml`, `tests/test_manifests.py`

**Interfaces:**
- Consumes: `lab/envs/<env>/generated/*` (Task 4), `lab/smoke/smoke.py` (Task 5), Secret `bifrost-env` (Task 3).
- Produces: per-env Deployment `bifrost`, Service `bifrost:80→8080`, PostSync Job `smoke`, ConfigMap `prune-canary`; NIMServices `glm`, `nemotron` in `raglab-<env>`.

- [ ] **Step 1: Failing test — every overlay builds and has the required properties**

```python
# tests/test_manifests.py
import shutil, subprocess, pytest, yaml
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl needed")

def build(path):
    out = subprocess.run(["kubectl", "kustomize", str(ROOT / path)], capture_output=True, text=True, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]

@pytest.mark.parametrize("env", ["dev", "qa", "prod"])
def test_env_overlay(env):
    docs = build(f"lab/envs/{env}")
    kinds = {(d["kind"], d["metadata"]["name"].split("-")[0]) for d in docs}
    assert ("Deployment", "bifrost") in kinds and ("Job", "smoke") in kinds
    for d in docs:
        assert d["metadata"].get("namespace", f"raglab-{env}") == f"raglab-{env}"
    dep = next(d for d in docs if d["kind"] == "Deployment")
    assert dep["spec"]["strategy"]["type"] == "Recreate"
    c = dep["spec"]["template"]["spec"]["containers"][0]
    assert "@sha256:" in c["image"] and c["resources"]["limits"]["memory"]
    cms = [d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"].startswith("bifrost-config-")]
    assert cms, "configMapGenerator must add a hash suffix (forces rollout on change)"
    pvc = next(d for d in docs if d["kind"] == "PersistentVolumeClaim")
    assert pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-options"] == "Prune=false,Delete=false"
    job = next(d for d in docs if d["kind"] == "Job")
    assert job["metadata"]["annotations"]["argocd.argoproj.io/hook"] == "PostSync"
    assert "sk-bf-" not in yaml.safe_dump_all(docs)

@pytest.mark.parametrize("env", ["dev", "qa", "prod"])
def test_nim_overlay(env):
    docs = build(f"lab/nim/{env}")
    assert len(docs) == 2
    for d in docs:
        assert d["kind"] == "NIMService" and d["spec"]["replicas"] == 0
        assert "emptyDir" in d["spec"]["storage"] and "nimCache" not in d["spec"]["storage"]
```
Run: `uv run --with pytest --with pyyaml pytest tests/test_manifests.py -q` → Expected: FAIL.

- [ ] **Step 2: Base manifests**

`lab/envs/base/kustomization.yaml`:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: [pvc.yaml, deployment.yaml, service.yaml, networkpolicy.yaml, ingressroute.yaml, smoke-job.yaml, prune-canary.yaml]
configMapGenerator:
  - name: smoke-script
    files: [smoke.py=smoke.py]
```
(`smoke.py` is copied into `lab/envs/base/` by `scripts/sync-smoke.sh` — see Step 5 — because kustomize refuses files outside the kustomization root.)

`lab/envs/base/pvc.yaml`:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: bifrost-data
  annotations:
    argocd.argoproj.io/sync-options: Prune=false,Delete=false
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: local-path
  resources: {requests: {storage: 1Gi}}
```

`lab/envs/base/deployment.yaml`:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata: {name: bifrost, labels: {app: bifrost}}
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector: {matchLabels: {app: bifrost}}
  template:
    metadata: {labels: {app: bifrost}}
    spec:
      securityContext: {runAsNonRoot: true, runAsUser: 1000, fsGroup: 1000, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: bifrost
          image: maximhq/bifrost:v2.6.0@sha256:5968d007ba4f74ee01bc4ceb071decb9927a0b7bb43dbb9072208f75e2d522e3
          args: ["-host", "0.0.0.0", "-port", "8080", "-app-dir", "/app/data", "-log-level", "info"]
          envFrom: [{secretRef: {name: bifrost-env}}]
          ports: [{name: http, containerPort: 8080}]
          readinessProbe: {httpGet: {path: /health, port: http}, initialDelaySeconds: 10, periodSeconds: 10}
          livenessProbe: {httpGet: {path: /health, port: http}, initialDelaySeconds: 30, periodSeconds: 20}
          resources: {requests: {cpu: 100m, memory: 512Mi}, limits: {memory: 768Mi}}
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
          volumeMounts:
            - {name: data, mountPath: /app/data}
            - {name: config, mountPath: /app/data/config.json, subPath: config.json, readOnly: true}
      volumes:
        - {name: data, persistentVolumeClaim: {claimName: bifrost-data}}
        - {name: config, configMap: {name: bifrost-config}}
```

`lab/envs/base/service.yaml`:
```yaml
apiVersion: v1
kind: Service
metadata: {name: bifrost}
spec:
  selector: {app: bifrost}
  ports: [{name: http, port: 80, targetPort: http}]
```

`lab/envs/base/networkpolicy.yaml`:
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: bifrost}
spec:
  podSelector: {matchLabels: {app: bifrost}}
  policyTypes: [Ingress, Egress]
  ingress:
    - from:
        - podSelector: {matchLabels: {app: smoke}}
        - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}
          podSelector: {matchLabels: {app.kubernetes.io/name: traefik}}
      ports: [{port: 8080}]
  egress:
    - to: [{namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}, podSelector: {matchLabels: {k8s-app: kube-dns}}}]
      ports: [{port: 53, protocol: UDP}, {port: 53, protocol: TCP}]
    - to: [{ipBlock: {cidr: 0.0.0.0/0, except: [10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16]}}]
      ports: [{port: 443}]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: smoke}
spec:
  podSelector: {matchLabels: {app: smoke}}
  policyTypes: [Egress]
  egress:
    - to: [{podSelector: {matchLabels: {app: bifrost}}}]
      ports: [{port: 8080}]
    - to: [{namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}, podSelector: {matchLabels: {k8s-app: kube-dns}}}]
      ports: [{port: 53, protocol: UDP}]
```

`lab/envs/base/ingressroute.yaml` (only `/v1`; admin UI never exposed):
```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata: {name: bifrost-v1}
spec:
  entryPoints: [web]
  routes:
    - match: Host(`raglab-env.lab`) && PathPrefix(`/v1`)
      kind: Rule
      services: [{name: bifrost, port: 80}]
```

`lab/envs/base/smoke-job.yaml`:
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: smoke
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 900
  template:
    metadata: {labels: {app: smoke}}
    spec:
      restartPolicy: Never
      securityContext: {runAsNonRoot: true, runAsUser: 1000, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: smoke
          image: python:3.12-slim@sha256:REPLACE_IN_STEP_4
          command: ["python3", "/smoke/smoke.py", "--base-url", "http://bifrost/v1",
                    "--models-file", "/catalogue/models.json", "--header-env", "x-bf-vk=BIFROST_VK",
                    "--expect-auth", "virtual key", "--limit-burst", "3",
                    "--limit-header-env", "x-bf-vk=BIFROST_VK_PROBE", "--max-ttft", "90",
                    "--max-tokens", "1024", "--json-report", "/tmp/report.json"]
          env:
            - name: BIFROST_VK
              valueFrom: {secretKeyRef: {name: bifrost-env, key: BIFROST_VK}}
            - name: BIFROST_VK_PROBE
              valueFrom: {secretKeyRef: {name: bifrost-env, key: BIFROST_VK_PROBE}}
            - name: SYNC_REVISION
              valueFrom: {fieldRef: {fieldPath: "metadata.annotations['raglab/revision']"}}
          resources: {requests: {cpu: 50m, memory: 64Mi}, limits: {memory: 128Mi}}
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
          volumeMounts:
            - {name: script, mountPath: /smoke}
            - {name: catalogue, mountPath: /catalogue}
      volumes:
        - {name: script, configMap: {name: smoke-script}}
        - {name: catalogue, configMap: {name: bifrost-config}}
```

`lab/envs/base/prune-canary.yaml` (proves prune is on; criterion 4):
```yaml
apiVersion: v1
kind: ConfigMap
metadata: {name: prune-canary}
data: {purpose: "deleted from git during acceptance test 4; must be pruned"}
```

- [ ] **Step 3: Overlays**

`lab/envs/dev/kustomization.yaml` (qa/prod identical except `dev` → `qa`/`prod`):
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: raglab-dev
resources: [../base]
configMapGenerator:
  - name: bifrost-config
    files: [config.json=generated/config.json, models.json=generated/models.json]
commonAnnotations:
  raglab/env: dev
patches:
  - target: {kind: IngressRoute, name: bifrost-v1}
    patch: |-
      - op: replace
        path: /spec/routes/0/match
        value: Host(`raglab-dev.lab`) && PathPrefix(`/v1`)
```
(The `raglab/revision` annotation is set by Argo CD in Task 7 via the Application's `kustomize.commonAnnotations` with `${ARGOCD_APP_REVISION}`. Kustomize also stamps it on pod templates, so **Bifrost restarts on every synced revision**. That's accepted in the lab (Recreate, seconds of downtime), and it means "a new pod" alone is not evidence of a config change. The evidence is the changed `bifrost-config-<hash>` name.)

`lab/nim/base/nimservice-glm.yaml` (nemotron identical with `name: nemotron`):
```yaml
apiVersion: apps.nvidia.com/v1alpha1
kind: NIMService
metadata: {name: glm, annotations: {argocd.argoproj.io/sync-wave: "1"}}
spec:
  image:
    repository: nvcr.io/nim/nvidia/vllm-model-free-nim
    tag: "2.1.6"
    pullPolicy: IfNotPresent
  replicas: 0
  storage:
    emptyDir: {sizeLimit: 1Gi}
  resources: {limits: {nvidia.com/gpu: 1}}
  expose: {service: {type: ClusterIP, port: 8000}}
```
`lab/nim/base/kustomization.yaml`: `resources: [nimservice-glm.yaml, nimservice-nemotron.yaml]`.
`lab/nim/dev/kustomization.yaml`: `namespace: raglab-dev`, `resources: [../base]` (qa/prod likewise).

- [ ] **Step 4: Pin the smoke image digest**

```bash
T=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/python:pull" | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")
D=$(curl -sI -H "Authorization: Bearer $T" -H 'Accept: application/vnd.oci.image.index.v1+json' https://registry-1.docker.io/v2/library/python/manifests/3.12-slim | awk -F': ' 'tolower($1)=="docker-content-digest"{print $2}' | tr -d '\r')
python3 - "$D" <<'PY'
import sys, pathlib
p = pathlib.Path("lab/envs/base/smoke-job.yaml")
p.write_text(p.read_text().replace("python:3.12-slim@sha256:REPLACE_IN_STEP_4", "python:3.12-slim@" + sys.argv[1]))
PY
grep -n 'python:3.12-slim@sha256:' lab/envs/base/smoke-job.yaml
```
Expected: one line with a real 64-hex digest.

- [ ] **Step 5: Sync script for smoke.py into the kustomize root, run tests, commit**

`scripts/sync-smoke.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
cp lab/smoke/smoke.py lab/envs/base/smoke.py
```
Add CI step: `- run: scripts/sync-smoke.sh && git diff --exit-code lab/envs/base/smoke.py`.

```bash
chmod +x scripts/sync-smoke.sh && scripts/sync-smoke.sh
uv run --with pytest --with pyyaml pytest tests/test_manifests.py -q
```
Expected: `6 passed`.
```bash
scripts/safety-check.sh
git checkout -b feat/manifests && git add lab/envs lab/nim tests/test_manifests.py scripts/sync-smoke.sh .github/workflows/ci.yml
git commit -m "feat(lab): Bifrost env and NIM (scaled-to-zero) kustomize overlays" && git push -u origin feat/manifests && gh pr create --fill
```

---

### Task 7: Argo CD bounded config, health check, applications

**Files:**
- Create: `lab/argocd/argocd-values.yaml`, `lab/argocd/cmp-plugin.yaml`, `lab/argocd/appproject-raglab.yaml`, `lab/argocd/root-app.yaml`, `lab/argocd/apps/{raglab-system,raglab-secrets,raglab-dev,raglab-qa,raglab-prod,raglab-nim-dev,raglab-nim-qa,raglab-nim-prod}.yaml`, `lab/platform/nim-operator/values.yaml`, `tests/health/{nimservice-*.yaml,expected.txt}`, `scripts/test-health.sh`

**Interfaces:**
- Consumes: Tasks 3, 4, 6 paths.
- Produces: Helm values consumed by Task 9 bootstrap; Lua health for `apps.nvidia.com/NIMService`.

- [ ] **Step 1: Health-check fixtures (the test)**

`tests/health/nimservice-scaled-zero.yaml`:
```yaml
apiVersion: apps.nvidia.com/v1alpha1
kind: NIMService
metadata: {name: glm, namespace: raglab-dev}
spec: {replicas: 0}
status: {state: NotReady}
```
`tests/health/nimservice-ready.yaml`: same with `spec: {replicas: 1}`, `status: {state: Ready}`.
`tests/health/nimservice-notready-scaled.yaml`: `spec: {replicas: 1}`, `status: {state: NotReady}`.
`tests/health/nimservice-failed.yaml`: `spec: {replicas: 1}`, `status: {state: Failed}`.
`tests/health/expected.txt`:
```
nimservice-scaled-zero.yaml Healthy
nimservice-ready.yaml Healthy
nimservice-notready-scaled.yaml Progressing
nimservice-failed.yaml Degraded
```
`scripts/test-health.sh`:
```bash
#!/usr/bin/env bash
# Runs Argo CD's own Lua engine on the fixtures. Needs argocd CLI v3.6.2.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
python3 - "$tmp/argocd-cm.yaml" <<'PY'
import sys, yaml
v = yaml.safe_load(open("lab/argocd/argocd-values.yaml"))
cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "argocd-cm"}, "data": v["configs"]["cm"]}
yaml.safe_dump(cm, open(sys.argv[1], "w"))
PY
fail=0
while read -r f want; do
  got=$(argocd admin settings resource-overrides health "tests/health/$f" --argocd-cm-path "$tmp/argocd-cm.yaml" 2>&1 | awk '/^STATUS:/{print $2}')
  [[ "$got" == "$want" ]] && echo "ok   $f $got" || { echo "FAIL $f got=$got want=$want"; fail=1; }
done < tests/health/expected.txt
exit $fail
```
Install the CLI (CI and local): `curl -sSLo /tmp/argocd https://github.com/argoproj/argo-cd/releases/download/v3.6.2/argocd-linux-amd64 && echo "$(curl -sSL https://github.com/argoproj/argo-cd/releases/download/v3.6.2/cli_checksums.txt | awk '/argocd-linux-amd64$/{print $1}')  /tmp/argocd" | sha256sum -c && chmod +x /tmp/argocd && sudo mv /tmp/argocd /usr/local/bin/argocd` (macOS: `argocd-darwin-arm64`, `shasum -a 256 -c`).

Run: `scripts/test-health.sh` → Expected: FAIL (values file missing).

- [ ] **Step 2: Argo CD Helm values (slim, bounded, CMP sidecar, Lua)**

`lab/argocd/argocd-values.yaml`:
```yaml
global:
  image: {tag: v3.6.2}
  networkPolicy: {create: true}
dex: {enabled: false}
notifications: {enabled: false}
applicationSet: {replicas: 0}
redis:
  resources: {requests: {cpu: 20m, memory: 64Mi}, limits: {memory: 128Mi}}
controller:
  resources: {requests: {cpu: 100m, memory: 256Mi}, limits: {memory: 512Mi}}
server:
  resources: {requests: {cpu: 50m, memory: 128Mi}, limits: {memory: 256Mi}}
  service: {type: ClusterIP}
configs:
  cm:
    admin.enabled: "true"
    exec.enabled: "false"
    kustomize.buildOptions: ""
    application.resourceTrackingMethod: annotation
    resource.customizations.health.apps.nvidia.com_NIMService: |
      hs = {}
      local st = nil
      if obj.status ~= nil then st = obj.status.state end
      local replicas = nil
      if obj.spec ~= nil then replicas = obj.spec.replicas end
      if st == "Ready" then
        hs.status = "Healthy"; hs.message = "Ready"; return hs
      end
      if st == "Failed" then
        hs.status = "Degraded"; hs.message = "NIMService failed"; return hs
      end
      if st == "NotReady" and replicas == 0 then
        hs.status = "Healthy"; hs.message = "scaled to zero (Phase A)"; return hs
      end
      hs.status = "Progressing"; hs.message = "waiting for NIMService (state: " .. tostring(st) .. ")"
      return hs
  params:
    server.insecure: "true"
repoServer:
  resources: {requests: {cpu: 100m, memory: 256Mi}, limits: {memory: 512Mi}}
  volumes:
    - {name: cmp-plugin, configMap: {name: cmp-plugin}}
    - {name: cmp-tmp, emptyDir: {}}
    - {name: custom-tools, emptyDir: {}}
    - {name: sops-age-key, secret: {secretName: sops-age-key}}
  initContainers:
    - name: install-sops
      image: ghcr.io/getsops/sops:v3.13.3-alpine@sha256:ae501277bf742f1662e0f881f43dd8fd6798b489a8058e921dbf6cda597140ea
      command: [/bin/sh, -c, cp /usr/local/bin/sops /custom-tools/]
      volumeMounts: [{name: custom-tools, mountPath: /custom-tools}]
  extraContainers:
    - name: sops-kustomize
      image: quay.io/argoproj/argocd:v3.6.2@sha256:bbcc3b6e79c5963439bdc5170f6e20a52365b41878133fac5ce8d6810d2641dc
      command: [/var/run/argocd/argocd-cmp-server]
      env: [{name: SOPS_AGE_KEY_FILE, value: /sops-age/keys.txt}]
      securityContext: {runAsNonRoot: true, runAsUser: 999}
      volumeMounts:
        - {name: var-files, mountPath: /var/run/argocd}
        - {name: plugins, mountPath: /home/argocd/cmp-server/plugins}
        - {name: cmp-plugin, mountPath: /home/argocd/cmp-server/config/plugin.yaml, subPath: sops-kustomize.yaml}
        - {name: cmp-tmp, mountPath: /tmp}
        - {name: sops-age-key, mountPath: /sops-age, readOnly: true}
        - {name: custom-tools, mountPath: /usr/local/bin/sops, subPath: sops}
```
Note: the age key is mounted only into the `sops-kustomize` sidecar (the main repo-server container has no `sops-age-key` mount). `admin.enabled: "true"` is lab-only (no SSO); the initial password is read by command, never printed into logs (Task 9).

`lab/argocd/cmp-plugin.yaml`: copy of homelab `argocd/cmp-plugin-configmap.yaml`, with `discover:` **removed** (selected only by explicit `plugin.name`):
```yaml
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
            # Fail closed: a decrypt failure fails the render (homelab incident #244/#245).
            for f in $(find . -type f -name "*.sops.yaml"); do
              if ! err=$(sops --decrypt --in-place "$f" 2>&1); then
                echo "sops decrypt FAILED for $f: $err" >&2; exit 1
              fi
            done
            kustomize build .
      lockRepo: false
```
`lab/argocd/repo-server-egress.yaml` (hand-applied by bootstrap; restricts where the pod holding the age key can talk):
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: repo-server-egress, namespace: argocd}
spec:
  podSelector: {matchLabels: {app.kubernetes.io/name: argocd-repo-server}}
  policyTypes: [Egress]
  egress:
    - to: [{namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}, podSelector: {matchLabels: {k8s-app: kube-dns}}}]
      ports: [{port: 53, protocol: UDP}, {port: 53, protocol: TCP}]
    - to: [{podSelector: {matchLabels: {app.kubernetes.io/name: argocd-redis}}}]
      ports: [{port: 6379}]
    - to: [{ipBlock: {cidr: 0.0.0.0/0, except: [10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16]}}]
      ports: [{port: 443}]
```
(Public HTTPS only, so it can reach GitHub and NGC but nothing on the LAN or in-cluster except DNS/Redis. Pinning GitHub's changing IP ranges is out of scope for the lab.)

And `lab/secrets/kustomization.yaml`:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: [dev.sops.yaml, qa.sops.yaml, prod.sops.yaml]
```

- [ ] **Step 3: Run the health test**

Run: `scripts/test-health.sh`
Expected:
```
ok   nimservice-scaled-zero.yaml Healthy
ok   nimservice-ready.yaml Healthy
ok   nimservice-notready-scaled.yaml Progressing
ok   nimservice-failed.yaml Degraded
```
Add to `.github/workflows/ci.yml` `gates.steps`:
```yaml
      - name: argocd CLI v3.6.2 (checksum-verified)
        run: |
          curl -sSLo /tmp/argocd https://github.com/argoproj/argo-cd/releases/download/v3.6.2/argocd-linux-amd64
          curl -sSL https://github.com/argoproj/argo-cd/releases/download/v3.6.2/cli_checksums.txt | awk '/argocd-linux-amd64$/{print $1"  /tmp/argocd"}' | sha256sum -c
          chmod +x /tmp/argocd && sudo mv /tmp/argocd /usr/local/bin/argocd
      - name: NIMService health check
        run: uv run --with pyyaml bash scripts/test-health.sh
```

- [ ] **Step 4: AppProject (hand-applied) and root app**

`lab/argocd/appproject-raglab.yaml`:
```yaml
# HAND-APPLIED by bootstrap. Not under lab/argocd/apps, so a merge cannot widen it.
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata: {name: raglab, namespace: argocd}
spec:
  sourceRepos: [https://github.com/OC15141355/rag-stack-lab.git, https://helm.ngc.nvidia.com/nvidia]
  destinations:
    - {server: https://kubernetes.default.svc, namespace: raglab-system}
    - {server: https://kubernetes.default.svc, namespace: raglab-dev}
    - {server: https://kubernetes.default.svc, namespace: raglab-qa}
    - {server: https://kubernetes.default.svc, namespace: raglab-prod}
  clusterResourceWhitelist:
    - {group: "", kind: Namespace}
    - {group: apiextensions.k8s.io, kind: CustomResourceDefinition}
    - {group: rbac.authorization.k8s.io, kind: ClusterRole}
    - {group: rbac.authorization.k8s.io, kind: ClusterRoleBinding}
  namespaceResourceWhitelist:
    - {group: "", kind: ConfigMap}
    - {group: "", kind: Secret}
    - {group: "", kind: Service}
    - {group: "", kind: ServiceAccount}
    - {group: "", kind: PersistentVolumeClaim}
    - {group: apps, kind: Deployment}
    - {group: batch, kind: Job}
    - {group: networking.k8s.io, kind: NetworkPolicy}
    - {group: rbac.authorization.k8s.io, kind: Role}
    - {group: rbac.authorization.k8s.io, kind: RoleBinding}
    - {group: traefik.io, kind: IngressRoute}
    - {group: apps.nvidia.com, kind: NIMService}
    - {group: monitoring.coreos.com, kind: ServiceMonitor}
```
(If the NIM Operator chart renders other kinds, the sync fails with "not permitted in project"; add only those kinds, each with a one-line reason, in a PR the owner reviews and hand-applies.)

`lab/argocd/root-app.yaml`:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: raglab-root, namespace: argocd}
spec:
  project: raglab-root
  source: {repoURL: https://github.com/OC15141355/rag-stack-lab.git, targetRevision: main, path: lab/argocd/apps}
  destination: {server: https://kubernetes.default.svc, namespace: argocd}
  syncPolicy: {automated: {prune: true, selfHeal: true}}
---
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata: {name: raglab-root, namespace: argocd}
spec:
  sourceRepos: [https://github.com/OC15141355/rag-stack-lab.git]
  destinations: [{server: https://kubernetes.default.svc, namespace: argocd}]
  clusterResourceWhitelist: []
  namespaceResourceWhitelist: [{group: argoproj.io, kind: Application}]
```

- [ ] **Step 5: Child applications**

`lab/argocd/apps/raglab-system.yaml`:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: raglab-system
  namespace: argocd
  finalizers: [resources-finalizer.argocd.argoproj.io]
spec:
  project: raglab
  sources:
    - repoURL: https://helm.ngc.nvidia.com/nvidia
      chart: k8s-nim-operator
      targetRevision: 3.1.4
      helm: {valueFiles: [$values/lab/platform/nim-operator/values.yaml]}
    - {repoURL: https://github.com/OC15141355/rag-stack-lab.git, targetRevision: main, ref: values}
  destination: {server: https://kubernetes.default.svc, namespace: raglab-system}
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true, ServerSideApply=true]
```

`lab/argocd/apps/raglab-secrets.yaml`:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: raglab-secrets, namespace: argocd, finalizers: [resources-finalizer.argocd.argoproj.io]}
spec:
  project: raglab
  source:
    repoURL: https://github.com/OC15141355/rag-stack-lab.git
    targetRevision: main
    path: lab/secrets
    plugin: {name: sops-kustomize}
  destination: {server: https://kubernetes.default.svc}
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [ServerSideApply=true]
    # namespaces are created by the env apps; retry until they exist
    retry: {limit: 10, backoff: {duration: 30s, factor: 2, maxDuration: 5m}}
```
(One secrets app tracks `main` for all envs: a secret rotation is a deliberate owner change, not a promotion. Destination namespaces come from each manifest's `metadata.namespace`.)

`lab/argocd/apps/raglab-dev.yaml` (qa/prod: `name`, `path: lab/envs/qa|prod`, `targetRevision: env/qa|env/prod`, namespace):
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: raglab-dev, namespace: argocd, finalizers: [resources-finalizer.argocd.argoproj.io]}
spec:
  project: raglab
  source:
    repoURL: https://github.com/OC15141355/rag-stack-lab.git
    targetRevision: main
    path: lab/envs/dev
    kustomize:
      commonAnnotations: {raglab/revision: "${ARGOCD_APP_REVISION}"}
      commonAnnotationsEnvsubst: true
  destination: {server: https://kubernetes.default.svc, namespace: raglab-dev}
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true, SkipDryRunOnMissingResource=true]
    retry: {limit: 5, backoff: {duration: 30s, factor: 2, maxDuration: 5m}}
    managedNamespaceMetadata:
      labels: {pod-security.kubernetes.io/enforce: restricted}
```
`lab/argocd/apps/raglab-nim-dev.yaml` (qa/prod analogous, same `targetRevision` as the env app):
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: raglab-nim-dev, namespace: argocd, finalizers: [resources-finalizer.argocd.argoproj.io]}
spec:
  project: raglab
  source: {repoURL: https://github.com/OC15141355/rag-stack-lab.git, targetRevision: main, path: lab/nim/dev}
  destination: {server: https://kubernetes.default.svc, namespace: raglab-dev}
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [SkipDryRunOnMissingResource=true]
    retry: {limit: 5, backoff: {duration: 30s, factor: 2, maxDuration: 5m}}
```

`lab/platform/nim-operator/values.yaml`:
```yaml
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
```
(If the chart doesn't accept `tag` with a digest, use its `digest`/`image` field instead. Verify with `helm template` in Step 6.)

- [ ] **Step 6: Render-check the operator chart and commit**

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia >/dev/null && helm repo update >/dev/null
helm template x nvidia/k8s-nim-operator --version 3.1.4 -f lab/platform/nim-operator/values.yaml \
  | grep -E '^kind:|image:' | sort | uniq -c
```
Expected: an image line containing `@sha256:3f84870a…`, and only kinds in the AppProject whitelist (adjust the whitelist with reasons if not). Run `helm template` where helm is installed (core-01).
```bash
scripts/safety-check.sh
git checkout -b feat/argocd && git add lab/argocd lab/platform lab/secrets/kustomization.yaml tests/health scripts/test-health.sh .github/workflows/ci.yml
git commit -m "feat(lab): bounded Argo CD (AppProject, fail-closed sops CMP, NIMService health), apps" && git push -u origin feat/argocd && gh pr create --fill
```

---

### Task 8: Create the lab VM on hv-01 **[OWNER, root on hv-01]**

**Files:** none (host config). Record commands/outputs in a private session log, not the repo.

- [ ] **Step 1: Precheck (read-only)**

```bash
ssh hv-01 'df -h / | tail -1; vgs --noheadings -o vg_name,vg_free pve; cat /proc/pressure/io /proc/pressure/memory | head -2; qm list | grep -c running'
```
Expected: root fs ≥ 20G free; `pve` VG free ≥ 14G; PSI `some avg60` ≈ 0.

- [ ] **Step 2: Dedicated thick LV + node-restricted storage**

```bash
ssh hv-01 'lvcreate -L 14G -n raglab pve && vgcreate raglabvg /dev/pve/raglab && pvesm add lvm raglab --vgname raglabvg --content images --nodes hv-01 && pvesm status | grep raglab'
```
Expected: `raglab  lvm  active ...`. (A thick LV is fully allocated up front, so it can't grow into the thin pool or the root fs.)

- [ ] **Step 3: Full clone with resource controls**

```bash
ssh hv-01 'set -e
ID=$(pvesh get /cluster/nextid)
qm clone 9001 $ID --name raglab --full 1 --storage raglab
qm set $ID --cores 2 --memory 5120 --balloon 0 --cpuunits 50 --onboot 0
DISK=$(qm config $ID | awk -F": " "/^(scsi|virtio)0:/{print \$1}")
qm resize $ID $DISK 14G 2>/dev/null || true
qm set $ID --$DISK "$(qm config $ID | awk -F": " "/^$DISK:/{print \$2}"),mbps_wr=50,iops_wr=500"
qm set $ID --ciuser ubuntu --sshkeys ~/.ssh/authorized_keys --ipconfig0 ip=dhcp
qm config $ID | grep -E "^(cores|memory|cpuunits|onboot|scsi0|virtio0|balloon)"
echo VMID=$ID'
```
Expected: `cores: 2`, `memory: 5120`, `cpuunits: 50`, `onboot: 0`, the disk on `raglab:` with `mbps_wr=50,iops_wr=500`. **Do not** add the VM to any backup job. Do not snapshot it.

- [ ] **Step 4: Start, find its address, record it privately**

```bash
ssh hv-01 "qm start <VMID> && sleep 40 && qm guest cmd <VMID> network-get-interfaces | grep -o '\"ip-address\" : \"192[^\"]*' | head -1"
```
Expected: a LAN IPv4. Put it only in the gitignored `lab/bootstrap/inventory.ini`.

---

### Task 9: Bootstrap (Ansible): k3s → Argo CD → age key → hand-applied AppProject/root

**Files:**
- Create: `lab/bootstrap/ansible.cfg`, `lab/bootstrap/inventory.example.ini`, `lab/bootstrap/playbooks/01-platform.yml`, `lab/bootstrap/playbooks/02-argocd.yml`, `lab/bootstrap/playbooks/03-handover.yml`

**Interfaces:**
- Consumes: Task 7 files; VM from Task 8; `~/.sops/raglab-age-key.txt` on the workstation.
- Produces: a cluster with Argo CD and `raglab-root` syncing; kubeconfig at `lab/bootstrap/kubeconfig` (gitignored).

- [ ] **Step 1: Inventory and config**

`lab/bootstrap/inventory.example.ini`:
```ini
[raglab]
raglab-vm ansible_host=<LAN IP from Task 8> ansible_user=ubuntu
```
`lab/bootstrap/ansible.cfg`:
```ini
[defaults]
inventory = inventory.ini
host_key_checking = True
stdout_callback = default
no_target_syslog = True
log_path =
```
Copy to `inventory.ini` (gitignored) and fill in the IP.

- [ ] **Step 2: Platform playbook (k3s pinned, checksum-verified, secrets encryption)**

`lab/bootstrap/playbooks/01-platform.yml`:
```yaml
- hosts: raglab
  become: true
  vars:
    k3s_version: v1.37.2+k3s1
  tasks:
    - name: Download k3s binary at the pinned version
      ansible.builtin.get_url:
        url: "https://github.com/k3s-io/k3s/releases/download/{{ k3s_version | urlencode }}/k3s"
        dest: /usr/local/bin/k3s
        mode: "0755"
        checksum: "sha256:https://github.com/k3s-io/k3s/releases/download/{{ k3s_version | urlencode }}/sha256sum-amd64.txt"
    - name: Download install script at the same tag
      ansible.builtin.get_url:
        url: "https://raw.githubusercontent.com/k3s-io/k3s/{{ k3s_version }}/install.sh"
        dest: /root/k3s-install.sh
        mode: "0700"
    - name: Install k3s server (binary already present)
      ansible.builtin.command:
        cmd: /root/k3s-install.sh
        creates: /etc/systemd/system/k3s.service
      environment:
        INSTALL_K3S_SKIP_DOWNLOAD: "true"
        INSTALL_K3S_EXEC: "server --secrets-encryption --write-kubeconfig-mode 0600"
    - name: Verify secrets encryption is on
      ansible.builtin.command: k3s secrets-encrypt status
      register: enc
      changed_when: false
      failed_when: "'Enabled' not in enc.stdout"
    - name: Fetch kubeconfig to the workstation (gitignored path)
      ansible.builtin.fetch:
        src: /etc/rancher/k3s/k3s.yaml
        dest: "{{ playbook_dir }}/../kubeconfig"
        flat: true
```
Run: `cd lab/bootstrap && ansible-playbook playbooks/01-platform.yml && sed -i '' "s/127.0.0.1/$(awk '/ansible_host/{split($2,a,"=");print a[2]}' inventory.ini)/" kubeconfig && KUBECONFIG=kubeconfig kubectl get nodes`
Expected: one node `Ready`; the task "Verify secrets encryption" `ok`.

- [ ] **Step 3: Argo CD + age key (from the workstation, no_log)**

`lab/bootstrap/playbooks/02-argocd.yml`:
```yaml
- hosts: localhost
  connection: local
  gather_facts: false
  environment: {KUBECONFIG: "{{ playbook_dir }}/../kubeconfig"}
  vars:
    lab: "{{ playbook_dir }}/../.."
  tasks:
    - name: Namespace argocd
      ansible.builtin.shell: kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply --server-side -f -
    - name: age key Secret (created, not applied; never logged)
      no_log: true
      ansible.builtin.shell: |
        kubectl -n argocd get secret sops-age-key >/dev/null 2>&1 || \
        kubectl -n argocd create secret generic sops-age-key --from-file=keys.txt="$HOME/.sops/raglab-age-key.txt"
    - name: CMP plugin ConfigMap
      ansible.builtin.command: kubectl apply --server-side -f {{ lab }}/lab/argocd/cmp-plugin.yaml
    - name: Argo CD (chart 10.18.3 = v3.6.2)
      ansible.builtin.command: >
        helm upgrade --install argocd argo-cd --repo https://argoproj.github.io/argo-helm
        --version 10.18.3 -n argocd -f {{ lab }}/lab/argocd/argocd-values.yaml --wait --timeout 10m
    - name: Hand-apply AppProject raglab, then root app
      ansible.builtin.command: kubectl apply --server-side -f {{ item }}
      loop: ["{{ lab }}/lab/argocd/repo-server-egress.yaml", "{{ lab }}/lab/argocd/appproject-raglab.yaml", "{{ lab }}/lab/argocd/root-app.yaml"]
```
Run: `ansible-playbook playbooks/02-argocd.yml` (from `lab/bootstrap`, `helm` on the workstation; use core-01 if the MacBook lacks helm).
Expected: all tasks ok; the age-key task shows `censored due to no_log`.

- [ ] **Step 4: Handover checks**

`lab/bootstrap/playbooks/03-handover.yml`:
```yaml
- hosts: localhost
  connection: local
  gather_facts: false
  environment: {KUBECONFIG: "{{ playbook_dir }}/../kubeconfig"}
  tasks:
    - name: Wait for all Applications Synced/Healthy with a Succeeded last operation
      ansible.builtin.shell: |
        kubectl -n argocd get applications -o json | python3 -c '
        import json,sys
        bad=[a["metadata"]["name"] for a in json.load(sys.stdin)["items"]
             if a.get("status",{}).get("sync",{}).get("status")!="Synced"
             or a.get("status",{}).get("health",{}).get("status")!="Healthy"
             or a.get("status",{}).get("operationState",{}).get("phase") not in ("Succeeded",None)]
        print(" ".join(bad)); sys.exit(1 if bad else 0)'
      register: apps
      retries: 40
      delay: 30
      until: apps.rc == 0
    - name: No Secret carries a client-side last-applied annotation
      ansible.builtin.shell: |
        kubectl get secrets -A -o json | python3 -c '
        import json,sys
        bad=[f"{s[\"metadata\"][\"namespace\"]}/{s[\"metadata\"][\"name\"]}" for s in json.load(sys.stdin)["items"]
             if "kubectl.kubernetes.io/last-applied-configuration" in (s["metadata"].get("annotations") or {})
             and (s["metadata"]["namespace"]=="argocd" or s["metadata"]["namespace"].startswith("raglab-"))]
        print(" ".join(bad)); sys.exit(1 if bad else 0)'
      changed_when: false
    - name: How to read the Argo admin password (command only, never the value)
      ansible.builtin.debug:
        msg: "kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d | pbcopy"
```
Run: `ansible-playbook playbooks/03-handover.yml`
Expected: both checks `ok` (the first may retry while hooks run).

- [ ] **Step 5: Commit bootstrap files**

```bash
scripts/safety-check.sh
git checkout -b feat/bootstrap && git add lab/bootstrap/ansible.cfg lab/bootstrap/inventory.example.ini lab/bootstrap/playbooks
git commit -m "feat(lab): layered bootstrap (k3s pinned + secrets encryption, Argo CD, handover checks)" && git push -u origin feat/bootstrap && gh pr create --fill
```

---

### Task 10: Promotion branches + PR evidence template **[OWNER for branch protection]**

**Files:**
- Create: `.github/pull_request_template.md`

- [ ] **Step 1: Create env branches from main**

```bash
git fetch origin && git push origin origin/main:refs/heads/env/qa origin/main:refs/heads/env/prod
```

- [ ] **Step 2: [OWNER] Protect them like main**

```bash
for b in env/qa env/prod; do
gh api -X PUT "repos/OC15141355/rag-stack-lab/branches/$b/protection" --input - <<'JSON'
{"required_status_checks":{"strict":true,"contexts":["gates"]},"enforce_admins":false,
 "required_pull_request_reviews":{"required_approving_review_count":0},
 "restrictions":null,"allow_force_pushes":false,"allow_deletions":false}
JSON
done
```

- [ ] **Step 3: PR template**

`.github/pull_request_template.md`:
```markdown
## What changes
<!-- one paragraph -->

## Promotion evidence (only for PRs into env/qa or env/prod)
- Source branch SHA being promoted: `<sha>`
- Smoke report from the **previous** env for that exact SHA (redacted: no IPs/hostnames):
  ```
  <paste: kubectl -n raglab-<env> logs job/smoke | tail -40>   # must show revision=<sha> and 0 failed
  ```
- [ ] Revision in the report equals the SHA above
- [ ] Report shows auth-negative PASS and limit-429 PASS
- [ ] I understand this gate is **attested, not enforced**; prod smoke detects, it doesn't prevent

## Secrets
- [ ] No plaintext keys, IPs or tailnet names added (hook + CI green)
```
Commit via PR as before.

---

### Task 11: Bring-up acceptance (spec criteria 1–6) + runbook (criterion 7)

**Files:**
- Create: `lab/README.md`

- [ ] **Step 1: Criterion 1** — run Task 9 Steps 2–4 on a fresh VM. Expected: handover checks pass.

- [ ] **Step 2: Criterion 2** — in each env: `KUBECONFIG=lab/bootstrap/kubeconfig kubectl -n raglab-<env> logs job/smoke | tail -20`. Expected: `0 failed`, lines `[PASS] auth-negative` and `[PASS] limit-429`, `revision=<sha>`. If chat returns 404 from upstream, change `upstream.base_url` in the catalogue to `https://integrate.api.nvidia.com/v1`, regenerate and PR. If `chat/glm` isn't routed, set the provider as default in Bifrost per its docs, then re-test. Record the outcome in the README.

- [ ] **Step 3: Criterion 3 (promotion)** — PR on `main`: change `environments.dev.requests_per_minute` 30 → 28; merge; dev Bifrost pod restarts (new ReplicaSet). Then PR `main → env/qa` with the dev smoke evidence; merge; then `env/qa → env/prod` with QA evidence. Expected: each env's generated ConfigMap hash changes, a new pod, smoke passes with the new SHA.

- [ ] **Step 4: Criterion 4 (prune protection)** — PR removing `prune-canary.yaml` **and** `pvc.yaml` from `lab/envs/base` (and from `resources:`). After dev sync: `kubectl -n raglab-dev get cm prune-canary` → NotFound; `kubectl -n raglab-dev get pvc bifrost-data` → still Bound. Revert the PR afterwards. `kubectl -n raglab-dev get nimservice` shows both, and Argo shows them Healthy "scaled to zero (Phase A)".

- [ ] **Step 5: Criterion 5 (host impact)** — during a 2-hour session, every 15 min: `ssh hv-01 'cat /proc/pressure/io /proc/pressure/memory'` and on k8s-ctrl `top -bn1 | grep '%Cpu' | awk '{print $16" st"}'`; before and after: `ssh k8s-ctrl 'sudo /var/lib/rancher/rke2/bin/etcdctl --cacert /var/lib/rancher/rke2/server/tls/etcd/server-ca.crt --cert /var/lib/rancher/rke2/server/tls/etcd/server-client.crt --key /var/lib/rancher/rke2/server/tls/etcd/server-client.key endpoint health'`. Expected: IO PSI `some avg60` < 10, steal < 10%, etcd `is healthy` before and after; `kubectl get events -A | grep -c -E 'OOMKill|Evict'` = 0 in the lab.

- [ ] **Step 6: Criterion 6 (gates)** — repeat Task 1 Step 7. Also push a branch with the fake key **with `--no-verify`** and confirm GitHub push protection rejects it. Expected: the push is rejected, naming a secret.

- [ ] **Step 7: Write `lab/README.md` (criterion 7)** with sections, each a numbered command list taken from the tasks above:
  - **Session start**: precheck (Task 8 Step 1), `qm start`, `argocd app get` + hard refresh + sync each env.
  - **Session stop**: `qm shutdown`.
  - **Bootstrap from scratch**: Tasks 8–9.
  - **Promotion**: Task 11 Step 3 + the PR template.
  - **NVIDIA key rotation**: new key → `sops edit` → PR → merge → secrets app syncs → `kubectl -n raglab-<env> rollout restart deploy/bifrost` → smoke PASS → revoke the old key at NVIDIA → negative probe `python3 lab/smoke/smoke.py ... --header-env x-bf-vk=OLD_VK` expecting failure.
  - **Age-key rotation (two-phase)** and **leak response** (revoke first).
  - **Stop rule** (spec): IO PSI > 10, steal > 10%, any etcd alarm → `qm shutdown`.
  - **Teardown checklist**: copied verbatim from the spec, with revoke-NVIDIA-key mandatory.

- [ ] **Step 8: Rebuild test** — the owner destroys the VM and rebuilds using only `lab/README.md`. Note any missing step in the README via PR.

---

## Self-review (done)

- **Spec coverage:**
  - gates (T1–2), secrets (T3), catalogue/schema (T4), smoke incl. limit/auth body/backoff (T5)
  - manifests + scaled-to-zero NIM + prune canary (T6)
  - bounded Argo, fail-closed CMP, Lua, SkipDryRun/retry (T7)
  - VM storage/CPU/IO (T8), bootstrap with no_log/SSA/secrets-encryption (T9)
  - env branches + attested evidence (T10), criteria 1–7 (T11)
  - Phase B not in scope.
- **Placeholders:**
  - `.sops.yaml` recipient is the owner's public key from T3 Step 1 (a value only the owner holds).
  - The python image digest is resolved by an exact command in T6 Step 4.
  - The LAN IP is filled into the gitignored inventory.
  - All three are runtime values with exact commands, not unspecified design.
- **Naming:** `bifrost-env` keys, `bifrost-config` ConfigMap (`config.json`, `models.json`), `smoke-script`, `raglab/revision`, and namespaces are consistent across T3–T11.
