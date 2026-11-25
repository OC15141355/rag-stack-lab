# Phase B fact-check (2026-11-25)

Checked 2026-11-25 against vendor docs and the `NVIDIA/k8s-nim-operator` repo (tag v3.1.4). Read-only; no sign-ups. Quotes are from fetched pages (some via a summarising fetcher, so wording is close, not guaranteed verbatim). Lambda pages moved from lambda.ai to lambda.com (301).

Verdicts: TRUE / FALSE / PARTLY / UNKNOWN (not resolvable without an account or a live page).

## 1. GPU providers

| claim | verdict | quote | URL / repo+tag |
|---|---|---|---|
| Lambda on-demand is a full VM | TRUE | "Linux-based, GPU-backed virtual machine instances" | https://docs.lambda.com/public-cloud/on-demand/ |
| Lambda gives root | UNKNOWN | Page does not state root/sudo. Only notes `sudo apt full-upgrade` errors on some 24.04 images, which implies sudo exists | same |
| Lambda per-minute billing (spec says "per-hour") | PARTLY (spec understates) | "bills in one-minute increments"; marketing page: "Pay by the minute" | https://docs.lambda.com/public-cloud/billing/ , https://lambda.com/service/gpu-cloud |
| Terminate stops billing | TRUE | Billing ends "the moment you terminate the instance" | billing page above |
| Stopped instances keep billing | UNKNOWN | Docs never describe a "stop" state for Lambda on-demand; instances are charged "as long as they're running". Spec's terminate-only plan is the safe reading | billing page above |
| Persistent filesystem cost | PARTLY | Billed "per GiB used per month, in increments of one hour"; the $0.20/GiB-month figure is "illustrative"; "The actual price will be displayed when you create your filesystem." Billing continues after instance deletion until the filesystem is deleted | https://docs.lambda.com/public-cloud/billing/ |
| Lambda Stack images include NVIDIA drivers | TRUE | "Lambda also preinstalls Lambda Stack ... drivers, tools, and frameworks"; includes NVIDIA driver, CUDA, cuDNN, NCCL. Default Ubuntu 22.04 | https://docs.lambda.com/public-cloud/on-demand/ |
| Lambda prices: A10 | TRUE | A10 (1x) $1.29/h (spec guessed 0.75-1.5) | https://lambda.com/service/gpu-cloud |
| Lambda prices: A100 / H100 | TRUE | A100 40GB $1.99/h (1x); A100 80GB HGX $3.19 (8x only listed); H100 PCIe $3.79; H100 SXM 1x $4.89 | same |
| Lambda has L4 / L40S | FALSE (not listed) | "The page does not list L4 or L40S pricing" (listed: A10, A6000 $1.09, RTX 6000 $0.69, V100, A100, GH200 $2.59, H100, B200) | same |
| Lambda "about 0.75 to 1.5/h" for 24 GB card | PARTLY | A10 $1.29 fits; A6000 (48 GB) $1.09 is also available and cheaper | same |
| Brev instance is a full VM | TRUE | "A GPU instance is a cloud virtual machine with one or more NVIDIA GPUs attached." Docker preinstalled | https://docs.nvidia.com/brev/latest/concepts/gpu-instances.md |
| Brev root access | UNKNOWN | Page only mentions SSH and default user `/home/ubuntu/workspace` | same |
| Brev billing / stop vs delete | TRUE (differs from Lambda) | "Brev bills you per hour for compute time." Stopped: "No compute charges, though minimal storage costs apply." Deleted: no charges. Stop releases the GPU; restart needs the same GPU type, so can fail on capacity | same |
| Brev hourly prices | UNKNOWN | "The page doesn't list actual prices" (per hour, by GPU type) | same |
| RunPod pods are containers (spec exclusion) | TRUE | "Runpod runs Docker for you, so you cannot spin up your own Docker instance"; templates are Docker images | https://docs.runpod.io/pods/overview |
| RunPod offers a true VM SKU | UNKNOWN (none found) | Pricing page mentions Pods, Serverless, Clusters ("Launch multi-GPU clusters in minutes"; up to 64 GPUs); no mention of VMs or bare metal | https://www.runpod.io/pricing |
| RunPod billing | PARTLY | Pods "billed by the second" (Secure L4 $0.69/h, L40S $1.09/h, A100 PCIe $2.09/h; Community cheaper). Not usable for GPU Operator regardless | https://docs.runpod.io/pods/overview , pricing page |

## 2. NIM `meta/llama-3.1-8b-instruct`

| claim | verdict | quote | URL / repo+tag |
|---|---|---|---|
| A 24 GB A10/L4 card is a viable target for this NIM | FALSE per the support matrix | Verified GPUs (2.1.6): A100 40/80, B200, B300, GB10, GB200, GB300, GH200, H100 80GB/NVL, H200, **L40S**, RTX PRO 4500/6000 Blackwell Server. "Neither A10G nor L4 appears in this model's verified GPU list" (L4 is not on the page at all) | https://docs.nvidia.com/nim/large-language-models/latest/supported-models.html |
| L40S has a profile | TRUE | `NVIDIA-L40S` verified. Profiles TP1: `vllm-bf16-tp1-pp1`, `vllm-fp8-tp1-pp1`, `vllm-nvfp4-tp1-pp1` (+ `-lora` variants) | same |
| Profile IDs are discoverable by name | PARTLY | Generic vLLM profiles have readable names (`vllm-bf16-tp1-pp1`); optimised profiles are hashes (B200 NVFP4, H200 FP8 only). No optimised hash for L40S listed | same |
| Current image tag | PARTLY | Docs say "2.1.6 (Latest)"; NGC catalog page lists highest numbered version 2.1.7, updated 2026-11-17. Pin the tag after `ngc registry image info`; do not use `latest` | https://docs.nvidia.com/nim/large-language-models/latest/release-notes.html , https://catalog.ngc.nvidia.com/orgs/nim/teams/meta/containers/llama-3.1-8b-instruct |
| Model-free image `vllm-model-free-nim:2.1.6` exists | PARTLY | Docs show tag shape `nvcr.io/nim/nvidia/vllm-model-free-nim:2.1.6-qwen3.8-2.4t` (model-specific variant); bare `:2.1.6` not confirmed | release notes URL above |
| "NIM LLM 3.0" exists / relationship to 2.1.6 | UNKNOWN | Docs mention no 3.0; 2.1.6 is "Latest (default)". Treat the spec's 3.0 worry as unsupported | release notes |
| Minimum VRAM / on-disk cache for the 8B | UNKNOWN | Support matrix gives neither (only other models' disk sizes, e.g. 133-360 GB for a large model). 8B BF16 weights approx 16 GB is arithmetic, not a vendor figure | supported-models URL |
| Free Developer Program account can pull it | UNKNOWN | NGC page: container is "NVIDIA AI Enterprise Supported"; terms listed are NVIDIA Software License, Product-Specific Terms for AI Products, Open Model Agreement, Llama 3.1 Community License. No page text on Developer Program entitlement. Needs a logged-in `docker pull` to prove | NGC URL above |

## 3. GPU Operator 26.7.x on k3s

| claim | verdict | quote | URL / repo+tag |
|---|---|---|---|
| 26.7.3 is current | TRUE | "The current patch release of this version of the NVIDIA GPU Operator is `v26.7.3`." | https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/getting-started.html |
| `driver.enabled=false` for pre-installed drivers | TRUE | "Set this value to `false` when using the Operator on systems with pre-installed drivers." | same |
| k3s values `CONTAINERD_CONFIG=/var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl`, `CONTAINERD_SOCKET=/run/k3s/containerd/containerd.sock` | UNKNOWN | Official page describes the env vars but has no k3s section ("page doesn't mention k3s"; the old Rancher page 404s). Socket path appears in SUSE RKE2 docs; `.tmpl` vs rendered `config.toml` unresolved | getting-started URL; https://documentation.suse.com/cloudnative/rke2/latest/en/add-ons/gpu_operators.html |
| 26.7 has a v26 equivalent that removes the need for those vars | TRUE (changes spec) | With the NRI plugin, "on platforms that configure containerd in a non-standard way, like k3s, k0s, and Rancher Kubernetes Engine 2" you no longer need `CONTAINERD_CONFIG`, `CONTAINERD_SOCKET`, `RUNTIME_CONFIG_SOURCE`. Requires CDI enabled and containerd v1.7.30 / v2.1.x / v2.2.x / v2.3.x; enable with `--set cdi.nriPluginEnabled=true` (appears opt-in) | https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/26.7/cdi.html |
| Operator creates RuntimeClass `nvidia` | PARTLY | Without NRI: yes (inferred; page only discusses CDI). With NRI: "the `nvidia` runtime class will not be created" (deleted if enabled later). So `runtimeClassName: nvidia` on NIM CRs and the `raglab-gpu-platform` whitelist entry for `RuntimeClass` depend on which mode is chosen | cdi.html above |
| Supported containerd on k3s | UNKNOWN | Platform-support table has a K3s column but versions were not extractable | https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html |

## 4. k3s over Tailscale

| claim | verdict | quote | URL / repo+tag |
|---|---|---|---|
| `--vpn-auth` Tailscale integration exists | TRUE, but experimental | Heading "Integration with the Tailscale VPN provider (experimental)"; "Available in v1.27.3, v1.26.6, v1.25.11 and newer." | https://docs.k3s.io/networking/distributed-multicloud |
| `--vpn-auth` is compatible with the spec's "no routes" rule (D6) | FALSE | Integration advertises the pod CIDR (default 10.42.0.0/16); "You must approve the routes, either through `autoApprovers` or in the admin console." Auth key "may be reusable"; example key tags nodes `testing-k3s`. Spec's manual `flannel-iface` choice is therefore the right one | same |
| `--flannel-iface` overrides flannel interface | TRUE | "Override default flannel interface." (agent option) | https://docs.k3s.io/networking/basic-network-options |
| MTU guidance in k3s docs | UNKNOWN | Neither the multicloud nor networking pages mention MTU. tailscale0 MTU (1280) and flannel overhead stay measure-on-node | both pages |
| `--node-external-ip` | PARTLY | Used in the multicloud setup with `--flannel-external-ip`; "Only applies when --node-external-ip is set on a node." Not needed for a node-ip = tailnet-IP design | both pages |
| UDP 8472 needed for flannel vxlan | TRUE | "The nodes need to be able to reach other nodes over UDP port 8472 when using the Flannel VXLAN backend." Also "should not be exposed to the world" | https://docs.k3s.io/installation/requirements |
| Agent token distinct from server token | TRUE | "By default, the agent token is the same as the server token"; "The agent token can be set before or after the cluster has been started"; option `--agent-token`, env `K3S_AGENT_TOKEN`; separate `agent-token` file | https://docs.k3s.io/cli/token |
| "Server token ... also permits joining servers" (spec) | TRUE | "The server token can be used to join both server and agent nodes to the cluster." | same |
| Agent token cannot join servers | UNKNOWN | Page does not say. Spec's T6 negative probe (old agent token fails after removal) still needs doing | same |
| wireguard-native flannel alternative | TRUE | "Use WireGuard to encapsulate and encrypt network traffic. May require additional kernel modules." | basic-network-options |

## 5. Tailscale

| claim | verdict | quote | URL / repo+tag |
|---|---|---|---|
| ACL `tests` syntax `{src, accept, deny}` with `host:port` | TRUE | "`src`: Specifies the user identity to test" (user, group, tag, host); "Each destination in the list is of the form `host:port`. Use a single numeric port. CIDR notation is not allowed." `proto` optional ("When omitted, the test checks for either TCP or UDP") | https://tailscale.com/kb/1337/acl-syntax |
| Spec test uses `dst` lists like `tag:raglab:6443` | PARTLY | Fine format, but comma lists of ports (spec's `tag:raglab:22,6443,10250` in `acls`) are valid for rules; for `tests` use one numeric port per entry | same |
| `*` as src matches tagged devices | UNKNOWN (doc silent; treat as yes) | "All traffic originating from Tailscale devices in your tailnet"; `autogroup:tagged` is a separate selector. Page does not say tagged devices are included, so the spec's "review every `*` src" is right | same |
| `autoApprovers` can use tags | TRUE | Approver "can be a user's full login email address, a group name, an autogroup or a tag" | same |
| Tags require `tagOwners` | TRUE | "You must define the tag in the tagOwners section of the tailnet policy file before using it in an ACL." (Auth-key page itself is silent) | same |
| Auth key flags: ephemeral, pre-approved, tags, reusable, expiry | TRUE | Ephemeral: "automatically remove the auth key after the device goes offline"; Pre-approved: "automatically authorize a device if you have device approval enabled" (only effective if device approval is on); Tags: "the device assumes the identity of the auth key's tags"; expiry 1 to 90 days | https://tailscale.com/kb/1085/auth-keys |
| "Single-use" key option | UNKNOWN | Page lists "Reusable" as a flag; single-use is the non-reusable default (inferred, not quoted) | same |
| `--accept-dns=false` interplay with provider resolver | UNKNOWN | Not checked beyond the flag name; verify on the node | n/a |
| Ephemeral device removal timing | UNKNOWN | Docs give no duration; delete explicitly (spec already does) | auth-keys page |

## 6. NIM Operator v3.1.4

Verified against source: `api/apps/v1alpha1/{nimservice,nimcache,common}_types.go` at tag `v3.1.4` (https://github.com/NVIDIA/k8s-nim-operator/tree/v3.1.4). `v3.1.4` is the latest release (published 2026-11-18).

| claim | verdict | quote | URL / repo+tag |
|---|---|---|---|
| v3.1.4 is current | TRUE | `gh api releases/latest` -> `v3.1.4`, 2026-11-18 | k8s-nim-operator v3.1.4 |
| NIMService has `nodeSelector`, `tolerations`, `runtimeClassName`, `labels`, `affinity`, `replicas`, `startupProbe`, `userID`, `groupID` | TRUE | `NodeSelector map[string]string`, `Tolerations []corev1.Toleration`, `RuntimeClassName string`, `Labels`, `Affinity *corev1.Affinity`, `StartupProbe Probe` | `nimservice_types.go` @ v3.1.4 |
| NIMCache has `tolerations`, `nodeSelector`, `runtimeClassName`, `resources`, `userID/groupID`, `env` | TRUE | `Tolerations`, `NodeSelector`, `RuntimeClassName` ("the runtimeclass for the caching job"), `Resources` "(cpu, memory, gpu)" | `nimcache_types.go` @ v3.1.4 |
| Spec's open question: `runtimeClassName` field exists on NIMService | TRUE | `RuntimeClassName string \`json:"runtimeClassName,omitempty"\`` (spec 7.3 can set it; add the same on NIMCache) | `nimservice_types.go` |
| `authSecret` optional on NIMService | TRUE | "AuthSecret is the name of an existing secret containing the NGC_API_KEY (and optionally HF_TOKEN). Optional for certain NIMs." NGC_API_KEY injected only when set | `nimservice_types.go` lines ~104, 344 |
| NIMService/NIMCache expose pod `securityContext` | UNKNOWN (likely FALSE) | Only `userID`/`groupID` seen in these types; no `securityContext`/`podSecurityContext` field matched in grep. Spec 7.6's caution (baseline PSS) is supported | grep of the three type files |
| NIMCache job needs a GPU | PARTLY | `Resources` documented as "(cpu, memory, gpu)"; `GPUs []GPUSpec` ("Product ... h100, a100, l40s") is a profile-selector, not a request. Whether the job requests a GPU by default was not determined; job can fall back to no GPU for non-buildable profiles (not verified) | `nimcache_types.go` |
| NIMCache storage options | TRUE | `PVC` {create, name, storageClass, size, volumeAccessMode, subPath, annotations}; `HostPath` is "Deprecated: use PVC instead." So spec's `local-path` PVC is the supported single-node route; hand-made hostPath PV is an alternative via `pvc.name` + `create:false` | `nimcache_types.go`, `common_types.go` |
| Job pod labels / Service name | UNKNOWN | Not read from the controller code; confirm on the live cluster | n/a |

## Remaining UNKNOWNs (need account, live cluster, or a login)

1. Lambda: root/sudo on the default user; whether "stop" exists (assume terminate-only); live capacity; any spend cap or auto-terminate.
2. Brev: hourly prices, root, API-driven auto-terminate.
3. RunPod: any true-VM SKU (none found).
4. NIM 8B: minimum VRAM and cache size; whether a free Developer Program account can `docker pull` (needs login); exact current tag (2.1.6 in docs vs 2.1.7 on NGC); whether the bare `vllm-model-free-nim:2.1.6` tag exists; tool-calling flag.
5. GPU Operator: authoritative k3s values for the non-NRI path (`.tmpl` vs rendered file); default of `cdi.nriPluginEnabled`; whether `toolkit.enabled` is needed with NRI; complete cluster-scoped kind list (run `helm template --include-crds`).
6. k3s: MTU behaviour on tailscale0; whether the agent token can join a server; local-path helper vs taint; cross-node NetworkPolicy.
7. Tailscale: whether `*` includes tagged devices in the owner's current ACL; `--accept-dns=false` with provider resolver; ephemeral removal delay.
8. NIM Operator: NIMCache job GPU request default; job pod labels; Service name; whether rendered pods pass `restricted`.
9. Bifrost items (section 14.9) were out of scope.
