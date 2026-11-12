# Tilt for local Kubernetes development

## In one paragraph

Tilt is a command-line tool that watches your source tree, rebuilds container images, applies Kubernetes manifests, and shows build and pod status in one web page, all driven by a program called a Tiltfile. Its main trick is "live update": instead of rebuilding an image and rolling a pod for every code change, it copies the changed files straight into the running container and optionally runs a command, which brings the edit-to-running loop down to seconds. You already know the other half of this: Helm renders manifests, `kubectl apply` applies them, Argo CD reconciles them. Tilt is the developer-side counterpart that does build, push, apply and watch in a loop, against a dev cluster, before anything reaches GitOps. Docs checked 2026-11-13; the Tilt docs pages do not state a single version (the install page example uses 0.37.8, which may not be current).

## The plain version

Imagine you are writing a recipe and testing it on guests. Without help, every time you change a pinch of salt you must cook the whole meal again, carry it to the dining room, and wait for the guests to taste it. Tilt is like a kitchen assistant who stands next to you: when you change the recipe, the assistant instantly adjusts the dish on the table when that is possible, and only re-cooks from scratch when the change is big. There is also a screen on the wall showing what is cooking, what burned, and what is ready.

Without Tilt, a developer testing against a real Kubernetes cluster has to repeat a long chain of steps by hand (build the package, upload it, tell the cluster to use it, wait, read the logs), and it can take minutes for each small change. People respond by testing less, or by testing somewhere that is not like the real thing.

The point is speed of feedback: seconds instead of minutes, in a setup that resembles production.

If you remember only five things:

- Tilt watches your files and keeps a practice cluster up to date with them.
- Its instructions live in a file called the `Tiltfile`, which is a small program.
- "Live update" copies changed files into a running program instead of rebuilding it.
- `tilt up` starts it, `tilt down` cleans up, and a web page at port 10350 shows status.
- It is for practice (development) clusters only; your real environments stay under GitOps.

## Why it exists

The inner loop problem: edit code, build image, push to registry, update the Deployment, wait for the pod, read logs. Done by hand that is minutes per change. A shell script or `make` can chain the steps but gives you no dependency graph, no live logs per service, and no incremental update. Tilt's docs say Live Update "optimizes your setup to get updates down from minutes to seconds".

Resembles: a controller reconcile loop for your laptop. You declare resources, Tilt keeps the cluster matching your working tree.

## How it works

In plain terms: Tilt notices you saved a file, decides the cheapest way to get that change into the running cluster, does it, and shows you the result. The precise version follows.

```
 working tree --(file watch)--> Tilt engine ---> build image  -> push -> kubectl apply
                                     |                                 (or)
                                     +--> live_update: sync files into running container, run cmd
                                     +--> local_resource: any host command (codegen, tests)
 web UI  http://localhost:10350  <--- status, logs, errors per resource
```

- The Tiltfile is written in Starlark, "a dialect of Python". It is executed on startup; Tilt records the files it reads and re-executes when one changes.
- A resource is a unit of work: an image build plus the Kubernetes objects it deploys, or a local command. Each shows as a row in the UI.
- Typical flow (Tilt "tiltfile_concepts"): `k8s_yaml` loads manifests, `docker_build` tells Tilt how to build an image named in those manifests, and Tilt matches them up and creates one resource per workload.

### Live update rules (docs.tilt.dev/live_update_reference.html)

Plain gloss: live update is "swap the changed pages into the running book" instead of "reprint the whole book"; these are the rules for when that is allowed.

- Only changes matching a `sync` step trigger a live update. A change in the build context that matches no `sync` triggers a full image build. A change outside both does nothing.
- A change matching `fall_back_on(files)` forces a full rebuild (use it for `pyproject.toml`, `uv.lock`, the Dockerfile).
- Step ordering: `sync` cannot follow `run`; `fall_back_on` must be first; `remotePath` in `sync` must be absolute; `run` commands execute from `/`, so use absolute paths.
- It needs a running container whose start does not depend on synced files. The `restart_process` extension covers most restart needs but does not work with `custom_build` images, shell-less images (scratch, distroless) or Compose; alternatives are a process that reloads itself, such as `uvicorn --reload`, or wrapper scripts. Live update itself does work with `custom_build`, with `deps` in place of `context`.

## How you run it

Install (macOS and Linux), and check:

```sh
brew install tilt                 # Homebrew
curl -fsSL https://raw.githubusercontent.com/tilt-dev/tilt/master/scripts/install.sh | bash   # official script
tilt version                      # confirm install
```

Run:

```sh
tilt up                           # start; terminal UI plus web UI on http://localhost:10350 (default --port 10350)
tilt up --stream                  # stream logs to the terminal instead of the TUI
tilt up --context my-dev-cluster --namespace dev-me   # override kube context and default namespace
tilt up -f Tiltfile.dev -- --env=dev                  # alternate Tiltfile; args after -- go to the Tiltfile
tilt down                         # delete the Kubernetes/Compose resources Tilt left behind
tilt ci                           # batch mode for CI: exit non-zero if a build fails or a server crashes; --timeout default 30m
```

Other `tilt up` flags verified on the CLI page: `--host`, `--port` (0 disables the server), `--legacy`, `--web-mode`, `--port-forwards` (default true), `--update-mode` (auto, image, container, exec), `--output-snapshot-on-exit`.

### Tiltfile functions you will use

Signatures from docs.tilt.dev/api.html (checked 2026-11-13):

- `docker_build(ref, context, build_args={}, dockerfile='Dockerfile', live_update=[], ignore=[], only=[], target='', platform='', ...)`.
- `custom_build(ref, command, deps, tag='', disable_push=False, skips_local_docker=False, live_update=[], outputs_image_ref_to='', ...)`. Tilt sets `$EXPECTED_REF` (a randomised tag) before running your command; the command must build and tag the image with that ref. Afterwards Tilt re-tags with a content-based tag and pushes. `deps` are real paths, not globs.
- `k8s_yaml(yaml)`: path, list of paths or a Blob (output of `helm()`, `kustomize()`, `local()`).
- `helm(chartDir, name, namespace, values=[], set=[])`: runs `helm template`, returns YAML for `k8s_yaml`. Good for your own chart; skips chart hooks. `helm_resource` (extension: `load('ext://helm_resource', 'helm_resource', 'helm_repo')`) runs a real `helm install`; the docs suggest it for installing third-party operators or servers into the dev environment.
- `k8s_resource(workload, new_name, port_forwards=[], resource_deps=[], objects=[], labels=[], trigger_mode=...)`. `port_forwards` accepts `'9000'`, `'9000:8000'` or `'host:9200:8000'`.
- `local_resource(name, cmd, deps=None, serve_cmd='', resource_deps=[], readiness_probe=None, labels=[], ...)`. `cmd` runs on change; `serve_cmd` is a long-running process.
- `default_registry(host, host_from_cluster=None, single_name='')`: image `user-service` becomes `host/user-service` (slashes and `@` in the name become `_`).
- `allow_k8s_contexts(contexts)`, `k8s_context()`, `watch_file(path)`, `load('ext://...')`.

### Podman and Harbor

Tilt's install page says you need Docker to build, and lists no alternative. Two routes (the first is documented by Tilt, the second is my inference):

1. Podman exposes a Docker-compatible API socket; point Tilt at it with `DOCKER_HOST` (Tilt reads the same environment variables as the `docker` CLI, per its FAQ). Whether every Tilt feature works against Podman's socket: UNVERIFIED.
2. Use `custom_build`. Tilt's own docs show a Buildah example:

```python
custom_build('frontend',
  'buildah bud -t $EXPECTED_REF frontend && buildah push $EXPECTED_REF $EXPECTED_REF',
  ['./frontend'], skips_local_docker=True)
```

A `podman build`/`podman push` version follows the same pattern. No official Tilt example using Podman: UNVERIFIED that it works unchanged.

Remote cluster and registry: by default Tilt refuses to develop against a remote cluster ("Tilt will not let you develop against a remote cluster"); you must add `allow_k8s_contexts('your-context-name')`. The docs say remote clusters need a remote image registry and recommend `live_update`; `default_registry('registry.example.com/project')` sets it manually. Harbor-specific behaviour (robot accounts, project paths) is not in Tilt's docs: UNVERIFIED, see doc 12.

### A complete small example: uv-based FastAPI service

Written by me from the documented signatures. UNVERIFIED by execution; test it.

```python
# Tiltfile
allow_k8s_contexts('dev-cluster')                       # name from `kubectl config current-context`
default_registry('harbor.example.com/dev',               # pushes land here
                 host_from_cluster='harbor.example.com/dev')

IMAGE = 'inference-service'

custom_build(
    IMAGE,
    'podman build -t $EXPECTED_REF . && podman push $EXPECTED_REF $EXPECTED_REF',
    deps=['pyproject.toml', 'uv.lock', 'Dockerfile', 'app'],
    skips_local_docker=True,                              # image is not in a Docker store
    live_update=[
        fall_back_on(['pyproject.toml', 'uv.lock', 'Dockerfile']),
        sync('./app', '/srv/app/app'),                    # absolute remote path
        # uvicorn --reload (set in the Dockerfile CMD) picks up the change; no run step needed
    ],
)

k8s_yaml(helm('deploy/chart', name='inference-service', namespace='dev',
              values=['deploy/chart/values-dev.yaml']))
k8s_resource('inference-service', port_forwards='8000:8000', labels=['app'])

local_resource('tests', 'uv run pytest -q', deps=['app', 'tests'],
               resource_deps=['inference-service'], labels=['checks'])
```

```dockerfile
# Dockerfile (dev target; see doc 16 for the uv-in-Docker pattern)
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /srv/app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
COPY app ./app
RUN uv sync --frozen
CMD ["/srv/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

The Helm values must reference the image name `inference-service`; Tilt substitutes the built ref into matching image fields. That substitution works on Helm output via `k8s_yaml(helm(...))`; for CRD-style or templated image strings it may not match (UNVERIFIED for your chart).

## How it fits the stack

- Runs inside the dev container (doc 13): install `tilt`, `kubectl`, `helm`, and `podman` there. Tilt's UI port (10350) and your service port go in `forwardPorts`. If Tilt runs in a container, `--host 0.0.0.0` is likely needed for the browser on the host to reach the UI: UNVERIFIED.
- Pushes to Harbor (doc 12); the cluster's nodes must be able to pull from it.
- Deploys the inference service (doc 16) that Cline (doc 15) will call through a port-forward or an ingress.
- Tilt is for development clusters. Argo CD still owns the real environments; do not point Tilt at them.

### Comparison

- Plain `kubectl apply`/`helm upgrade` plus a script: no file watching, no live update, no unified logs. Fine for CI.
- Skaffold (skaffold.dev, "Skaffold 2.0 Documentation"): similar goal, declarative `skaffold.yaml`, commands `dev`, `build`, `deploy`, `run`, `render`, with optional file sync. The page checked says Skaffold will be removed from gcloud CLI releases after 2027-01-15 and that the GitHub repository will be archived on 2027-01-29; confirm current status before choosing it. Tilt uses a programmable Tiltfile with a richer UI; Skaffold uses config.
- Docker Compose: Tilt can also drive `docker_compose`, but your target is Kubernetes.

## What goes wrong

- "Tilt will not let you develop against a remote cluster": add `allow_k8s_contexts`.
- Image pushed but pods `ImagePullBackOff`: the cluster cannot reach or authenticate to Harbor; check `host_from_cluster` and image pull secrets.
- Custom build: Tilt cannot find the image: missing `skips_local_docker=True`, or the command did not tag `$EXPECTED_REF`.
- Live update does not trigger: changed file does not match any `sync`, so a full rebuild happened (or nothing, if outside the context).
- Live update works but process does not restart: no reload mechanism; `restart_process` does not apply to `custom_build`.
- Tiltfile re-executes constantly: Helm sub-chart directories change; add `**/charts` and `**/tmpcharts` to `.tiltignore`.
- Chart changes ignored when using `local('helm template ...')`: add `watch_file()` for the chart and values.
- `helm()` hooks not run: it uses `helm template`.

## Check yourself

1. What does Tilt do on a file change that matches a `sync` step, versus one that matches none?
2. Why use `fall_back_on` for `uv.lock`?
3. What does `skips_local_docker=True` tell Tilt and why do you need it with Podman or Buildah?
4. What is `$EXPECTED_REF`, and who tags and pushes after your command exits?
5. Difference between `helm()` and `helm_resource`; which would you use for your own chart?
6. Why does Tilt refuse your cluster and what is the fix?
7. How would you run Tilt in CI, and what makes it exit non-zero?
8. What does `default_registry` do to an image name?

## References

All checked 2026-11-13. Tilt pages show no overall version.

- https://docs.tilt.dev/api.html
- https://docs.tilt.dev/tiltfile_concepts.html
- https://docs.tilt.dev/live_update_reference.html
- https://docs.tilt.dev/example_python.html
- https://docs.tilt.dev/custom_build.html
- https://docs.tilt.dev/helm.html
- https://docs.tilt.dev/choosing_clusters.html
- https://docs.tilt.dev/cli/tilt_up.html and https://docs.tilt.dev/cli/tilt_ci.html
- https://docs.tilt.dev/install.html (example version 0.37.8)
- https://docs.tilt.dev/faq.html
- https://skaffold.dev/docs/ ("Skaffold 2.0 Documentation", footer 2026)
