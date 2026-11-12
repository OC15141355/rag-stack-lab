# Reading an established repo

**In one paragraph.** You will be handed repositories other people have been
building for months: a Python inference service, a chat portal with a React
frontend and FastAPI backend, Helm charts, Tiltfiles. You cannot read them top
to bottom, and you do not need to. This document gives a repeatable method:
find out how the thing is run, find where a request enters, follow one request
all the way through, and write down a one-page map. It works on any repo, and
it has specific pointers for the kinds of repo in this stack.

## The plain version

Reading a codebase is like arriving in a city you have never visited. You do
not learn it by walking every street in order. You get a map, find the main
station and the main roads, then take one real journey from the station to
somewhere you need to go, noticing what you pass. After that one journey the
map means something, and every later trip is easier.

In a repo, the "map" is the folder layout and the config files. The "main
station" is the entry point: the place where the program starts or where a
request arrives. The "journey" is following one request through the code, file
by file, until the response goes back out.

Without a method you either read randomly and remember nothing, or wait for
someone to explain it, which never fully happens.

If you remember only five things:

- Start with **how it is run**, not with the source code.
- Find the **entry point**, then follow **one request** end to end.
- **Run it and break it.** A log line or a breakpoint teaches more than an
  hour of reading.
- Read **tests and git history**: they show what the code is meant to do and
  why it changed.
- **Write a one-page map.** If you cannot write it, you have not understood it
  yet.

## Why a method is needed

Source files are arranged for the people who wrote them, not for a newcomer.
Most of a repo is detail you do not need on day one: error handling, edge
cases, helpers. What you need first is the skeleton: what starts, what calls
what, what talks to the outside. A method gets you the skeleton quickly and
tells you which details to ignore for now.

You already do this with infrastructure. Faced with an unfamiliar cluster you
do not read every manifest; you list namespaces, look at ingresses, pick one
service and follow it to its pods and config. This is the same move applied to
code.

## How it works: five passes

Each pass has a time box. Stop when the time is up, even if you feel you have
not finished. The passes build on each other.

```
Pass 1  Orient      15 min   What is this and how is it run?
Pass 2  Run         30 min   Get it running; see it respond
Pass 3  Entry       20 min   Where does a request come in?
Pass 4  Trace       60 min   Follow one request to the end and back
Pass 5  Map         20 min   Write the one-page map
```

### Pass 1: Orient (do not open source files yet)

Read the files that describe the project from the outside. In rough order:

| File | What it tells you |
|---|---|
| `README.md`, `docs/`, `CONTRIBUTING.md` | What the authors think you need to know |
| `pyproject.toml`, `uv.lock` | Python version, dependencies, and under `[project.scripts]` the commands that start things |
| `package.json` | Frontend dependencies and, under `scripts`, how to start, build and test |
| `Dockerfile` / `Containerfile` | The final `CMD` or `ENTRYPOINT` is exactly how the service starts in production |
| `Tiltfile` | Every service in the dev environment, how each is built, and which ports are forwarded |
| `.devcontainer/devcontainer.json` | The tools and environment the team actually develops with |
| `helm/` or `charts/` (`values.yaml`) | Every configuration knob and every other service this one talks to |
| `.env.example`, settings module | Environment variables: the list of external dependencies in disguise |
| `.github/workflows/`, `.gitlab-ci.yml` | What must pass before code merges: the real definition of "working" |
| `Makefile`, `justfile`, `scripts/` | The commands the team runs every day |

The dependency list is a table of contents. If `pyproject.toml` lists
`fastapi`, `httpx`, `opensearch-py`, `neo4j` and `opentelemetry-sdk`, you
already know the service is a web API that calls other HTTP services, a search
engine and a graph database, and emits traces.

Useful commands:

```bash
git log --oneline | wc -l                 # how much history there is
git log --format='%an' | sort | uniq -c | sort -rn | head   # who to ask
git log --since='2 months ago' --name-only --format= | sort | uniq -c | sort -rn | head -20
                                          # files changing most: where the work is
find . -type f -not -path './.git/*' -not -path '*/node_modules/*' \
  | sed 's|/[^/]*$||' | sort | uniq -c | sort -rn | head -20
                                          # which folders hold the most files
```

### Pass 2: Run it

Get it running the way the team does: open the dev container, run `tilt up`,
or follow the README. Then make one request and see one response. Use the
tests too:

```bash
uv sync                # install exactly the locked dependencies
uv run pytest -x -q    # run tests, stop at first failure
npm ci && npm test     # frontend equivalents
```

If it will not run, that is your first useful finding. Write down what was
missing; the next newcomer hits the same wall.

FastAPI services publish their own API description. With the service running,
open `/docs` (interactive) or fetch `/openapi.json`. That is a complete list
of every route, generated from the code, so it cannot be out of date.

### Pass 3: Find the entry points

An entry point is where execution begins or where the outside world gets in.

**Python / FastAPI backend.** Find the app object and the routes:

```bash
grep -rn "FastAPI(" --include='*.py' .          # where the app is created
grep -rn "include_router" --include='*.py' .    # how route files are attached
grep -rnE "@(app|router)\.(get|post|put|delete|patch)" --include='*.py' .
                                                # every route, with file and line
grep -rn "Depends(" --include='*.py' . | head   # shared logic injected into routes (auth, DB)
grep -rn "lifespan\|on_event" --include='*.py' .  # what happens at startup and shutdown
```

**React / TypeScript frontend.** Find where it mounts, its pages, and its API
calls:

```bash
grep -rn "createRoot" src/                      # where the app starts (usually main.tsx)
grep -rnE "createBrowserRouter|<Route " src/    # the list of pages
grep -rnE "fetch\(|axios|EventSource|useQuery" src/ | head -30
                                                # every place the frontend calls the backend
```

**Deployment.** In the Helm chart or manifests, find the `Ingress` or
`IngressRoute` (what URL reaches this service), the `Service` (which port),
and the `Deployment`'s `env` and `envFrom` (what configuration it receives and
which other services it is told about).

### Pass 4: Trace one request

Pick the single most important thing the service does. For an inference
service that is `POST /v1/chat/completions`. For a chat portal it is "user
sends a message".

Start at the route handler found in pass 3 and follow it. At every function
call, ask one question: *does this talk to something outside the process?* If
no, skim it. If yes (HTTP call, database query, queue, file), stop and note
what it calls and with what.

Keep a running list as you go:

```
POST /v1/chat/completions
  routes/chat.py:42      handler; validates body with ChatRequest model
  deps/auth.py:17        checks API key header              -> (outside: key store?)
  services/router.py:63  picks upstream by model name       <- config: MODEL_MAP
  clients/nim.py:28      httpx stream to upstream /v1/chat/completions  -> OUTSIDE: NIM
  routes/chat.py:71      wraps upstream chunks as SSE back to caller
```

That list of five to ten lines *is* your understanding of the service.

Confirm it by running, not by trusting your reading:

- Add a temporary log line or set a breakpoint in the handler and send a
  request. Does it hit?
- Turn on debug logging and watch the outgoing call.
- If tracing is enabled, find the request's trace in the tracing UI. The spans
  are the same list you just wrote, produced by the system itself.
- Change one thing (a model name, a header) and predict what will happen
  before you send it.

For the frontend, open the browser's developer tools, go to the Network tab,
perform the action, and click the request. You see the URL, the body sent, and
the streamed response. Then search the source for that URL path to find the
code that sent it.

### Pass 5: Write the map

One page, in your own words. Use this template:

```markdown
# <repo name> — map

**What it is (one sentence):**
**How to run it locally:**
**How it is deployed:**                 (image, chart, namespace)
**Entry points:**                       (routes, CLI commands, scheduled jobs)
**Talks to:**                           (each external service, and which env var points at it)
**Main request traced:**                (the list from pass 4)
**Where configuration lives:**
**Where tests live and how to run them:**
**Things I do not understand yet:**
**Who to ask:**
```

The last two lines are the most valuable. A specific question ("why does the
router retry on 429 but not 503?") gets a good answer from a colleague in two
minutes. "Can you walk me through the repo?" does not.

## Reading aids

**Tests as documentation.** A test file shows how the authors expect a piece
of code to be called and what it should return. Read the test for a function
before the function.

**History as explanation.** Code shows what; history shows why.

```bash
git log --oneline -- path/to/file.py     # the story of one file
git log -p -S 'MODEL_MAP' -- .           # every commit that added or removed that text
git blame -L 60,80 path/to/file.py       # who last changed these lines, in which commit
git show <commit>                        # the full change and its message
```

Merge or pull request descriptions linked from those commits often contain the
design discussion.

**Search over browsing.** Install `ripgrep` (`rg`). Searching for a string you
saw in the UI, a log message, a URL path or an environment variable name takes
you straight to the relevant code:

```bash
rg -n "chat/completions"            # where this path is defined and where it is called
rg -n "NIM_BASE_URL"                # where a config value is read
rg -n "class .*Settings" -t py      # the settings object: all config in one place
```

**Editor navigation.** In VS Code, "Go to Definition" (F12) and "Find All
References" (Shift+F12) follow calls without searching. They work best inside
the dev container, where the language servers have the right dependencies.

**Using a coding assistant to read.** Once Cline is connected to the internal
model, it is a good reading partner, provided you make it show evidence. Ask
for things you can check:

- "List every HTTP route in this service with file and line number."
- "Trace `POST /v1/chat/completions` from the route handler to the outgoing
  request. Cite file and line for each step."
- "Which environment variables does this service read, and where?"

Then open the cited lines and confirm. An assistant's summary of a repo is a
hypothesis; the file and line numbers are what make it checkable. Use plan
mode so it reads without editing. Only use an assistant the organisation has
approved for that code.

## How it fits the stack

Each repo you meet is one box on [the map](../00-map/README.md). Before
opening a repo, find its box and note the arrows in and out. Those arrows tell
you what to look for: the inference service must contain an outgoing HTTP
client pointed at the model servers; the portal backend must contain a call to
the inference service; anything doing retrieval must contain search-engine and
graph-database clients. Knowing what must be there turns reading into
confirming.

Suggested order for the repos in this stack:

1. **Inference service** — smallest, and everything else depends on it.
2. **Portal backend** — calls the inference service; holds users and
   conversations.
3. **Portal frontend** — calls the backend; easiest to explore through the
   browser's Network tab.
4. **Deployment repo / charts** — ties them together; read it last, when the
   service names mean something.

## What goes wrong

| Symptom | Cause | What to do |
|---|---|---|
| Hours spent, nothing retained | Reading files in order with no question in mind | Go back to pass 4: one request, one list |
| Lost in helpers and utilities | Following every call to the bottom | Only stop at calls that leave the process |
| The code "obviously" does X but behaves differently | Reading without running | Add a log line or breakpoint and send a request |
| Config value cannot be found in the repo | It is injected at deploy time | Look in the Helm values, ConfigMaps and Secrets |
| Route exists in code but returns 404 | The edge proxy or a path prefix rewrites it | Read the ingress route and any strip-prefix rule |
| README steps fail | Docs drifted from reality | Trust the Dockerfile, Tiltfile and CI config; then fix the README |
| Assistant's explanation was confidently wrong | Summary accepted without checking | Ask for file and line; open them |

## Check yourself

1. Why read the Dockerfile and Tiltfile before any source file?
2. What is an entry point, and what are the entry points of a FastAPI service?
3. While tracing a request, which function calls deserve your attention and
   which can you skim?
4. Name three ways to confirm a trace you produced by reading.
5. Where would you look for a configuration value that appears nowhere in the
   repo?
6. What does `git log -p -S 'text'` find that `grep` cannot?
7. What goes in the last two lines of a repo map, and why do they matter most?

## References

- FastAPI, automatic interactive API docs: https://fastapi.tiangolo.com/features/
- Git documentation, `git log` (pickaxe `-S`): https://git-scm.com/docs/git-log
- ripgrep user guide: https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md
- VS Code code navigation: https://code.visualstudio.com/docs/editing/editingevolved

This document is method, written from general practice; it was not researched
against a specific product release.
