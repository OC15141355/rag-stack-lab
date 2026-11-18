# Argo CD in an Ansible + GitLab shop

Reading level: you already run Argo CD (app-of-apps, Helm sources, SSO, SOPS). This page skips the basics. It covers what changes when Argo CD sits next to Ansible playbooks and GitLab environment branches, with plaintext `.env` files, on VMware VKS/Tanzu, possibly air-gapped behind Harbor. Ansible and secrets get their depth in [26-ansible-gitlab-iac.md](26-ansible-gitlab-iac.md); this page only links there.

Checked against the Argo CD docs on 2026-11-18. Items I could not confirm are marked `UNVERIFIED:`.

## In one paragraph

In a mixed shop, Argo CD is one of at least two things that can change a cluster. Ansible and GitLab CI can too. Most of the real risk is not in Argo CD itself. It is in the seams: two tools owning the same object, environment branches that have drifted apart, credentials and CA certificates the repo-server cannot reach or trust, and plaintext secrets that Argo copies into its cache. Reading an existing setup means answering one question per workload: who is the single writer, and where does its desired state live? The current stable line is 3.6 (3.6.1, released 2026-11-04). Anything from 2.x carries real default changes.

## The plain version

Think of a building with two caretakers. One, Ansible, is the contractor who builds the foundations and wires the electricity: clusters, namespaces, the Argo install itself. The other, Argo CD, is the resident manager who keeps each flat looking like the blueprint on file. Both are competent. Trouble starts when the contractor comes back and rearranges a flat's furniture, and the manager moves it all back that night. Neither is wrong. They are both just doing their job on the same room.

The blueprint is a Git branch. In a GitLab shop with environment branches, each environment has its own blueprint, and Argo CD points at the matching branch. If the branches drift, the environments are no longer copies of each other, and "it worked in test" stops meaning anything.

Five things to remember:

1. Every object needs exactly one writer. Decide per object whether Ansible or Argo owns it.
2. Argo CD only knows what is in Git (plus Helm/OCI sources). Anything Ansible templates into a cluster behind its back is invisible, then "drift".
3. A branch is a promotion path only if you merge into it deliberately. Check whether environments differ by branch, by directory, or by values file.
4. Anything in the Argo-watched repo is also in Argo's memory: the repo-server cache, Redis, and diffs. Plaintext secrets do not stay in Git only.
5. In 3.x, resource tracking uses annotations, not labels. Objects deployed by another tool but labelled like an Argo app are no longer confusingly adopted, but old label-tracked apps behave differently after upgrade.

## Refresher, and what changed in 3.x

| Object | What it is | What to look for here |
|---|---|---|
| Application | One source (or several) rendered and applied to one destination | `targetRevision`, `path`/`chart`, `syncPolicy`, `ignoreDifferences` |
| AppProject | Boundary: allowed repos, destinations, resource kinds, roles | `sourceRepos`, `destinations`, whether everything is `*` |
| ApplicationSet | Template plus generators producing many Applications | Generator type; whether it is the only thing creating env apps |
| Sync policy | `automated` (`prune`, `selfHeal`), sync options | `prune: false` and no `selfHeal` means Argo only reports; it does not fix |
| Sync waves/hooks | Ordering via `argocd.argoproj.io/sync-wave`; `PreSync`/`PostSync` hook Jobs | Ansible-like logic hiding in hook Jobs |
| Health | Built-in and Lua checks per kind; Application health is the worst child | Custom checks in `argocd-cm`; CronJob and CRD checks changed in 3.x |

### Version position

Argo CD 3.0 was the last major break. As of today the stable release is 3.6.1 (2026-11-04). The release page said 3.3 reached end of life on 3 Nov 2026, so an install on 3.3 or older is out of support. The upgrade-guide index also lists a 3.6-to-3.7 page, which suggests 3.7 is in development; I did not read it. `UNVERIFIED:` the exact support window policy (the docs describe supporting the latest three minors, but I did not confirm this on the page I read).

### 3.0 changes that matter to an operator

Source: the 2.14 to 3.0 upgrade guide.

- Annotation-based resource tracking is the default instead of labels. Opt out with `application.resourceTrackingMethod: label` in `argocd-cm`. After upgrading, apps with `ApplyOutOfSyncOnly=true` should be synced explicitly to avoid orphaned resources. In a shop where Helm or Ansible also stamps labels on objects, annotation tracking reduces ambiguity about which tool owns what, but check both before assuming.
- RBAC: fine-grained `update`/`delete` no longer cascade to sub-resources (restore with `server.rbac.disableApplicationFineGrainedRBACInheritance: "false"`). Log access is enforced, so a role needs an explicit `logs, get`. Dex SSO subjects switched from `sub` to `federated_claims.user_id`; this matters if policy lines in `argocd-rbac-cm` reference raw subjects.
- `ignoreDifferences` also applies to resource updates by default (`ignoreDifferencesOnResourceUpdates: false` reverts).
- Status comparison went from `crd` to `all` (`ignoreResourceStatusField: crd` reverts).
- `resource.exclusions` now excludes high-churn kinds such as `Endpoints`, `EndpointSlice` and `Lease`.
- Health is no longer persisted in the Application CR (`controller.resource.health.persist: "true"` reverts). Scripts that read `.status.resources[].health` from `kubectl get applications -o yaml` may find it missing.
- Removed: legacy repository settings in `argocd-cm` (repos must be Secrets), and the metrics `argocd_app_sync_status` and `argocd_app_health_status` (use labels on `argocd_app_info`).
- The project API response is sanitised so it no longer returns repository and cluster credentials.

### 3.1 to 3.6, quick scan

Sources: the individual upgrade guides.

- 3.1: OIDC PKCE flow handled by the server; add `/auth/callback` to the identity provider redirect URIs if `enablePKCEAuthentication` is on. Helm 3.18, Kustomize 5.7.
- 3.2: CronJob health changed (apps may flip to `Degraded`; `argocd.argoproj.io/ignore-healthcheck: "true"` excludes one). ApplicationSet `status.resources` is capped at 5000.
- 3.3: the ApplicationSet CRD is too large for client-side apply, so a self-managed Argo needs `ServerSideApply=true` and manual upgrades need `kubectl apply --server-side --force-conflicts`. Helm upgrades are not affected.
- 3.4: cluster version labels are now `vMajor.Minor.Patch`; ApplicationSets using `argocd.argoproj.io/auto-label-cluster-info` must use `argocd.argoproj.io/kubernetes-version`. An Application reports `Missing` only if all resources are missing.
- 3.5: Helm 4. `spec.source.helm.version: v3` is ignored. Plain-HTTP OCI repositories need `insecureOCIForceHttp`. Repos without credentials validate SSH host keys against `argocd-ssh-known-hosts-cm`. mTLS to the repo-server turns on automatically once the `argocd-repo-server-mtls` Secret exists.
- 3.6: apps with `ServerSideApply=true` now use Server-Side Diff (a dry-run against the API server, which also runs validating webhooks). Opt out per app with `ServerSideDiff=false`. Matters on a shared VKS control plane with admission webhooks.

`UNVERIFIED:` I did not confirm whether Helm 4 changes break charts written for Helm 3 in practice beyond what the 3.5 guide lists; test any chart on a non-production cluster first.

## How environment branches map to Argo

The branch-per-environment model (`dev`, `test`, `prod` branches, or `main` plus release branches) maps to Argo as one Application per environment, each with a different `targetRevision`.

```yaml
spec:
  source:
    repoURL: https://gitlab.internal.example/platform/apps.git
    targetRevision: env/test      # the branch
    path: charts/app
```

### Generators that produce one app per environment

| Generator | Fits when | Watch for |
|---|---|---|
| List | Few envs, explicit values (`env`, `branch`, `cluster`) | Simplest to read; envs are listed in one file, not discovered |
| Git (directories or files) | Env config lives as folders or `config.json` files | The generator reads one revision; with branches, it reads that branch only |
| Cluster | One app per registered cluster (labels select env) | Cluster labels become the source of truth; check who sets them |
| Matrix | App list x env list | Large fan-out; look for accidental cross products |

A neat shop pattern is a List or Cluster generator that sets `targetRevision: '{{branch}}'`. A Git generator over branches does not exist as such: it reads directories or files at a fixed revision. `UNVERIFIED:` whether the current docs offer any generator that enumerates branches (I believe not, and the SCM Provider generator, which can enumerate repositories and branches from GitLab, is the closest, but I did not re-read its page).

### Multi-source apps

An Application can have several `sources`, so one can be a chart (Helm repo, OCI, or Git) and another a Git ref used only for values:

```yaml
sources:
  - repoURL: oci://harbor.internal.example/charts
    chart: app
    targetRevision: 1.4.2
    helm:
      valueFiles:
        - $values/envs/test/values.yaml
  - repoURL: https://gitlab.internal.example/platform/config.git
    targetRevision: env/test
    ref: values
```

This separates "chart version" from "environment config". It is a good fit for Harbor-hosted charts and per-env values in GitLab.

### Pitfalls

- Branches drift. Nothing forces `env/prod` to be a subset of `env/test`. Check with `git log env/prod..env/test` and a diff of the values files. A hotfix committed straight to prod and never merged back is the classic case.
- Promotion by merge versus by `targetRevision`. If promoting means merging `test` into `prod`, the merge is the release. If promotion means bumping `targetRevision` (tag or chart version) in an Application, the Application manifest is the release and who can edit it matters. Pick one, and find out which this shop uses.
- Branch protection. Argo CD only reads from the repo, so protected branches are not a problem for it. They matter when something writes back (Argo CD Image Updater, the source hydrator, or CI committing values). Those need a token that is allowed to push, and a protected branch will block it. `UNVERIFIED:` I did not check whether the source hydrator pushes to a separate branch by default; the 3.2 and 3.3 guides say hydrated paths must be non-root and that cleanup of stale files is manual.
- A moving `targetRevision` on a branch means a push is an instant deploy to that environment if automated sync is on. A tag or commit SHA pins it.
- A webhook change on a monorepo can refresh every app. Scoping with the manifest-paths annotation keeps refreshes small; see GitLab integration below.

## Who deploys what: Ansible vs Argo

Three patterns appear.

1. Ansible bootstraps, Argo owns. Ansible builds the cluster, installs Argo CD (often via Helm), applies a root Application, and stops. This is the clean pattern. Check that Ansible does not keep re-running its Argo install role with different values on every pipeline run.
2. Ansible templates values into a Git repo that Argo reads. Fine in principle, since Git is still the source of truth, but the commit is now made by a playbook. Look for the identity committing (a service account), whether the commit is reviewed, and whether a failed run leaves half-written values on a branch Argo watches.
3. Both manage the same release. Ansible runs `helm upgrade` (via `kubernetes.core.helm`) or `kubectl apply`, and an Argo Application renders the same chart or manifests. This is the fight.

### What a fight looks like

- The app flips between `Synced` and `OutOfSync` repeatedly, or self-heal keeps reverting a change right after a pipeline.
- `argocd app diff <app>` shows a stable difference even though Git has not changed.
- The Helm release secrets (`sh.helm.release.v1.*`) exist for something that Argo also manages. Argo renders with `helm template`, so a Helm release secret for the same objects means another tool installed them.
- `managedFields` show more than one manager:

```bash
kubectl get deploy my-app -n my-ns -o yaml --show-managed-fields | grep -A3 'manager:'
```

Typical managers: `argocd-controller` (client-side apply) or `argocd-controller` with server-side apply, `helm`, `kubectl-client-side-apply`, `kubectl-edit`, and whatever user agent Ansible's Kubernetes module reports (often shown as `OpenAPI-Generator` or `Ansible`; `UNVERIFIED:` the exact string depends on the collection version). If a non-Argo manager owns fields Argo also sets, that is the conflict.

Also read the tracking annotation on the object: `argocd.argoproj.io/tracking-id` (3.x default) or `app.kubernetes.io/instance` (label tracking). An object with no tracking mark is not Argo's.

### Recommendations

- Assign ownership per layer: Ansible for hosts, cluster lifecycle and the Argo install; Argo for everything in-cluster that has a Git source. Write it down.
- If both must touch an object, use `ignoreDifferences` with `managedFieldsManagers` (documented in the diffing guide) to ignore a named manager's fields, or `RespectIgnoreDifferences=true` on the sync option. This is a workaround, not a design.
- Never let Ansible `helm upgrade` a release that has an Argo Application. Let Ansible commit a values change or bump a chart version instead.
- Keep the root Application and the Argo install in different roles, so a playbook rerun cannot reset Argo settings.

## GitLab integration

### Repository credentials

- HTTPS with a deploy token or project access token: the least-privilege option for read-only. Prefer a deploy token with `read_repository` only.
- SSH deploy key: a read-only key per repo (GitLab allows one key to be enabled on multiple projects, but then it is shared). For SSH, the host key must be known to Argo: in 3.5+ repos without configured credentials validate against `argocd-ssh-known-hosts-cm`.
- Credential templates: a `repo-creds` Secret (label `argocd.argoproj.io/secret-type: repo-creds`) with a URL prefix such as `https://gitlab.internal.example/platform`. Any repo under that prefix inherits the credential, so one token covers a group. Check whether a broad token is being used where a narrow one would work.
- Since 3.0 the legacy repository config in `argocd-cm` is gone; repos must be Secrets in the `argocd` namespace. List them with `kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type`.

### Webhooks

GitLab sends push events to `https://<argocd>/api/webhook`. Set a secret in GitLab and store the same value in `argocd-secret` as `webhook.gitlab.secret`. Without webhooks Argo polls (the default interval is 3 minutes; `UNVERIFIED:` this is from memory, check `timeout.reconciliation` in `argocd-cm`). In an air-gapped or segmented network, GitLab must be able to reach the Argo ingress; if it cannot, polling is the fallback and slow syncs are expected, not a fault.

### Internal CA for GitLab

A self-signed or internal-CA GitLab fails with `x509: certificate signed by unknown authority`. Put the CA in `argocd-tls-certs-cm`, keyed by the repo hostname (no scheme, port included only if non-standard), value is the PEM. The same ConfigMap serves Helm and OCI hosts such as Harbor. Do not "fix" it with `insecure: true` on the repo Secret; that disables verification for that repo.

### Air-gapped repo-server

The repo-server is the component that clones and renders. It needs to reach GitLab, any Helm repository, and Harbor; it does not need the internet if everything is mirrored. Things to check:

- Helm charts: with Harbor, use OCI (`oci://harbor.internal.example/<project>`) rather than a classic index. Register the repo with `enableOCI` and credentials as a repo Secret (robot account recommended). Remember `insecureOCIForceHttp` for plain-HTTP registries in 3.5+.
- Image pulls on the cluster are separate: VKS nodes pull images through whatever registry and pull-secret configuration the cluster has. Argo does not fix an `ImagePullBackOff`.
- Kustomize remote bases or Helm dependencies pointing at the public internet will fail to render. Look for `https://github.com/...` in `kustomization.yaml` or `Chart.yaml` dependencies.
- Plugins fetched at run time (a CMP sidecar downloading a binary) fail offline; they must be baked into the sidecar image.
- `UNVERIFIED:` VKS/Tanzu specifics (namespace creation via supervisor namespaces, PSA labels, and whether Argo CD is run in a vSphere Namespace or inside a guest cluster). Check the platform docs before assuming normal namespace permissions.

## Secrets when there's no Vault/SOPS

The Argo CD secret-management page splits approaches in two. Destination-cluster tools (Sealed Secrets, External Secrets Operator, Secrets Store CSI Driver) mean Argo never sees the secret value; the docs strongly recommend this. Manifest-generation tools (argocd-vault-plugin, KSOPS, helm-secrets, run as config management plugins) inject secrets at render time; the docs strongly discourage it. Argo will keep supporting it but will not prioritise new features.

| Option | How it fits | Notes |
|---|---|---|
| External Secrets Operator | Needs a backend (Vault, cloud secret store, etc.) | Fits only if some store exists; check before proposing |
| Sealed Secrets | Encrypt to a cluster key, commit ciphertext | Needs the controller key backed up; re-seal per cluster |
| KSOPS / helm-secrets (CMP) | SOPS-encrypted files decrypted at render | Needs the key available to the repo-server; rendered output is cached |
| argocd-vault-plugin | Placeholders replaced from a vault at render | The secret-management page lists it only as an example of a generation plugin, not as supported or deprecated. `UNVERIFIED:` project maintenance status; check the plugin's repository |

The docs also say plugin-generated manifests that contain injected secrets are cached in Redis in plaintext and are retrievable through the repo-server gRPC API. Plaintext in the repo has a related effect: anything the repo-server renders into a ConfigMap or Secret manifest is held in its cache and used for diffs, so a `.env` committed to the watched branch ends up in three places (Git history, Argo's cache, any rendered ConfigMap).

What to set:
- Network policy around Redis and the repo-server, so only Argo components reach them (the docs recommend this).
- Use `ignoreDifferences` for fields that Ansible or an operator legitimately rotates, so they do not show in diffs.
- `UNVERIFIED:` whether the UI masks `Secret` `data` values in diff views and live manifests. I did not find this stated on the diffing page; test by opening a Secret in the UI. ConfigMap contents are not masked in any case I know of.
- `UNVERIFIED:` any single Argo setting that redacts or hides values in diffs; I did not find one. The honest control is to keep the secret out of the watched repo.

Doc 26 covers the underlying problem, plaintext `.env` and Ansible without a vault; see [26-ansible-gitlab-iac.md](26-ansible-gitlab-iac.md). Reading is not fixing: record where plaintext lives and say so, without moving anything.

## Reading an existing Argo setup read-only

Use a read-only login (a `readonly` role bound to your SSO group, or a view-only kubeconfig). None of these commands change anything.

```bash
argocd login <server> --sso
argocd app list -o wide
argocd app get <app> --show-params          # source(s), sync status, resources
argocd app diff <app>                       # live vs Git
argocd app history <app>
argocd app manifests <app>                  # what Argo would apply (renders; may print secrets!)
argocd app manifests <app> --source live    # live state
argocd proj list ; argocd proj get <proj>
argocd repo list ; argocd repocreds list
argocd cluster list
argocd appset list ; argocd appset get <name>
```

Note: `argocd app manifests` and `app diff` can print plaintext secrets to your terminal. Do not paste the output anywhere.

The kubectl equivalents work even when the CLI is awkward (SSO, ingress). They also expose what the CLI hides:

```bash
kubectl get applications,applicationsets,appprojects -n argocd
kubectl get applications -n argocd -o yaml
kubectl get applications -n argocd -o custom-columns=NAME:.metadata.name,PROJECT:.spec.project,REV:.spec.source.targetRevision,SYNC:.status.sync.status,HEALTH:.status.health.status
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type    # names only; do not print data
```

Since 3.0, `.status.health` on individual resources is not persisted by default, and the app-level health still is.

### ConfigMaps to read

| ConfigMap | Check |
|---|---|
| `argocd-cm` | `application.resourceTrackingMethod`; `resource.exclusions`; `resource.customizations.*` (custom health, ignoreDifferences); `url`; `oidc.config` or `dex.config`; `timeout.reconciliation`; `exec.enabled`; `kustomize.buildOptions` |
| `argocd-rbac-cm` | `policy.default` (should be empty or `role:readonly`, not `role:admin`); `policy.csv`; `scopes`; any `g, <group>, role:admin` lines |
| `argocd-cmd-params-cm` | `server.insecure`; `controller.*` sharding and parallelism; `reposerver.*` timeouts and parallelism limits; `applicationsetcontroller.*` (policy, allowed SCM providers); `application.namespaces` (apps in other namespaces) |
| `argocd-tls-certs-cm`, `argocd-ssh-known-hosts-cm` | Internal CA entries, host keys |
| `argocd-secret` | Do not print. Check only that keys exist (`webhook.gitlab.secret`, `admin.password` status) |

Also check whether the built-in `admin` account is enabled (`admin.enabled` in `argocd-cm`), and which AppProjects use wildcards.

### Drawing the app tree

1. List Applications and ApplicationSets: `kubectl get applications,applicationsets -A`.
2. For each, record project, `repoURL`, `path` or chart, `targetRevision`, destination cluster and namespace, and sync policy.
3. Find parents: an Application whose source `path` contains other `Application` manifests (app-of-apps), or an ApplicationSet (look at `metadata.ownerReferences` on generated apps).
4. Note the root: usually one Application created by Ansible or a manual `kubectl apply`. That is where the tree attaches to the automation.
5. Draw boxes per environment and mark the branch each env follows. Mark which objects are also touched by Ansible (search playbooks for the namespace or release name).
6. Mark any Application with `selfHeal` or `prune`. These are the ones that will revert hand changes.

## What goes wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| App flips OutOfSync after every CI run | Ansible or CI also applies the same objects | Pick one owner; or ignore the other manager via `managedFieldsManagers` |
| Permanent OutOfSync on unchanged Git | Mutating webhook or controller rewrites fields (`caBundle`, replicas from HPA) | `ignoreDifferences` for those fields; on 3.6 check Server-Side Diff behaviour |
| `x509: certificate signed by unknown authority` | Internal CA missing | Add the CA to `argocd-tls-certs-cm` keyed by hostname |
| `authentication required` / `repository not found` | Deploy token expired, wrong scope, or credential template prefix mismatch | Check the repo Secret and token expiry in GitLab |
| ComparisonError rendering a chart | Chart repo or dependency not reachable from the repo-server (air gap) | Mirror into Harbor; fix `Chart.yaml` dependencies; register OCI repo |
| Syncs slow, not instant after push | No webhook or GitLab cannot reach Argo | Configure `/api/webhook`; otherwise accept polling delay |
| Env `prod` differs unexpectedly from `test` | Branch drift or hotfix not merged back | Diff branches; adopt a merge-back rule |
| After upgrade, apps flip health | CronJob and CRD health changes in 3.x | Check upgrade notes; `ignore-healthcheck` annotation |
| After upgrade, orphaned or "unknown" resources | Tracking changed from label to annotation | Sync affected apps explicitly; or pin `resourceTrackingMethod: label` temporarily |
| Users lost log access or edit rights after upgrade | 3.0 RBAC changes | Add `logs, get`; review fine-grained inheritance setting |
| Self-managed Argo upgrade fails on ApplicationSet CRD | 3.3 CRD too large for client-side apply | `ServerSideApply=true` and `--force-conflicts` |
| Plaintext values visible in app diff or manifests | Plaintext in watched repo | Move to a destination-cluster secret mechanism; restrict who can run `app manifests` |

## Questions to ask

- Who is the single writer for each layer (hosts, cluster, Argo install, namespaces, workloads, secrets)?
- Is promotion a merge between branches, or a change to `targetRevision`? Who can do either?
- Are environment branches long-lived, and when did `prod` last get merged from `test` (or the reverse)?
- Does any playbook run `helm upgrade`, `kubectl apply`, or edit a values file in Git? Which runs on which trigger?
- How is the Argo CD install itself upgraded, and by what?
- Which credentials does Argo use for GitLab and Harbor, and when do they expire?
- Is there a webhook, and can GitLab reach Argo?
- What is Argo's version, and when was it last upgraded (relative to the 3.0 defaults)?
- Where do secrets and `.env` files live, and does the watched branch contain them?
- Is Redis and the repo-server restricted by network policy?
- Is the cluster really air-gapped, and where do charts and images come from (Harbor project names, mirrors)?
- Who has `role:admin`, and is the local `admin` account enabled?

## Check yourself

1. What is the single clearest sign that Ansible and Argo are both managing an object? (Answer: more than one manager in `managedFields`, or a Helm release secret for an Argo-managed object.)
2. Why is a moving branch as `targetRevision` riskier than a tag, and when does that risk become a deploy?
3. Where does a `.env` committed to the watched repo end up, besides Git?
4. Which ConfigMap holds the internal CA for GitLab, and what is the key?
5. What changed about resource tracking in 3.0, and what would you check after an upgrade?
6. Why is "destination-cluster secrets" preferred over "manifest generation" in the Argo docs?
7. What does the multi-source `ref: values` pattern buy you?
8. Name three read-only commands that show you the live-versus-Git difference.

## References

- Argo CD docs home: https://argo-cd.readthedocs.io/en/stable/
- Upgrade guide 2.14 to 3.0: https://argo-cd.readthedocs.io/en/latest/operator-manual/upgrading/2.14-3.0/
- Upgrade guides 3.0-3.1 through 3.5-3.6 (same path, `3.0-3.1/` ... `3.5-3.6/`): https://argo-cd.readthedocs.io/en/latest/operator-manual/upgrading/overview/
- Releases (3.6.1 latest, 2026-11-04): https://github.com/argoproj/argo-cd/releases
- Secret management: https://argo-cd.readthedocs.io/en/latest/operator-manual/secret-management/
- Webhooks: https://argo-cd.readthedocs.io/en/latest/operator-manual/webhook/
- Diffing and ignoreDifferences: https://argo-cd.readthedocs.io/en/latest/user-guide/diffing/
- Declarative setup, repositories, TLS certs: https://argo-cd.readthedocs.io/en/latest/operator-manual/declarative-setup/
- ApplicationSet generators: https://argo-cd.readthedocs.io/en/latest/operator-manual/applicationset/Generators/
- Multiple sources: https://argo-cd.readthedocs.io/en/latest/user-guide/multiple_sources/
- Sibling doc: [26-ansible-gitlab-iac.md](26-ansible-gitlab-iac.md)
