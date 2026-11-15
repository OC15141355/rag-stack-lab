# Day-one field guide

## In one paragraph

This guide collects what you will wish you had known on the first day of working on an established, in-development LLM platform that runs on Kubernetes: a chat portal, an inference service, an LLM gateway and NVIDIA NIM containers serving models such as GLM 5.2 and Nemotron 3 Super. It covers five things the other pre-reading docs do not: how reasoning models behave as coding agents (thinking output, per-request toggles, sampling, tool-call parsers, and the ways they fail inside Cline), how to use an agent to understand a codebase without being misled, the corporate-environment friction of private CAs, proxies, Harbor and VKS access, a read-only command list to map a cluster on day one, and a checklist of questions for colleagues. Setup is in [13-dev-containers.md](13-dev-containers.md), [14-tilt.md](14-tilt.md) and [15-cline-with-a-self-hosted-model.md](15-cline-with-a-self-hosted-model.md); stack basics in [16-uv-fastapi-react-primer.md](16-uv-fastapi-react-primer.md); reading method in [18-reading-an-established-repo.md](18-reading-an-established-repo.md). Claims I could not confirm against a current official page are marked `UNVERIFIED:`.

## The plain version

Starting on a big existing project is like being handed the keys to a large building at night. You do not need to understand every room on the first day. You need a torch (read-only commands that show what is there), a floor plan (a trace of one request through the building), and a few phone numbers (the right questions for the right people). An AI assistant is a helpful guide who has also never been in the building: it will describe rooms confidently whether or not it has seen them, so you check its claims against the doors.

The two models behave differently from the chatty assistants most people know. They "think" first, in a separate stream of text, and that thinking costs tokens and time. If the tool talking to them does not understand that stream, you get empty replies, stalls, or half-finished edits. Most of these problems are plumbing (a parser flag, a token limit, a certificate) rather than the model being "bad".

Corporate networks add friction of their own. A private certificate authority means every tool, such as the editor, Node, Python, uv, Podman and kubectl, needs to be told to trust it, separately. None of this is difficult, but each tool has its own switch.

Five things to remember:

1. Thinking is on by default for both models. If a reply is empty, suspect a token limit eaten by thinking or a parser mismatch before suspecting the model.
2. Prove the endpoint with curl before blaming Cline (doc 15 has the checks).
3. Make the agent cite file and line for every claim, and open the file yourself for the claims that matter.
4. One private CA, many trust stores: editor, Node, Python, uv, Podman, kubectl each need their own setting.
5. Map before you touch: namespaces, deployments, images, ingress routes, GPU nodes, all with read-only commands.

## 1. GLM 5.2 and Nemotron 3 Super as coding agents

*Plain gloss: both models reason before answering, so how you switch that on and off, parse it and give it room decides whether an agent works at all.*

### 1.1 How reasoning shows up in responses

Servers built on vLLM and SGLang separate the model's thinking from its answer when a reasoning parser is configured. The thinking goes into a `reasoning_content` field on the message (or on each streamed `delta`), and the answer goes into `content`. SGLang's GLM 5.2 page shows a tool-call response with both `reasoning_content` and `tool_calls` filled. vLLM has been moving some of its API toward a `reasoning` field name; `UNVERIFIED:` which spelling your NIM version emits, so print a raw response and look.

Consequences worth knowing:

- If the parser is missing or mismatched, the thinking appears inside `content` as raw text (often between think tags) and clients get confused.
- With a parser present but the model omitting its opening think tag, `reasoning_content` can come back empty while the reasoning is mixed into `content`. A vLLM forum thread reports exactly this for GLM 4.7 FP8; `UNVERIFIED:` whether it applies to 5.2.
- For Nemotron 3 Super, vLLM's parser swaps the fields when thinking is disabled, so a short answer may land in `reasoning_content`. The model cards for hosts that document this say to read both fields.
- Thinking tokens count against `max_tokens`. A request can finish with `finish_reason: "length"`, empty `content` and a full `reasoning_content`. Cline reports that as "Model returned empty response".

### 1.2 Turning thinking on or off, per request

Both models use the same pass-through mechanism, a `chat_template_kwargs` object in the request body. With the OpenAI Python client it goes in `extra_body`:

```python
client.chat.completions.create(
    model="<served-model-name>",
    messages=[...],
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
```

| | GLM 5.2 | Nemotron 3 Super |
|---|---|---|
| Default | Thinking on | Thinking on |
| Off | `enable_thinking: false` (vLLM recipe and SGLang page agree; the SGLang page says the key is `enable_thinking`, not `thinking`) | `enable_thinking: false` |
| Depth control | `reasoning_effort` (top level or in kwargs): `"high"` lowers effort, anything else or omitted means max. No effect with thinking off | `low_effort: true` (with thinking on) gives much shorter traces; `reasoning_budget` caps the trace (model tries to stop at a newline, hard stop about 500 tokens past the budget) |

Caveats:

- Some GLM guides say `thinking` rather than `enable_thinking` for the SGLang path. The SGLang cookbook mirror I read says `enable_thinking`. Test against your own server: send both and see which changes the output.
- Whether the gateway between the client and NIM forwards `chat_template_kwargs` is a gateway question. A gateway that rebuilds the request body may drop unknown fields. `UNVERIFIED:` for Bifrost; test through the gateway, not just direct to the NIM.
- Cline's OpenAI Compatible provider has a Reasoning Effort selector but, per one third-party write-up, no way to send `chat_template_kwargs`. If you need thinking off, you may need a gateway or server-side default. `UNVERIFIED:` against the current Cline release.

### 1.3 Sampling

- GLM 5.2: temperature 1.0 and top_p 0.95 appear in SGLang's page (stated to match the checkpoint's `generation_config.json`) and in the model card for reasoning evals. The model card's coding and agent evals mostly used temperature 1.0 with top_p 1.0. So: start from the server defaults and do not tune unless you have a reason.
- Nemotron 3 Super: the model card says temperature 1.0 and top_p 0.95 for all tasks and backends, including tool calling.
- Do not lower temperature to "make it more deterministic" for reasoning models without testing; both vendors tune for 1.0.

### 1.4 Tool-call and reasoning parsers

| Backend | GLM 5.2 | Nemotron 3 Super |
|---|---|---|
| vLLM | `--tool-call-parser glm47 --reasoning-parser glm47 --enable-auto-tool-choice` (vLLM recipe) | `--tool-call-parser qwen3_coder --reasoning-parser nemotron_v3 --enable-auto-tool-choice` |
| SGLang | `--tool-call-parser glm47`, `--reasoning-parser glm45` (SGLang page; the older `glm45` tool parser leaves calls as raw text in `content`) | `--tool-call-parser qwen3_coder --reasoning-parser nemotron_3` |

Two things follow. First, "tool calls come back as text in `content`" almost always means the wrong or missing tool-call parser. Second, a NIM container normally chooses these flags for you; what you can see are the engine and profile it picked. `UNVERIFIED:` I could not load NVIDIA's NIM pages for GLM 5.2 and reasoning models, so I cannot confirm which flags or environment variables your NIM version exposes for overriding them. Read the NIM docs for your exact version.

One more reported failure: tool-call corruption on a self-hosted vLLM that was cured by disabling multi-token-prediction speculative decoding (MTP). This was a report from another editor's forum, not Cline, and `UNVERIFIED:` for NIM.

### 1.5 Known failure modes in Cline with reasoning models, and fixes

| Symptom | Likely cause | Try |
|---|---|---|
| "Model returned empty response" | Thinking used the whole output budget; or content went into `reasoning_content` | Raise Cline's max output tokens (GLM supports very large outputs; Cline's default cap is far lower); set reasoning effort lower; check a raw curl response |
| Tool calls appear as text, then it stalls | Wrong tool-call parser on the server | Fix server flags (1.4) |
| Reads files forever, never edits | Context too large or task too vague | Smaller task; Plan mode first; start a fresh task |
| Loops repeating the same step | Context pollution or lost earlier steps | New task with a written summary; reduce context; lower reasoning effort |
| Diff edits fail ("SEARCH block does not match") | Model reproduces file text imperfectly, especially after long thinking, or file changed | Ask for smaller edits; ask it to re-read the file first; as a last resort, ask for a whole-file rewrite of small files |
| Truncated edit or response | Output cap hit mid-stream | Raise max output; request smaller chunks |
| Works in the CLI but not the extension | Different streaming/reasoning handling | Try the Cline CLI. One closed issue for a different model reported exactly this pattern |
| Slow first token | Thinking happens before any visible output | Expected; lower effort or turn thinking off for simple edits |

Cline's `replace_in_file` tool uses SEARCH/REPLACE blocks and asks for small blocks, which is why "small edits" is the standard advice. Also: Cline 4.1.4 added retries for empty responses on all providers (reported in a third-party search summary; `UNVERIFIED:` check the changelog).

A starter `.clinerules/00-working-agreement.md` that helps weaker or slower models:

```markdown
# Working agreement
- Always read a file before editing it. Never edit from memory.
- Make one small change per step. Prefer several small edits to one large one.
- If an edit fails, re-read the file and retry once; do not rewrite the whole file unless asked.
- Cite file:line for every claim about the code. Say "not found" rather than guessing.
- Do not run commands that change cluster state. Read-only kubectl only.
- After each task, write a 5-line summary to docs/notes/progress.md.
```

Cline reads rules from `.clinerules/` or `.cline/rules/` in the workspace (and from global rule folders); rules without frontmatter are always on, and rules with a `paths:` glob list load only when matching files are in context. Keep them short, since they use context tokens.

### 1.6 Which model for what

Public evidence is thin, so treat this as a starting hypothesis to test on your own tasks:

- GLM 5.2: published as an agentic and coding model, MIT licence, 1M-token context, evaluated in agent harnesses at long output lengths. Default for multi-step edits in Cline.
- Nemotron 3 Super (120B total, 12B active): positioned for agentic workflows, tool use, RAG and long-context, high-volume work. Its model card lists SWE-Bench (OpenHands) 60.47, below Qwen3.5-122B on the same table but above GPT-OSS-120B. Context default 256k, up to 1M with an environment variable and more memory. Sensible for fast, cheap or long-context passes: summarising a large module, scanning logs, bulk questions.
- Your deployment may cap context far below the headline numbers. `UNVERIFIED:` actual `max_model_len` on your NIMs; check the pod environment (section 4).

Run a small eval of your own: ten real tasks, both models, and compare, rather than trusting leaderboard rows.

## 2. Using an AI agent to understand a codebase safely

*Plain gloss: treat the agent as a fast but unreliable research assistant whose every claim must come with a page number.*

### 2.1 Prompts that work

- Orientation, no edits: "Plan mode. Read only. List the top-level directories and, for each, one sentence on its purpose, citing the file that proves it."
- Citations: "For each claim give `path:line`. If you cannot find evidence, write NOT FOUND."
- Request trace: "Trace what happens when the browser sends a chat message. List every function in order with `path:line`, then draw a Mermaid sequence diagram of the same path." Then verify three random hops yourself.
- Boundaries: "Where does this service call another service? List each outbound call with URL source (config key or env var)."
- Explain-back: after you read, you explain the flow in your own words and ask the agent to find mistakes in your explanation. This catches gaps in you rather than in it.
- Adversarial: "What in your explanation are you least sure about, and what would you open to check it?"

### 2.2 Keeping a weaker or self-hosted model on track

- Small, scoped tasks with one verifiable output each (a list, a diagram, a one-paragraph summary).
- Plan mode first, Act mode only after you agree with the plan. Keep Act mode on manual approval for the first week.
- Context hygiene: start a new task per question; do not let one session wander across the repo. Long sessions are where loops and forgotten steps appear.
- Memory-bank-style notes: ask the agent to keep `docs/notes/map.md` (components, entry points, config keys, glossary) and read it at the start of each task via a `.clinerules` line such as "Read docs/notes/map.md first". You review those notes, since a wrong note poisons every later session.
- Read-only by default: give the agent a read-only kubeconfig context, or none; paste command output into the chat instead.

### 2.3 Spotting hallucinated explanations

Red flags: confident descriptions of files it never opened (check the tool-call log in Cline for read-file events); function or class names that `grep` cannot find; explanations that match the framework's usual layout rather than this repo's; line numbers that do not contain the quoted code; "typically" and "usually" language; and diagrams with neat boxes for components you cannot find in the manifests. Cheap checks: `grep -rn "<name>"` for every symbol cited, and ask the same question twice in fresh tasks and compare. Disagreement means it is guessing. See also doc 18 for the five-pass method this builds on.

## 3. Corporate dev environment friction

*Plain gloss: a private certificate authority and a proxy are invisible until a tool fails, and every tool keeps its own list of who to trust.*

### 3.1 One CA, many trust stores

Get the root (and any intermediate) certificate as PEM from the platform team. Then:

| Where | Setting |
|---|---|
| macOS/Windows system store | Install the CA there first; many tools can then use it |
| VS Code and extensions | VS Code reads the system store for its own networking (the `http.systemCertificates` setting, on by default). Extensions that bundle their own HTTP stack may not; `UNVERIFIED:` whether Cline does. Test with the endpoint check in doc 15 |
| Node (Cline CLI, tools) | `NODE_EXTRA_CA_CERTS=/path/ca.pem` (adds to, rather than replaces, the built-in roots; must be set before Node starts) |
| Python (requests, httpx, openai) | `SSL_CERT_FILE=/path/bundle.pem` (httpx and `ssl` default), `REQUESTS_CA_BUNDLE=/path/bundle.pem` (requests), `CURL_CA_BUNDLE` for curl-based tools. `SSL_CERT_FILE` replaces the defaults, so use a bundle that includes public roots too |
| uv | `SSL_CERT_FILE` / `SSL_CERT_DIR` override uv's certificate source entirely. Or use the OS store with `UV_SYSTEM_CERTS=true` / `--system-certs` (added in uv 0.11.0). `UV_NATIVE_TLS` / `--native-tls` still exists but the current reference marks it deprecated in favour of `UV_SYSTEM_CERTS`. Older uv versions only know `--native-tls`, so check `uv --version` |
| Podman | Per-registry: put the CA at `/etc/containers/certs.d/<registry-host>/ca.crt` (inside the Podman VM on macOS: `podman machine ssh`). Avoid `--tls-verify=false` except as a diagnostic |
| Inside the dev container | The container has its own trust store. Mount the PEM and set the variables in `containerEnv`, or bake the CA into the image with `update-ca-certificates`. Doc 13 covers mounting |
| kubectl | CA is normally embedded in the kubeconfig cluster entry (`certificate-authority-data`). If the API server sits behind a corporate TLS inspector, you may need `certificate-authority:` pointing at the right file |
| git | `git config http.sslCAInfo /path/ca.pem` |

A quick diagnostic: `curl -v https://host/ 2>&1 | grep -E "issuer|verify"` shows which CA signed the endpoint. `openssl s_client -connect host:443 -showcerts` shows the chain.

### 3.2 Proxy variables

`HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY` (and lower-case twins, which some tools read first). `NO_PROXY` must list cluster-internal names and the registry if those are reached directly: `.svc,.cluster.local,10.0.0.0/8,localhost,127.0.0.1` (CIDR support varies by tool; `UNVERIFIED:` per tool). In a dev container, pass them via `containerEnv` or `remoteEnv`; Podman machine on macOS may need them set inside the VM for image pulls.

### 3.3 Harbor

- Log in: `podman login <harbor-host>`. Interactive users authenticate with their directory or OIDC identity, which for the CLI is a CLI secret from the Harbor user profile rather than the SSO password. `UNVERIFIED:` for your instance's auth mode.
- Robot accounts are non-human credentials scoped to a project. Their names look like `robot$project+name`; the `$` must be single-quoted in a shell: `podman login -u 'robot$myproj+ci' --password-stdin <host>`.
- Tell apart "unauthorized" (credential or permission) from "x509: unknown authority" (CA) from "manifest unknown" (wrong tag or path). Doc 12 covers Harbor in more detail.
- Pulling credentials into the cluster is a different thing: image pull secrets in the namespace. Check `kubectl get secret -n <ns>` for `kubernetes.io/dockerconfigjson` types without printing their contents.

### 3.4 kubectl on Tanzu/VKS

- Access normally comes from a kubeconfig supplied by the platform team or generated by a vendor login plugin. `UNVERIFIED:` the current login command and flow for your VKS version (it has changed across Tanzu releases); ask which one applies.
- List and switch: `kubectl config get-contexts`, `kubectl config use-context <name>`, `kubectl config current-context`. Pin a namespace per context: `kubectl config set-context --current --namespace=<ns>`.
- Expect namespace-scoped RBAC. Cluster-wide `kubectl get nodes` or `get namespaces` may be forbidden. That is normal, not a broken setup.
- Find out what you may do: `kubectl auth can-i --list -n <ns>`, and test the specific verbs: `kubectl auth can-i get pods -n <ns>`, `can-i create deployments -n <ns>`, `can-i get pods/log -n <ns>`.
- Tokens from login plugins expire; "Unauthorized" after a lunch break usually means re-login, not misconfiguration.

## 4. First-day orientation commands (read-only)

*Plain gloss: a short list of questions you can ask the cluster that cannot break anything.*

Everything below is `get`, `describe`, `logs` or `top`. Add `-n <ns>` where cluster-wide listing is forbidden.

```bash
# Who am I, where am I
kubectl config current-context
kubectl auth can-i --list -n <ns>

# What exists
kubectl get ns
kubectl get deploy,sts,ds,job,cronjob -n <ns> -o wide
kubectl get svc,ep -n <ns>
kubectl get ingressroute,ingressroutetcp,middleware -A        # Traefik CRDs (traefik.io); older installs use traefik.containo.us
kubectl get ingress -A
kubectl get cm,secret -n <ns>                                 # names only; do not print secrets
kubectl get pvc -n <ns>

# Helm and GitOps
helm list -A                                                  # needs read on release secrets
kubectl get applications -A                                   # if Argo CD is used
kubectl get kustomization,helmrelease -A                      # if Flux is used

# Which images, from which registries
kubectl get pods -n <ns> -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .spec.containers[*]}{.image}{" "}{end}{"\n"}{end}'
kubectl get pods -A -o jsonpath='{range .items[*]}{range .spec.containers[*]}{.image}{"\n"}{end}{end}' | cut -d/ -f1 | sort | uniq -c   # registries in use

# GPUs
kubectl get nodes -L nvidia.com/gpu.product,nvidia.com/gpu.count
kubectl describe node <gpu-node> | grep -A8 -E "Allocatable|Allocated resources"
kubectl get pods -A -o custom-columns='NS:.metadata.namespace,POD:.metadata.name,GPU:.spec.containers[*].resources.limits.nvidia\.com/gpu'
kubectl get runtimeclass

# NIM pods: env, profile, args
kubectl describe pod <nim-pod> -n <ns>
kubectl get pod <nim-pod> -n <ns> -o jsonpath='{range .spec.containers[*].env[*]}{.name}={.value}{"\n"}{end}'
kubectl logs <nim-pod> -n <ns> | head -200                    # startup log names the selected profile and engine
kubectl get nimservice,nimcache -A                            # only if the NIM Operator is installed

# Metrics where permitted
kubectl top pods -n <ns>
```

Notes:

- Cluster-wide commands such as `get ns`, `get nodes` and `-A` listings may be denied. Namespace-scoped alternatives will still work.
- In the NIM environment output, look for variables naming the served model, the model profile, maximum model length and log level. Names like `NIM_MODEL_PROFILE`, `NIM_SERVED_MODEL_NAME`, `NIM_MAX_MODEL_LEN` and `NIM_LOG_LEVEL` are what I remember from NIM documentation; `UNVERIFIED:` confirm in the NIM docs for your version. The startup log is the more reliable source.
- Env values are sometimes injected from Secrets. `jsonpath` on `.env[*]` shows `valueFrom` entries as empty `value`; that is expected, and you should not go hunting for the secret value.
- The `get pods -A` registries one-liner tells you which registries need CAs and pull secrets (section 3).

### Following one request end to end

1. Pick a request: one chat message from the portal. Open the browser developer tools, Network tab, and note the URL, status and any `traceparent` or request-ID response header.
2. Traefik: `kubectl logs -n <traefik-ns> deploy/traefik --tail=50` (access logging may be off; `UNVERIFIED:` check the Traefik static config). Match the route: `kubectl get ingressroute -A -o yaml | grep -B3 -A10 <hostname>` to see which service and middlewares apply.
3. Portal API: `kubectl logs deploy/<portal-api> -n <ns> --since=2m | grep <request-id>`. Then find the upstream URL it calls, in code (doc 18, pass 4) or in its ConfigMap or env.
4. Gateway: logs of the gateway deployment for the same request ID; the gateway config (usually a ConfigMap or Secret-backed file) shows the model name to provider mapping.
5. NIM: `kubectl logs <nim-pod> --since=2m` shows the completion request and timings. Direct check with a port-forward: `kubectl port-forward svc/<nim> 8000:8000` then `curl localhost:8000/v1/models`.
6. Traces: with OpenTelemetry, take the trace ID from the `traceparent` header (the 32-hex-character second field) and search for it in whichever trace UI the platform uses. A healthy trace has spans for the portal, inference service, gateway and sometimes NIM. A gap shows where context propagation is not configured. `UNVERIFIED:` which of those components emit spans here.
7. Write what you found as a diagram in your map file (doc 18, pass 5).

If you have no cluster access yet, do steps 1 and 3 from the repo alone, and mark the rest "to confirm".

## 5. Questions to ask colleagues in week one

*Plain gloss: ten minutes of the right question saves a day of reading code that no longer matters.*

**Access and environment**
- Which kubeconfig or login flow do I use, and which namespaces am I allowed in?
- What is the proxy and CA setup, and where do I get the CA bundle?
- Which Harbor project and robot account is for local development?
- Is the dev environment shared or per-person, and how do I reset it?

**Code and architecture**
- Which service is the source of truth for chat history, users, and model lists?
- Which directories are dead or legacy? What should I never edit by hand (generated clients, vendored code)?
- Which tests actually matter, and which are flaky?
- Is there a request-flow diagram, and who last updated it?

**Models and inference**
- Which model is the default, and why? Which are experimental?
- What are the real context limits and output limits on each NIM, and are they lower than the vendor's headline numbers?
- Is thinking enabled by default through the gateway, and can clients pass `chat_template_kwargs`?
- Which sampling settings are fixed server-side?

**Gateway and observability**
- How does the gateway pick a route, apply retries, fall back or rate-limit?
- Where do I see logs, metrics and traces? Is there a request ID I can search?
- What alerts exist, and what has paged recently?

**Delivery and process**
- How does a change get from my branch to the dev environment (Tilt, CI, GitOps)?
- What is the review process, and what do reviewers care about most?
- What data may I put into prompts, including to my own coding agent? (Doc 15 covers data handling.)
- Who owns the GPUs, and how do I request capacity?

## Check yourself

1. A Cline task returns "empty response". Name three causes in the order you would check them.
2. How do you switch off thinking for one request, and what would make that request ignore the setting on the way to the model?
3. Tool calls arrive as text inside `content`. Which server flag do you suspect first?
4. Which two variables would you set for Python and for Node to trust a private CA, and why does `SSL_CERT_FILE` need a full bundle?
5. What does `kubectl auth can-i --list` tell you that `kubectl get` does not?
6. A claim from the agent says "auth is handled in `middleware/auth.py:42`". What are your two quickest checks?
7. Write the commands to list every container image registry in use in a namespace.
8. Why is `robot$project+name` awkward in a shell, and what do you do about it?

## References

Checked 2026-11-15 unless noted.

- vLLM recipe for GLM 5.2: https://recipes.vllm.ai/zai-org/GLM-5.2 (parsers `glm47`, `enable_thinking`, reasoning effort)
- SGLang cookbook GLM 5.2: https://docs.sglang.io/cookbook/autoregressive/GLM/GLM-5.2 (`glm45` reasoning parser, `glm47` tool parser, sampling)
- GLM 5.2 model card: https://huggingface.co/zai-org/GLM-5.2 (sampling in evals, MIT licence, 1M context)
- Nemotron 3 Super model card: https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16 (sampling, `enable_thinking`, `low_effort`, parsers, benchmarks)
- vLLM Nemotron 3 Super blog: https://vllm.ai/blog/nemotron-3-super
- NVIDIA NIM GLM 5.2 page (could not be loaded when checked): https://docs.nvidia.com/nim/large-language-models/latest/get-started/advanced/get-started-glm-5-2.html
- NVIDIA NIM reasoning models (could not be loaded when checked): https://docs.nvidia.com/nim/large-language-models/latest/reasoning-model.html
- Cline rules: https://docs.cline.bot/features/cline-rules
- Cline issue on reasoning stream handling, another model (closed 2026-11-13): https://github.com/cline/cline/issues/12385
- Third-party GLM 5.2 in Cline notes (secondary source): https://dev.to/owen_fox/glm-52-in-cline-setup-thinking-cost-vs-sonnet-5-2026-1iln
- vLLM forum on GLM 4.7 reasoning start tag: https://discuss.vllm.ai/t/glm-4-7-fp8-reasoning-start-issues/2146
- uv certificates: https://docs.astral.sh/uv/concepts/authentication/certificates/
- uv environment variables: https://docs.astral.sh/uv/reference/environment/
- Not re-checked this session (from general knowledge): Node `NODE_EXTRA_CA_CERTS`, Python `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`, Podman `certs.d`, Harbor robot accounts, `kubectl auth can-i`. Confirm in each tool's own docs.
