# NVIDIA developer access and GPU options (as of 2026-11)

Research date: 2026-11-24. Statuses are one of: current / renamed / deprecated / sunset / unclear. Anything I could not confirm against an official page is marked `UNVERIFIED:`. Several NVIDIA doc pages returned 404 or gave only link stubs to my fetch tooling, so the UNVERIFIED list is longer than I would like; re-check those items in a browser before spending money.

## Summary

- Joining the NVIDIA Developer Program gives free hosted NIM API access for prototyping (build.nvidia.com) and the right to pull and self-host NIM containers for development and testing. Production use needs NVIDIA AI Enterprise (current; developer.nvidia.com/nim, checked 2026-11-24).
- The hosted API is OpenAI-compatible at `https://integrate.api.nvidia.com/v1`; `GET /v1/models` answers without auth (HTTP 200, 2026-11-24) and returned only 32 models. Keys start `nvapi-` (UNVERIFIED: not stated on the pages I could read; matches long-standing behaviour).
- Neither GLM 5.2 nor Nemotron 3 Super 120B appears in that hosted list. The hosted catalog has `z-ai/glm-5.3-flash` and `nvidia/nemotron-3.5-super-vl-120b-a12b` (early access) instead. Both named models are self-hostable NIMs on the support matrix, but they are multi-GPU (Nemotron 3 Super needs 8x H100 80GB per its model card).
- Rate limits are not officially published on the pages I could read. Forum users report a default of 40 requests per minute and a starting balance of about 1,000 credits (community reports, not official; `UNVERIFIED:`). The NIM FAQ says limits vary per model and are shown in your account.
- NeMo Microservices are sunset as of 2026-10-01 (docs banner), and NIM Operator manages their CRDs only as deprecated since v3.1.3. A NIM Operator lab should use only NIMService, NIMCache and related NIM CRs, not NeMo CRs.
- NIM Operator is at v3.1.4 (2026-11-18). 3.x is supported, 2.x deprecated, 1.x end of support. It requires GPU Operator 24.3.0 or newer; the current GPU Operator is v26.7.3 (2026-11-17).
- The NIM for LLMs documentation now describes a "model-free" vLLM NIM next to per-model NIMs. Version 2.1.6 is the documented default, while the operator docs also mention NIM for LLMs 3.0 with a sidecar. These generations need to be checked before pinning an image tag.
- The RAG Blueprint repo is archived (API-confirmed `archived: true`), and nv-ingest now lives as `NVIDIA/NeMo-Retriever` (renamed).
- For Phase B you need a full GPU VM, not a container, because the GPU Operator needs host-level access. Brev is a VM product with Launchables and is current; DGX Cloud Lepton is a marketplace product still shown as current. No official hourly price was found for either.
- Cheapest sensible plan: Phase A at zero cost on hosted endpoints; Phase B about 3 to 6 hours on one 24 to 48 GB GPU, roughly USD 3 to 10 total (third-party price snapshots, see section 4).

## The plain version

NVIDIA lets anyone with a free Developer Program account do two things with its "NIM" model-serving packages. First, call models NVIDIA hosts, using an OpenAI-style API with a key that starts `nvapi-`. It is meant for prototyping and is rate limited. Second, download the NIM containers from NVIDIA's registry and run them on your own GPU for development and testing. If you want to run it for real, you pay for NVIDIA AI Enterprise.

For the lab, this splits cleanly. Phase A needs no GPU: the gateway, the GitOps layout and the DEV/QA/PROD promotion can all point at hosted endpoints, so you can build and test the whole delivery pipeline for nothing. Phase B proves that the NIM Operator custom resources actually work. That needs a real NVIDIA GPU, so you rent a virtual machine with one GPU for a few hours, install a small Kubernetes, the GPU Operator and the NIM Operator, and apply a small model.

The two big models you may have in mind are not on the hosted API under those names and need many GPUs to self-host, so use stand-ins. A lot of NVIDIA's own naming changed this year, so check the table in section 6 before copying older tutorials.

## 1. NVIDIA Developer Program today

| Item | What you get | Status | Source (date checked) |
|---|---|---|---|
| Hosted NIM APIs | Free access to NIM API endpoints "for unlimited prototyping, powered by DGX Cloud" | current | developer.nvidia.com/nim (2026-11-24) |
| Self-hosting | "Deploy on your own infrastructure for development and testing" | current | developer.nvidia.com/nim (2026-11-24) |
| Production | Requires NVIDIA AI Enterprise or a partner's enterprise endpoints | current | developer.nvidia.com/nim (2026-11-24) |
| NIM Operator prerequisite | "AI Enterprise subscription or Developer Program membership" for NIM containers and models | current | docs.nvidia.com/nim-operator/latest/install.html (2026-11-24) |

Details:

- **Hosted API.** Base URL `https://integrate.api.nvidia.com/v1`. I confirmed it answers `GET /v1/models` with HTTP 200 on 2026-11-24 (the list is public; chat calls need a key). It is OpenAI-compatible, so any OpenAI client works with `base_url` and `api_key`. Key format `nvapi-...`: `UNVERIFIED:` on official pages (the quickstart page I fetched says only "Get API Key" and a placeholder).
- **Credits and rate limits.** The official FAQ text I could reach says rates vary per model and by concurrency and that you should check your account on build.nvidia.com. Forum threads (2026) repeatedly mention 40 RPM and a 1,000-credit starting balance, with users asking for 200 RPM and 5,000 credits. A moderator thread states increases are not granted via the forum. `UNVERIFIED:` all numbers are community reports. A forum reply also says free access is for study and development, with production excluded; consistent with the product page, but I did not see the licence text.
- **GPU count limit for self-hosting.** Older Developer Program wording capped self-hosted dev/test at a small number of GPUs (I remember 16). `UNVERIFIED:` I could not reach the licence or FAQ pages (both 404 on the URLs I tried), so treat it as unknown. A single-GPU lab is far below any plausible cap.
- **NGC access.** Pulling from `nvcr.io` uses an NGC personal API key with username `$oauthtoken`; the NIM Operator docs use the same pattern for a pull secret (docs.nvidia.com/nim-operator/latest/install.html, 2026-11-24). The NGC release notes page I tried returned 404, so recent NGC CLI changes are `UNVERIFIED:`.
- **Recent changes.** The product page now cites DGX Cloud as the hosting base for the API catalog, and the catalog is branded build.nvidia.com. Programme wording around credits is not published on the pages I could read.

## 2. Hosted endpoints for the models in scope

| Model | Hosted API (anonymous `/v1/models`, 2026-11-24) | Self-hostable NIM | Status |
|---|---|---|---|
| GLM 5.2 (zai-org) | not listed; `z-ai/glm-5.3-flash` is listed | yes, "GLM-5.2" on NIM LLM support matrix | GLM 5.2 hosted: unclear; successor-named 5.3 Flash hosted: current |
| Nemotron 3 Super 120B A12B | not listed; `nvidia/nemotron-3.5-super-vl-120b-a12b` is listed (early access) | yes, "Nemotron 3 Super 120B-A12B" on support matrix | hosted: unclear; self-host: current |

Notes:

- The anonymous list returned only 32 entries, which is probably not the full catalog (it may be filtered or pared back). `UNVERIFIED:` whether GLM 5.2 or Nemotron 3 Super is callable with a key. Test with an authenticated `curl .../v1/models` once you have a key, and ask the model-specific page on build.nvidia.com. The model card for Nemotron 3 Super (released 2026-03-11) names `nvidia/nemotron-3-super` only as a locally served name and does not list a hosted endpoint.
- **Cheap stand-ins confirmed in the hosted list:** `nvidia/nemotron-3.5-bolt-e4b` (compact text model for reasoning, tool calling, agentic chat), `nvidia/nemotron-3.5-lightning-30b-a3b`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`, `google/gemma-4-31b-it`, `google/gemma-3-4b-it`, `z-ai/glm-5.3-flash`. For embeddings (useful for the RAG side): `nvidia/nemotron-3.5-embed-1b`, `nvidia/nemotron-3.5-embed-8b`, `nvidia/llama-3.2-nv-embedqa-1b-v1`.
- **Streaming, tool calling, `/v1/models`.** `/v1/models` is confirmed. The fetched catalog describes tool calling for `glm-5-3-flash` and `nemotron-3.5-bolt-e4b`. Streaming is supported on the OpenAI-compatible endpoint in my experience, but `UNVERIFIED:` on an official page I could read; send `stream: true` in a smoke test.
- **Rate limits.** See section 1: about 40 RPM reported, not official.

## 3. Self-hostable small NIMs for a single GPU (Phase B)

Source: NIM for LLMs support matrix, docs.nvidia.com/nim/large-language-models/latest/supported-models.html (2026-11-24; I read the first ~100k of ~172k characters).

| NIM | Catalog path | Profiles seen | Fits | Free dev account can pull? |
|---|---|---|---|---|
| Llama 3.1 8B Instruct | catalog.ngc.nvidia.com/orgs/nim/teams/meta/containers/llama-3.1-8b-instruct | BF16, FP8, NVFP4, each with/without LoRA, TP1 | 24 GB for FP8/BF16 8B is plausible (about 16 GB weights BF16) | yes under Developer Program terms (see section 1); `UNVERIFIED:` per-image entitlement |
| Nemotron 3 Nano (`nvidia/nemotron-3-nano`) | catalog.ngc.nvidia.com/orgs/nim/teams/nvidia/containers/nemotron-3-nano | BF16 TP1-8, FP8 TP1-8, NVFP4 TP1-8 | `UNVERIFIED:` parameter count; the Nano family is a roughly 30B-A3B MoE, so FP8 on a 48 GB card is the likely fit, BF16 on 24 GB is not | same |
| Nemotron 3.5 Bolt E4B | listed on the support matrix as a VLM-section entry | BF16 TP1, tested on GB10, RTX PRO 6000/4500 Blackwell, H100 80GB | small (4B-class); no L40S/L4 profile seen | same |

- **Image path.** Pattern is `nvcr.io/nim/<team>/<name>:<tag>`, for example `nvcr.io/nim/meta/llama-3.1-8b-instruct:<tag>`. The support page does not list tags (the page said so), so `UNVERIFIED:` the exact tag; read it from the catalog page at pull time. The only full image path I saw is for the model-free image: `nvcr.io/nim/nvidia/vllm-model-free-nim:2.1.6`.
- **Profiles.** Names are engine-prefixed (`vllm-fp8-tp1-pp1`, `vllm-...-lora`) and each optimised profile also has a 64-character ID. Run `list-model-profiles` in the container to see what matches your GPU.
- **Minimum compute capability.** The page states no single global minimum. Per-profile guidance: BF16/W4A16 from Ampere (SM 8.0), some profiles on Ada (SM 8.9, e.g. L40S), Hopper (SM 9.0) without native NVFP4, and NVFP4 generic profiles need Blackwell (SM 10.0+). So choose BF16 or FP8 for L4/L40S/A100. `UNVERIFIED:` whether every model has a profile for Ada and L4; FP8 on Ada works in principle but the "optimised" profiles listed were B200, H200 and A100-80GB. Expect a fallback or generic profile and check `list-model-profiles` first.
- **Which to choose.** Llama 3.1 8B Instruct is the least risky: small, TP1, long-standing, and widely used for demos. Nemotron 3 Nano is the more "current NVIDIA" pick if the card has 48 GB.

## 4. Renting a GPU

Prices are indicative snapshots from third-party pages dated May to November 2026 and are not directly comparable; confirm in each console before launching.

| Provider | Status | GPUs | Price indication | VM or container | Launchables |
|---|---|---|---|---|---|
| NVIDIA Brev (brev.nvidia.com; docs.nvidia.com/brev) | current (docs live 2026-11-24; no sunset notice found) | not listed in the docs I read; multi-cloud instances | `UNVERIFIED:` no official hourly price found; a SourceForge listing shows USD 3.01/h with no GPU named | VM (docs: preconfigured VMs with CUDA, Docker, Jupyter) | yes, one-click shareable environments (nvidia.com/en-us/launchables) |
| NVIDIA DGX Cloud Lepton | current as a marketplace/orchestration product (nvidia.com page, copyright 2026); Tom's Hardware (2026) reports DGX Cloud itself being de-emphasised in favour of Lepton. A "Legacy Lepton Access" mention surfaced in one search summary but not on the page I fetched, so `UNVERIFIED:` | partner-supplied | `UNVERIFIED:` | dev pods, endpoints and batch jobs per its docs; VM suitability for GPU Operator `UNVERIFIED:` | no |
| RunPod | current | L40S, A100, H100 and others | H100 PCIe USD 2.89/h secure, 1.99/h community; A100 PCIe 2.09/h secure, 1.19/h community; L40S about 0.79/h in one comparison (third-party, 2026-09 to 2026-11) | Mainly containers (pods); Kubernetes in a pod is awkward; `UNVERIFIED:` whether bare-metal VM SKUs fit | no (templates) |
| Lambda | current | A100, H100 | H100 SXM about 3.99/h; A100 80GB 1.29 to 2.79/h across sources (third-party, 2026) | full VM | no |
| Hyperscaler VM (AWS g6e L40S, GCP g2 L4, Azure NC) | current | L4, L40S, A100, H100 | L40S median across 35 providers about USD 1.57/h on-demand (getdeploying, 2026-11) | full VM | no |

Recommendation: use a full VM. The GPU Operator installs drivers and patches the container runtime on the host, which does not work inside a locked-down container. Brev (VM, Launchables) or a hyperscaler/Lambda VM are the safe choices. Expect an L40S or L4-class VM at roughly USD 1 to 2 per hour, so a 3 to 6 hour session costs about USD 3 to 12.

## 5. Phase B stack on a rented GPU VM

1. **Kubernetes.** A single-node distribution: k3s, RKE2 or microk8s. The NIM Operator platform page does not name distributions and defers to the GPU Operator docs (2026-11-24). Use RKE2 if you want parity with a homelab RKE2 estate; use k3s for the fastest install.
2. **GPU Operator, current v26.7.3 (published 2026-11-17).**
   ```
   helm install --wait gpu-operator -n gpu-operator --create-namespace \
     oci://nvcr.io/nvidia/cloud-native-charts/gpu-operator --version=v26.7.3
   ```
   Classic repo alternative: `helm repo add nvidia https://helm.ngc.nvidia.com/nvidia`, then `nvidia/gpu-operator --version=v26.7.3` (docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/getting-started.html, 2026-11-24). If the VM image already has a driver, set `driver.enabled=false` (`UNVERIFIED:` against the 26.7.3 values reference).
3. **containerd paths (the k3s and RKE2 gotcha).** Defaults assume `/etc/containerd/config.toml` and `/run/containerd/containerd.sock`, with a drop-in at `/etc/containerd/conf.d/99-nvidia.toml`. k3s and RKE2 keep their containerd config elsewhere (typically a generated `config.toml` under `/var/lib/rancher/k3s/agent/etc/containerd/` and a socket at `/run/k3s/containerd/containerd.sock`), so set `toolkit.env` for `CONTAINERD_CONFIG` and `CONTAINERD_SOCKET`. The doc page I fetched gives explicit values for MicroK8s only and says nothing for k3s; RKE2 is deferred to RKE2 docs. `UNVERIFIED:` exact k3s and RKE2 values for 26.7.x; take them from the GPU Operator "Platform notes" page. MicroK8s values (docs): config `/var/snap/microk8s/current/args/containerd-template.toml`, socket `/var/snap/microk8s/common/run/containerd.sock`.
4. **NIM Operator, current v3.1.4 (2026-11-18).** The install page still shows `--version=3.1.2`; use the latest instead.
   ```
   helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && helm repo update
   kubectl create namespace nim-operator
   helm upgrade --install nim-operator nvidia/k8s-nim-operator -n nim-operator --version=3.1.4
   ```
   Requires GPU Operator 24.3.0 or newer. Validation webhooks need cert-manager (v3.0.2 notes). You still need image-pull and API-key secrets for NGC; the exact secret names and `NIMCache`/`NIMService` fields come from the "Caching Models" and "NIM Services" pages, which I did not read (`UNVERIFIED:`).
5. **Argo CD registration over Tailscale.** `UNVERIFIED:` NVIDIA documents none of this; it is standard Argo CD. Install Tailscale on the VM, give the Kubernetes API a tailnet-reachable address (k3s `--tls-san <tailscale-ip-or-name>`), create a ServiceAccount with a long-lived token on the remote cluster, then `argocd cluster add` or a declarative cluster Secret with `server: https://<tailscale-name>:6443`. Use a tailnet ACL so only the Argo CD host can reach port 6443, and tag the VM as ephemeral so it vanishes from the tailnet when destroyed. Do not expose the API on a public IP.
6. **Known gotcha for any VM.** The NIM pulls model weights on first start, so size the disk for tens of GB and use a `NIMCache` PVC so a pod restart does not re-download.

## 6. Deprecations and renames to watch

| Item | Status | Replacement | Source / date |
|---|---|---|---|
| NeMo Microservices | sunset 2026-10-01 | NeMo Platform | docs.nvidia.com/nemo/microservices banner (2026-11-24) |
| NIM Operator NeMo CRDs and deployments | deprecated in v3.1.3 (2026-10-28; v3.1.1 notes pre-announced it) | NeMo Platform docs | docs.nvidia.com/nim-operator release notes (2026-11-24) |
| NIM Operator 2.x / 1.x | 2.x deprecated, 1.x end of support | 3.x | nim-operator platform-support (2026-11-24) |
| NIM Proxy | unclear | none found; no 3.x deprecation entry. Older note deprecates the NIMCache `spec.certConfig` in favour of `spec.proxy` (a different "proxy") | nim-operator release notes (2026-11-24). `UNVERIFIED:` NIM Proxy product status |
| NeMo Deployment Management | unclear, folded into NeMo Microservices deprecation | NeMo Platform | `UNVERIFIED:` named page not read |
| RAG Blueprint (`NVIDIA-AI-Blueprints/rag`) | deprecated/archived (GitHub API `archived: true`; archive date 2026-11-05 per your brief; last push 2026-11-23 on the metadata) | `UNVERIFIED:` replacement not identified | GitHub API (2026-11-24) |
| nv-ingest | renamed | `NVIDIA/NeMo-Retriever` ("NeMo Retriever Library") | GitHub API (2026-11-24) |
| API Catalog naming | renamed in practice | "build.nvidia.com" / NIM API; docs at docs.api.nvidia.com | developer.nvidia.com/nim (2026-11-24) |
| NGC CLI changes | unclear | n/a | NGC release-notes URL 404; `UNVERIFIED:` |
| NIM LLM container generations | current but split | per-model NIMs (e.g. `llama-3.1-8b-instruct`) plus model-free vLLM NIM (`vllm-model-free-nim:2.1.6`); docs say 2.1.6 is latest, operator docs mention NIM for LLMs 3.0 with an extra sidecar container | NIM LLM docs and operator platform-support (2026-11-24); `UNVERIFIED:` how 3.0 relates to 2.1.6 |
| Brev | current (VM product, Launchables) | n/a | docs.nvidia.com/brev (2026-11-24) |
| DGX Cloud Lepton | current but positioning shifting; "legacy" wording `UNVERIFIED:` | n/a | nvidia.com/dgx-cloud-lepton page (2026-11-24), Tom's Hardware (2026) |
| AI Workbench | unclear | n/a | docs index returned nothing useful; `UNVERIFIED:` |
| DRA driver | version note | NIM Operator 3.1.0 supports NVIDIA DRA Driver 25.12.0, `resource.k8s.io/v1` only (v1beta2 dropped) | release notes (2026-11-24) |
| Model names | renamed/versioned | Nemotron 3.5 family (Bolt, Lightning, Super VL); older Llama NIMs on matrix | support matrix (2026-11-24) |

## Recommendation for a homelab GitOps lab

**Phase A (cost: USD 0, a few hours of setup).**
- Gateway to hosted endpoints at `https://integrate.api.nvidia.com/v1`, key in a SOPS-encrypted secret, never in git.
- Stand-in models: `nvidia/nemotron-3.5-bolt-e4b` as the cheap default, `z-ai/glm-5.3-flash` for the GLM-like tier, `nvidia/nemotron-3.5-lightning-30b-a3b` for the larger tier. Keep the model name a per-environment value so DEV, QA and PROD can differ (for example, DEV on Bolt, QA and PROD on Lightning).
- Respect the roughly 40 RPM reported limit with client-side backoff; do not run load tests against the free tier.
- Write the NIMService and NIMCache manifests now, as templates in Git, even though nothing applies them yet.

**Phase B (cost: about USD 3 to 12 in compute, plus egress).**
- Rent one VM with a 24 to 48 GB GPU (L40S 48 GB preferred, L4 24 GB is the minimum for an 8B model at FP8). Provider order: Brev (Launchable VM) or a hyperscaler/Lambda VM; budget USD 1 to 2/hour for 3 to 6 hours.
- Stack: k3s or RKE2, then GPU Operator v26.7.3, then NIM Operator v3.1.4 (check for newer on the day), then a `NIMCache` and `NIMService` for `meta/llama-3.1-8b-instruct`. Join the VM to Tailscale, register it in Argo CD, and let Argo CD sync the apps; destroy the VM at the end.
- Download time dominates: have the NGC key ready and budget 20 to 40 minutes for first pull and model download.
- Set a billing alarm and a reminder to destroy the VM; idle GPU hours are the main way this exercise overspends.

## References

- https://developer.nvidia.com/nim (2026-11-24): Developer Program benefits for NIM.
- https://docs.api.nvidia.com/nim/docs/api-quickstart (2026-11-24): API quickstart.
- https://integrate.api.nvidia.com/v1/models (2026-11-24): live hosted model list, HTTP 200.
- https://forums.developer.nvidia.com/t/nvidia-nim-faq/300317 (reached via search 2026-11-24; direct fetch 403).
- https://forums.developer.nvidia.com/t/is-nim-free/369368 and rate-limit request threads (2026): community reports of 40 RPM and 1,000 credits.
- https://build.nvidia.com/models (2026-11-24): catalog.
- https://docs.nvidia.com/nim/large-language-models/latest/supported-models.html (2026-11-24): support matrix, NIM LLM 2.1.6.
- https://docs.nvidia.com/nim-operator/latest/release-notes.html, /install.html, /platform-support.html (2026-11-24).
- https://api.github.com/repos/NVIDIA/k8s-nim-operator/releases (2026-11-24): v3.1.4 on 2026-11-18, v3.1.3 on 2026-10-28.
- https://api.github.com/repos/NVIDIA/gpu-operator/releases/latest (2026-11-24): v26.7.3 on 2026-11-17.
- https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/getting-started.html (2026-11-24).
- https://docs.nvidia.com/nemo/microservices/latest/index.html (2026-11-24): sunset banner, 2026-10-01.
- https://docs.nvidia.com/brev/latest/ (2026-11-24); https://www.nvidia.com/en-us/launchables/pricing (2026).
- https://www.nvidia.com/en-us/data-center/dgx-cloud-lepton/ (2026-11-24); https://www.tomshardware.com/tech-industry/nvidia-steps-back-from-dgx-cloud (2026).
- GitHub API for `NVIDIA-AI-Blueprints/rag` (archived) and `NVIDIA/NeMo-Retriever` (2026-11-24).
- RunPod, Lambda and aggregator price snapshots (getdeploying.com, spheron.network, runpod.io/pricing; 2026-05 to 2026-11), indicative only.
