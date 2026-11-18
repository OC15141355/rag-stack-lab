# Ansible and GitLab as infrastructure-as-code

Prereading for anyone who knows Kubernetes, Helm, ArgoCD, SOPS+age and Terraform, and who has just met a platform whose infrastructure lives in Ansible playbooks and GitLab branches. Written 2026-11-18. Items I could not confirm against current official docs are marked `UNVERIFIED:`.

## In one paragraph

Ansible is an agentless, mostly procedural automation tool: you describe an ordered list of tasks, each task calls a module that tries to be idempotent, and Ansible runs them over SSH or an API against an inventory of hosts. It has no state file. GitLab holds the playbooks and runs them from CI pipelines. A very common arrangement is one long-lived Git branch per environment (dev, staging, prod), where merging a branch forward promotes a change and the pipeline on each branch runs `ansible-playbook` against that environment's inventory. Teams choose this because it uses tools their operations staff already know, reaches things Kubernetes cannot (hypervisors, VMs, OS packages, load balancers), and needs no extra services in restricted networks. The cost is weaker drift detection, awkward branch maintenance, and, if secrets sit in plaintext `.env` files, a real security gap. All of that is fixable in small steps, and none of it needs a rewrite.

## The plain version

Think of a restaurant that runs from a binder of recipe cards. Each card lists steps in order: "preheat oven, season, bake 20 minutes unless already cooked". Anyone on staff can follow a card, and the cards say what to do rather than what the finished kitchen should look like. Terraform is closer to a floor plan with an inspector: you draw the kitchen you want, and the inspector compares it with the real one and fixes the difference. Ansible is the binder. It works well when you know the steps, and it has no inspector, so the only way to know the kitchen matches the binder is to run the cards again and see what changes.

The GitLab part is the binder's filing system. One shelf per site (dev, staging, prod). A new recipe is tested on the dev shelf, then copied to the next shelf by a merge. A robot (the CI runner) reads the shelf and cooks.

Why teams pick this: the binder needs one skill (YAML and a bit of Jinja2), the cook walks in over SSH with nothing installed on the targets, and the people who manage VMs and operating systems already think in ordered steps. In an air-gapped site, the whole toolchain (GitLab, a runner, Ansible, a mirrored set of collections, Harbor) can sit inside the perimeter without calling out to a SaaS control plane.

Five things to remember:

1. Ansible describes steps, not desired state. Good modules make steps idempotent, but nothing records what exists.
2. Variables are the real configuration. Most of what you want to know is in `group_vars/`, `host_vars/` and role `defaults/`, and precedence decides which value wins.
3. A branch is an environment. To learn how prod differs from dev, diff the branches.
4. A pipeline job is just `ansible-playbook` with an inventory and credentials. Read `.gitlab-ci.yml` first and everything else follows.
5. Plaintext secrets in Git are the one finding that is not a style preference. Raise it privately and propose a small fix.

## Ansible in 15 minutes for a Terraform/Helm person

### Inventory

The inventory is the list of things Ansible can act on, grouped. Static form is an INI or YAML file:

```yaml
# inventories/prod/hosts.yml
all:
  children:
    k8s_control:
      hosts:
        cp-01.example.internal:
        cp-02.example.internal:
    k8s_workers:
      hosts:
        wk-[01:06].example.internal:
    harbor:
      hosts:
        harbor-01.example.internal:
```

Dynamic inventory uses a plugin that asks a system for the host list. For vSphere that is the `vmware.vmware.vms` inventory plugin (newer) or `community.vmware.vmware_vm_inventory` (older), which group VMs by tags, folders or custom attributes. `UNVERIFIED:` exact current plugin names and whether `community.vmware` has been formally deprecated in favour of `vmware.vmware`; check `ansible-doc -t inventory -l | grep -i vmware` on their controller.

Variables attach to inventory objects by directory convention: `group_vars/<group>.yml` (or a directory of files) and `host_vars/<host>.yml`, next to the inventory or next to the playbook. The group `all` is the base layer, and more specific groups override it.

### Playbooks, plays, tasks, handlers

A playbook is a YAML list of plays. A play maps a host group to roles and tasks. A task calls one module with arguments. A handler is a task that runs only when notified by a task that reported `changed`, typically "restart service", and runs once at the end of the play.

```yaml
- name: Configure container hosts
  hosts: k8s_workers
  become: true
  tasks:
    - name: Render containerd registry config
      ansible.builtin.template:
        src: hosts.toml.j2
        dest: /etc/containerd/certs.d/harbor.example.internal/hosts.toml
        mode: "0644"
      notify: restart containerd
  handlers:
    - name: restart containerd
      ansible.builtin.service:
        name: containerd
        state: restarted
```

### Roles and collections

A role is a directory with a fixed layout: `tasks/main.yml`, `defaults/main.yml` (lowest-precedence variables, meant to be overridden), `vars/main.yml` (high precedence, not meant to be overridden), `templates/`, `files/`, `handlers/main.yml`, `meta/main.yml` (dependencies). Roles are Ansible's closest thing to a Helm chart: reusable, parameterised, with defaults.

A collection is the distribution unit: modules, plugins and roles under a namespace such as `kubernetes.core` or `community.vmware`. Use fully qualified names (`kubernetes.core.helm`) to see where a module comes from. Collections are installed with `ansible-galaxy collection install -r requirements.yml`.

### Variables and precedence (the gotcha)

Ansible has about 22 levels of variable precedence. The official page groups it simply: configuration settings and environment variables are lowest, then command-line options, then playbook keywords, then variables, then direct assignment, with `-e` extra vars the highest variable level (confirmed against docs.ansible.com, "Controlling how Ansible behaves: precedence rules"). Inside "variables", the ones you will meet most, low to high:

1. role `defaults/main.yml`
2. inventory `group_vars/all`, then more specific `group_vars/<group>`
3. inventory `host_vars/<host>`
4. play `vars:`, `vars_files:`
5. role `vars/main.yml`
6. task `vars:`, `set_fact`, registered variables
7. `-e` / `--extra-vars` (always wins)

The gotchas: a value you edit in `group_vars/prod.yml` can be silently overridden by a role's `vars/main.yml`, a `set_fact`, or a CI job passing `-e`. When groups at the same level conflict, the order is alphabetical by group name unless `ansible_group_priority` is set. Do not guess; ask Ansible (see "How to read their setup").

### Facts

Before tasks run, Ansible gathers facts about each host (`ansible_facts`: OS family, IPs, memory, and so on). Templates and conditionals use them (`when: ansible_facts['os_family'] == 'Debian'`). Gathering can be disabled with `gather_facts: false` for speed, which also means those variables are absent.

### Idempotence, check mode, diff mode

Idempotence means that running a task twice leaves the same result and the second run reports `ok` instead of `changed`. Well-written modules (`template`, `package`, `kubernetes.core.helm`) manage this. `ansible.builtin.shell` and `command` do not unless you add `creates:`, `changed_when:` or similar. A playbook full of `shell` tasks is the procedural end of the spectrum and behaves much less like Terraform.

`--check` is a dry run: modules that support it report what they would change. `--diff` shows file and template differences. Together they are Ansible's `terraform plan`, with caveats: modules without check support are skipped, and tasks that depend on the output of earlier skipped tasks can give misleading results.

### Templates (Jinja2)

`ansible.builtin.template` renders a `.j2` file using the host's variables. This is how `.env` files, `values.yaml` and config files are usually produced:

```jinja
# templates/llm-gateway.env.j2
GATEWAY_URL={{ gateway_url }}
DB_HOST={{ db_host }}
DB_PASSWORD={{ db_password }}
{% for model in enabled_models %}
MODEL_{{ loop.index }}={{ model }}
{% endfor %}
```

If a `.env` contains a plaintext password in the repo, it is either committed directly, or a template variable like `db_password` is defined in plaintext in `group_vars`. Look for both.

### requirements.yml, ansible.cfg

`requirements.yml` pins collections (and optionally roles). In an air-gapped site, expect an internal Galaxy mirror, a private Automation Hub, or a vendored `collections/` directory, with `collections_path` set in `ansible.cfg`.

```yaml
collections:
  - name: kubernetes.core
    version: ">=5.0.0"
  - name: community.vmware
  - name: community.sops   # only if they use SOPS
```

`ansible.cfg` sets defaults: `inventory = inventories/dev`, `roles_path`, `collections_path`, `remote_user`, `vault_password_file`, `host_key_checking`, `callbacks_enabled`. An `ansible.cfg` in the current directory wins over `~/.ansible.cfg`, which wins over `/etc/ansible/ansible.cfg`; `ANSIBLE_CONFIG` overrides all. Check which is active with `ansible-config dump --only-changed`.

### Execution environments and ansible-navigator

An execution environment (EE) is a container image holding ansible-core, collections and Python dependencies, built with `ansible-builder`. `ansible-navigator run site.yml -m stdout --eev` runs a playbook inside one. This fixes the "works on my laptop" problem and suits registries like Harbor: the EE image is pushed there and the CI runner pulls it. If you see `execution-environment.yml` in a repo, that is the build recipe. If CI uses a plain image such as `python:3.x` plus `pip install ansible`, there is no EE. `UNVERIFIED:` the latest recommended ansible-navigator flags; check `ansible-navigator --help`.

### Concept mapping

| Concept | Terraform | Ansible | Helm / ArgoCD |
|---|---|---|---|
| Style | Declarative: desired end state | Mostly procedural: ordered tasks, with declarative-ish modules | Declarative |
| State | State file or backend records what exists | None. Each run inspects the target live | Release secret (Helm); live cluster plus Git (Argo) |
| Drift detection | `terraform plan` shows it | Only by running `--check --diff`; no continuous detection | Argo shows OutOfSync continuously |
| Execution | Provider API calls from the runner | SSH or API from the controller; agentless | In-cluster controller reconciles |
| Reuse | Modules | Roles and collections | Charts |
| Parameters | variables, tfvars | inventory variables, group_vars, `-e` | values.yaml, Argo parameters |
| Dependency graph | Computed from references | You order it by hand (plays, tags, `import_role`) | Sync waves, hooks |
| Destroy | `terraform destroy` removes what it created | Only if you write a task with `state: absent` | Prune on sync |
| Secrets | state may hold them; sensitive vars | ansible-vault, external lookups | SOPS, ESO, Sealed Secrets |

The most important row is state. Because Ansible has no record of what it created, removing a task from a playbook does not remove the thing it created. Orphans accumulate quietly, and "what is actually deployed" can only be answered by looking at the targets.

## How Ansible usually manages a stack like this

A platform on vSphere with Tanzu-style Kubernetes and Harbor tends to be built in layers, with Ansible touching the lower ones and sometimes the upper ones.

1. **VMs and cluster infrastructure.** The vmware collections create folders, clone VMs from templates, set CPU and memory, attach networks, and power them on. Typical modules are `community.vmware.vmware_guest`, `vmware_guest_disk`, `vmware_cluster` and `vmware_content_library_manager`, with `vmware.vmware` as the newer collection. `UNVERIFIED:` which of these module names are current as of 2026-11; compare `ansible-doc -l | grep vmware` on their controller. For Tanzu/VKS, a Supervisor namespace and `TanzuKubernetesCluster` or `Cluster` objects are Kubernetes resources, so they are often applied with `kubernetes.core.k8s` against the Supervisor rather than with a vmware module. `UNVERIFIED:` the current API kind names under VKS.
2. **OS configuration.** Packages, NTP, sysctls, container runtime trust of the Harbor CA, `/etc/hosts`, proxy settings and GPU drivers on worker nodes. This is Ansible's home turf and the main reason it exists in these shops.
3. **Kubernetes content.** `kubernetes.core.helm` installs charts (`chart_ref`, `release_name`, `release_namespace`, `values_files`, `create_namespace`, `atomic`; confirmed in the kubernetes.core 6.6.0 docs). Note that `values_files` are read from the target host, not the controller, which surprises people. `kubernetes.core.k8s` applies manifests, often rendered from Jinja2 templates; it supports `state: present/absent`, server-side apply and `--check`.
4. **Values and config from variables.** A single `group_vars/<env>/` tree feeds templates that produce `values.yaml`, ConfigMaps and `.env` files, so the same role deploys every environment with different numbers.
5. **Bootstrapping ArgoCD.** Ansible installs Argo (Helm or a manifest), applies a root `Application` or `ApplicationSet`, and registers the repo credentials and cluster secrets. After that, Argo owns in-cluster apps and Ansible stays below it.

Typical repository layout, annotated:

```
platform-iac/
├── .gitlab-ci.yml            # START HERE: what runs, on which branch, with which secrets
├── ansible.cfg               # inventory path, roles/collections paths, vault settings
├── requirements.yml          # pinned collections (kubernetes.core, community.vmware ...)
├── execution-environment.yml # optional: how the runner image is built
├── site.yml                  # top-level playbook, imports the others in order
├── playbooks/
│   ├── 10-vsphere.yml        # VMs / clusters (vmware collections)
│   ├── 20-os-baseline.yml    # packages, CA trust, kernel settings
│   ├── 30-cluster-addons.yml # helm/k8s modules: ingress, storage, GPU operator
│   └── 40-argocd-bootstrap.yml
├── inventories/              # or a single inventory/ if branches carry the env
│   ├── dev/hosts.yml
│   ├── staging/hosts.yml
│   └── prod/hosts.yml
├── group_vars/               # per-group values; may be per-env inside inventories/
│   ├── all.yml               # shared defaults
│   ├── k8s_workers.yml
│   └── llm_platform/
│       ├── vars.yml          # image tags, replica counts, hostnames
│       └── secrets.env       # <- plaintext .env lives here or nearby; look for this
├── host_vars/
├── roles/
│   └── llm_gateway/
│       ├── defaults/main.yml # overridable defaults
│       ├── tasks/main.yml    # the steps
│       ├── templates/        # values.yaml.j2, config.env.j2
│       ├── handlers/main.yml
│       └── meta/main.yml
├── collections/              # vendored collections for air-gapped runs, maybe
└── README.md
```

## GitLab branches as environments

### The pattern

The environment-branch pattern keeps one long-lived branch per environment: `dev`, `staging`, `main` (or `prod`). A change is made on a feature branch, merged to `dev`, tested, then promoted by merging `dev` into `staging`, then `staging` into `prod`. The branch name selects the inventory, the variables and the credentials. GitLab protects the upper branches so only certain people can merge or run jobs there.

Why teams choose it:

- Promotion has an obvious UI: a merge request, with approvals, history and a diff.
- Access control is built in: protected branches, protected variables and protected environments line up with "who can touch prod".
- It matches the mental model of operators who already think "prod is a different copy".
- It needs no tooling beyond Git and GitLab, which is a real advantage when the site is restricted.
- Environment-specific values can be edited on that environment's branch without risking the others.

### GitLab CI in brief

`.gitlab-ci.yml` defines `stages` and jobs. A job has a `script`, optional `rules` deciding whether it runs, an `image` or `tags` selecting where it runs, and optionally `environment`. Key points (checked against docs.gitlab.com/ci/yaml):

- `rules: - if: $CI_COMMIT_BRANCH == "prod"` selects jobs by branch. `$CI_COMMIT_BRANCH` is a predefined variable that is empty in merge request pipelines, where `$CI_MERGE_REQUEST_TARGET_BRANCH_NAME` is used instead.
- `environment: name: prod` records deployments in GitLab's Environments page and enables protected environments and deployment approvals.
- `when: manual` makes a job wait for a click. Note that `allow_failure` defaults to `true` for manual jobs, but to `false` when `when: manual` is set inside `rules`, so a manual job can block or not block a pipeline depending on how it is written.
- `tags` select a runner. In restricted networks, runners are usually self-hosted and tagged by network zone (for example one that can reach the prod vCenter), so the tag is a security boundary as well as a scheduling hint.
- Protected branches and protected variables: a variable marked protected is only exposed to pipelines on protected branches or tags (confirmed at docs.gitlab.com/ci/variables). This is how prod credentials are kept away from feature branches.

### Example pipeline

```yaml
# .gitlab-ci.yml
stages: [lint, check, deploy]

default:
  image: harbor.example.internal/platform/ansible-ee:2.17   # image tag illustrative
  tags: [ansible-runner]

variables:
  ANSIBLE_FORCE_COLOR: "true"
  # Branch name picks the inventory: dev, staging or prod
  INVENTORY: "inventories/${CI_COMMIT_BRANCH}"

lint:
  stage: lint
  script:
    - ansible-lint
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

check:
  stage: check
  script:
    - ansible-galaxy collection install -r requirements.yml
    - ansible-playbook -i "$INVENTORY" site.yml --check --diff
  rules:
    - if: $CI_COMMIT_BRANCH =~ /^(dev|staging|prod)$/

deploy_dev:
  stage: deploy
  environment: { name: dev }
  script:
    - ansible-playbook -i inventories/dev site.yml --vault-password-file "$VAULT_PASS_FILE"
  rules:
    - if: $CI_COMMIT_BRANCH == "dev"

deploy_prod:
  stage: deploy
  environment: { name: prod }
  tags: [ansible-runner, prod-network]
  script:
    - ansible-playbook -i inventories/prod site.yml --vault-password-file "$VAULT_PASS_FILE"
  rules:
    - if: $CI_COMMIT_BRANCH == "prod"
      when: manual
```

`VAULT_PASS_FILE` here is a file-type CI variable. If the repo instead uses plaintext `.env` files, there will be no vault lines, and values are read straight from the checkout.

### Environment branches versus trunk-based with directory-per-environment

| | Environment branches | Trunk plus `inventories/<env>/` |
|---|---|---|
| Promotion | Merge between branches | Change the pinned version in the next environment's directory, or promote by pipeline |
| What differs between envs | Whatever the branch diff says; unbounded | Visible, bounded to the env directories |
| Seeing all envs at once | Need to check out or diff several branches | One checkout shows every environment |
| Access control | Strong: protected branches map to envs | Needs CODEOWNERS, protected environments and path-based approvals |
| Code drift | Easy: branches diverge | Not possible for shared code; one copy |
| Hotfix to prod | Branch from prod, then back-merge or cherry-pick | Fix on trunk, promote |
| Merge safety | Merges can carry env-specific values to the wrong place | Env values live in separate files, so merges do not collide |
| Audit | `git log` per branch | `git log` plus per-directory history |

Known failure modes of environment branches, which the reader will probably recognise:

- **Drift between branches.** A hotfix lands on `prod` and is never back-merged. Months later `dev` and `prod` have different role code, not just different values, so testing on dev proves less than it should.
- **Cherry-pick hell.** Teams stop merging forward because a merge drags in unfinished work, so they cherry-pick individual commits. Now no branch is an ancestor of another, and `git log` no longer tells you what is in prod.
- **Merges carrying environment values.** `group_vars/all.yml` contains `replicas: 1` on dev and `replicas: 6` on prod. A normal forward merge from dev overwrites the prod value, or produces conflicts that are resolved under time pressure. The same happens to hostnames, registry paths and, if present, secrets.
- **Review blindness.** The MR diff for dev to staging is huge and mixed, so reviewers skim.
- **Branch count creep.** `dev`, `dev2`, `staging-eu`, `prod-dr`, each with its own accidental differences.

Teams that stay on branches usually mitigate by keeping environment-specific values in a small, clearly separated set of files, and by promoting with strict forward-only merges. If the repo's `git diff dev..prod --stat` touches only `group_vars/` and `inventories/`, it is being run well. If it touches `roles/`, drift has begun.

## How to read their setup

Read in this order. The goal at each step is a one-line answer to a question.

1. **`.gitlab-ci.yml` (and any `include:` files).** Which jobs run on which branch? What inventory and playbook do they call? Which tags and images? Where do credentials come from (CI variables, a file in the repo, a vault password)? Is there a `--check` job? Are prod jobs manual?
2. **`ansible.cfg`.** Which inventory is the default? Where are roles and collections loaded from? Is `vault_password_file` set? Which callbacks and plugins are enabled?
3. **`requirements.yml`.** Which collections and versions? From which Galaxy source? Does it include `kubernetes.core`, `community.vmware`, `community.sops`?
4. **Inventories.** `inventories/*/hosts.yml` or a dynamic inventory config (`*.vmware.yml`). Which groups exist? Which hosts are in them?
5. **`group_vars/` and `host_vars/`.** The real configuration: versions, hostnames, replica counts, registry URLs, and, importantly here, secrets.
6. **`site.yml` and `playbooks/`.** The order of operations. Look for `import_playbook`, `tags:`, and `when:` guards.
7. **`roles/*/tasks/main.yml`, `defaults/main.yml`, `templates/`.** What each step does, and which variables each template consumes.
8. **`.env` files, `*.j2`, `values*.yaml`.** Find where each one is generated and where the values originate.

Commands. All are read-only unless noted; `--check` is read-only for modules that support it, but verify first, since some tasks (`shell`, `command`, some API modules) may still act or be skipped.

```bash
# What does the inventory look like, for the environment I am on?
ansible-inventory -i inventories/prod --graph
ansible-inventory -i inventories/prod --host wk-01.example.internal   # merged vars, i.e. who wins
ansible-inventory -i inventories/prod --list --yaml                   # everything, one document

# What would the playbook do, without doing it?
ansible-playbook -i inventories/prod site.yml --list-hosts
ansible-playbook -i inventories/prod site.yml --list-tasks
ansible-playbook -i inventories/prod site.yml --list-tags
ansible-playbook -i inventories/prod site.yml --syntax-check

# Dry run with diffs (needs credentials; treat as production-touching until proven otherwise)
ansible-playbook -i inventories/dev site.yml --check --diff --tags helm

# Documentation for any module, plugin or inventory plugin, offline
ansible-doc kubernetes.core.helm
ansible-doc -t inventory -l
ansible-doc -l | grep -i vmware

# Active configuration
ansible-config dump --only-changed

# Git: shape of history and environment differences
git log --graph --oneline --all --decorate | head -60
git diff dev..prod --stat
git diff dev..prod -- group_vars/ inventories/
git diff dev..prod -- roles/ playbooks/    # should be empty or nearly so
git merge-base dev prod                    # how far have they diverged?
git log prod..dev --oneline                # in dev, not yet in prod
git log dev..prod --oneline                # in prod, never back-merged (drift)
```

`ansible-inventory --host` is the best tool for the precedence problem: it shows the merged inventory-level variables for one host. It does not show role `vars`, `set_fact` or `-e` values, so also grep the roles and the CI file.

Finding where a Kubernetes resource or value comes from:

```bash
# Resource name or image tag seen in the cluster
grep -rn "llm-gateway" --include='*.yml' --include='*.j2' --include='*.yaml' .
# Where is a variable defined, and where is it used?
grep -rn "gateway_image_tag" .
# Which template renders a given file?
grep -rn "template:" -A3 roles/ | grep -B2 -A2 "values.yaml"
# Which tasks deploy via helm or k8s modules?
grep -rn "kubernetes.core\.\(helm\|k8s\)" roles/ playbooks/
# In the cluster: who owns it? (Helm labels, ArgoCD tracking annotation)
kubectl get deploy llm-gateway -n ns -o jsonpath='{.metadata.labels}{"\n"}{.metadata.annotations}'
```

If the object carries `app.kubernetes.io/managed-by: Helm` and a `meta.helm.sh/release-name` annotation, Ansible's `helm` module or a human ran Helm. If it carries `argocd.argoproj.io/tracking-id`, Argo owns it. If neither, it came from `kubernetes.core.k8s` or `kubectl apply`.

## Secrets: where plaintext .env leaves you, and the realistic upgrade path

### Why this matters

Committed plaintext secrets are a high-severity finding, not a backlog item, for four reasons that do not depend on how good the rest of the repo is:

- **Git history is forever.** Deleting the file in a later commit leaves the value in every clone and in every branch, including the environment branches.
- **A clone is a credential.** Anyone with read access to the repo, every CI runner, every laptop that cloned it, and any backup of GitLab holds the secret.
- **CI logs and artifacts.** Playbooks that print rendered templates or run with `-v` can echo values into job logs, which are retained and often broader-readable than the repo. `no_log: true` on sensitive tasks helps.
- **Environment branches multiply it.** The same value may exist on three branches with different values, and the prod branch is the one with the real secret.

Nothing here assumes bad intent. Plaintext `.env` files are what you get when the first goal is "make it work in a restricted network", and secrets management arrives later, if at all.

### Options, in order of friction

**1. ansible-vault (built in).** Lowest friction because it is part of ansible-core and the repo already speaks Ansible.

```bash
# Encrypt a whole vars file
ansible-vault encrypt group_vars/prod/secrets.yml
# Encrypt one value to paste inline
ansible-vault encrypt_string 'S3cr3t' --name 'db_password'
# Edit, view, rekey
ansible-vault edit group_vars/prod/secrets.yml
ansible-vault rekey group_vars/prod/secrets.yml
# Per-environment vault IDs
ansible-vault encrypt --vault-id prod@prompt group_vars/prod/secrets.yml
ansible-playbook site.yml --vault-id dev@dev.pass --vault-id prod@prod.pass
# Interactive vs CI
ansible-playbook site.yml --ask-vault-pass
ansible-playbook site.yml --vault-password-file "$VAULT_PASS_FILE"
```

In CI, store the vault password as a masked, protected, file-type variable and pass its path; do not commit the password file. Use a separate vault ID per environment so a dev runner cannot decrypt prod. Pros: no new services, works offline, diffs show that a value changed even though not what it is. Cons: one shared password per vault ID, rotation means re-encrypting, no audit trail of reads, and encrypted blobs produce noisy diffs. Air-gapped fit: excellent.

**2. GitLab CI variables.** Move values out of Git entirely and inject them at run time. Per docs.gitlab.com/ci/variables: *masked* variables are replaced with `[MASKED]` in job logs (value must be a single line, at least 8 characters; masking is not a guarantee against a malicious job author); *hidden* ("masked and hidden") variables additionally cannot be revealed in the settings UI, and must be chosen at creation; *protected* variables are only exposed on protected branches and tags; *file-type* variables write the value to a temp file and give you its path, which suits certificates, kubeconfigs and vault password files. Set scope per environment. Pros: fast, native, solves the "in Git" problem immediately. Cons: secrets live only in GitLab (backup and disaster recovery matter), any maintainer can usually read non-hidden values, no versioned history, and a developer cannot easily run the playbook locally. Air-gapped fit: good with self-managed GitLab.

**3. SOPS + age with `community.sops`.** Familiar to this reader. Files in Git are encrypted per key with the structure left readable.

```bash
age-keygen -o key.txt
sops --encrypt --age age1... group_vars/prod/secrets.sops.yml > out && mv out group_vars/prod/secrets.sops.yml
# in requirements.yml: community.sops ; then in the play:
#   vars_files / lookup('community.sops.sops', 'secrets.sops.yml') or the vars plugin
```

The collection provides a lookup, a vars plugin and an action plugin. `UNVERIFIED:` the exact vars-plugin enablement setting for current community.sops; check its docs. The CI runner needs the age private key as a protected file variable (`SOPS_AGE_KEY_FILE`), and `sops` and `age` binaries in the EE image. Pros: reviewable diffs, per-file recipients, same tool as the reader's other estate, no server. Cons: a new tool for the team, key distribution is on you, rotating a leaked key needs re-encryption. Air-gapped fit: excellent (single static binaries, mirrorable in Harbor or an artifact store).

**4. In-cluster options: External Secrets Operator and Sealed Secrets.** These solve secrets for workloads running in Kubernetes, not for Ansible's own variables.

- *Sealed Secrets*: `kubeseal` encrypts a Secret to a controller's public key; only the cluster can decrypt. Pros: one controller, offline-friendly. Cons: tied to the cluster key (back it up), a per-cluster ciphertext, no central rotation.
- *External Secrets Operator*: syncs from a backend (Vault, cloud secret managers, and others) into Kubernetes Secrets. Pros: central rotation, no secrets in Git. Cons: needs a backend, which in an air-gapped site means running one.

Both fit naturally with Argo, and both leave the Ansible layer unfixed. Air-gapped fit: Sealed Secrets good, ESO only with an internal backend.

**5. Vault or OpenBao.** A real secrets service with policies, audit, short-lived credentials and dynamic secrets. Ansible reads via `community.hashi_vault` lookups; Kubernetes via ESO or the agent injector. Pros: the right end state for many teams, strong audit. Cons: another critical service to run, unseal and back up, and a bootstrapping problem (how does the runner authenticate?). Air-gapped fit: possible and common, but significant effort. `UNVERIFIED:` current OpenBao compatibility notes for the hashi_vault collection.

The rule of thumb: ansible-vault or CI variables this month, SOPS if the team wants secrets in Git, a Vault-class service only after the first two are habit.

### Cleanup, in the right order

1. **Rotate first.** Treat every value that ever appeared in Git as exposed. Rotating is the only step that actually removes risk. Do prod and anything with broad reach first.
2. **Then rewrite history, if you will.** `git filter-repo --replace-text expressions.txt` (or `--path secrets.env --invert-paths`) removes values from all branches; then force-push, have everyone re-clone, and ask GitLab admins to run housekeeping and clear caches and MR refs. Protected branches must be temporarily unprotected. This is disruptive, and after step 1 it is hygiene rather than emergency, so schedule it. `UNVERIFIED:` GitLab's current documented procedure for purging objects from a repository (docs.gitlab.com "Repository size / Remove blobs").
3. **Then prevent recurrence.** A `pre-commit` hook running `gitleaks`, and GitLab's secret detection (the `Secret-Detection` CI template, plus push protection where the tier supports it). `UNVERIFIED:` which GitLab tier includes secret push protection on the version they run. Add `.env` to `.gitignore` and commit a `.env.example` with placeholders.

### Raising it constructively

Do it privately, first to the lead who owns the repo, not in a public MR comment or channel. Frame it as "I found something in the repo that I would want someone to tell me about", name the file path but never paste the value, and say how you found it. Bring a proposal that costs little: move prod secrets to GitLab masked/protected variables or ansible-vault with per-environment vault IDs, rotate the exposed values, and add a gitleaks check in the MR pipeline. Offer to do the first PR for one secret as a template. Do not propose Vault, SOPS or Terraform as a replacement; that reads as a rewrite and will be refused for good reasons. Ask what constraints exist (compliance, who has runner access, air-gap rules) before assuming they have been overlooked.

## Where Ansible and ArgoCD meet

The common and healthy split:

- **Ansible owns what is below or around Kubernetes**: VMs, OS, certificates on nodes, cluster creation, storage and networking prerequisites, and the one-time bootstrap of Argo itself (install, root Application, repo and cluster credentials).
- **ArgoCD owns what runs in the cluster**: charts and manifests for platform and application workloads, reconciled continuously from Git.

The conflict arises when both manage the same resource. Typical symptoms:

- Ansible's `kubernetes.core.helm` or `k8s` task changes a Deployment or ConfigMap that an Argo Application also tracks. Argo reports OutOfSync and, with self-heal on, reverts it; the next Ansible run changes it back, so each tool "fixes" the other.
- A `helm` release created by Ansible is then adopted by Argo, which renders the chart itself and ignores Helm release state; the Helm release secret and Argo's view diverge.
- Values live in two places: Ansible templates a `values.yaml` and Argo has its own, and nobody knows which is live.
- Pruning: Argo with `prune: true` deletes objects that Ansible created in a namespace it manages.

Ways to read and resolve it: check the tracking annotation and `managed-by` label on a resource (see above); for each in-cluster component decide one owner; if Ansible must set something Argo manages, use `ignoreDifferences` or have Ansible write the value into the Git repo Argo reads rather than into the cluster. Ansible creating `Application` objects is fine; Ansible then editing the resources those Applications deploy is not.

See doc 27 (ArgoCD) for Argo's sync, drift and ownership behaviour in detail: [27-argocd-in-an-ansible-gitlab-shop.md](27-argocd-in-an-ansible-gitlab-shop.md).

## Incremental improvements that don't require a rewrite

Ordered by effort, each independently useful:

1. **ansible-lint in the MR pipeline.** `ansible-lint` flags non-idempotent `shell` use, unnamed tasks, deprecated syntax and missing `no_log`. Start with the default profile, accept a baseline (`ansible-lint --generate-ignore`) and tighten over time.
2. **`--syntax-check` and `--check --diff` on every MR**, against dev. Treat the diff as the "plan" reviewers read. Expect some tasks to be skipped in check mode; mark them with `check_mode: false` or `when: not ansible_check_mode` deliberately.
3. **Secrets out of Git** via the options above. This is the highest-value change.
4. **Directory-per-environment inventories** (`inventories/dev|staging|prod/{hosts.yml,group_vars/}`), even while branches remain. This makes environment differences explicit and reviewable, and makes a later move away from env branches trivial: merge the branches into one trunk when the env directories already hold every difference.
5. **Pin versions**: collections in `requirements.yml`, chart versions in the helm tasks, and the EE or runner image by digest.
6. **Molecule** for roles that matter: `molecule test` with a container or VM driver gives role-level convergence and idempotence checks (it runs the role twice and fails if the second run changes anything). `UNVERIFIED:` current recommended Molecule driver setup for an air-gapped site.
7. **A drift job**: a scheduled pipeline (`$CI_PIPELINE_SOURCE == "schedule"`) running `--check --diff` against each environment and alerting on any `changed`. It is a poor man's `terraform plan` and the best answer to "no state".
8. **Branch hygiene**: forward-only merges, a CI check that fails if `roles/` or `playbooks/` differ between `dev` and `prod` beyond an allowed lag.

## Check yourself

1. Ansible has no state file. How does that change what happens when you delete a task from a playbook?
2. You edit `group_vars/prod/vars.yml` and the deployed value does not change. Name three places the value could be overridden, and the command that shows the inventory-level merge for a host.
3. What is the difference between `--check` and `terraform plan`, and why can `--check` mislead?
4. In the environment-branch pattern, what does `git log dev..prod --oneline` show, and why do you care?
5. A Deployment has the label `app.kubernetes.io/managed-by: Helm` but also an Argo tracking annotation. What might be going wrong?
6. Why is rotating a leaked secret more urgent than rewriting history?
7. Which secrets option needs no new service, works offline, and keeps the repo's existing Ansible workflow? What must the CI job hold to use it, and how should it be stored?
8. Give two reasons to propose ansible-vault or CI variables before Vault or SOPS.
9. Where does `values_files` in `kubernetes.core.helm` read files from?
10. How does a directory-per-environment layout make later movement off env branches easier?

## References

Fetched and checked on 2026-11-18:

- Ansible, precedence rules: https://docs.ansible.com/ansible/latest/reference_appendices/general_precedence.html
- kubernetes.core.helm module (kubernetes.core 6.6.0 docs): https://docs.ansible.com/ansible/latest/collections/kubernetes/core/helm_module.html
- GitLab CI/CD YAML reference: https://docs.gitlab.com/ci/yaml/ (only the first part of the page was read; `rules` detail is from prior knowledge)
- GitLab CI/CD variables: https://docs.gitlab.com/ci/variables/

Not re-fetched on 2026-11-18 (from prior knowledge; verify before relying on specifics):

- Ansible vault guide: https://docs.ansible.com/ansible/latest/vault_guide/index.html
- Ansible inventory and variables guide: https://docs.ansible.com/ansible/latest/inventory_guide/index.html
- ansible-navigator and execution environments: https://docs.ansible.com/ansible/latest/getting_started_ee/index.html
- kubernetes.core collection: https://docs.ansible.com/ansible/latest/collections/kubernetes/core/index.html
- community.vmware: https://docs.ansible.com/ansible/latest/collections/community/vmware/index.html
- vmware.vmware: https://docs.ansible.com/ansible/latest/collections/vmware/vmware/index.html
- community.sops: https://docs.ansible.com/ansible/latest/collections/community/sops/index.html
- GitLab secret detection: https://docs.gitlab.com/user/application_security/secret_detection/
- GitLab protected branches and environments: https://docs.gitlab.com/user/project/repository/branches/protected/
- git-filter-repo: https://github.com/newren/git-filter-repo
- gitleaks: https://github.com/gitleaks/gitleaks
- Sealed Secrets: https://github.com/bitnami-labs/sealed-secrets
- External Secrets Operator: https://external-secrets.io
- OpenBao: https://openbao.org
- Molecule: https://ansible.readthedocs.io/projects/molecule/
