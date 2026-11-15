# Dev environment setup — dev containers, VS Code, Tilt, commits

## In one paragraph

A practical setup guide for a common inner loop on a project like this. VS
Code opens the repo inside a dev container, which holds the whole toolchain.
From inside it, Tilt builds images and deploys them to your own namespace in a
shared dev cluster, and commits go through an npx-driven tool (usually
commitizen and commitlint, enforced by git hooks). Background: dev containers
are explained in [13](13-dev-containers.md) and Tilt in [14](14-tilt.md); this
is the hands-on companion. Values that differ per project are shown as
`<placeholders>`; read them from the project's own files.

## The plain version

Think of a workshop that comes flat-packed with every tool already on the
wall.

- **The dev container** is the workshop. You don't install tools on your
  laptop; you open the project, and VS Code moves you into a ready-made room
  with the right versions of everything. Your terminal, your extensions (Cline
  included) and the git hooks all run in that room.
- **Tilt** is a conveyor belt from the workshop to a test bay. Every time you
  save, it packs your change into an image, sends it to the cluster, and puts
  it into *your* bay (your namespace). Nobody else's bay is touched. It also
  runs a hose back (port-forwards) so you can poke the running thing from your
  laptop.
- **The commit tool** is the dispatch desk. It asks you a few questions and
  writes a correctly formatted label for your change. A checker at the door
  (the commit hook) rejects badly labelled parcels.

Without these, every developer hand-builds their machine, deploys by hand, and
writes commit messages however they like. That gives you "works on my machine",
slow feedback and an unreadable history.

**Five things to remember**

1. Everything runs *inside* the container: the terminal, Cline and the hooks.
   Set up certificates and credentials there.
2. Read `devcontainer.json` and the `Tiltfile` before running anything; they
   are the instructions.
3. Check your kube context and namespace before every `tilt up`.
4. `tilt down` removes only what Tilt applied.
5. Never use `--no-verify` to get past a hook. Fix the cause.

## How the pieces fit

```
Laptop                     Dev container (on the laptop)            Dev cluster
------                     -----------------------------            -----------
VS Code window ─────────▶  shell, uv, node, kubectl, tilt,          your namespace
(UI only)                  Cline, git hooks                          ├─ service A
                           │                                         ├─ service B
                           └─ tilt up ─ build ─▶ registry ─▶ deploy ─┘
                              └─ port-forward ◀──────────────────────┘
VS Code forwards those container ports to the laptop's localhost
```

## 1. One-time laptop setup

*Plain gloss: install the editor, a container engine, and make sure git and SSH
work on the laptop, because the container borrows them.*

1. **VS Code** plus the **Dev Containers** extension
   (`ms-vscode-remote.remote-containers`).
2. **A container engine.** Use whatever the project uses.
   - Docker Desktop: nothing else to configure.
   - Podman:
     ```sh
     podman machine init --cpus 4 --memory 8192 --disk-size 60
     podman machine start
     podman info | head
     ```
     Then in VS Code `settings.json`: `"dev.containers.dockerPath": "podman"`.
     VS Code officially supports only Docker; Podman works but has
     rootless/user-mapping quirks (doc 13). Ask for the project's known-good
     settings.
3. **Git identity and SSH.** VS Code copies your `.gitconfig` into the
   container and forwards your SSH agent, so check both work on the laptop:
   ```sh
   ssh-add -l
   git config --global user.name; git config --global user.email
   ```
4. **Kubeconfig** for the dev cluster. Find out whether `devcontainer.json`
   mounts `~/.kube` into the container or whether you log in from inside.
5. Optional: **the devcontainer CLI**, which does the VS Code button's job from
   a terminal:
   ```sh
   npm i -g @devcontainers/cli
   ```

## 2. Read the two instruction files first

*Plain gloss: these two files tell you what the workshop contains and where the
conveyor belt goes. Ten minutes here saves hours.*

**`.devcontainer/devcontainer.json`**

| Key | Question it answers |
|---|---|
| `image` / `build.dockerfile` | What is the toolchain built from? |
| `features` | Which tools are layered on (kubectl, node, …)? |
| `mounts` | Are `~/.kube`, `~/.ssh` or CA certificates mounted in? |
| `forwardPorts` | Which ports reach the laptop? |
| `postCreateCommand` | What runs on first build (`uv sync`, `npm ci`)? |
| `remoteUser` / `containerUser` | Which user am I inside? |
| `customizations.vscode.extensions` | Which extensions are preinstalled (is Cline)? |
| `containerEnv` / `remoteEnv` | Proxy and certificate variables? |

**`Tiltfile`**

| Look for | Question it answers |
|---|---|
| `allow_k8s_contexts(...)` | Which cluster contexts Tilt may deploy to |
| `default_registry(...)` | Where images are pushed |
| namespace (`k8s_namespace`, a variable, `config.define_string`) | How it targets *your* namespace |
| `docker_build` vs `custom_build` | Docker, or Podman/Buildah/remote builds |
| `live_update=[sync(...), run(...)]` | What hot-reloads vs what forces a rebuild |
| `k8s_resource(..., port_forwards=...)` | Local port → service mapping |
| `helm(...)` / `k8s_yaml(...)` | Where manifests come from |
| `config.define_*` | Flags you pass after `--` |

## 3. Open the repo in the container

*Plain gloss: one command moves VS Code from your laptop into the workshop.*

VS Code command palette (Cmd/Ctrl+Shift+P):
- **Dev Containers: Reopen in Container**. The first build is slow.
- **Dev Containers: Rebuild Container** after `devcontainer.json` or its
  Dockerfile changes.
- **Dev Containers: Show Container Log** when the build fails.

The bottom-left corner shows `Dev Container: <name>` when you're inside.

The same from a terminal:
```sh
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . bash
```

## 4. Check everything from inside the container

*Plain gloss: before deploying anything, confirm you're pointed at the right
cluster and namespace and that every tool works.*

```sh
whoami; pwd                                  # user and workspace path
kubectl config get-contexts
kubectl config current-context               # must be the dev cluster
kubectl config set-context --current --namespace=<your-ns>
kubectl auth can-i --list | head -30         # what you're allowed to do
kubectl get pods                             # what's already in your namespace
podman login <registry-host>                 # or: docker login <registry-host>
tilt version; uv --version; node -v; npx --version
git remote -v; git status
```

Certificate errors from `kubectl`, `uv sync`, `npm ci` or the registry are the
private-CA problem; see [doc 19, section 3.1](19-day-one-field-guide.md).

## 5. Tilt

*Plain gloss: `tilt up` starts the conveyor belt; the web UI shows each
service's build and logs.*

```sh
tilt up                          # start; UI on http://localhost:10350
tilt up --stream                 # logs in the terminal instead of the UI
tilt up -- --some-flag=value     # Tiltfile config flags go after --
tilt get uiresources             # resources and status
tilt logs <resource>             # one resource's logs
tilt trigger <resource>          # force a rebuild or rerun
tilt down                        # delete what Tilt deployed (only that)
tilt ci                          # bring up once and exit; "does it come up at all"
```

Reading the UI:
- **Red resource:** open it and read the build log first, then the pod log.
- **Image rebuilt but behaviour unchanged:** `live_update` only syncs the paths
  in `sync()`. Other changes need a full rebuild (`tilt trigger`) or a Tiltfile
  change.
- **Port forward not reachable:** Tilt forwards to the *container's*
  localhost, and VS Code then forwards that to the laptop. Check VS Code's
  **Ports** tab.

Safety:
- Run `kubectl config current-context` before `tilt up`. `allow_k8s_contexts` is
  a guardrail, not a guarantee.
- `tilt down` deletes only what Tilt applied; anything else in the namespace
  stays.
- Find out whether the project expects `tilt down` at the end of the day.
  Idle dev pods hold cluster resources, and GPU ones cost a lot.

## 6. Committing with npx

*Plain gloss: a prompt writes a correctly formatted commit message; hooks check
your code and the message before the commit is accepted.*

Find out what's wired in:

```sh
ls -a .husky 2>/dev/null                          # git hooks (pre-commit, commit-msg)
grep -A5 -E '"commitizen"|"scripts"' package.json
ls commitlint.config.* .czrc .commitlintrc* 2>/dev/null
ls .pre-commit-config.yaml 2>/dev/null            # Python-side hooks, if any
```

The usual flow (the exact command varies; check `package.json` scripts):

```sh
git status
git add -p                     # stage hunk by hunk; know exactly what goes in
npx cz                         # commitizen prompt (or: npx git-cz, or npm run commit)
git push -u origin <branch>
```

Messages follow Conventional Commits: `type(scope): subject`, for example
`feat(api): add streaming timeout` or `fix(ui): handle empty response`. The
common types are `feat`, `fix`, `docs`, `refactor`, `test` and `chore`.

When a hook rejects the commit:
- Read which hook failed: lint, format, type check, tests, or commitlint.
- Fix the cause and commit again.
- Check a message on its own: `echo "feat: x" | npx commitlint`.
- Reproduce Python-side hooks: `uvx pre-commit run --all-files`.
- Don't use `--no-verify`.

## 7. The daily loop

```
open VS Code → Reopen in Container → check context and namespace → tilt up
→ edit → watch Tilt rebuild → test via the forwarded port (or Cline)
→ git add -p → npx cz → push → tilt down (if expected)
```

## 8. Cline inside the container

- Install Cline **in the container**: Extensions view, "Install in Dev
  Container". Or have it added to `customizations.vscode.extensions`.
- Run the endpoint probes from [doc 15](15-cline-with-a-self-hosted-model.md)
  **from the container terminal**; that's the network Cline uses.
- Corporate CAs must be trusted inside the container (`NODE_EXTRA_CA_CERTS`
  for Cline), not just on the laptop.
- Point Cline at the gateway as described in
  [doc 06](06-bifrost-llm-gateway.md) ("Pointing Cline at Bifrost").

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| Container build fails | Registry or CA access, or a feature download blocked | Container log; proxy/CA variables in `devcontainer.json` |
| `permission denied` on mounted files (Podman) | Rootless user mapping | `remoteUser`/`containerUser`, `--userns=keep-id` (doc 13) |
| `git push` asks for credentials | SSH agent not forwarded | `ssh-add -l` inside the container |
| `tilt up` refuses the context | Context not in `allow_k8s_contexts` | Are you on the dev cluster context? |
| Image push denied | Not logged in, or no rights to that registry project | `podman login`; ask for registry project access |
| Pod `ImagePullBackOff` | Wrong registry/tag or pull secret | `kubectl describe pod`; the image name Tilt used |
| Changes not showing | Path not in live_update `sync()` | `tilt trigger`, or read the Tiltfile |
| Commit rejected | Hook or commitlint | Read the hook output; fix the cause |

## Questions to ask on day one

1. Docker Desktop or Podman, and which VS Code settings do I need?
2. Is my namespace created, what's it called, and does the Tiltfile pick it up
   automatically?
3. Does Tilt push to the registry, or do images get built some other way?
4. Is `npx cz` the commit command, or is there an npm script?
5. Should `tilt up` be left running, or should I `tilt down` at the end of the
   day?

## Check yourself

1. Where does your terminal run once the repo is open in a dev container, and
   why does that matter for certificates?
2. Which two files do you read before running anything, and what three things
   do you look for in each?
3. What does `tilt down` delete, and what does it leave?
4. A change isn't showing up in the pod. Give two possible reasons.
5. Why is a port-forward set up by Tilt reachable from your laptop's browser?

## References (checked 2026-11-15; from general knowledge, verify against current docs)

- Dev Containers: https://code.visualstudio.com/docs/devcontainers/containers
- devcontainer.json reference: https://containers.dev/implementors/json_reference/
- devcontainer CLI: https://github.com/devcontainers/cli
- Tilt API (Tiltfile): https://docs.tilt.dev/api.html
- Tilt CLI: https://docs.tilt.dev/cli/tilt.html
- Commitizen: https://commitizen-tools.github.io/commitizen/ and https://github.com/commitizen/cz-cli
- commitlint: https://commitlint.js.org/
- Husky: https://typicode.github.io/husky/
- Conventional Commits: https://www.conventionalcommits.org/
