# Volcano and GPU Scheduling on Kubernetes

Checked 2026-11-13. The Volcano docs site shows "Latest" with releases up to v1.16.0 (v1.16 announced on the CNCF blog 2026-10-28). Items I could not confirm from an opened page are marked `UNVERIFIED:`.

## In one paragraph

Volcano is a second scheduler you install next to kube-scheduler. It adds the things AI and batch jobs need and the default scheduler lacks: **gang scheduling** (start a group of pods together or not at all), **queues** with quotas and fair sharing between teams, preemption and reclaim between queues, and GPU-aware plugins including GPU sharing. Pods opt in with `schedulerName: volcano`; everything else in the cluster keeps using kube-scheduler. For an LLM/RAG stack on H100/H200 GPUs it is the layer that decides which team's pods get the scarce GPUs, and it prevents a multi-GPU workload from grabbing half its GPUs and deadlocking.

## The plain version

Picture a shared kitchen with a few very expensive ovens, and many cooks who each need several ovens at once for a big banquet. The ordinary house rule is "first come, first served, one oven at a time". Two cooks each grab half the ovens they need, both wait for the rest, and nobody can cook: a deadlock, with the expensive ovens sitting idle. Volcano is a kitchen manager with a booking book. A cook asks for all the ovens needed, and gets them all at once or waits; teams get fair shares, borrowing is allowed when ovens are idle, and the manager can ask for them back when the owner turns up.

Without it, expensive graphics cards sit reserved but unused, big jobs never start, one busy team can starve the others, and nobody can say who is entitled to what. The special cards are costly enough that idle time is real money.

It does not replace the ordinary manager for everything. Only the jobs you mark go through Volcano; the rest of the cluster carries on as before.

If you remember only five things:

- Volcano is a second scheduler (the part that decides which computer runs which program); programs opt in by naming it.
- "Gang scheduling" means all-or-nothing: a group of programs starts together or not at all.
- Queues are named buckets with shares and limits, one per team or purpose.
- Graphics cards are normally handed out whole; Volcano can also split them, with caveats.
- NVIDIA's GPU Operator makes the cards visible; Volcano decides who gets them.

## Why it exists

You know kube-scheduler: it takes one pending pod at a time, filters nodes, scores them, binds. That is fine for stateless web apps. For GPUs and distributed work it has gaps:

- **No all-or-nothing.** A job needing 4 pods x 8 GPUs may get 3 pods placed and wait forever for the fourth while holding 24 GPUs. Two such jobs can deadlock each other. Upstream Kubernetes is only now adding gang scheduling: the Kubernetes docs page describes it as **beta since v1.37, disabled by default**, behind the `GenericWorkload` feature gate and the `scheduling.k8s.io/v1beta1` PodGroup API (kubernetes.io page checked 2026-11-13). Do not assume your cluster has it on.
- **No queues or quotas by team.** `ResourceQuota` is a hard cap per namespace, not a fair-share system with borrowing of idle capacity and reclaiming it later.
- **No cross-job preemption policy** that understands "this team is over its share".
- **GPUs are whole, opaque integers** (`nvidia.com/gpu: 1`); there is no native fractional sharing.

Analogy: kube-scheduler is like Proxmox placing one VM at a time on a free host; Volcano is closer to an HPC batch system (Slurm) for Kubernetes.

## How it works

Volcano installs three components in `volcano-system` (Volcano installation page): `volcano-scheduler`, `volcano-controllers`, `volcano-admission` (a webhook; plus a one-shot `volcano-admission-init` job).

```
 Deployment / vcjob / Ray / Spark ...
        |  pod.spec.schedulerName: volcano
        v
 PodGroup (minMember, minResources, queue, priorityClass)   <- created by you, or auto-created
        |
 Queue (weight | deserved | capability | guarantee, parent)
        |
 volcano-scheduler: every cycle opens a "session" and runs ACTIONS in order,
   each action calls PLUGINS (grouped in TIERS) for ordering/scoring/veto
        |
 bind pods to nodes (only when the PodGroup's minMember can be satisfied)
```

Core objects (docs: Queue, PodGroup, VolcanoJob pages). Each starts with a plain gloss.

- **Queue** (gloss: a named waiting line with a share of the cluster) (`scheduling.volcano.sh/v1beta1`, `kind: Queue`): a collection of PodGroups, the unit for dividing the cluster. Spec fields: `weight` (relative share, used by the *proportion* plugin, default 1), `capability` (hard upper limit), `deserved` (expected amount, used by the *capacity* plugin; use above this can be reclaimed), `guarantee` (reserved, other queues cannot use it), `reclaimable` (default true), `priority`, `parent` (defaults to root). States: Open, Closed, Closing, Unknown.
- **PodGroup** (gloss: a party booking, "I need 4 seats together or none") (`scheduling.volcano.sh/v1beta1`): `minMember` (pods that must run together), `minResources`, `queue` (must be Open), `priorityClassName`. Phases: pending, inqueue, running, unknown. If a VolcanoJob has no PodGroup, Volcano creates one named after the job.
- **VolcanoJob / `vcjob`** (gloss: an ordinary batch job with the booking built in) (`batch.volcano.sh/v1alpha1`, `kind: Job`): like a Kubernetes Job with `schedulerName`, `minAvailable`, `queue`, `maxRetry`, `tasks` (each with replicas and a pod template), lifecycle `policies`, and `plugins` (`ssh`, `env`, `svc` for MPI/distributed training wiring).

Gloss for actions: the steps the manager does on each pass, in order, like "check bookings, hand out ovens, take back borrowed ones". Precisely, actions, executed in the configured order (Volcano scheduler overview page): **enqueue** (admit pending jobs whose minimum resources fit), **allocate** (pick nodes), **preempt** (higher-priority tasks displace lower-priority ones *within* a queue), **reclaim** (take back resources lent to another queue that went over its share), **backfill** (place small best-effort pods in gaps).

Gloss for plugins: the individual rules of thumb the manager consults, such as "be fair" or "pack tightly". Precisely, plugins documented on the plugins page: **gang** (do not run a partial job; decides evictions only if the job can still reach `minAvailable`), **conformance** (never preempt `kube-system` pods), **drf** (dominant resource fairness: favour jobs holding less of their dominant resource), **nodeorder** (score nodes), **predicates** (can this pod bind to this node), **priority** (order by `priorityClassName`). Others that appear in configs: **proportion** (divide the cluster between queues by `weight`), **capacity** (queues carry an explicit `deserved` amount; elastic borrow and reclaim; **conflicts with proportion**, enable only one), **binpack** (pack pods onto fewer nodes), **overcommit**, **deviceshare** (GPU sharing). UNVERIFIED: binpack's argument names (`binpack.weight`, `binpack.cpu`, `binpack.resources`, ...): the docs pages I opened did not list them, so read the Scheduler/plugins reference before tuning.

The scheduler reads its config from the ConfigMap `volcano-scheduler-configmap` in `volcano-system`, key `volcano-scheduler.conf`. The Volcano example config shows:

```yaml
actions: "enqueue, allocate, backfill"
tiers:
- plugins:
  - name: priority
  - name: gang
  - name: conformance
- plugins:
  - name: overcommit
  - name: drf
  - name: predicates
  - name: proportion
  - name: nodeorder
  - name: binpack
```

(Plugin names and order from the chart's config, as summarised by the fetch tool; I could not retrieve it verbatim.) A tier is a priority level: plugins in tier 1 are consulted first; later tiers only break ties or decide if earlier tiers abstain. For cross-queue fairness you must **add `reclaim`** to `actions`.

Capacity plugin variant (capacity plugin user guide): add `reclaim` to actions, replace `proportion` with `capacity` in tier 2 (with `gang` and `drf` having preemption disabled), give each Queue a `spec.deserved` per resource (`cpu`, `memory`, `nvidia.com/gpu`), and for hierarchies set `enableHierarchy: true` and optionally `ancestorReclaimLevel`.

**Hierarchical queues** (gloss: queues inside queues, like a department with sub-teams sharing the department's allowance) (hierarchical queue page): queues have a `parent`; the scheduler auto-creates a `root`. Jobs can only be submitted to **leaf** queues; a parent that already has tasks cannot gain children; children's `deserved`/`guarantee` sums cannot exceed the parent's; reclaim goes to sibling queues first, then ancestors. Volcano v1.16 adds an **alpha, off-by-default `NamespaceQueue`** so teams can build sub-hierarchies inside their namespace (needs capacity, not proportion) and a **fairshare** plugin that decays each namespace's historical usage (default half-life four hours).

## How you run it

Install with Helm (Volcano installation page; the page gives no chart version, so pin one yourself):

```bash
helm repo add volcano-sh https://volcano-sh.github.io/helm-charts   # add chart repo
helm repo update
helm install volcano volcano-sh/volcano -n volcano-system --create-namespace   # installs scheduler, controllers, admission
kubectl get all -n volcano-system                                  # expect scheduler, controllers, admission Running
kubectl get queue                                                  # a 'default' queue exists after install (UNVERIFIED: not shown on the install page)
```

GitOps: put the same chart in an ArgoCD `Application` with `targetRevision` pinned. The admission webhook and CRDs mean first sync may need `ServerSideApply=true` (UNVERIFIED: general ArgoCD practice, not from Volcano docs).

A queue and a gang job:

```yaml
apiVersion: scheduling.volcano.sh/v1beta1
kind: Queue
metadata: {name: llm-inference}
spec:
  weight: 4            # proportion plugin
  reclaimable: true
  capability:          # hard cap
    nvidia.com/gpu: 8
---
apiVersion: batch.volcano.sh/v1alpha1
kind: Job
metadata: {name: finetune}
spec:
  schedulerName: volcano
  queue: llm-inference
  minAvailable: 2          # gang: start 2 workers or none
  maxRetry: 3
  plugins: {svc: [], env: [], ssh: []}
  tasks:
  - name: worker
    replicas: 2
    template:
      spec:
        restartPolicy: OnFailure
        containers:
        - name: trainer
          image: harbor.example.internal/ai/trainer:1.0
          resources: {limits: {nvidia.com/gpu: 4}}
```

**How a normal Deployment (an inference server) opts in.** Set `schedulerName: volcano` in the *pod template*. Volcano's design notes (found via search; not an opened Volcano doc) say a bare pod with no group annotation gets an auto-created PodGroup owned by the pod, and one with the `scheduling.k8s.io/group-name` annotation is attached to the PodGroup you created. The queue is chosen by an annotation or label on the pod; I saw `volcano.sh/queue-name` used as a **label** (KubeRay docs, opened) and `scheduling.volcano.sh/queue-name` as an **annotation** (Huawei docs, via search). UNVERIFIED: which key your Volcano version honours for plain Deployments. Test and then confirm with `kubectl get pg`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: {name: nim-llm}
spec:
  replicas: 2
  selector: {matchLabels: {app: nim-llm}}
  template:
    metadata:
      labels: {app: nim-llm}
      annotations:
        scheduling.k8s.io/group-name: nim-llm-pg      # attach to PodGroup (UNVERIFIED key behaviour for Deployments)
        scheduling.volcano.sh/queue-name: llm-inference   # UNVERIFIED key, see text
    spec:
      schedulerName: volcano
      containers:
      - name: nim
        image: harbor.example.internal/nvidia/nim/llama:1.0
        resources: {limits: {nvidia.com/gpu: 1}}
```

KubeRay and Spark operators have built-in Volcano support (`batchScheduler.name=volcano` in the KubeRay Helm chart).

Day-to-day commands:

```bash
kubectl get queue                         # queues and state
kubectl get podgroup -A                   # PodGroups and phase
kubectl describe podgroup <name> -n <ns>  # why Pending/Inqueue (events list unschedulable reasons)
kubectl get vcjob -A                      # VolcanoJobs  (short name per CRD; UNVERIFIED)
vcctl job list                            # NAME, PHASE, MIN, PENDING, RUNNING ...
vcctl job suspend --name finetune -n default
vcctl job resume  --name finetune -n default
vcctl job delete  --name finetune -n default
vcctl -h                                  # the CLI docs I opened cover job commands only; UNVERIFIED: `vcctl queue ...` subcommands
kubectl -n volcano-system logs deploy/volcano-scheduler    # scheduling decisions
```

GPU features:

- **Whole GPU:** `resources.limits: nvidia.com/gpu: N`, advertised by the NVIDIA device plugin. Volcano sees it as an ordinary extended resource, so queues can cap it (`capability`/`deserved` keyed `nvidia.com/gpu`).
- **GPU sharing** (Volcano GPU virtualization page): two modes, set per node: **HAMi-core** (software; CUDA API interception limits memory and cores; works on any GPU) and **dynamic MIG** (hardware slices; needs A100/H100-class). Requires Volcano 1.9+, Kubernetes 1.16+. You deploy `volcano-vgpu-device-plugin` *instead of* the standard device plugin on those nodes, confirm nodes advertise `volcano.sh/vgpu-number` and `volcano.sh/vgpu-memory`, and enable the `deviceshare` plugin in the scheduler config with `deviceshare.VGPUEnable: true` and `deviceshare.SchedulePolicy: binpack|spread`. Pods request `volcano.sh/vgpu-number` (count), optionally `volcano.sh/vgpu-cores` (percent, HAMi only) and `volcano.sh/vgpu-memory` (MB), plus annotation `volcano.sh/vgpu-mode: "hami-core"|"mig"`. "GPU number" is how many GPU devices; "memory" is per-vGPU memory, so 2 vGPUs x 3000 MB is a different request from 1 x 6000.
- **NUMA/topology:** Volcano has a NUMA-aware plugin and, since 1.16, HyperNode topology (network-topology tiers such as supernodes) and PodGroup topology anti-affinity. v1.16 notes "more accurate NUMA resource accounting". UNVERIFIED: how to configure NVLink/PCIe-aware placement for 8-GPU H100/H200 nodes; I found no page for it.

## How it fits the stack

```
VKS GPU worker VMs --> GPU Operator (driver, toolkit, DEVICE PLUGIN, DCGM) --> node advertises nvidia.com/gpu
                                                                                  |
Harbor images -----> pods (schedulerName: volcano) --> Volcano Queue/PodGroup --> bind to GPU node
```

The **NVIDIA GPU Operator** (v26.7.2 docs) installs the driver, container toolkit, device plugin, GPU Feature Discovery, DCGM exporter and MIG manager. The device plugin is what puts `nvidia.com/gpu` into a node's allocatable resources; Volcano never touches drivers. The two meet at node capacity: Operator makes GPUs visible, Volcano decides who gets them. If you adopt Volcano's vGPU plugin you replace the device plugin on those nodes, which collides with the Operator's plugin: UNVERIFIED how to disable only the plugin operand (the Operator has a `devicePlugin.enabled` Helm value, not verified this session).

Choosing between schedulers:

| | Volcano | Kueue | KAI Scheduler |
|---|---|---|---|
| Role | Replaces kube-scheduler for opted-in pods; own CRDs (Queue, PodGroup, vcjob) | Quota/admission layer; placement stays with kube-scheduler (Kueue overview page) | Replaces kube-scheduler for AI pods; built on kube-batch, CNCF sandbox, Apache-2.0 (GitHub README) |
| Gang | PodGroup minMember | "All-or-nothing with ready Pods" (timeout based, `waitForPodsReady`) | Gang scheduling, elastic workloads |
| Queues | Flat and hierarchical; DRF/proportion/capacity | ClusterQueue/LocalQueue, cohorts, fair sharing, preemption | Hierarchical queues, DRF, time-based fairshare |
| GPU sharing | HAMi-core or MIG via volcano-vgpu | None itself | "GPU sharing" listed |
| Workloads | vcjob, Pods, Ray, Spark, others | Job, JobSet, Deployment, StatefulSet, Pod groups, RayCluster, MPIJob... | Needs NVIDIA GPU Operator for GPUs |

UNVERIFIED: the relation between KAI Scheduler and Run:ai (the KAI README I opened does not mention it); install a pinned KAI version only after reading its releases page.

## What goes wrong

- **Pods stay Pending with no events from kube-scheduler.** Normal if `schedulerName: volcano` but Volcano is not installed or the admission webhook is down; check `kubectl get pods -n volcano-system`.
- **PodGroup stuck in `pending`/`inqueue`.** Its `minResources` or `minMember` cannot be met; `kubectl describe podgroup` shows the reason. The queue may also be `Closed`, or at `capability`.
- **Queue annotation silently ignored**, job lands in `default` queue (reported for KubeRay when the batch scheduler was not enabled in Helm). Verify with `kubectl get pg -o wide`.
- **Reclaim never happens.** `reclaim` is missing from `actions`, queues are `reclaimable: false`, or you enabled `proportion` and `capacity` together (documented conflict).
- **Preemption of services you care about.** Inference Deployments and training jobs in one queue can preempt each other; use PriorityClasses and separate queues.
- **Mixed schedulers fighting.** Two schedulers can both see the same node's free GPUs and race; the loser gets `UnexpectedAdmissionError`. Keep GPU nodes' pods all on Volcano, or reserve nodes by taint/label (UNVERIFIED: not from Volcano docs).
- **vGPU requests don't schedule.** Node doesn't advertise `volcano.sh/vgpu-*`, `deviceshare` plugin not enabled, or the stock device plugin is still running.
- **Version drift.** v1.16 supports Kubernetes 1.36 and needs Go 1.26 to build from source; pin chart and check support for your VKS Kubernetes version.

## Check yourself

1. Describe a deadlock that default kube-scheduler allows with two 4-pod GPU jobs, and how a PodGroup with `minMember: 4` prevents it.
2. What is the difference between a Queue's `weight`, `deserved`, `guarantee` and `capability`, and which plugin uses which?
3. Why must `reclaim` be in the `actions` list, and why can't `capacity` and `proportion` be enabled together?
4. What are tiers in the scheduler config and why does the order of plugins matter?
5. Write the minimal change needed to move an existing inference Deployment from kube-scheduler to Volcano, and how would you confirm a PodGroup was created?
6. Which component makes `nvidia.com/gpu` appear on a node, and what does Volcano do with that number?
7. When would you choose HAMi-core sharing versus MIG, and what do `vgpu-number`, `vgpu-cores` and `vgpu-memory` each mean?
8. In what situations would you pick Kueue or KAI Scheduler instead of Volcano?

## References

- Volcano docs index https://volcano.sh/en/docs/ (Latest; versions up to v1.16.0), pages Queue, PodGroup, VolcanoJob (`/en/docs/queue/`, `/podgroup/`, `/vcjob/`), Scheduler overview (`/schduler_introduction/`), Installation (`/installation/`), CLI (`/cli/`), Plugins (`/plugins/`), GPU virtualization (`/gpu_virtualization/`), Hierarchical queue (`/hierarchical_queue`); checked 2026-11-13
- Volcano v1.16 release post, https://www.cncf.io/blog/2026/10/28/volcano-v1-16-released-namespacequeue-fairshare-and-a-broader-hypernode-ecosystem/, checked 2026-11-13
- Capacity plugin guide (summarised), https://raw.githubusercontent.com/volcano-sh/volcano/master/docs/user-guide/how_to_use_capacity_plugin.md, checked 2026-11-13
- Kubernetes gang scheduling, https://kubernetes.io/docs/concepts/scheduling-eviction/gang-scheduling/, checked 2026-11-13
- KubeRay + Volcano, https://docs.ray.io/en/latest/cluster/kubernetes/k8s-ecosystem/volcano.html, checked 2026-11-13
- Kueue overview (main docs), https://kueue.sigs.k8s.io/docs/overview/, checked 2026-11-13
- KAI Scheduler, https://github.com/NVIDIA/KAI-Scheduler, checked 2026-11-13
- NVIDIA GPU Operator v26.7.2, https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/getting-started.html, checked 2026-11-13
- Not opened (search summaries only): Volcano PodGroup auto-creation design note and Huawei CCE docs on pod annotations.
