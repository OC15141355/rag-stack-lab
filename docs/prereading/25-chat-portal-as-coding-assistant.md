# Using a chat portal as your coding assistant

## In one paragraph

When an agentic tool like Cline isn't available, a chat portal in front of a
capable model (GLM 5.2, say) still makes a good coding assistant. The
difference is that **you** are the agent: you choose which files it sees,
paste them in, and apply what comes back. This document covers doing that
well from the command line: packing repo context, prompt templates that get
useful answers, getting changes back into the repo safely, keeping sessions
clean, and, where an API is permitted, scripting the same thing in a few lines
of Python.

## The plain version

Think of a brilliant consultant who works by post. They can't walk around your
building, open drawers or run anything. They only see what you put in the
envelope, and they send back advice and drafted changes.

So the skill moves to you:
- **Packing the envelope.** Send the right files, with file names and line
  numbers, plus a short note on what the project is. Too little and they
  guess; too much and the important part gets lost (and the envelope has a
  size limit).
- **Asking a precise question.** "Explain this repo" gets a vague essay.
  "Trace a request through these three files and cite line numbers" gets
  something you can check.
- **Checking and applying the reply yourself.** The consultant never saw the
  running system. Every claim is a hypothesis until you've checked it against
  the code and run it.

Done well, this is slower than an agent but teaches you more. Every file you
choose to send forces you to decide what matters, which is exactly the skill
of reading an established codebase.

**Five things to remember**

1. You choose the context. Send names, line numbers and a project primer.
2. One question per conversation; carry a short summary forward to the next.
3. Ask for citations and diffs; verify both.
4. Never paste secrets, `.env` files, credentials or real user data. The
   portal stores conversations, and an insights pipeline may read them.
5. Apply changes through git (`git apply --check` first), then run the tests.

## 0. Before you start

*Plain gloss: make sure you're allowed, and know where your pastes go.*

- Confirm that pasting the project's code into the portal is allowed. It
  usually is for an internal, self-hosted model, but ask once.
- Assume everything you paste is **stored** and may be **read by an insights
  pipeline** ([17](17-clio-conversation-insights.md),
  [24](24-clio-pipeline-reading-and-deploying.md)). Paste code, not secrets.
- Find the portal's real limit. Paste increasingly large blocks until it
  refuses or the answers clearly lose the early material. A rough estimate is
  **1 token ≈ 4 characters of code**, so `wc -c` ÷ 4 gives you the size.
  Practical sweet spot: under a third of the limit per message, so the reply
  and follow-ups fit too.

## 1. Map before you pack

*Plain gloss: find the handful of files that matter before sending anything.*

```sh
git ls-files | wc -l                                  # how big is it
git ls-files | sed 's#/[^/]*$##' | sort | uniq -c | sort -rn | head -20   # where the files are
rg -n '@(app|router)\.(get|post|put|delete|patch)\(' --type py            # FastAPI routes
rg -n 'FastAPI\(|APIRouter\(' --type py                                    # app and routers
rg -n '_URL|BASE_URL|base_url' --type py -g '!*test*' | head -30           # outbound calls
rg -n 'fetch\(|axios\.|useQuery\(' -g '*.ts' -g '*.tsx' | head -30         # frontend → backend calls
git log --oneline -15 -- <path>                                            # recent history of an area
```

(`rg` is ripgrep. Without it, use `grep -rn`.) Pick 3–8 files for the
question you have. That selection *is* understanding.

## 2. Pack the context

*Plain gloss: turn the chosen files into one paste, with file names and line
numbers so the model can cite them.*

### 2.1 No-install version (plain shell)

Put this in your shell profile **inside the dev container**:

```sh
# ctx FILE... : print files with headers and line numbers, copy to clipboard, report size
ctx() {
  local out
  out=$(for f in "$@"; do
    case "$f" in (*.env|*.env.*|*secret*|*.pem|*.key) echo "SKIPPED $f (sensitive)" >&2; continue;; esac
    printf '\n===== %s =====\n' "$f"
    nl -ba -w4 -s'  ' "$f"
  done)
  printf '%s\n' "$out" | { pbcopy 2>/dev/null || xclip -selection clipboard 2>/dev/null || wl-copy 2>/dev/null || clip.exe 2>/dev/null || cat; }
  echo "~$(( ${#out} / 4 )) tokens copied" >&2
}

ctx app/main.py app/routes/chat.py app/settings.py
ctx $(git ls-files 'app/routes/*.py')
```

In a dev container the clipboard may not reach your laptop. If nothing
pastes, redirect to a file instead (`ctx ... > /tmp/ctx.txt`), open it in VS
Code, select all and copy.

### 2.2 Tools, if they're available or approved

Both need a package download (npm or PyPI). In a restricted environment,
check that the registry mirror has them and that installing them is allowed.

**Repomix** (Node): packs a repo or subset into one file. It runs a
**secret scan by default** (Secretlint) and leaves out flagged files.

```sh
npx repomix --include "app/**/*.py,pyproject.toml" --style markdown \
  --output-show-line-numbers --copy              # copy to clipboard
npx repomix --include "app/**/*.py" --compress -o /tmp/ctx.md   # signatures/structure only, much smaller
npx repomix --token-count-tree                   # where the tokens are; decide what to leave out
```

Other flags: `-i/--ignore`, `--remove-comments`, `--stdout`, and
`--no-security-check`. Don't use that last one.

**files-to-prompt** (Python):

```sh
uvx files-to-prompt app -e py -n -m -o /tmp/ctx.md    # .py files, line numbers, markdown fences
uvx files-to-prompt app --ignore "*test*" -c          # Claude-style XML wrapping
git ls-files -z 'app/*.py' | uvx files-to-prompt --null -n
```

Neither tool reads your intent. Pack only what the question needs.

### 2.3 A project primer you reuse

Keep a private `primer.md` (not in the work repo unless the team wants it) and
paste it first in every new conversation. It does the job `.clinerules` does
for an agent:

```markdown
Project: <one sentence: what this service does>
Stack: Python 3.x, FastAPI, uv; React + TypeScript frontend; deployed via Helm/Tilt to Kubernetes.
Request path: browser → ingress → portal backend → gateway → model server.
Conventions: <formatter, test command, commit style>
Rules for you: cite file:line for every claim; say "not in the provided files" instead of guessing;
propose changes as unified diffs against the files I gave you; keep changes minimal.
```

## 3. Prompt templates

*Plain gloss: precise questions with a required answer format get checkable
answers.*

**Orient**
```
[primer]
Here are the entry point, the route file and the settings file. List: how the service starts,
every route (method, path, handler file:line), and every external service it calls (setting name
→ where used, file:line). Table format. Don't describe anything not in these files.
```

**Trace one request**
```
Trace POST /v1/chat/completions from arrival to response. One line per step:
file:line — what happens — does it call out of the process (yes/no, to what).
Mark anything you're inferring rather than reading.
```

**Explain one file** (then explain it back)
```
Explain this file for someone who knows Kubernetes and HTTP well but is new to FastAPI.
Then ask me 3 questions to check I understood.
```

**Propose a change**
```
Goal: <one sentence>. Constraints: minimal change, keep style, no new dependencies.
Answer with: (1) a 3-line plan, (2) a unified diff (git format, paths relative to repo root)
against exactly the files I provided, (3) how to test it.
```

**Review my change**
```
Here's my diff (git diff output) and the files it touches. List bugs, edge cases and
style mismatches, most serious first, each with file:line. Don't rewrite the diff.
```

**Debug**
```
Here is the error and the stack trace, the code around each frame (with line numbers),
and what I expected. Give the 3 most likely causes ranked, and for each the one command
or check that would confirm or rule it out.
```

## 4. Getting changes back into the repo

*Plain gloss: let git check that the proposed change fits before it touches
your files.*

```sh
pbpaste > /tmp/change.diff            # or save the reply's diff block to a file in VS Code
git apply --check /tmp/change.diff    # does it apply cleanly?
git apply --recount /tmp/change.diff  # LLM diffs often get the hunk line counts wrong
git diff                              # read what actually changed
<run tests / tilt rebuild>
```

If the diff won't apply, don't hand-fix it. Ask for the **complete new
version of one function** and paste it in yourself. Small changes in small
steps, like the advice for Cline (doc 19, 1.5).

Then commit through the project's normal flow (doc 21: `git add -p`, the
commit tool, the hooks).

## 5. Session hygiene

*Plain gloss: long conversations get worse; start fresh often and carry a
summary.*

- **One question per conversation.** When the topic changes, start a new one.
- At the end, ask: *"Summarise what we established in 10 lines, with file:line
  references."* Save that to your private notes. It becomes the opening
  context for the next conversation, and your own map of the codebase.
- If answers start contradicting earlier ones or forgetting the files, the
  context is full or muddled. Start fresh with the primer and the summary.
- If the model reasons visibly (GLM 5.2 thinks by default), simple lookups
  are slow. That's expected.

## 6. Verify everything

*Plain gloss: the model never saw the running system; treat claims as leads.*

```sh
rg -n '<function or symbol it named>'        # does it exist where it says?
sed -n '120,160p' app/routes/chat.py         # read the cited lines yourself
```

Red flags: function names that don't exist, confident claims about files you
didn't send, config keys that aren't in the settings file, "typically"
explanations instead of citations. Run it: a passing test or a working curl
beats any explanation.

## 7. Via code, if an API is permitted

*Plain gloss: if you're allowed an API key for the same model, a short script
does the packing and asking for you. Don't automate the web UI itself.*

Only if you've been given an API endpoint and key for the model (the portal's
own API, the inference service, or the gateway) **and** scripted use is OK.
Don't script or scrape the browser UI.

```python
# ask.py — usage: uv run ask.py "question" file1 file2 ...
# /// script
# dependencies = ["openai>=1.40"]
# ///
import os, sys, pathlib
from openai import OpenAI

client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
question, files = sys.argv[1], sys.argv[2:]
primer = pathlib.Path(os.environ.get("PRIMER", "primer.md"))
ctx = "".join(
    f"\n===== {f} =====\n" + "".join(f"{i:4}  {l}" for i, l in enumerate(open(f), 1))
    for f in files
)
stream = client.chat.completions.create(
    model=os.environ["LLM_MODEL"],
    stream=True,
    messages=[
        {"role": "system", "content": primer.read_text() if primer.exists() else ""},
        {"role": "user", "content": f"{ctx}\n\nQuestion: {question}"},
    ],
)
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
print()
```

```sh
export LLM_BASE_URL=<endpoint>/v1 LLM_MODEL=<model id from /v1/models> LLM_API_KEY=<key>
uv run ask.py "Trace POST /v1/chat/completions, cite file:line" app/main.py app/routes/chat.py
```

`uv run` reads the inline `# /// script` block and installs `openai` in a
throwaway environment. Run the endpoint probes from doc 15 first. With a
reasoning model, the thinking may arrive in a separate field and won't print;
see doc 19, 1.1.

## 8. What you lose compared with an agent, and how to compensate

| An agent does | You do instead |
|---|---|
| Finds relevant files itself | Section 1: map with `rg` and `git ls-files` |
| Reads more files when needed | Answer its "not in the provided files" with another `ctx` |
| Applies edits | `git apply --check`, then apply |
| Runs tests and reads output | Run them; paste the failure back with the code |
| Remembers across steps | Summary at the end of each conversation, primer at the start |

## Check yourself

1. Why paste with line numbers, and what instruction makes them useful?
2. What should never go into a portal conversation, and why does an insights
   pipeline make that more important?
3. A proposed diff fails `git apply --check`. What do you do?
4. When do you start a new conversation, and what do you carry over?
5. When is the script in section 7 appropriate, and when isn't it?

## References (checked 2026-11-18)

- Repomix: https://github.com/yamadashy/repomix
- files-to-prompt: https://github.com/simonw/files-to-prompt
- uv inline script metadata: https://docs.astral.sh/uv/guides/scripts/
- OpenAI Python client (streaming): https://github.com/openai/openai-python
- `git apply`: https://git-scm.com/docs/git-apply
- ripgrep: https://github.com/BurntSushi/ripgrep
