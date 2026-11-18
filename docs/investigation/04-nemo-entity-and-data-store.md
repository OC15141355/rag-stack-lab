# NeMo Entity Store, Data Store, and what the planned items really map to

Research date: 2026-11-19. Sources are NVIDIA's own documentation (NIM Operator 3.1.x, archived NeMo Microservices 25.x, NeMo Helix 0.7 to latest). Anything I could not confirm from a fetched page is marked `UNVERIFIED:`. Note that the archived NeMo Microservices pages carry a notice that they are "no longer actively maintained, validated, or updated", and several archive pages returned only that notice or navigation, so field-level detail is thinner than I would like.

## Summary

- NVIDIA has no component called a "model store". The nearest pieces are the Entity Store (metadata records), the Data Store (files), NIMCache (a PVC of pulled NIM artifacts), and NGC or a registry (images and artifacts).
- Entity Store manages "general entities": namespaces, projects, datasets and models. It is a metadata service backed by PostgreSQL. It is not a user or session store.
- Data Store is a Hugging Face Hub-compatible file store for model and dataset repositories, using PostgreSQL for repo/branch/LFS metadata, a PVC for Git history and an object store for LFS files. It exists to feed fine-tuning and evaluation (Customizer, Evaluator), not to serve NIM.
- Neither store holds NIM container images. Images come from NGC (`nvcr.io`) or a private mirror such as Harbor.
- The NIM Operator is a Kubernetes controller. Its "API" is CRDs. `NemoEntitystore` and `NemoDatastore` only deploy those two services and wire in an external Postgres, they do not manage model entries.
- NIM Operator support for the NeMo Microservices CRDs is being deprecated (callout in the 3.1.1, 3.1.2 and later docs); the product line is moving into "NeMo Platform", now documented as NeMo Helix.
- Nothing in these components publishes a "token limits" contract for a gateway to consume or enforce. Context length is a property of the model and of the serving engine (for example `max_model_len`).
- No DEV to QA to PROD promotion workflow with approvals and an audit log exists in NeMo Microservices, the NIM Operator or NeMo Helix, as far as the fetched docs show.
- Helix folds Entity Store, Data Store and a model concept into one platform: entities scoped to workspaces, filesets, model entities, and workspace RBAC. It is closer to what planned items (a) and (b) describe, but still has no promotion workflow.
- Planned items (a) to (e) are mostly not NVIDIA features. Item (c) matches well; the rest are either partial or must be built or sourced elsewhere.

## The plain version

The plan talks about a "model store" and an "entity store" living inside the NeMo operator, with Postgres behind them, and about model metadata and promotion flowing through "the operator API". NVIDIA's actual layout is different.

The operator is a controller. You give it a custom resource and it creates Deployments, Services and Ingress. For NeMo, it can deploy an Entity Store service and a Data Store service. It does not hold any model records itself.

The Entity Store is a small REST service that keeps records about namespaces, projects, datasets and models in Postgres. A "model" record there describes a model used for customization (base model, adapters, a pointer to files). It is not a catalogue of NIM images, and it holds no users or sessions. The Data Store is a Hugging Face-style file server for weights and datasets used by fine-tuning and evaluation.

NIM images and NIM model weights take another route: images come from NGC or your own registry, and weights get pulled by a NIMCache onto a volume.

Nothing here hands a gateway a context-window figure, and nothing enforces token limits. The serving engine rejects over-long requests; a gateway can only enforce what you tell it. Nothing here promotes a model from DEV to QA to PROD with approvals and an audit trail either. Newer Helix docs have workspaces and role-based access, which helps with separation, but promotion would be your own pipeline (Git, CI, approvals).

Postgres plans are fine: both stores need an external Postgres, and the docs say the embedded one is not for production.

## 1. NeMo Entity Store

*In one sentence: a Postgres-backed REST service holding shared metadata records (namespaces, projects, datasets, models) for the NeMo microservices.*

**What it manages.** The archived 25.9.0 "About Managing Entities" page says Entity Store handles shared "general entities," which are objects used by multiple microservices, and lists them as "namespaces, projects, datasets and models." Service-specific entities (evaluation targets, configurations, jobs, results) belong to their own services, for example Evaluator. The page says "The NeMo Entity Store microservice helps you manage these general entities."

**REST API.** The archived API index lists Namespaces (Create, Update, Get, List, Delete) and Models (Get Details, Update, List, Delete), plus Projects and Datasets sections. The nav shows these page titles but no paths. `UNVERIFIED:` exact paths (my recollection is `/v1/namespaces`, `/v1/projects`, `/v1/datasets`, `/v1/models`) and whether a create-model endpoint exists in the same form.

**Model entity fields.** The archived Models page distinguishes "Base models" (default models paired with customization configurations as a starting point for fine-tuning) and fine-tuned models (fine-tuned with a custom dataset). The field list was not retrievable. `UNVERIFIED:` field names. From memory of 25.x: name, namespace, description, project, base_model, peft, prompt, an artifact block (files URL, GPU architecture, backend engine, status), a spec block (parameter count, context size, precision, chat flag), custom_fields, ownership and timestamps. Treat the presence of a `context_size`-style field as unconfirmed; in Helix, the model spec is described differently (section 7).

**Users or sessions.** No. The entity types documented are namespaces, projects, datasets and models. Nothing in the fetched pages describes users, sessions or chat state. Confirmed absent from the documented entity list.

**Auth.** None documented. The archived pages say "This page doesn't cover authentication for Entity Store", and the NIM Operator CRD page has no authentication field. The only credentials in the CRD are the database secret and image pull secrets. `UNVERIFIED:` whether any 25.x deployment offered an auth layer; the archive nav mentions "Security for NeMo Microservices" and "API Key Authentication" (under Evaluate) but I could not read them. Safest assumption: put it behind your own network controls or an authenticating proxy.

**Postgres.** Required. The archived deploy page lists "Access to an external PostgreSQL database to store entities and metadata" as a prerequisite. By default the NeMo Microservices Helm chart deploys a Bitnami PostgreSQL chart. For an external DB see the chart's PostgreSQL config guide.

**Migrations.** The deploy page does not cover them. `UNVERIFIED:` whether the service runs its own schema migrations at start-up (very likely, since the operator CRD takes only connection details, but not documented in the pages I could read). The NIM Operator upgrade page (`nemo-upgrade.html`) was not read.

**Persistence.** All state is in Postgres. The CRD has no storage field. Losing the database loses the entities.

**Link to Data Store.** The Entity Store needs a Data Store URL (`appConfig.BASE_URL_DATASTORE` in Helm; `spec.datastore.endpoint` or `BASE_URL_DATASTORE` env in the CRD). The operator docs say a valid URL is "required for the Entity Store to function correctly" and that the two should be deployed together. That makes a Data Store a hard dependency for the supported deployment.

## 2. NeMo Data Store

*In one sentence: an HF-Hub-compatible file store for model and dataset repositories, with Git history on a volume, large files in object storage, and metadata in Postgres.*

**What it is.** The archived docs call it "the default file storage solution for the NeMo microservices platform," exposing APIs compatible with the Hugging Face Hub client (`HfApi`). The 25.9.0 deploy page puts the HF-compatible API under `/v1/hf` and namespace creation at `/v1/datastore/namespaces`; clients can pass an empty token.

**Gitea.** The 25.9.0 deploy page does not mention Gitea. The operator CRD page lists a `giteaAdminSecret`, and a third-party mirror of the operator API reference describes the service as Git-based using Gitea. `UNVERIFIED:` Gitea as the engine from an NVIDIA-authored page; the `giteaAdminSecret` field is strong circumstantial evidence.

**Storage.** From the 25.9.0 page: PostgreSQL "stores repository, branch, and LFS metadata" (external or in-cluster); an object store holds large files (external such as S3, or an internal local volume); a PVC "stores Git history for models and datasets". The operator CRD page says the Git history PVC is NFS-backed with ReadWriteMany in its example.

**Postgres needs.** Required, separate database from Entity Store's data in practice (CRD takes its own `databaseConfig`). `UNVERIFIED:` whether sharing one Postgres server across both is advised; it is technically feasible with separate databases.

**API and auth.** HF Hub-compatible endpoints, plus namespace creation. Secrets listed: DB credentials, object store credentials, NGC pull secret, and a JWT secret (LFS JWT in the CRD). Client token handling is not explained. Treat it as having service-to-service secrets but no documented user-level auth model.

**Relation to weights.** Customizer and Evaluator in the same cluster use the Data Store's internal URL to read and write models and datasets. The docs describe it as where fine-tuning inputs and outputs live. I found no page describing NIM loading weights from the Data Store. `UNVERIFIED:` any NIM-from-Data-Store path. The NIM Operator way of getting weights to a NIM is NIMCache (section 3), and the 3.1.x docs mention Hugging Face and mirrored sources (S3, HTTPS) as sources there, not the Data Store. The archive import tutorial notes that not all Hugging Face models are compatible with Customizer.

## 3. Is there an NVIDIA "model store" component?

*In one sentence: no; the closest candidates each cover one slice, and none stores NIM images except a registry.*

| Component | What it actually stores | Stores NIM images? | Stores weights? | Model records with metadata? |
|---|---|---|---|---|
| Entity Store | Namespaces, projects, datasets, model records (Postgres) | No | No (points to files) | Yes, for customization |
| Data Store | Repos of model/dataset files (PVC + object store + Postgres) | No | Yes, for customization | No (file repos) |
| NIMCache (operator CRD) | A PVC populated by a download Job from NGC, Hugging Face, or S3/HTTPS mirror | No | Yes, NIM model artifacts | No |
| NGC (catalog and private registry) | Container images, model artifacts, Helm charts | Yes (`nvcr.io`) | Artifacts | Catalog metadata |
| Harbor (not an NVIDIA product) | Whatever you mirror into it | Yes, if you mirror them | n/a | n/a |

NIMCache facts from the 3.1.x pages: it is the custom resource `nimcaches.apps.nvidia.com`; the controller runs a Job named `<nimcache-name>-job` to download artifacts; you can have the operator create the PVC or point at an existing one; if the operator created the PVC, deleting the NIMCache deletes the PVC and cached models; each cache pulls from a single source; HostPath is deprecated and not recommended for production.

So "model store" in the plan should be decomposed: images (NGC or Harbor), weights (NIMCache volume, or a fileset/Data Store for customization), and records (Entity Store, or something you own).

## 4. Operator CRDs: NemoEntitystore and NemoDatastore

*In one sentence: the CRDs deploy and configure the two services; they hold no model data themselves.*

**NemoEntitystore** (`nemoentitystores.apps.nvidia.com`, `apps.nvidia.com/v1alpha1`), per the 3.1.2 page:
- `spec.databaseConfig` (required): `databaseName`, `host`, `port` (default 5432), `credentials.user`, `credentials.secretName`, `credentials.passwordKey` (default `password`). External PostgreSQL only.
- `spec.datastore.endpoint` (required): Data Store endpoint.
- `spec.image` (required): repository, tag, pullPolicy (example also `pullSecrets`).
- `spec.env`: custom variables, notably `BASE_URL_DATASTORE`.
- `spec.expose`: Service (type, port 8000 default, annotations, labels) and `router` (Ingress or Gateway API HTTPRoute, mutually exclusive); `ingress.enabled` is deprecated in favour of `router`.
- Also `replicas`, `resources`, `metrics.enabled` with ServiceMonitor, `groupID` (2000), annotations, labels.
- No storage field: persistence is the external Postgres.
- Operator creates: Deployment, Service, optional Ingress or HTTPRoute, optional ServiceMonitor, status conditions (`Ready`, `Failed`).

**NemoDatastore** (`nemodatastores.apps.nvidia.com`):
- `databaseConfig` (required), same shape as above.
- `objectStoreConfig`: endpoint, bucketName, region, credentials, `ssl`, `serveDirect`.
- `pvc` (name, create, size, storageClass) and `storage.pvc` (volumeAccessMode, subPath); example uses ReadWriteMany.
- `image`: example `nvcr.io/nvidia/nemo-microservices/datastore`, tag `25.08`.
- `secrets` (required): `datastoreConfigSecret`, `datastoreInitSecret`, `datastoreInlineConfigSecret`, `giteaAdminSecret`, `lfsJwtSecret`.
- `authSecret`: NGC API key for image pulls (table says required, the example omits it).
- `scale` (HPA), `metrics`, `expose`, `replicas`, `tolerations`, `resources`, `userID`/`groupID`.
- Operator creates: Deployment, Service, optional PVC (deleted with the CR if the operator created it), Ingress or HTTPRoute, HPA, ServiceMonitor.

**Operator versus service.** The operator reconciles Kubernetes objects and reports status. It does not run schema migrations that we can see, does not create the Postgres database, does not back anything up, and exposes no model CRUD. Model CRUD is the Entity Store's REST API (to the extent documented above).

**Deprecation.** The 3.1.1 and 3.1.2 pages carry the verbatim notice: "The NIM Operator is deprecating support for the NeMo Microservices CRDs and deployments in the next release. The NeMo Microservices are transitioning into the NeMo Platform. Refer to the NeMo Platform documentation for details on continuing to use NeMo Microservices." The 3.1.2 and later release notes repeat an "Important" callout. `UNVERIFIED:` the exact release in which the CRDs are removed, and whether 3.1.0 itself carried the notice (the earliest wording I found is 3.1.1). Also, `spec.expose.ingress` is deprecated separately. Building new work on `NemoEntitystore` or `NemoDatastore` therefore builds on a CRD pair with a stated end of life.

## 5. Model metadata, token limits, and the "operator API"

*In one sentence: no NVIDIA component serves gateway-ready model metadata or enforces token limits, and the operator's API is its CRDs.*

- **Operator API.** The NIM Operator is a Kubernetes controller. Its interface is its CRDs (`NIMService`, `NIMCache`, `NemoEntitystore`, and others) read through the Kubernetes API. There is no operator REST API for consumers. The REST APIs belong to the microservices (Entity Store, Data Store, and in Helix the platform API).
- **Entity Store model records** are metadata for customization. `UNVERIFIED:` a context-size field in the 25.x model spec; even if present, it is descriptive of a customization target and nothing documented makes a gateway read it.
- **Helix model spec.** The Helix "Manage Model Entities" page says the Model Spec is "metadata about the model's architecture, populated automatically", and the example reads `family`, `base_num_parameters` and `num_layers`. The page "does not mention a context window field".
- **Helix virtual models.** A virtual model is "a named inference route in the Inference Gateway"; its only token setting is `max_output_tokens` for the classifier's judge in the router middleware, which "doesn't limit the routed backend model's response". Routing types: `random_routing`, `stage_router`, `llm_classifier`.
- **Enforcement.** The serving engine enforces its own context bound (for example vLLM-style `max_model_len`, which NIM LLM containers expose through their configuration). `UNVERIFIED:` the exact NIM environment variable name and per-profile defaults for the NIMs in scope; confirm against the NIM docs for the specific model.
- **Consequence.** If a gateway such as Bifrost must enforce token limits, the limits have to be configured in the gateway (or derived from a source you own, such as a Git-managed model catalogue), and kept consistent with the engine setting.

## 6. DEV to QA to PROD promotion

*In one sentence: none of NeMo Microservices, the NIM Operator or Helix ships a promotion workflow with approvals and an audit log.*

- **NIM Operator.** It reconciles whatever custom resources you apply. Promotion is "apply a different manifest to a different cluster or namespace", which is GitOps territory.
- **NeMo Microservices (25.x).** The documented concepts are namespaces, projects, customization, evaluation. No stage, promotion, approval, or audit-log concept appears in the pages fetched. `UNVERIFIED:` anything in the archived 25.x "Security for NeMo Microservices" page.
- **Helix.** The latest index has pages on workspaces, authorization (roles, role bindings, scopes, a policy engine) and vulnerability scanning ("Audit" in that index refers to model security audits, not an administrative audit log). Searching the index for "promotion" found nothing, and the authorization page does not cover audit logging. `UNVERIFIED:` whether Helix emits an administrative audit log elsewhere.
- **What it implies.** Validation gates, approval, audit and reproducibility must come from your own tooling: a Git repo with pinned image digests, model revisions and configuration; CI that runs evaluations; protected-branch approvals; and Argo CD or an equivalent applying the result per environment. Workspaces in Helix (or namespaces in 25.x) can separate environments inside one platform instance, but separate clusters or Postgres databases are the stronger boundary.

## 7. Helix equivalents

*In one sentence: Helix merges the Entity Store and Data Store ideas into workspace-scoped entities and filesets with RBAC, which is closer to the plan but is a different product line from the deprecated CRDs.*

- **Entities.** "Entities are the underlying data objects that power the NeMo Helix." Models, datasets, jobs and configurations are all entities in one shared store with common metadata and consistent CRUD. "Entities are always scoped to a workspace", names are unique per workspace, and "access control is applied at the workspace level". Raw HTTP access is the Entity Store API (the index shows `.../apis/entities/v2/workspaces/{workspace}/entities/{entity_type}` style endpoints). Exact paths beyond that index entry are `UNVERIFIED:`.
- **Files.** A fileset is "a named container that holds files", with unique names per workspace and a permanent ID. Backends: `local` (default, read/write), `s3` (Amazon S3 or MinIO, read/write), and read-only `huggingface`, `ngc`, `git`, `github`. Read-only backends are registrations; deleting one removes only the registration. Access via Python SDK, `nemo files` CLI, or fsspec. PVC is not named as a backend; `local` is the closest. `UNVERIFIED:` how `local` maps to a volume in a Kubernetes deployment.
- **Model entity.** "The platform's representation of a model": a FileSet reference, a Model Spec (architecture metadata, auto-populated), adapters (after training), and a base-model link. Weights live in the fileset, the entity references it. Registration, deployment and inference run through the gateway; the Models controller creates a passthrough virtual model per model entity.
- **Authorization.** Roles Viewer, Editor, Admin; role bindings of principal, role and workspace; token scopes; a PDP check followed by scope and role checks. The page does not describe authentication or OIDC.
- **Database.** The platform stores entities in SQL. The Helm chart deploys an embedded PostgreSQL by default, documented as unsuitable for production; for production you set `postgresql.enabled` to false and configure `externalDatabase` with a URI secret or host/port/user plus password secret. A URI secret is better for TLS. Upgrades must preserve the secrets encryption key and its Secret reference. The page does not cover migrations or backups.
- **Maturity.** Docs show versions 0.5 through 0.10 plus "latest": a pre-1.0 line, with the docs renamed through NeMo Microservices to NeMo Platform to NeMo Helix. Expect API churn. `UNVERIFIED:` NIM Operator integration details for Helix and any support commitments.

## 8. Mapping table: planned items to NVIDIA components

| Planned item | Actual NVIDIA component | Match quality | Notes |
|---|---|---|---|
| (a) "Model store" in the operator: weights, NIM images, configs, CRUD, persistent | None. Pieces: NIMCache (weights on PVC), NGC or Harbor (images), Entity Store model records (metadata), Data Store (fine-tuning files) | Mismatch | No single store. The operator has no CRUD for model entries; its API is CRDs. Images are never in Entity or Data Store. Entity Store CRUD exists but for customization records. |
| (b) "Entity store" for users, sessions, metadata, CRUD, persistent | NeMo Entity Store (deprecated CRD route) or Helix entities | Partial | The name matches, the content does not. Entity types are namespaces, projects, datasets, models; no users or sessions. Persistent via Postgres. App users and sessions need your own database. |
| (c) Postgres backend: schema, migrations, pooling/HA, backups, DEV/QA/PROD | External PostgreSQL required by both stores and by Helix | Matches | Both CRDs take an external Postgres via `databaseConfig`. Embedded Postgres is dev-only. Schema, migrations, pooling, HA, backups and per-environment separation are not documented or provided: they are your responsibility. `UNVERIFIED:` service-run migrations. |
| (d) Model metadata exposed via the operator API; token limits enforced from it | None | Not an NVIDIA feature | No operator API exists (CRDs only). Entity Store and Helix model records hold descriptive metadata; no documented context-window contract for a gateway; Helix spec shows family, parameter count, layer count. Enforcement is the engine (`max_model_len`) or the gateway's own config. |
| (e) DEV to QA to PROD promotion via the operator with gates, approval, audit, reproducibility | None | Not an NVIDIA feature | No promotion workflow found in NeMo Microservices, NIM Operator or Helix. Build with Git, CI evaluation gates, protected-branch approvals, pinned digests, GitOps per environment. Helix workspaces and RBAC help isolation only. |

## References

Fetched or searched 2026-11-19 unless noted.

- NIM Operator 3.1.2, Managing NeMo Entity Store: https://docs.nvidia.com/nim-operator/3.1.2/entity-store.html
- NIM Operator 3.1.2, Managing NeMo Data Stores: https://docs.nvidia.com/nim-operator/3.1.2/data-store.html
- NIM Operator 3.1.1 versions of the same pages (earliest deprecation wording found): https://docs.nvidia.com/nim-operator/3.1.1/data-store.html
- NIM Operator release notes (latest, 3.1.x callouts): https://docs.nvidia.com/nim-operator/latest/release-notes.html
- NIM Operator 3.1.2, Caching NIM Models: https://docs.nvidia.com/nim-operator/3.1.2/cache.html (via search results only; page body not read in full)
- NIM Operator 3.1.x upgrade page (not read): https://docs.nvidia.com/nim-operator/3.1.2/nemo-upgrade.html
- NeMo Microservices 25.9.0 (archive), About Managing Entities: https://archive.docs.nvidia.com/nemo/microservices/25.9.0/manage-entities/index.html
- NeMo Microservices 25.9.0 (archive), Models: https://archive.docs.nvidia.com/nemo/microservices/25.9.0/manage-entities/models/index.html
- NeMo Microservices 25.9.0 (archive), Data Store deployment: https://archive.docs.nvidia.com/nemo/microservices/25.9.0/set-up/deploy-as-microservices/data-store.html
- NeMo Microservices 25.9.0 (archive), Entity Store deployment: https://archive.docs.nvidia.com/nemo/microservices/25.9.0/set-up/deploy-as-microservices/entity-store.html
- NeMo Microservices 25.9.0 (archive), Platform API index: https://archive.docs.nvidia.com/nemo/microservices/25.9.0/api/platform.html
- NeMo Helix, Entities (v0.7.3): https://docs.nvidia.com/nemo-helix/v0.7.3/documentation/get-started/core-concepts/entities.md
- NeMo Helix, database setup (v0.7.3): https://docs.nvidia.com/nemo-helix/v0.7.3/documentation/kubernetes-deployment/setup/helm/database-setup.md
- NeMo Helix, latest index: https://docs.nvidia.com/nemo-helix/latest/llms.txt
- NeMo Helix, Manage Files: https://docs.nvidia.com/nemo-helix/latest/documentation/get-started/core-concepts/manage-files.md
- NeMo Helix, Manage Model Entities: https://docs.nvidia.com/nemo-helix/latest/documentation/customizer-reference/manage-model-entities/overview.md
- NeMo Helix, Virtual Models: https://docs.nvidia.com/nemo-helix/latest/documentation/models-and-inference/virtual-models.md
- NeMo Helix, Authorization: https://docs.nvidia.com/nemo-helix/latest/documentation/access-control/authorization.md

## UNVERIFIED items

- Exact Entity Store REST paths and the full model entity field list (including any context-size field).
- Whether Entity Store and Data Store run schema migrations at start-up.
- Any authentication on Entity Store or Data Store beyond service secrets.
- Gitea as the Data Store engine, from an NVIDIA-authored page (only `giteaAdminSecret` and a third-party mirror suggest it).
- Any NIM-from-Data-Store weight-loading path.
- The release in which the NeMo CRDs are removed from the NIM Operator, and whether 3.1.0 carried the notice.
- NIM context-length environment variable names and defaults for the NIMs in scope.
- An administrative audit log, or any promotion feature, anywhere in Helix beyond what the index shows.
- Helix `local` fileset backend mapping to a Kubernetes volume, and Helix NIM Operator integration.
