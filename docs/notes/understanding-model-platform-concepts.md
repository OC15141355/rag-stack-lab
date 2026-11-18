# Understanding notes: operators, stores, metadata, promotion

Personal notes on the concepts behind this investigation, plain version first.
Correct them as you learn; mark anything you've confirmed on a real system.

## Operator vs API vs service

**Plain:** an operator is a robot that watches a to-do list in Kubernetes
and makes reality match it. It doesn't have its own front desk for people to
call. You talk to it by editing the to-do list.

- A **Kubernetes operator** = custom resource definitions (CRDs) plus a
  controller. You create objects such as `NIMService`; the controller creates
  Deployments, Services and PVCs, and keeps them matching.
- Its "API" is the Kubernetes API: `kubectl apply/get/delete` on its CRDs.
  "CRUD via the operator" means creating, listing, updating and deleting those
  objects.
- The **microservices** an operator deploys (e.g. NeMo Entity Store) have
  their own REST APIs. Those are separate from the operator.
- So "metadata exposed via the operator API" means either fields on a CR that
  consumers read from Kubernetes (unusual for a gateway), or a service's REST
  API (e.g. Entity Store). Be precise about which.

## Model artifacts: what lives where

| Thing | Where it usually lives |
|---|---|
| NIM container image | Registry (NGC → mirrored into Harbor) |
| Model weights / engine files | NGC or Hugging Face; locally in a PVC cache (`NIMCache`) |
| Model serving config (profile, TP, precision, max context) | `NIMService` / `NIMCache` spec, or Helm values / env vars |
| Model "catalogue" (names, descriptions, limits) for consumers | Gateway config, a config repo, or a catalogue service |
| Fine-tuned weights, datasets (customisation workflows) | NeMo Data Store (HF-compatible) / object storage |
| Metadata about models, datasets and projects for NeMo workflows | NeMo Entity Store |

A "model store" is usually several of these together, not one component.

## NIMCache and NIMService (NIM Operator)

**Plain:** NIMCache is "download the model once into a cupboard". NIMService
is "run the model from that cupboard, this many copies, with these
settings".

- `NIMCache`: pulls weights (or engines) for selected profiles into a PVC.
  Large models mean long downloads, so pre-stage them in an air-gap.
- `NIMService`: runs the NIM using the cache, with an image, resources,
  replicas, scaling, expose and probes.
- **Pin the profile** (engine, precision, tensor parallelism), or different
  GPU types pick different profiles and environments drift.

## Entity Store (NeMo)

**Plain:** a filing cabinet of *records about* things NeMo works with
(projects, models, datasets), so other NeMo services can find them. It is not
the things themselves, and not a user database.

Check against the docs (see investigation doc 04). It's a NeMo component,
backed by Postgres, and the operator's NeMo CRDs that deploy it are
deprecated.

## Data Store (NeMo)

**Plain:** a file store that speaks the Hugging Face protocol, where
datasets and fine-tuned models are uploaded and fetched by NeMo services.

## Model metadata and token limits

**Plain:** metadata is the label on the box: what the model is, how much
text it can take. *Enforcing* limits is a guard's job at the door (the
gateway), not the label's.

- The **context window** is enforced by the model server (`max_model_len`):
  over-long requests get a 400.
- **Per-user/app token or rate limits** are enforced by the gateway (e.g.
  Bifrost budgets and rate limits).
- Metadata is useful as *the source of truth that config is generated from*:
  one place defines "model X: 128k context, tools yes", and the gateway config
  and UI are derived from it.

## Promotion DEV → QA → PROD

**Plain:** promotion means "the exact thing we tested goes up a level",
with a record of who sent it and why.

- In Kubernetes, the "thing" is a set of pinned versions: image digest,
  model/profile, config values.
- The usual mechanism is **git**: a merge request that changes the pinned
  versions for the next environment. Approvals on the MR are the approval
  workflow, and git history is the audit log.
- **Validation gates** are pipeline jobs (smoke tests against QA) that must
  pass before the PROD MR can merge.
- Operators don't usually do promotion. They apply what git says.
  Promotion is a pipeline and process job.

## Questions I still have

-
