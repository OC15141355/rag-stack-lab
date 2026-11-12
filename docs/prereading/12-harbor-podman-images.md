# Harbor, Podman and Container Images for Restricted Environments

Checked 2026-11-13. Harbor docs: the `main` branch, whose version selector lists 2.16.0 as the latest release. Podman docs: "latest" (no version printed on the pages I opened). NIM for LLMs air-gap page: version 2.1.5. Items I could not confirm from an opened page are marked `UNVERIFIED:`.

## In one paragraph

A container image is a packaged filesystem plus metadata, stored in a registry and fetched by name. Harbor is a self-hosted registry that adds access control, vulnerability scanning, signing checks, replication and a pull-through cache on top of plain image storage. Podman is a tool for building and running containers that works like the Docker command line but has no always-running background service. In a restricted or disconnected environment the cluster cannot reach `nvcr.io` or Docker Hub, so you copy the images you need into Harbor once (with skopeo, replication or a cache), and point every node at Harbor.

## The plain version

Think of a restaurant that can only buy ingredients from a supplier across a river, and the bridge is closed to the kitchen staff. So the restaurant keeps its own pantry just inside the kitchen. Someone with permission to cross the bridge fetches ingredients, checks them for spoilage, labels them, and stocks the pantry. The cooks only ever take from the pantry. Podman is the cook's set of tools for preparing a new packaged meal; Harbor is the pantry, with a lock, a log of who took what, and a spoilage inspector.

Without a pantry, every cook would walk to the supplier each time. In a closed environment they simply could not, so dinner stops. Even in an open one, the supplier might change a product under the same name, run out, or limit how often you can visit. A pantry also lets you check what you bought, and prove it has not been tampered with.

The pain points are the very large items: the AI model packages from NVIDIA are many gigabytes, so stocking the pantry takes planning and disk space.

If you remember only five things:

- An image is a sealed package; a registry is the shelf it is stored on; Harbor is the shelf you control.
- A tag is a label that can be moved; a digest is a fingerprint that cannot. Pin by digest when it matters.
- Podman does what Docker does without a permanent background service, and can run without admin rights.
- In a disconnected setup you copy images in deliberately (skopeo or Harbor replication), then point every node at Harbor and teach it to trust Harbor's certificate.
- Plan disk and time for huge NVIDIA images and model files; check sizes before you start.

## Why it exists

You know Docker and containerd on RKE2. Three problems appear when you move to a locked-down environment:

1. **Reach.** Nodes cannot pull from `nvcr.io` (NVIDIA's registry, which NIM images and the GPU Operator come from), Docker Hub, `registry.k8s.io` or `ghcr.io`. Something inside must serve them.
2. **Control.** You want per-team permissions, a record of who pulled what, no unscanned images, and only signed images allowed to run.
3. **Tooling.** Build servers and hardened Linux hosts often cannot run the Docker daemon (a root-owned background service), so Podman is used instead.

Terms:

- **OCI image**: the Open Container Initiative standard format: a manifest (JSON list) pointing at layers (compressed filesystem diffs) plus a config. Docker, Podman, containerd and Harbor all speak it.
- **Registry**: a web service storing images by name: `host/project/repo:tag`.
- **Tag vs digest**: a tag like `1.0` is a movable label. A digest like `sha256:ab12...` is a hash of the manifest; it identifies exact content. `repo:1.0@sha256:...` is allowed and the digest wins. Mirroring tools should preserve digests (skopeo has `--preserve-digests`).
- **Multi-arch image**: a "manifest list" or index pointing at one image per CPU architecture. Copying only one architecture changes the digest of what you store, which matters for signatures.

## How it works

Plain gloss for each part, then the precise version.

```
 internet side                 closed side
 nvcr.io, docker.io  ---skopeo/replication/proxy-cache--->  HARBOR  <--- pull ---  RKE2/VKS nodes (containerd)
                                                              |  Trivy scan, cosign/Notation check, RBAC, quotas
 Podman build host  ------------------ push --------------->  |
```

**Podman** (gloss: Docker's commands without the permanent boss process). Podman is "a daemonless, open source, Linux native tool" for finding, running, building, sharing and deploying OCI containers; most users can alias `docker` to `podman` (Podman docs). "Daemonless" means each `podman` command starts the containers itself, as child processes of your own login, rather than asking a central service running as root. "Rootless" means an ordinary user can do this; containers run in a user namespace. It manages pods too (groups of containers sharing a network namespace, the same idea as a Kubernetes pod). `podman build` builds images from a `Containerfile` (a Dockerfile is accepted). UNVERIFIED: that `podman build` is implemented with Buildah code; it is widely stated but the pages I opened did not say so. **Skopeo** (gloss: a courier that moves images between shelves without unpacking them) copies images between registries and local formats without a daemon. On macOS, containers need a Linux kernel, so `podman machine` creates a small Linux VM; the default provider on macOS is libkrun, with applehv as the alternative, and machine commands are rootless only (podman-machine page).

**Quadlet** (gloss: describe a container in a small config file and let the operating system's service manager keep it running). Quadlet reads unit files such as `.container`, `.pod`, `.kube`, `.network`, `.volume`, `.build`, `.image` from `/etc/containers/systemd/` (rootful) or `~/.config/containers/systemd/` (rootless) and generates systemd services (Podman systemd.unit page). It is how Podman replaces `docker run` plus a restart policy on a server.

**Harbor** (gloss: a pantry with locks, a spoilage inspector and a courier). Harbor is a registry with these parts:

- **Projects**: namespaces that group repositories and carry permissions, e.g. `harbor.example/nvidia/...`. Access is by role per project.
- **Robot accounts**: non-human credentials for CI and clusters. Per the Harbor docs: they cannot log in to the web UI; project robots work in one project, system robots (since v2.2) can span projects; the username is `<prefix><project>+<name>` where an admin sets the prefix; you set an expiry; the secret is shown once and can only be refreshed, not retrieved. Use `docker login`/`podman login` with the full robot username.
- **Proxy cache project**: a project that pulls through from an upstream registry on first request and keeps a copy. You create a registry endpoint, then a project with the Proxy Cache switch. Pull URL: `<harbor>/<proxy_project>/<upstream path>`. Pushes are rejected. Each new proxy project gets a default 7-day tag retention. If the upstream is down the cached copy still works. Supported upstream types in the project UI: Harbor, Docker Hub, Docker registry, AWS ECR, Azure ACR, Google GCR, Quay, GitHub GHCR, JFrog Artifactory.
- **Replication**: rules that copy images between Harbor and another registry in pull or push mode, filtered by pattern and triggered manually, on a schedule or on events; matching Cosign signatures are copied too. The provider list for endpoints (Alibaba, ECR, Azure, Docker Hub, Docker registry, GHCR, GCR/Artifact Registry, Huawei, JFrog, Tencent, VolcEngine, or another Harbor) does not name NVIDIA NGC. UNVERIFIED: whether the generic "Docker registry" provider works against `nvcr.io` (it should, as nvcr.io speaks the registry API, but I did not test or find a source). Replication between different Harbor versions is not supported.
- **Vulnerability scanning**: Trivy is the default scanner, enabled at install (`--with-trivy` for the installer); you can schedule scans of all images; Cosign signatures cannot be scanned. Offline Trivy DB import is described on a separate Harbor page I did not open (UNVERIFIED details). 
- **Signing**: Harbor supports Cosign and Notation. A project admin can tick Cosign and/or Notation in project Configuration so that only signed artifacts can be pulled; if both ticked, the artifact needs both.
- **Retention, quotas, garbage collection**: deleting an image does not free disk; garbage collection removes unreferenced blobs. It runs online (the docs say pushes, pulls and deletes continue), can be scheduled (hourly, daily, weekly, custom cron), has a dry-run mode, and skips blobs touched within a two-hour window. Tag retention rules and project storage quotas exist (UNVERIFIED: I did not open those pages).

## How you run it

### Podman essentials

```bash
podman login harbor.example.internal -u 'robot$ci+builder'   # full robot name; paste secret (note single quotes: $ is special in shells)
podman build -t harbor.example.internal/ai/rag-api:1.0 -f Containerfile .   # build
podman push harbor.example.internal/ai/rag-api:1.0                           # push
podman images --digests                                                       # show digests
podman machine init && podman machine start                                   # macOS only: create/start the Linux VM
podman compose up -d                  # wrapper: runs docker-compose or podman-compose against the Podman socket
```

`podman compose` is only a wrapper that passes your arguments to an external provider (`docker-compose` is preferred if both are installed; override via `compose_providers` in `containers.conf` or `PODMAN_COMPOSE_PROVIDER`).

Quadlet example, saved as `~/.config/containers/systemd/harbor-test.container`:

```ini
[Container]
Image=harbor.example.internal/ai/rag-api:1.0
PublishPort=8080:8080
[Service]
Restart=always
[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload && systemctl --user start harbor-test.service   # generate and start the service
```

### Install Harbor

Resource needs (Harbor installation prerequisites page): minimum 2 CPU / 4 GB RAM / 40 GB disk; recommended 4 CPU / 8 GB / 160 GB, plus Docker Engine above 20.10 and Docker Compose above 2.3 for the installer path. Real disk depends on how many NIM images you store (see sizes below); plan terabytes, not 160 GB, for a large model library. Components include PostgreSQL 15.10 and Redis 7.2.6 (install-config page).

Offline installer (for a host without internet):

```bash
tar xzvf harbor-offline-installer-<version>.tgz          # from github.com/goharbor/harbor/releases; contains pre-built images
cp harbor.yml.tmpl harbor.yml                             # set hostname, HTTPS cert paths, data volume, admin password
sudo ./install.sh --with-trivy                            # installs with the Trivy scanner; default admin login admin / Harbor12345 -- change it
```

The signature check uses `gpg --keyserver hkps://keyserver.ubuntu.com --receive-keys 644FF454C0B4115C` then `gpg -v --verify <file>.asc`. Keep the extracted directory: you need it for upgrades.

Helm (HA on Kubernetes; Deploying Harbor with High Availability via Helm page):

```bash
helm repo add harbor https://helm.goharbor.io
helm fetch harbor/harbor --untar                        # read values.yaml
helm install my-release harbor/                          # then override values below
```

Values called out by the docs: `externalURL` (must be a domain root, no sub-path), `expose.ingress.hosts.core`, `database.type=external` / `redis.type=external` for HA, storage via a ReadWriteMany StorageClass or object storage (`persistence.imageChartStorage.type`), and replicas of 2+ for `portal`, `core`, `jobservice`, `registry`. HA needs highly available PostgreSQL and Redis that Harbor does not provide. UNVERIFIED: the `expose.type` setting and the chart version: the page does not mention them. For a disconnected cluster, mirror Harbor's own images first (the offline installer contains them; for the chart, UNVERIFIED how to export them).

### Mirror from nvcr.io into Harbor

Authenticate to NGC: username is the literal string `$oauthtoken`, password is your NGC API key (NGC catalog guide):

```bash
skopeo login nvcr.io -u '$oauthtoken'                       # stores credentials in the auth file
skopeo copy --all --preserve-digests \
  docker://nvcr.io/nim/meta/llama-3.1-8b-instruct:<tag> \
  docker://harbor.example.internal/nvidia/nim/llama-3.1-8b-instruct:<tag> \
  --dest-creds 'robot$ci+mirror:<secret>' --retry-times 3  # copies manifest list + all architectures, keeps digests
```

`--all` copies every image in a list; `--preserve-digests` fails if digests cannot be preserved; `--src-creds/--dest-creds`, `--authfile`, `--src-tls-verify/--dest-tls-verify`, `--dest-cert-dir`, `--retry-times` exist (skopeo-copy page). The image path `nim/meta/llama-3.1-8b-instruct` comes from the NIM Operator docs via search and is an example; check the NGC catalog for the real path. Bulk mirroring with a file:

```yaml
# sync.yml
nvcr.io:
  credentials: {username: $oauthtoken, password: "<NGC key>"}
  images:
    nvidia/gpu-operator: ["v26.7.2"]
    nvidia/driver: ["595.91.07-ubuntu22.04"]
```

```bash
skopeo sync --src yaml --dest docker sync.yml harbor.example.internal/nvidia/
```

(`skopeo sync` yaml fields: `images`, `images-by-tag-regex`, `images-by-semver`, `credentials`, `tls-verify`, `cert-dir`. Check how the destination path is formed with `--scoped`; the exact result path for my example is UNVERIFIED.)

Air-gapped hop (when the closed side has no route even to a staging host): `skopeo copy ... dir:/media/usb/img` then on the other side `skopeo copy dir:/media/usb/img docker://harbor.../img` (the `dir:` transport is in the skopeo pages). Or `skopeo sync --src docker --dest dir`, then `--src dir --dest docker`.

Model files for NIM: images are separate from models. The NIM LLM 2.1.5 air-gap guide: on a connected host run `download-to-cache -p <PROFILE_HASH>` (list profiles with `list-model-profiles`) with `NGC_API_KEY` set and a cache directory mounted at `/opt/nim/.cache`; optionally `create-model-store -p <HASH> -m /model-repo`; move the cache or model store plus the image archive to the closed side; there, do not set `NGC_API_KEY` or `HF_TOKEN`, and run with `NIM_MODEL_PROFILE` or `NIM_MODEL_PATH=/model-repo`. On Kubernetes the cache lives on a PersistentVolume. The guide shows `docker save`/`docker load`/`docker push` for images; skopeo does the same job.

Sizes: I did not find a current authoritative number. A search snippet of the NIM 1.1.0 support matrix recommended at least 50 GB of disk for container plus model for Llama 3.1 8B, and a 1.8.x registry listing showed about 9 GB for that image; both are old and unconfirmed (UNVERIFIED). Expect the image itself to be several to tens of GB, and model profile caches for 70B-class or larger models to be tens to hundreds of GB each, per profile, per GPU configuration (UNVERIFIED estimate, not from a source). Use `ngc registry image list` (shows an Image Size column) and the NIM support matrix for your exact model before sizing Harbor storage and transfer media. The GPU Operator air-gap page lists the images to mirror: `nvcr.io/nvidia/gpu-operator:v26.7.2` and `nvcr.io/nvidia/driver:<version>-<os>`, plus a local OS package repository for kernel headers unless using precompiled drivers.

### Point nodes at Harbor

containerd with `hosts.toml` (containerd docs; enable via `config_path = "/etc/containerd/certs.d"`; no restart needed):

```toml
# /etc/containerd/certs.d/nvcr.io/hosts.toml
server = "https://nvcr.io"                       # omit this line to forbid falling back to upstream
[host."https://harbor.example.internal/v2/nvidia"]   # path style depends on Harbor project layout
  capabilities = ["pull", "resolve"]
  ca = "/etc/containerd/certs.d/harbor-ca.crt"   # trust your private CA
  override_path = true                           # UNVERIFIED: needed when the mirror lives under a project path
```

RKE2 (you know this): `/etc/rancher/rke2/registries.yaml`; restart RKE2 on the node after a change (RKE2 docs):

```yaml
mirrors:
  nvcr.io:
    endpoint: ["https://harbor.example.internal"]
    rewrite: {"^(.*)": "nvidia/$1"}          # prepend the Harbor project; regex rewrite changes name, not tag
  docker.io:
    endpoint: ["https://harbor.example.internal"]
configs:
  "harbor.example.internal":
    auth: {username: 'robot$k8s+pull', password: "<secret>"}
    tls: {ca_file: /etc/ssl/harbor-ca.crt}
```

`disable-default-registry-endpoint: true` stops fallback to upstream; the RKE2 page says that suits true air-gap. On VKS you cannot edit nodes; trust a private CA with the `osConfiguration.trust.additionalTrustedCAs` cluster variable (VKS variable reference; see file 10).

Kubernetes pull secret, for pods that reference Harbor directly:

```bash
kubectl create secret docker-registry harbor-pull -n rag \
  --docker-server=harbor.example.internal --docker-username='robot$k8s+pull' --docker-password='<secret>'
# then in the pod spec: imagePullSecrets: [{name: harbor-pull}]  (or patch the ServiceAccount)
```

Useful checks:

```bash
crictl pull harbor.example.internal/nvidia/gpu-operator:v26.7.2     # test from a node (containerd's CLI)
skopeo inspect --raw docker://harbor.example.internal/nvidia/gpu-operator:v26.7.2 | head   # manifest or index?
skopeo inspect docker://nvcr.io/nvidia/gpu-operator:v26.7.2 | grep Digest              # compare digests, source vs mirror
```

## How it fits the stack

Harbor sits under everything: the GPU Operator and NIM images (file 10), Volcano's own images (file 11), the RAG application images you build with Podman, and Helm charts (Harbor stores OCI artifacts, including charts). ArgoCD pulls charts from Git or OCI; pods pull images from Harbor through the node's mirror config. On VCF, Harbor can also be the Cloud Native Registry Supervisor Service (versions 2.12.4 to 2.14.3 in the catalogue) and is the base of the Private AI Services Model Store. UNVERIFIED: which of these your employer already runs; ask before installing your own.

## What goes wrong

- **`x509: certificate signed by unknown authority`** on pulls: nodes do not trust Harbor's CA. Fix in `registries.yaml`/`hosts.toml` (or the VKS trust variable), not by `insecure_skip_verify` except for testing.
- **`ImagePullBackOff` with 401/403**: the robot secret expired (robots have an expiry), lacks Pull permission on that project, or the pull secret is in the wrong namespace. The secret cannot be retrieved later, only refreshed.
- **Image name mismatch**: pod says `nvcr.io/nim/...`, mirror rewrite sends it to a Harbor project that does not exist. Test with `crictl pull` and read the Harbor access log.
- **Digest changed after mirroring**: you copied one architecture, or converted manifest format (`--format`), or skipped `--preserve-digests`; signatures and digest-pinned manifests then fail. Use `--all`.
- **Silent upstream fallback**: node still reaches `nvcr.io` through a proxy and masks a broken mirror. Use `disable-default-registry-endpoint` and test from an isolated node.
- **Harbor disk full after deleting images**: you forgot garbage collection (run a dry run first). Proxy cache projects fill disk too; set retention and quotas.
- **Trivy cannot update its DB** offline: scans fail or are stale; import the vulnerability data per Harbor's offline instructions (UNVERIFIED details).
- **Proxy cache pulls anything upstream credentials allow**: use a least-privilege upstream account (Harbor docs warning).
- **NIM starts and tries to download models**: the cache volume is not mounted or was not populated while connected; in strict air-gap the container fails (NIM docs).
- **Quadlet service "not found"**: the generator rejected the file; run `/usr/lib/systemd/system-generators/podman-system-generator --dryrun` (add `--user` for rootless).

## Check yourself

1. What is the difference between a tag and a digest, and why does multi-arch copying affect digests?
2. Why does Podman not need a daemon, and what does rootless mean for file permissions and ports below 1024? (the second part needs further reading)
3. Name three Harbor features that plain `registry:2` lacks, and what each protects against.
4. Compare a proxy cache project with a replication rule for getting `nvcr.io` images into Harbor. When does each fail in a fully disconnected environment?
5. Write the `skopeo copy` command that mirrors a NIM image with all architectures and original digests.
6. Where do the model weights for a NIM live, and how do they reach an air-gapped cluster separately from the image?
7. Show the RKE2 `registries.yaml` entry that sends `nvcr.io` pulls to Harbor and trusts a private CA. What changes on a VKS cluster where you cannot edit nodes?
8. A robot account worked yesterday and gets 401 today. List the likely causes in order.

## References

- Podman docs, https://docs.podman.io/en/latest/ ; podman-machine https://docs.podman.io/en/latest/markdown/podman-machine.1.html ; podman-compose https://docs.podman.io/en/latest/markdown/podman-compose.1.html ; podman-systemd.unit (Quadlet) https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html ; checked 2026-11-13 (no version printed)
- Skopeo copy and sync man pages, https://github.com/containers/skopeo/blob/main/docs/skopeo-copy.1.md and `skopeo-sync.1.md` (main branch), checked 2026-11-13
- Harbor docs (main; 2.16.0 latest in selector): install-config https://goharbor.io/docs/main/install-config/ ; prerequisites ; download-installer ; run-installer-script ; harbor-ha-helm ; proxy cache https://goharbor.io/docs/main/administration/configure-proxy-cache/ ; replication https://goharbor.io/docs/main/administration/configuring-replication/ and create-replication-endpoints ; robot accounts https://goharbor.io/docs/main/working-with-projects/project-configuration/create-robot-accounts/ ; garbage collection https://goharbor.io/docs/main/administration/garbage-collection/ ; vulnerability scanning https://goharbor.io/docs/main/administration/vulnerability-scanning/ ; content trust https://goharbor.io/docs/main/working-with-projects/project-configuration/implementing-content-trust/ ; checked 2026-11-13
- NVIDIA NIM for LLMs air-gap deployment (version 2.1.5), https://docs.nvidia.com/nim/large-language-models/latest/deployment/air-gap-deployment.html, checked 2026-11-13
- NVIDIA NGC catalog user guide (nvcr.io login, image list), https://docs.nvidia.com/ngc/latest/ngc-catalog-user-guide.html, checked 2026-11-13
- NVIDIA GPU Operator v26.7.2 air-gapped install, https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/install-gpu-operator-air-gapped.html, checked 2026-11-13
- containerd registry hosts, https://github.com/containerd/containerd/blob/main/docs/hosts.md ; RKE2 private registry, https://docs.rke2.io/install/private_registry ; checked 2026-11-13
- Not opened (search summaries only): NIM support matrix disk figures; Harbor tag retention and quota pages.
