# uv, FastAPI and React with TypeScript: a primer

## In one paragraph

This is a map of the application layer you will touch in the project. uv is the Python tool that creates environments, pins dependencies in a lock file and runs commands. FastAPI is the Python web framework used to write the inference service's HTTP API, including routes that stream model output. React with TypeScript is how a browser front end (for example a chat page) is built and typed; Vite is the tool that serves it during development and bundles it for production. The aim is that you can read these codebases, run them, and make small changes, not that you become a front-end developer. Docs checked 2026-11-13; most pages state no version (exceptions are noted inline: FastAPI SSE needs 0.135.0 or later, Vite needs Node 20.19+ or 22.12+).

## The plain version

Picture a restaurant. The kitchen is the part that does the real work (the language models). Customers sit in the dining room (the web page in the browser). Between them is a waiter who takes orders, carries them to the kitchen, and brings the food back plate by plate as each comes out, rather than waiting for the whole meal. FastAPI is the waiter. React is how the dining room is laid out and updated: when a new plate arrives, only that part of the table changes. uv is the person who orders supplies and makes sure that every branch of the restaurant stocks the exact same brands in the same quantities, written on a shopping list that nobody edits by hand.

Without these pieces, every developer would install slightly different versions of everything, the browser page would have to be rebuilt by hand whenever data changed, and answers from the model would only appear after the whole thing was finished, which feels broken when a reply takes thirty seconds.

If you remember only five things:

- `pyproject.toml` says what you want; `uv.lock` records exactly what you got. Commit both.
- `uv run <command>` is the way to run anything; it keeps the environment in sync first.
- FastAPI turns a typed Python function into an HTTP route and checks the incoming data for you.
- For streamed model output, the server sends many small pieces over one open connection and the browser reads them as they arrive.
- In production, the React app is just static files that something (the API server or a web server) hands to the browser.

## Why it exists

You already know the shapes. uv is to Python what a lock file plus a pinned toolchain is to Go modules or Helm chart versions: a reproducible set of inputs. FastAPI is a small framework like the HTTP handlers you may have written in Go, except that types drive validation and documentation. React is the unfamiliar one: a way to describe a page as a function of data, so that when data changes the page updates itself. Think of it as a reconcile loop for the DOM (the browser's tree of page elements): you declare what the page should look like for the current state, and React works out the diff.

## How it works

### uv

Plain gloss: uv installs the right Python and the right libraries into a private folder for the project, and records exactly which versions it chose.

- `pyproject.toml` holds project metadata and dependency requirements, and may hold `[tool.uv]` settings. `uv.lock` is the cross-platform lock file; commit it, do not edit it by hand. `.venv/` is the project's virtual environment (an isolated folder of installed packages). `.python-version` sets the default Python version.
- uv respects `requires-python` in `pyproject.toml`. By default it downloads a Python version if it cannot find a suitable one.
- `uv run` runs a command in the project environment. `uv sync` brings `.venv` in line with the lock file.
- Tools: `uvx ruff` (alias for `uv tool run`) runs a tool in a temporary isolated environment; `uv tool install ruff` puts it on your PATH.

### FastAPI

Plain gloss: you write ordinary Python functions with type hints, and FastAPI turns them into web endpoints that check input, produce documentation, and run many requests at once.

- ASGI is the standard interface between Python async web apps and the servers that run them; uvicorn is a common ASGI server. UNVERIFIED: I could not open the uvicorn site (host did not resolve), so treat statements about uvicorn flags as from memory; the FastAPI docs instead use `fastapi dev` and `fastapi run`.
- A path operation is a function bound to a method and a URL, such as `@app.get("/")`.
- A request body is declared as a Pydantic model (a class with typed fields). FastAPI reads the JSON, converts and validates it, returns a clear error if invalid, passes your function a typed object, and generates JSON Schema in the OpenAPI document and the interactive docs at `/docs`.
- Dependency injection: you declare what a function needs with `Annotated[T, Depends(fn)]`; FastAPI calls `fn` per request and passes the result. Use it for settings, HTTP clients, auth. `Annotated` needs FastAPI 0.95.0 or later.
- `async def` versus `def`: use `async def` when the code awaits things (such as an HTTP call with httpx); use `def` for blocking libraries, which FastAPI runs in a threadpool. Blocking inside `async def` stalls the whole server. When unsure, use `def`.
- Lifespan: startup and shutdown code goes in an `@asynccontextmanager` function passed as `FastAPI(lifespan=...)`. Code before `yield` runs once at start, after it at shutdown. The old `on_event` handlers are deprecated, and if you pass `lifespan` they are ignored.

## How you run it

### uv commands

```sh
uv init inference-service              # new project (use `uv init awesome --bare` for a minimal pyproject.toml)
uv add "fastapi[standard]" httpx pydantic-settings   # add deps; updates pyproject.toml and uv.lock, creates .venv
uv add --dev pytest                    # dev-only dependency (--dev flag: UNVERIFIED on the pages I opened)
uv sync                                # make .venv match uv.lock
uv sync --locked                       # fail if lock is out of date (as used in the Docker guide)
uv run fastapi dev                     # dev server with auto-reload at http://127.0.0.1:8000, docs at /docs
uv run fastapi run                     # production-style run
uv run pytest -q                       # run tests in the project env
uv lock --upgrade-package httpx        # bump a single package
uv python list                         # show installed/available Pythons
uv python pin 3.12                     # write .python-version
uvx ruff check .                       # run a tool without installing it
uv tool install ruff                   # install a tool onto PATH, isolated
```

### uv in a Dockerfile (from docs.astral.sh/uv/guides/integration/docker)

```dockerfile
FROM python:3.12-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /uvx /bin/     # pin a version tag; the page uses 0.13.8 as its example
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project       # layer with deps only; cached until the lock changes
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
ENV PATH="/app/.venv/bin:$PATH"
CMD ["fastapi", "run", "app/main.py", "--port", "8000"]
```

The guide also advises adding `.venv` to `.dockerignore`, using multi-stage builds with `uv sync --frozen --no-install-project --no-editable` and copying only `/app/.venv` to the final stage (with `UV_PYTHON_DOWNLOADS=0`). The bind-mount of `pyproject.toml` in my version is a small extension of the guide's `uv.lock`-only example: UNVERIFIED. Note that `RUN --mount` needs a builder that supports it; whether Podman's build path supports `--mount=type=cache` and `type=bind` here: UNVERIFIED, test on your Podman version.

### A minimal service with settings, tests, and an OpenAI-compatible proxy route

Written by me from documented pieces; UNVERIFIED by execution.

```python
# app/main.py
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    upstream_base: str = "http://nim.local:8000/v1"   # env var UPSTREAM_BASE overrides (case-insensitive)
    upstream_key: str = ""
    model_config = SettingsConfigDict(env_file=".env")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = Settings()
    # read=300: wait up to 5 min between chunks (httpx default is 5 s of inactivity)
    app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=300.0))
    yield
    await app.state.client.aclose()


app = FastAPI(lifespan=lifespan)


def get_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.client


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.post("/v1/chat/completions")
async def chat(
    request: Request,
    client: Annotated[httpx.AsyncClient, Depends(get_client)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    body = await request.json()          # pass the OpenAI-shaped body through untouched
    headers = {"Authorization": f"Bearer {settings.upstream_key}"}
    url = f"{settings.upstream_base}/chat/completions"

    if not body.get("stream"):
        r = await client.post(url, json=body, headers=headers)
        return r.json()                  # status code is dropped here; handle errors in real code

    async def relay() -> AsyncIterator[bytes]:
        async with client.stream("POST", url, json=body, headers=headers) as r:
            async for chunk in r.aiter_bytes():     # forward raw SSE bytes as they arrive
                yield chunk

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},   # ask nginx not to buffer
    )
```

What is documented: `client.stream()` and `aiter_bytes()` (httpx async docs), `StreamingResponse` accepting an async generator (FastAPI docs), `Timeout` syntax (httpx), the `X-Accel-Buffering: no` header (nginx docs), lifespan and `Depends` patterns. What is not: passing `media_type` to `StreamingResponse` (the FastAPI page I opened did not show it; I believe it is a standard Starlette argument); that errors from upstream during a stream are handled sensibly (they are not here). FastAPI 0.135.0+ also has a built-in `EventSourceResponse` (`from fastapi.sse import EventSourceResponse`) that JSON-encodes each yielded item into an SSE `data:` field, sends a ping comment every 15 seconds and sets `Cache-Control: no-cache` and `X-Accel-Buffering: no`. It re-encodes items, so for a byte-for-byte relay of an upstream's stream, plain `StreamingResponse` is the simpler fit (my judgement). Raw `data: [DONE]` lines need its `raw_data` field.

Tests:

```python
# tests/test_health.py
from fastapi.testclient import TestClient
from app.main import app

def test_health():
    with TestClient(app) as client:        # `with` runs lifespan startup/shutdown
        assert client.get("/healthz").json() == {"ok": True}
```

`TestClient` is built on httpx; install `httpx` and `pytest`; tests are plain `def` with no `await`. Using it as a context manager to trigger lifespan is my usage and is UNVERIFIED on the page I opened. Override dependencies in tests with `app.dependency_overrides[get_settings] = override` (documented in the settings page).

Settings: `pydantic-settings` `BaseSettings` reads environment variables case-insensitively; `model_config = SettingsConfigDict(env_file=".env")` also reads a `.env` file.

### React with TypeScript

Plain gloss: a React page is built from small functions called components; each returns a description of a piece of the page, and React redraws only what changed when the data behind it changes.

- Component: a function that returns markup (JSX, HTML-like syntax inside JavaScript). Names start with a capital letter. `.tsx` is the file extension for TypeScript with JSX.
- Props are inputs passed from parent to child as attributes. State is data a component remembers: `const [x, setX] = useState(initial)`; calling `setX` re-renders.
- Hooks are functions starting with `use`; call them only at the top level of a component (not in loops or conditions).
- Effects (`useEffect`) synchronise a component with something outside React after rendering. The second argument is the dependency array: `[]` runs on mount, `[a, b]` re-runs when they change. Return a cleanup function. In development Strict Mode runs setup, cleanup, setup once to expose missing cleanup, so a fetch effect may run twice; this is expected.
- TypeScript: types for props, state and data. `useState<Status>("idle")`, `interface Props { title: string }`, `React.ChangeEvent<HTMLInputElement>` for input events.

Create and run (Vite docs; Node 20.19+ or 22.12+):

```sh
npm create vite@latest chat-ui -- --template react-ts   # scaffold (note the extra -- for npm 7+)
cd chat-ui && npm install
npm run dev        # dev server, default http://localhost:5173
npm run build      # production build (vite build); output goes to dist/ (dist/ default: UNVERIFIED on the pages opened)
npm run preview    # serve the build locally
```

Dev proxy so the browser calls the API without cross-origin trouble (`server.proxy`, documented in Vite server options):

```ts
// vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: true, proxy: { '/v1': 'http://localhost:8000' } },  // host: true listens on all addresses (needed inside a container)
})
```

A streamed chat component. The read loop (`getReader`, `read()`, `{done, value}`) is from MDN; the decoding and SSE parsing are mine and simplified (UNVERIFIED by execution; real SSE parsing must also handle events split across chunks, which the buffer below does):

```tsx
// src/Chat.tsx
import { useState } from 'react'

interface ChatChunk { choices: { delta: { content?: string } }[] }

export default function Chat() {
  const [prompt, setPrompt] = useState('')
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)

  async function send() {
    setBusy(true); setAnswer('')
    const res = await fetch('/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: 'glm-5.2', stream: true,
                             messages: [{ role: 'user', content: prompt }] }),
    })
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })   // keeps multi-byte characters intact
      const lines = buffer.split('\n'); buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.startsWith('data: ') || line.includes('[DONE]')) continue
        const chunk = JSON.parse(line.slice(6)) as ChatChunk
        setAnswer(a => a + (chunk.choices[0]?.delta?.content ?? ''))
      }
    }
    setBusy(false)
  }

  return (
    <div>
      <input value={prompt} onChange={e => setPrompt(e.target.value)} />
      <button onClick={send} disabled={busy}>Send</button>
      <pre>{answer}</pre>
    </div>
  )
}
```

This uses an event handler (a click) rather than an effect, which is the right place for "user sends a message". The `delta.content` shape follows the OpenAI chat streaming format; confirm against your endpoint's output from doc 15's curl test. For typing API responses in general, write an `interface` that mirrors the JSON and cast or validate the parsed value; types are erased at runtime, so they do not validate anything by themselves (standard TypeScript behaviour, not from the pages opened).

## How it fits the stack

- The Python inference service (run with uv) is the thing Cline (doc 15) and the React page call. It fronts the NIMs, so it needs a streaming-safe, OpenAI-shaped route like the sketch above.
- It runs in the dev container (doc 13) and deploys to the cluster through Tilt (doc 14) using the uv Dockerfile pattern. Tilt `fall_back_on` should list `pyproject.toml` and `uv.lock`; code changes sync in and `--reload` restarts the server.
- Serving the built front end in a container: build the React app (`npm run build` in a Node build stage), copy the output into the Python image, and mount it with `app.mount("/", StaticFiles(directory="dist", html=True), name="spa")` after your API routes. The FastAPI page I opened notes `html=True` comes from Starlette, not that page, and mentions an `app.frontend()` helper; I did not read that page, so check it before hand-writing the mount (UNVERIFIED). Alternatively serve the static files from nginx and proxy `/v1` to the API.
- Behind a gateway like LiteLLM: your service can either call it as its upstream (OpenAI-compatible, `openai/<name>` with `api_base` ending `/v1`) or be called by it.

## What goes wrong

- `uv run` or `uv sync` rewrites the lock unexpectedly: use `--locked` in CI and Docker to fail instead.
- Image builds are slow: dependency layer not separated; copy `pyproject.toml` and `uv.lock` first, sync with `--no-install-project`, then copy source.
- `.venv` copied into the image from your Mac: the virtualenv is platform-specific; add `.venv` to `.dockerignore`.
- Server hangs under load: a blocking call inside an `async def` route.
- Streamed output arrives in one lump: a buffering proxy, or a client that waits for the whole body. Check with `curl -N`.
- httpx `ReadTimeout` on slow first tokens: default is 5 seconds of inactivity; raise `read`.
- `async` generator keeps running after the client disconnects: FastAPI notes that cancellation only happens at an `await`.
- Browser: CORS (cross-origin request) errors in dev if you call another origin directly: use the Vite proxy or CORS middleware (CORS middleware not covered by pages opened).
- Effect fires twice in dev: Strict Mode, expected; fix missing cleanup, do not guard with refs.
- Blank page after deployment: SPA mounted before API routes so it shadows them, or the build was not copied into the image.
- Vite dev server unreachable from the host when running in a container: `host` defaults to `localhost`; set `host: true` and forward port 5173.

## Check yourself

1. What is the difference between `pyproject.toml` and `uv.lock`, and which command fails if they disagree?
2. Why is `uv sync --frozen --no-install-project` run before copying the source in a Dockerfile?
3. When should a FastAPI route be `async def` versus `def`, and what breaks if you get it wrong?
4. What does `Depends` do, and how would you replace the settings object in a test?
5. How does a proxy route relay a model's streamed reply without buffering it, and which headers and timeouts matter?
6. What are props, state and an effect, and why does a fetch effect often run twice in development?
7. In the Chat component, why is the incoming text accumulated in a buffer and split on newlines?
8. How does the built React app get to the browser in a container, and what must be true about route ordering if FastAPI serves it?

## References

All checked 2026-11-13. Pages generally show no version number.

- https://docs.astral.sh/uv/guides/projects/ , https://docs.astral.sh/uv/concepts/python-versions/ , https://docs.astral.sh/uv/guides/tools/ , https://docs.astral.sh/uv/guides/integration/docker/ (example uv tag 0.13.8)
- https://fastapi.tiangolo.com/tutorial/ , /tutorial/body/ , /tutorial/dependencies/ , /async/ , /advanced/events/ , /advanced/settings/ , /tutorial/testing/ , /tutorial/static-files/ , /advanced/custom-response/ , /tutorial/server-sent-events/ (SSE added in FastAPI 0.135.0)
- https://www.python-httpx.org/async/#streaming-responses and https://www.python-httpx.org/advanced/timeouts/
- https://nginx.org/en/docs/http/ngx_http_proxy_module.html (X-Accel-Buffering)
- https://react.dev/learn , https://react.dev/learn/typescript , https://react.dev/learn/synchronizing-with-effects (no React version stated)
- https://vite.dev/guide/ (Node 20.19+ / 22.12+) and https://vite.dev/config/server-options.html
- https://developer.mozilla.org/en-US/docs/Web/API/Streams_API/Using_readable_streams
- Not reachable: https://www.uvicorn.org/ (DNS failure)
