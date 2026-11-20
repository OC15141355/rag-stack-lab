# Fill-in sheet: return this tomorrow

How to use: for each item, run the command (or look), then either answer the one-liner or paste the
output under it. "?" is a fine answer. Redact hostnames, IPs, tokens and secrets before pasting back
(replace with `<host>`, `<redacted>`). Never paste `.env` contents or keys.

Run the repo commands from the **deployment repo** root.

---

## A. Deployment repo

**A1. What objects make up each model?**
```sh
grep -rn -E '^kind:' --include='*.y*ml' . | sort | uniq -c | sort -rn | head -20
```
```
<paste>
```

**A2. Replicas per model**
```sh
grep -rn -E 'replicas:' --include='*.y*ml' .
```
```
<paste>
```

**A3. Images and tags (per env)**
```sh
grep -rn -E 'image:' --include='*.y*ml' .
```
```
<paste>
```

**A4. GPUs per model**
```sh
grep -rn -E 'nvidia.com/gpu' --include='*.y*ml' .
```
```
<paste>
```

**A5. NIM env vars (served name, profile, context, tools)**
```sh
grep -rn -E 'NIM_[A-Z_]+' --include='*.y*ml' . | sort -u
```
```
<paste>
```

**A6. Weights PVC (size, storage class, access mode)**
```sh
grep -rn -B2 -A12 -E 'kind: PersistentVolumeClaim' --include='*.y*ml' .
```
```
<paste>
```

**A7. Helper pod: what it runs, where weights come from**
```sh
grep -rln -iE 'helper|download|rsync|aws s3|cp -r|huggingface|ngc ' . | grep -v '^./.git'
```
File(s): `<path>`. Its `command:`/`args:`:
```
<paste>
```
How long does it take / who runs it? → `<answer>`

**A8. Speech model(s)**
```sh
grep -rn -iE 'whisper|riva|parakeet|tts|asr|audio' --include='*.y*ml' .
```
```
<paste>
```
ASR only, TTS only, or both? → `<answer>`
Image is `nvcr.io/nim/...` (NVIDIA speech NIM) or something else (community Whisper, e.g. faster-whisper / openai-whisper)? → `<answer>`
Ports it exposes (9000 HTTP / 50051 gRPC / other)? → `<answer>`

**A9. How environments are separated**
```sh
ls; git branch -a | head -20
```
```
<paste>
```
Folders per env / branches per env / other → `<answer>`

**A10. How it gets applied**
```sh
ls -a; sed -n 1,60p .gitlab-ci.yml 2>/dev/null
grep -rn -iE 'ansible|kubectl apply|helm|argocd' . | grep -v '^./.git' | head -20
```
```
<paste>
```
Ansible / CI / Argo / manual → `<answer>`

**A11. Who changes PROD's image**
```sh
git log --format='%h %ad %an %s' --date=short -15 -- $(grep -rl -E 'image:' --include='*.y*ml' . | grep -i prod)
```
```
<paste (names can be replaced with roles)>
```

**A12. Probes and Service names (by eye)**
- Model A Service name:port → `<answer>`  startupProbe timeout → `<answer>`
- Model B Service name:port → `<answer>`  startupProbe timeout → `<answer>`
- Speech Service name:port → `<answer>`

---

## A+. New (from the operators folder and install notes)

**A13. Are LLM services NIMService CRs or plain Deployments?**
```sh
grep -rln -E 'kind: (NIMService|NIMCache)' . | grep -v '^./.git'
grep -rln -E 'kind: Deployment' . | xargs grep -l -i -E 'nim|nvcr' 2>/dev/null
```
```
<paste>
```

**A14. Which NeMo microservices are deployed / configured?**
```sh
ls <operators>/nemo-deployment-management <operators>/nemo-deployment-management/charts 2>/dev/null
grep -rn -iE 'entity-?store|data-?store|nim-?proxy|deployment-?management|customizer|evaluator|guardrail' --include='*.y*ml' . | cut -c1-160 | head -30
```
```
<paste>
```
Does anything call Deployment Management / NIM Proxy / Entity Store today? → `<answer>`

**A15. Operator versions and source of truth**
```sh
grep -rn -E 'version:|appVersion:|image:.*(k8s-nim-operator|gpu-operator)' <operators>/k8s-nim-operator <operators>/gpu-operator-v25.10.0 2>/dev/null | head
git branch -a | head -20; git log --oneline -5 --all -- <operators>
```
```
<paste>
```
Which branch is "real" for DEV / QA / PROD? → `<answer>`

**A16. Cache pre-populator**
```sh
ls <path>/cache-prepopulator; sed -n 1,80p <path>/cache-prepopulator/*.yaml
```
```
<paste>
```

## B. Cluster (only if you have read access)

```sh
kubectl config current-context
kubectl get pods -A | grep -iE 'gpu-operator|nvidia' | head        # B1 GPU Operator present?
kubectl get nodes -L nvidia.com/gpu.product,nvidia.com/gpu.count   # B2 GPUs per node
kubectl get pvc -A | grep -iE 'model|weight|nim|cache'             # B3 weights PVCs
kubectl get crd | grep -iE 'nvidia|nim|nemo'                       # B4 any NVIDIA CRDs already?
kubectl auth can-i create customresourcedefinitions                # B5 can we install CRDs? (probably no)
```
```
<paste>
```
Which env was this? → `DEV / QA / PROD`

---

## C. Auth (from yesterday's 404)

```sh
# in the Traefik IngressRoute for the portal / inference service:
grep -rn -iE 'middlewares|forwardAuth|authResponseHeaders|stripPrefix' --include='*.y*ml' <ingress repo or dir>
```
```
<paste>
```
Decoded token claims (`echo "$TOKEN" | cut -d. -f2 | base64 -d`): is `iss` the Keycloak URL? `exp`?
→ `<answer, no token itself>`

---

## D. One-liners from people (ask if you get the chance)

| # | Question | Answer |
|---|---|---|
| D1 | What problem is the move to the NVIDIA operator approach meant to solve? | |
| D2 | Where did "NVIDIA-recommended NeMo microservices operator" come from, and when? | |
| D3 | Is anyone aware NeMo Microservices was sunset (1 Oct 2026)? | |
| D4 | Is the DEV/QA RC tag ever re-pushed with the same name? | |
| D5 | Is the speech model in scope for this ticket? | |
| D6 | Is there an NVIDIA account team / support contact? | |
| D7 | Do DEV GPUs match QA/PROD? | |
| D8 | Who would approve installing a cluster-wide operator? | |
| D9 | Does anything need user/session storage (the "entity store" ticket)? Where does it live today? | |

---

## E. Anything else you noticed
-
