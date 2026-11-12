# Cline with a self-hosted model

## In one paragraph

Cline is an open-source coding agent that runs as a VS Code extension, a command-line tool, a desktop app and a JetBrains plugin. You give it a task; it asks a language model what to do, then reads files, edits them and runs commands on your machine, asking your permission as it goes. It can talk to any server that speaks the OpenAI chat-completions API, so it can be pointed at the team's inference service in front of GLM 5.2 and Nemotron 3 Super. The model is only as good as the endpoint: Cline sends large prompts, expects streamed replies, and works much better when the endpoint handles tool calls and long contexts properly. This document covers how Cline behaves, the exact settings, what the endpoint must provide, how to prove the endpoint works with curl before blaming Cline, and what leaves your machine. Versions: GitHub releases page (checked 2026-11-13) showed VS Code extension v4.1.26 and CLI v3.0.74 as the newest, dated 26 Oct; the docs pages themselves state no version.

## The plain version

Think of hiring a very fast contractor who can see only what you put on the table in front of them. The contractor (Cline) is the one who walks around your house with a clipboard: opening drawers, moving furniture, running errands. But the contractor does not think for themselves; every few minutes they phone an expert (the language model) and read out what they see, and the expert says what to do next. In your case the expert lives in your own company's building rather than somewhere on the internet.

If this setup did not exist, you would copy and paste code into a chat window and carry the answers back by hand. That works for small questions, but not for a task such as "find why this test fails and fix it", which needs dozens of look-then-act steps.

What goes wrong is usually the phone line, not the contractor: the expert's desk is too small to hold everything the contractor reads out, the line drops mid-sentence, or a gatekeeper in between hangs up on long calls.

If you remember only five things:

- Cline is the hands; the model behind the endpoint is the brain.
- Everything Cline reads may be sent to the endpoint, so you need to be happy with where it goes.
- The endpoint must be OpenAI-compatible, streaming, and have a large context window.
- Test the endpoint with `curl` first. If curl works and Cline does not, then look at Cline.
- Keep auto-approve minimal; Cline can run commands and edit files on your machine.

## Why it exists

Coding help from a chat window does not scale to multi-step work. An agent loop lets the model inspect the repo, make an edit, run the tests and react to failures. Cline provides that loop and keeps a human approval step in it. You already run LiteLLM as a gateway: Cline is just another client of an OpenAI-compatible API, like any application calling your gateway, except it is very hungry (long prompts, many requests) and sensitive to streaming and tool-call quality.

## How it works

In plain terms: Cline repeatedly asks the model "what next?", the model answers with a request to use a tool (read a file, run a command), Cline does it after you approve, and feeds the result back, until the model says it is done. The precise version follows.

Cline's docs (docs.cline.bot, checked 2026-11-13) describe: the model chooses a tool, Cline runs it, and the result goes back to the model. The repo README says one shared engine now powers the CLI, desktop app, VS Code extension and JetBrains plugin.

```
 you --task--> Cline (in VS Code, inside the dev container)
                 |  1. build prompt: system prompt + rules + task + files read so far + tool results
                 v
        HTTPS POST /v1/chat/completions  (stream: true)
                 |
         [ gateway / inference service ]  -->  NIM serving GLM 5.2 or Nemotron 3 Super
                 |  2. reply streamed back (SSE): text and/or a tool call
                 v
               Cline asks you to approve ("Read project files", "Run command", ...)
                 |  3. runs the tool, appends the result, goes back to step 1
```

### Plan and Act modes

Plain gloss: Plan is "think and look, touch nothing"; Act is "go and do".

Per the docs, Plan mode can read the codebase and discuss approaches but "cannot modify any files or execute commands". Act mode keeps the planning context and can edit files and run commands. The conversation carries over. Settings allow "Use different models for Plan and Act", so you could, for example, use one model to plan and another to implement.

### Built-in tools

The tools reference lists, for the current core: `read_files`, `search_codebase`, `run_commands`, `fetch_web_content`, `apply_patch` or `editor` (only one of those two per session), `skills`, `ask_question`, `submit_and_exit`. It notes that older docs used names such as `read_file` and `execute_command`; those have been replaced. Other Cline docs, older blog posts and screenshots may therefore not match the version you install.

### How the model is driven: native tool calling or text

Plain gloss: there are two ways to let a model "press buttons": a structured field in the API for tool calls, or asking the model to write tool requests as special text that Cline parses.

- Cline v3.35 release post: native tool calling (tool definitions sent as JSON schemas in the API request) became the default for a listed set of models and providers (Claude 4+, Gemini 2.5, Grok 4, Grok Code, GPT-5 excluding gpt-5-chat; providers Cline, Anthropic, Gemini, OpenRouter, xAI, OpenAI, Vercel AI Gateway). "Models without native support continue using the text-based approach."
- The current docs page for the OpenAI Compatible provider says nothing about tool-call mode. The SDK page mentions `modelId`, `baseUrl`, `apiKey` and optional `headers` only.
- UNVERIFIED: whether the current Cline sends native `tools` or text-formatted tool use to a generic OpenAI Compatible endpoint serving GLM 5.2. Measure it: run Cline once against a logging proxy (or the inference service's request log) and look at whether requests contain a `tools` array. The diagnostic in "How you run it" step 6 does this.

## How you run it

### Settings in the extension (OpenAI Compatible provider)

From docs.cline.bot/provider-config/openai-compatible (checked 2026-11-13):

1. Open Cline settings (gear icon) and choose API Provider "OpenAI Compatible".
2. Base URL: the endpoint, which must differ from the official OpenAI URL. Use the `/v1` root, for example `https://inference.example.internal/v1` (not the full `/chat/completions` path). The docs only say "provider's endpoint"; the `/v1` root is the convention LiteLLM documents ("make sure `api_base` ends in `/v1`") and is my inference for Cline: UNVERIFIED for Cline.
3. API Key: the key issued by the gateway. (There is also an Azure Identity Authentication checkbox; ignore it.)
4. Model ID: the exact name the gateway exposes, which you can list with `curl .../v1/models`.
5. Model Configuration: Max Output Tokens, Context Window size, Image Support, Computer Use (for models with tool/function calling), Input and Output Price. Set the context window to what the deployment really serves, not what the model card says (see below).

Not on that docs page, so UNVERIFIED for the extension UI: custom request headers, temperature, streaming toggles. The SDK doc says provider config "can include `headers`" without a format. A Verify button exists in the quickstart for v0.

### CLI

```sh
npm i -g cline                                   # install the CLI (from docs.cline.bot intro)
cline auth                                       # guided setup
cline auth -p openai-compatible -k "$KEY" -m glm-5.2 -b https://inference.example.internal/v1   # flags -p -k -m -b exist per CLI reference; the provider ID "openai-compatible" is from the SDK page; the CLI accepting that ID: UNVERIFIED
cline version                                    # show version
cline --json "summarize this repo" | jq -r 'select(.type=="run_result") | .text'   # headless, JSON lines
```

Important: per the CLI reference, a prompt given on the command line "runs in yolo mode by default" (everything auto-approved). Pass `--auto-approve false` (or `--plan`/`--act`) to opt out. Config lives in `~/.cline`; provider data in `~/.cline/data/settings/providers.json`; log at `~/.cline/data/logs/cline.log`. Other flags: `-t/--timeout <seconds>` (default 0, none), `--retries` (default 3).

### Rules, MCP, approvals

- Rules: put project instructions in `.clinerules/` (or `.cline/rules/`) at the repo root, one Markdown file per topic. Cline also detects `.cursorrules`, `.windsurfrules` and a root `AGENTS.md`. Global rules default to `~/Documents/Cline/Rules`. Workspace rules win in conflicts. Conditional rules use YAML front matter `paths:` globs.

```markdown
<!-- .clinerules/01-project.md -->
This is a uv-managed Python 3.12 FastAPI service. Run tests with `uv run pytest -q`.
Never edit uv.lock by hand; use `uv add`. Do not touch deploy/ without asking.
```

- MCP servers (tools from external programs): add them from the MCP Servers icon, Configure tab; config JSON is `mcpServers`. Transports: stdio, streamable HTTP (recommended, set `"type": "streamableHttp"`), legacy SSE (the default if `type` is omitted). Each server has an `autoApprove` list; keep it short. CLI file: `~/.cline/data/settings/cline_mcp_settings.json`.
- Auto-approve categories (docs.cline.bot/features/auto-approve): read project files, read all files, edit project files, edit all files, execute safe commands, execute all commands, browser, MCP, notifications. The docs recommend enabling only "Read project files" by default. There is no command allowlist; the model flags each command as requiring approval or not, which means a weak model may mislabel a risky command. YOLO mode approves everything; use only in a throwaway environment, which is one real argument for a dev container.

## What the endpoint must provide

Plain gloss: Cline sends a lot of text, expects the answer to arrive word by word, and relies on the model to ask for tools in a clean format; if the endpoint cannot do these things, the agent stalls or loops.

- Route `POST /v1/chat/completions` and `GET /v1/models`, OpenAI schema. If you front NIM with LiteLLM: model prefix `openai/<name>`, `api_base` ending in `/v1` (docs.litellm.ai).
- Streaming over Server-Sent Events (SSE, a long-lived HTTP response of `data: {...}` lines ending with `data: [DONE]`). Anything between Cline and the model must not buffer the response.
- A real context window. Each Cline request carries the system prompt, rules, the conversation, and every file and command output so far. Small windows (8k to 32k) fill after a few file reads and the task fails or the history gets truncated. Set Cline's Context Window field to what you actually deploy. NIM and vLLM-style servers often cap context lower than the model supports, so read it from the server (`/v1/models` may show a max length: UNVERIFIED for your service) or test it.
- Enough output tokens for whole-file edits. Set Max Output Tokens high enough but within the server's limit; too high may be rejected with a 400.
- Tool calling that works. NIM docs: older LLM NIM (1.10 to 1.15) documents `tools` and `tool_choice` (`none`, `auto`, or a named tool), with `NIM_ENABLE_AUTO_TOOL_CHOICE=1` listed; NIM 2.0.x docs say `--enable-auto-tool-choice` and `--tool-call-parser` must be set together (pass-through via `NIM_PASSTHROUGH_ARGS` on Kubernetes), otherwise `tool_choice: "auto"` is rejected. Which NIM version the team runs: UNVERIFIED, ask.
- Reasoning output handling. Models that think emit reasoning separately; make sure it does not leak into `content` or empty the content.

## GLM and Nemotron as coding models: what is public

- GLM 5.2 (Z.ai). Z.ai's own page (docs.z.ai/guides/llm/glm-5.2) lists: 1M context, 128K max output, function calling supported, thinking modes (`"thinking": {"type": "enabled"}`, `reasoning_effort` `"max"`), MCP support. It does not say whether tool-call arguments stream, nor a release date. A third-party post (dev.to, dated 2026-06-15) says it shipped 2026-06-13, is a 744B-parameter mixture-of-experts model fine-tuned toward coding, had no published benchmarks at launch, and warns that "tool-use formatting differences can surface on complex agentic tasks" (said about a translation layer). Treat benchmark claims as unverified. Open weights under MIT were "confirmed" for 2026-06-16 to 20 per that post; whether they were released: UNVERIFIED.
- The 1M window is the model's, not necessarily your deployment's. What your NIM serves, and GLM 5.2's tool-calling behaviour in YOUR stack: UNVERIFIED. Measure: (a) `curl /v1/models`; (b) send prompts of growing size (below) until it fails and note the token count in the error; (c) run the tool-call test in step 5 ten times and count how many return a well-formed `tool_calls`.
- Nemotron 3 Super (NVIDIA). Hugging Face card: hybrid Mamba-2 + MoE + attention, 120B total / 12B active parameters; supports up to 1M context though the HF config default is 256k; tool calling via `--enable-auto-tool-choice --tool-call-parser qwen3_coder` (vLLM) with `--reasoning-parser nemotron_v3`; reasoning is on by default and controlled with `enable_thinking` in `chat_template_kwargs`; for coding agents the card recommends `"force_nonempty_content": True`; recommended sampling temperature 1.0, top_p 0.95. The card also mentions a custom `super_v3` parser while its vLLM command uses `nemotron_v3`; check which your version needs. Whether the team's NIM exposes these knobs: UNVERIFIED.
- Z.ai lists Cline among supported coding tools per a third-party article; I did not open an official Z.ai page confirming this: UNVERIFIED.

## How it fits the stack

- Cline runs inside the dev container (doc 13), because that is where the VS Code server and extensions live. The inference service is reached from the container's network. A service on your Mac host is not `localhost` from inside a Podman machine VM or container; use `host.containers.internal` (Podman's host alias; UNVERIFIED in the docs I opened) or a Tilt port-forward (doc 14), which exposes the in-cluster service on a port that you forward via `forwardPorts`.
- The inference service (doc 16) is the OpenAI-compatible front. Point Cline at it, or at LiteLLM in front of it.
- Cline's CLI also runs inside the container, so proxy and CA variables must be set there.

## How you prove the endpoint works (do this before blaming Cline)

```sh
export BASE=https://inference.example.internal/v1   # your endpoint
export KEY=...                                       # your key
# 1. Reachability and TLS
curl -sv $BASE/models -H "Authorization: Bearer $KEY" 2>&1 | head -30     # expect HTTP 200 and a model list; cert errors show here
# 2. Plain completion
curl -s $BASE/chat/completions -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"glm-5.2","messages":[{"role":"user","content":"Say hi"}],"max_tokens":32}'
# 3. Streaming (-N disables curl buffering)
curl -sN $BASE/chat/completions -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"glm-5.2","stream":true,"messages":[{"role":"user","content":"Count to 20"}]}'
# expect many "data: {...}" lines arriving gradually, ending with "data: [DONE]". One big burst at the end = something is buffering.
# 4. Long-response timeout: ask for a long answer and time it
time curl -sN $BASE/chat/completions ... -d '{"model":"glm-5.2","stream":true,"max_tokens":4000,"messages":[{"role":"user","content":"Write 3000 words about Kubernetes"}]}' | tail -3
# 5. Tool call
curl -s $BASE/chat/completions -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' -d '{
 "model":"glm-5.2","tool_choice":"auto",
 "messages":[{"role":"user","content":"What is in README.md? Use the tool."}],
 "tools":[{"type":"function","function":{"name":"read_file","description":"Read a file","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}}]}'
# expect choices[0].message.tool_calls with arguments as valid JSON. A 400 about "auto" tool choice means the server was started without tool parsing.
# 6. Context ceiling: generate a big prompt and increase until failure
python3 - <<'EOF' > /tmp/big.json
import json; print(json.dumps({"model":"glm-5.2","max_tokens":16,"messages":[{"role":"user","content":"word "*100000+"\nReply OK"}]}))
EOF
curl -s $BASE/chat/completions -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' -d @/tmp/big.json | head -c 600
```

Step 6 sends roughly 100k tokens (about one token per "word "; adjust). Raise or lower the repeat count to find the ceiling; the error message usually states the limit. Adjust model names to what `/v1/models` returned. If steps 1 to 5 pass from inside the dev container but Cline fails, compare headers, model ID, and the presence of a `tools` array in the request logs.

## Proxies, certificates and gateways

- VS Code extension: per Cline docs, the extension "uses VS Code's built-in proxy settings". The VS Code network page says proxy support comes from Chromium, the OS trust store is used for certificates, and that extensions "don't yet get the same proxy support as VS Code itself" (tracked in a GitHub issue). For a private CA, the preferred fix is adding it to the OS trust store of the machine where the extension runs, which for a dev container means the container. `http.proxyStrictSSL=false` is described as not recommended for production.
- CLI: reads `http_proxy`, `https_proxy`, `no_proxy`, and `NODE_EXTRA_CA_CERTS=/path/ca.pem` (PEM). HTTP proxies only: no SOCKS, no PAC.
- Test certs with `curl --cacert /path/ca.pem -vv $BASE/models`.
- Cline docs do not document timeouts. Reverse proxy defaults matter: nginx `proxy_buffering` is on by default (it holds streamed replies back), and `proxy_read_timeout` defaults to 60s between successive reads, so a slow first token from a reasoning model can trip it. Use `proxy_buffering off;`, a larger `proxy_read_timeout`, or have the upstream send `X-Accel-Buffering: no`. Your ingress controller and gateway have their own equivalents: UNVERIFIED for your stack.
- Release notes mention retries capped at 3 (v4.1.26), so repeated gateway failures surface quickly.
- Auth: the gateway key goes in the API Key field, sent by the OpenAI-style client as a bearer token (UNVERIFIED that Cline uses `Authorization: Bearer`; verify in your gateway logs). Extra headers: see the UNVERIFIED note above.

## Data handling

- Everything Cline reads for a task (file contents, command output, your prompts) is sent to whichever model endpoint you configured. With a self-hosted endpoint it stays on your infrastructure, but your gateway, its logs and any request-logging callbacks (you know LiteLLM's) may store it.
- Telemetry (docs.cline.bot/enterprise-solutions/monitoring/telemetry): records feature usage, task counts, errors, token counts, timings, model and provider names, version, OS, editor, and a device ID. It does not include code, file contents or prompts except for requests to Cline's own and ClinePass providers. Turn it off: gear icon, General, clear "Allow error and usage reporting" (VS Code); `telemetryOptOut: true` in `~/.cline/data/settings/global-settings.json` (CLI). Even with telemetry off, the page says Cline still contacts its servers for sign-in, feature flags, and its own provider requests; whether that happens when you only use a self-hosted provider and never sign in: UNVERIFIED. Check by watching outbound connections in an isolated test.
- In a regulated setting, assume nothing: read the telemetry page, test with a network capture, then decide.

## What goes wrong

- Agent loops or stops mid-task after a few steps: context window too small, or the Context Window field set above what the server accepts.
- 400 errors on every request: server rejects the `tools` field or `tool_choice: auto` (tool parsing not enabled), or a parameter such as `max_tokens` is above the limit. Release notes show Cline switched to `max_completion_tokens` for GPT-6 style OpenAI requests; some servers accept only one name.
- Text appears all at once, or the UI hangs then fails: proxy buffering or read timeout.
- "Model not found": the Model ID differs from `/v1/models`; the base URL lacks `/v1`.
- Invalid or malformed tool calls, repeated retries: model/parser mismatch. The Cline docs list troubleshooting only generically (invalid key, model not found, connection errors, unexpected results).
- Certificate errors from the extension but not curl: curl uses the container trust store or `--cacert`; the extension may use a different one.
- Cline cannot reach the service: `localhost` means the container, not the Mac.
- Surprise edits: auto-approve or yolo on; the CLI defaults to yolo for a command-line prompt.

## Check yourself

1. What is the difference between Plan and Act mode, and what can Plan mode not do?
2. What does Cline send in each request, and why does that make a small context window fatal?
3. Which three values are required by the OpenAI Compatible provider, and which extra model settings should match your deployment?
4. What is the difference between native tool calling and text-formatted tool use, and what test shows which one Cline is using?
5. Why does a buffering reverse proxy break a streamed reply, and what two nginx settings matter?
6. What curl commands prove an endpoint is fit for Cline, in order?
7. Where does the Cline extension run when you use a dev container, and how does it reach a service on your host or in the cluster?
8. What does Cline's telemetry collect, and what leaves the machine when you use a self-hosted model?

## References

All checked 2026-11-13.

- https://docs.cline.bot/ (intro; no version), https://docs.cline.bot/llms.txt (page index)
- https://docs.cline.bot/provider-config/openai-compatible.md
- https://docs.cline.bot/core-workflows/plan-and-act.md
- https://docs.cline.bot/tools-reference/all-cline-tools.md
- https://docs.cline.bot/sdk/model-providers.md
- https://docs.cline.bot/cli/cli-reference.md
- https://docs.cline.bot/features/auto-approve.md
- https://docs.cline.bot/customization/cline-rules.md
- https://docs.cline.bot/mcp/mcp-overview.md
- https://docs.cline.bot/troubleshooting/networking-and-proxies.md
- https://docs.cline.bot/enterprise-solutions/monitoring/telemetry.md
- https://cline.bot/blog/cline-v3-35 (native tool calling, models list as of that release)
- https://github.com/cline/cline and https://github.com/cline/cline/releases (v4.1.26 extension, CLI v3.0.74, 26 Oct)
- https://docs.z.ai/guides/llm/glm-5.2 (GLM 5.2: 1M context, 128K output, function call)
- https://dev.to/akaranjkar08/glm-52-zai-ships-1m-token-coding-model-with-zero-benchmarks-35d (third party, dated 2026-06-15)
- https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16 (model card)
- NIM tool calling: https://docs.nvidia.com/nim/large-language-models/1.15.0/function-calling.html and https://docs.nvidia.com/nim/large-language-models/2.0.12/advanced-use-cases/tool-calling-and-mcp.html (seen in search results; the 'latest' page returned empty when fetched; I did not open the versioned pages directly)
- https://code.visualstudio.com/docs/setup/network
- https://nginx.org/en/docs/http/ngx_http_proxy_module.html
- https://docs.litellm.ai/docs/providers/openai_compatible
