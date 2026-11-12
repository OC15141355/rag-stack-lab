# Dev Containers

## In one paragraph

A dev container is a container that holds your development environment (compiler, interpreter, CLIs, editor extensions) instead of your laptop holding it. A file in the repo, `.devcontainer/devcontainer.json`, tells a supporting tool (VS Code, the `devcontainer` CLI, GitHub Codespaces, CI) how to build or pull that container, mount your source into it, and run setup commands. Everyone on the team then gets the same tool versions. For this project the engine under it is Podman rather than Docker, which works but is the "not officially supported" path, so most of the pain is in user-ID mapping, SELinux labels and the macOS VM. This document covers the file, the CLI, the Podman setup and how to reach a cluster and a private registry from inside.

Sources and versions: the spec pages on containers.dev show no version number (footer "2026 Microsoft"); the VS Code docs page is dated 11/11/2026; the devcontainer CLI install script example uses 0.82.0 (an example, not necessarily latest). All checked 2026-11-13.

## The plain version

Think of a professional kitchen versus cooking at home. At home, every cook uses their own pans, knives and half-remembered recipes, so the same dish tastes different each time. In a restaurant, every station is set up the same way: same knives, same pans, same labelled ingredients, and a new cook can start on day one. A dev container is that station, for people who write software. Instead of each person installing the right versions of tools on their own computer and slowly drifting apart, the project carries a written description of the workspace, and the computer builds an identical, sealed-off workspace from it.

Without it, a new person spends days installing things, and then hears "it works on my machine" every time something behaves differently. Small differences, such as a slightly older tool, cause confusing bugs that no one can reproduce. Cleaning up is also hard: if your laptop is full of half-installed tools, you cannot easily start fresh.

The catch for this project: the tool that builds the sealed workspace is normally Docker, and this team uses a different one, Podman. It mostly works, but you will meet some fiddly problems about who owns which files.

If you remember only five things:

- A dev container is a ready-made, identical workspace described in one file in the project.
- The file is `.devcontainer/devcontainer.json`.
- Your editor runs inside the workspace, so its extensions (including Cline) live there too.
- Podman replaces Docker through one VS Code setting, `dev.containers.dockerPath`.
- Most problems are about file ownership, or the workspace not being able to reach the cluster or registry.

## Why it exists

The problem: "works on my machine". Onboarding means installing the right Python, kubectl, Helm, Tilt, linters, and extensions, and those drift between people. You already know the cure in your own world: pin the toolchain in a declarative file and let a tool reconcile it. A dev container is that, for a workstation. It resembles a CI runner image that you also type into, and it resembles a Helm values file in the sense that the repo declares the desired environment.

The spec describes itself as metadata added to existing container formats; it does not create a new orchestrator. Its first format is `devcontainer.json`, "structured JSON with Comments (jsonc)". (containers.dev/overview)

## How it works

In plain terms: your editor is split in two, a thin front half on your computer and a working back half inside a container, and a small tool in the middle starts the container for you. The precise version follows.

```
 host (Mac / Linux)                       container engine (Podman)
 +---------------------+   CLI calls     +-----------------------------+
 | VS Code (UI side)   | --------------> | dev container               |
 | Dev Containers ext. |  dev.containers | - your repo (bind mount)    |
 +---------------------+  .dockerPath    | - VS Code server + most     |
                                         |   extensions (incl. Cline)  |
                                         | - tools: uv, kubectl, tilt  |
                                         +-----------------------------+
```

Per the VS Code docs: workspace files are bind-mounted from the local filesystem (or cloned into a volume); most extensions install and run inside the container, while UI extensions such as themes stay local; terminals open inside the container. The extension drives the engine through its CLI, not its socket API. That is why "Docker-compatible CLI" substitutes can work at all, and why the VS Code docs say other CLIs "may work" but are "not officially supported".

### Three ways to define the container

Plain gloss: you can describe the workspace as "use this ready-made box", "build a box from this recipe", or "start several boxes that work together".

1. Image: `"image": "mcr.microsoft.com/devcontainers/python:3.12"`. Simplest.
2. Dockerfile: `"build": { "dockerfile": "Dockerfile", "context": "..", "args": {...}, "target": "..." }`. Paths are relative to `devcontainer.json`. Use when you need to bake in a corporate CA or pinned tools.
3. Docker Compose: `"dockerComposeFile": "compose.yaml"`, `"service": "dev"`, optional `"runServices"`. Use when the dev container needs sidecars (for example a database). Later files in an array override earlier ones.

### Anatomy of the properties you will meet

Plain gloss: these are the settings on the workspace description: what to install, which doors to open, which user you are, and what to run after it is built.

All from containers.dev/implementors/json_reference (checked 2026-11-13):

- `features`: object whose keys are OCI references, for example `"ghcr.io/devcontainers/features/kubectl-helm-minikube:1": {}`. A Feature is a reusable bundle of metadata plus install scripts. The registry page lists `kubectl-helm-minikube` (1.3.2 at time of check) and `python` (1.8.1). No official `uv` Feature is listed; community ones exist (for example `ghcr.io/jsburckhardt/devcontainer-features/uv:1`).
- `forwardPorts`: array like `[3000, "db:5432"]`; makes container ports reachable on the host. `portsAttributes` sets labels and auto-forward behaviour. The docs recommend this over `appPort`.
- `mounts`: string or object using Docker `--mount` syntax, for example `{ "source": "...", "target": "...", "type": "bind" }`.
- `workspaceMount` and `workspaceFolder`: override where the source goes; they must be given together.
- `remoteUser`: the user your tools and terminals run as. `containerUser`: the user for everything in the container (defaults to root or the last `USER`). `updateRemoteUserUID` (default true): on Linux, aligns the container user's UID/GID with yours.
- `containerEnv`: environment fixed at container creation (needs rebuild to change). `remoteEnv`: environment for tool processes; changeable without rebuild. Variables: `${localEnv:NAME:default}`, `${localWorkspaceFolder}`, `${containerWorkspaceFolder}`, `${devcontainerId}`.
- `runArgs`: extra arguments to the engine's `run`, array form only (no shell quoting).
- `customizations.vscode`: VS Code specific `extensions` and `settings`.
- `hostRequirements`: minimum `cpus`, `memory`, `storage`, `gpu`.
- `initializeCommand`, `onCreateCommand`, `updateContentCommand`, `postCreateCommand`, `postStartCommand`, `postAttachCommand`: lifecycle hooks, run in that order. The first runs on the host; the rest run inside the container. `postCreateCommand` runs once after the container is first assigned to a user; `postStartCommand` on each start; `postAttachCommand` each time a tool attaches. String form runs in `/bin/sh`; array form runs without a shell; object form runs named commands in parallel. If one script fails, the remaining ones are skipped. `waitFor` chooses which step the tool waits for before connecting (default `updateContentCommand`).

## How you run it

Minimal file for a uv-based Python repo that talks to Kubernetes:

```jsonc
// .devcontainer/devcontainer.json
{
  "name": "inference-service",
  "build": { "dockerfile": "Dockerfile", "context": ".." },
  "features": {
    "ghcr.io/devcontainers/features/kubectl-helm-minikube:1": { "minikube": "none" }
  },
  "remoteUser": "vscode",
  "containerUser": "vscode",
  "runArgs": ["--userns=keep-id"],
  "forwardPorts": [8000],
  "postCreateCommand": "uv sync",
  "customizations": {
    "vscode": { "extensions": ["ms-python.python", "charliermarsh.ruff"] }
  }
}
```

The `"minikube": "none"` option is UNVERIFIED (I did not open that Feature's option list); check its README. Do not paste the file blindly. `runArgs` and the user pair are explained in the Podman section.

VS Code: install the Dev Containers extension, then Command Palette, "Dev Containers: Reopen in Container".

### The devcontainer CLI (useful for CI and for scripting)

```sh
curl -fsSL https://raw.githubusercontent.com/devcontainers/cli/main/scripts/install.sh | sh   # installs a bundled-Node build to ~/.devcontainers/bin
export PATH="$HOME/.devcontainers/bin:$PATH"
npm install -g @devcontainers/cli                                   # alternative; needs Python + C/C++ toolchain
devcontainer up --workspace-folder . --docker-path podman           # create and run
devcontainer exec --workspace-folder . --docker-path podman uv run pytest   # run a command inside
devcontainer read-configuration --workspace-folder .                # print resolved config
devcontainer build --workspace-folder .                             # build/pre-build the image
devcontainer down --workspace-folder .                              # stop and delete
```

Subcommands listed in the README: `up`, `build`, `run-user-commands`, `read-configuration`, `exec`, `outdated`, `upgrade`, `features`, `templates`, `stop`, `down`. Flags `--docker-path`, `--docker-compose-path`, `--remove-existing-container`, `--skip-post-create`, `--mount type=bind,source=...,target=...`, `--remote-env name=value`, `--id-label`, `--config` appear in the CLI source (`devContainersSpecCLI.ts`, main branch) but not in the README. Lockfiles for Features are generated by default; `--no-lockfile` and `--frozen-lockfile` control that. Whether `stop` and `down` exist in the version you install: UNVERIFIED, run `devcontainer --help`.

## Using Podman instead of Docker

VS Code docs (code.visualstudio.com/remote/advancedcontainers/docker-options): Podman 5 or later is "mostly compatible with Docker's CLI commands"; set `dev.containers.dockerPath` to `podman` (Linux, Windows, macOS). `podman compose` needs a provider (Docker Compose or Podman Compose); the community setting `dev.containers.dockerComposePath` (set to `podman-compose` in a community guide) points to it. The docs state that VS Code does not officially support non-Docker CLIs.

```jsonc
// VS Code user settings.json
{
  "dev.containers.dockerPath": "podman",
  "dev.containers.dockerComposePath": "podman-compose"   // only for compose-based setups
}
```

### macOS: podman machine

On macOS containers run inside a Linux VM. `podman machine` subcommands: `init`, `start`, `stop`, `ssh`, `set`, `rm`. The default provider is libkrun; `applehv` is also supported. All `podman machine` commands are rootless only. (docs.podman.io, podman-machine; no Podman version stated on the page.)

```sh
podman machine init --cpus 4 --memory 8192 --disk-size 60   # flags UNVERIFIED: not on the page I opened; check `podman machine init --help`
podman machine start
podman info | head                                            # confirm the VM is reachable
```

Bind-mount default behaviour of the VM (which host folders are shared): UNVERIFIED, the page did not cover it. Keep the repo under your home directory and test a mount early.

### Rootless: UID mapping and SELinux

Plain gloss: inside the box you are a different "person" with a different ID number than outside, so files can look like they belong to a stranger; these settings line the two identities up.

Rootless Podman uses a user namespace (a remapping of user IDs between host and container). From the `podman run` man page:

- `--userns=keep-id` maps your host UID:GID to the same numbers inside the container, and runs the container's init as your UID, overriding the image `USER` unless you set `--user`. `keep-id:uid=200,gid=210` maps you to a chosen container UID/GID.
- `--userns=host` in rootless mode makes your UID appear as root (0) inside the container.
- `z` / `Z` (in `--mount`, `relabel=shared` / `relabel=private`) apply SELinux labels so the mounted files are readable; `--security-opt label=disable` turns SELinux separation off for the container.

A community mini-guide (universal-blue.discourse.group, not official) found that `remoteUser`, `containerUser` and `runArgs: ["--userns=keep-id"]` had to be set together, and used `"workspaceMount": "source=${localWorkspaceFolder},target=/workspace,type=bind,consistency=cached,relabel=private"` plus `"workspaceFolder": "/workspace"` on an SELinux host. SELinux only matters on Linux hosts such as Fedora; on a Mac it is inside the VM and you will usually not hit it. How `updateRemoteUserUID` behaves under rootless Podman: UNVERIFIED (no authoritative source found; forum reports only).

## How it fits the stack

- Tilt (doc 14) and `kubectl` run inside the dev container, so they must be baked in via a Dockerfile or Features.
- uv (doc 16) is the Python entry point: `postCreateCommand: "uv sync"`.
- Cline (doc 15) is a VS Code extension, so it runs inside the container; its network view is the container's, which affects how it reaches the inference endpoint.
- Registry: Harbor (doc 12) is where images that Tilt builds are pushed.

### Reaching the cluster and the registry from inside

These are general practices, not spec features. UNVERIFIED against a source unless stated.

- Kubeconfig: mount your host `~/.kube/config` read-only, for example `"mounts": ["source=${localEnv:HOME}/.kube,target=/home/vscode/.kube,type=bind,readonly"]`. Beware: if the API server address is `127.0.0.1` or a hostname only your host resolves, it will fail inside the container or the Podman VM.
- Private CA: copy the CA into the image in the Dockerfile and run `update-ca-certificates`; for Python set `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE`; for Node-based tools `NODE_EXTRA_CA_CERTS`.
- Proxies: pass `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` via `containerEnv` or `remoteEnv` using `${localEnv:...}`.
- Registry login: `podman login <harbor-host>` inside the container writes `~/.config/containers/auth.json`; to share a host login, mount that file.

## What goes wrong

- Files owned by `nobody` or root, "permission denied" writing the workspace: UID mapping. Try `--userns=keep-id` with `containerUser`/`remoteUser` set to a non-root user.
- "permission denied" on a readable file only on SELinux hosts: missing label. Use `relabel=private` on the mount, or `label=disable` as a last resort.
- Extension complains it cannot find `docker`: `dev.containers.dockerPath` is not set in the right scope (user vs workspace vs remote).
- Compose-based config fails: no compose provider installed.
- Container starts then `postCreateCommand` fails: later lifecycle steps are skipped; read the creation log (Command Palette, "Dev Containers: Show Container Log").
- `kubectl` works on the host but not inside: kubeconfig points to localhost, or CA/proxy not present inside.
- Config edits not applied: `containerEnv`, `runArgs`, `features` need "Rebuild Container".

## Check yourself

1. What is the difference between `remoteUser` and `containerUser`, and between `containerEnv` and `remoteEnv`?
2. In what order do the lifecycle commands run, and which one runs on the host?
3. Why can a Docker-compatible CLI substitute for Docker with the Dev Containers extension, and what support level does VS Code state for it?
4. What does `--userns=keep-id` do in rootless Podman, and why is it paired with `containerUser`?
5. What does `relabel=private` do, and when would you need it?
6. Where does the Cline extension run when you are attached to a dev container, and what follows for networking?
7. Why might a mounted kubeconfig fail inside the container even though `kubectl` works on the host?
8. When would you pick Compose over a plain Dockerfile for the dev container?

## References

All checked 2026-11-13.

- https://containers.dev/implementors/json_reference/ (no spec version shown)
- https://containers.dev/overview and https://containers.dev/features (Feature versions as listed on the day)
- https://code.visualstudio.com/docs/devcontainers/containers (page dated 11/11/2026)
- https://code.visualstudio.com/remote/advancedcontainers/docker-options (Podman 5+, `dev.containers.dockerPath`)
- https://github.com/devcontainers/cli and https://raw.githubusercontent.com/devcontainers/cli/main/src/spec-node/devContainersSpecCLI.ts (main branch)
- https://docs.podman.io/en/latest/markdown/podman-run.1.html and https://docs.podman.io/en/latest/markdown/podman-machine.1.html (no Podman version stated)
- https://universal-blue.discourse.group/t/mini-guide-podman-devcontainers/7667 (community, not official)
