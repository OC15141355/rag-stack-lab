# VMware Tanzu / vSphere Kubernetes Service

Checked 2026-11-13. Docs read: VKS 3.8.0 variable reference, Supervisor Services catalogue (VKS 3.4.0 listed as newest at fetch time on that page), VCF 9.0 Supervisor docs, vSphere 8.0 Supervisor docs. Items I could not confirm from an opened page are marked `UNVERIFIED:`.

## In one paragraph

"Tanzu Kubernetes" in a Broadcom-era vSphere shop now means **vSphere Kubernetes Service (VKS)**: a service that runs inside the **vSphere Supervisor** (a Kubernetes control plane built into vCenter/VCF) and creates ordinary upstream-style Kubernetes clusters as sets of VMs, using Cluster API. You do not install Kubernetes yourself, as you do with RKE2 on Proxmox. You ask the Supervisor for a `Cluster` object in a vSphere Namespace and it builds the VMs, the load balancer and the storage plumbing. You then get a kubeconfig and use the cluster as normal Kubernetes. GPUs reach pods because the cluster's VMs carry a GPU (passthrough or vGPU) via a VM class, and the NVIDIA GPU Operator runs inside the cluster.

## The plain version

Think of a big company with a building full of computers run by an IT department. A project team wants a private workshop where they can run their programs, but they do not want to build the workshop themselves: pour the floor, run the power, buy the machines. So the IT department offers a service. The team fills in an order form saying "I need a workshop with this many machines, this size, this much storage", and within minutes a ready-made workshop appears, inside a fenced-off area with a spending limit that IT set. The team gets keys to their workshop only. That is what this product does for Kubernetes (the system that starts, stops and supervises programs across many computers).

Without it, every team would have to ask IT for individual virtual computers, install and patch Kubernetes on them by hand, and wire up networking and storage themselves. That is slow, easy to get wrong, and IT loses track of who is using what. The special-graphics-card machines needed for AI are the scarcest items, and this service lets IT hand them out in a controlled way.

The confusing part is naming: the product has had several names over the years, so the same thing appears in old documents under different labels.

If you remember only five things:

- The product you want to know is called vSphere Kubernetes Service (VKS); older names for it are TKG Service and "vSphere with Tanzu".
- It runs inside a control layer called the Supervisor, and you order clusters from it with a short form (a YAML file).
- IT controls the fenced-off area (the vSphere Namespace): size limits, machine types, storage.
- Graphics cards reach your programs by attaching the card to the virtual machine, and NVIDIA's GPU Operator then sets up the software inside.
- You log in with a Broadcom command-line tool, and logins expire, so re-logging in fixes many odd errors.

## Why it exists

You already run RKE2 on Proxmox: you create VMs, install RKE2, manage etcd, upgrades and CNI yourself, with ArgoCD on top. In a company with a large VMware estate, the vSphere administrators own the hypervisors, networking, storage and GPUs, and a separate team wants Kubernetes without owning all of that. VKS is the answer: the infrastructure team defines quotas, VM sizes and storage in vCenter, and Kubernetes users self-provision clusters inside those limits. It is closest to "Proxmox + Cluster API + a cloud provider", packaged and supported by the hypervisor vendor.

Names matter, because they changed several times:

| Name | What it is now | Source |
|---|---|---|
| **vSphere Supervisor** | The Kubernetes control plane built into vSphere. Formerly "vSphere IaaS control plane". Older names (vSphere with Tanzu, Workload Management, WCP) refer to the same family. | Supervisor-Services README (Broadcom vsphere-tmm repo) |
| **vSphere Kubernetes Service (VKS)** | Creates and lifecycle-manages workload clusters. Formerly "TKG Service" / "TKGS". Since vSphere 8.0 U3 it is installed as a **Supervisor Service**, so it can be upgraded separately from vCenter and the Supervisor. | same |
| **VMware Cloud Foundation (VCF)** | The bundle of vSphere, vSAN, NSX, and management tooling. VCF 9 documents the Supervisor and VKS as part of its platform. | VCF 9.0 techdocs |
| **Tanzu Kubernetes Grid (TKG), standalone** | The older "install Kubernetes with the `tanzu` CLI" product. UNVERIFIED: secondary sources say standalone TKG 2.5.4 was the final release and VKS is the successor; I did not open a Broadcom lifecycle page. |  |
| **Tanzu Platform** | Application-platform products (Cloud Foundry lineage). UNVERIFIED: only secondary sources, which say the SKUs were reorganised. It is not what you will operate for Kubernetes. |  |

Rule of thumb for conversations: if someone says "Tanzu cluster" they almost certainly mean a VKS workload cluster on a Supervisor. Ask which VCF/vSphere version and which VKS version, because behaviour differs (for example `kubectl vsphere login` versus the VCF CLI).

## How it works

```
 vCenter / VCF
   |
   +-- vSphere cluster(s) = vSphere Zone(s)
         |
         +-- SUPERVISOR  (1 or 3 control-plane VMs; Kubernetes API you log in to first)
               |  Supervisor Services: VKS, Harbor (Cloud Native Registry), Contour, ArgoCD Service ...
               |
               +-- vSphere Namespace "team-a"   (quota, permissions, VM classes, storage policies)
                     |
                     +-- Cluster object (Cluster API, ClusterClass-based)  --> VKS creates:
                           control-plane VMs + worker VMs (node pools)  = your workload cluster
                           (you get a separate kubeconfig for it)
```

Each idea below starts with a plain one-line gloss, then the precise version.

- **Supervisor** (gloss: the building manager's own Kubernetes, which takes your orders for new clusters): a Kubernetes control plane enabled on a vSphere cluster. It can run with one or three control-plane VMs, and over one or three vSphere Zones (zones are vSphere clusters used as failure domains). With NSX networking it can also run "vSphere Pods"; with vSphere-distributed-switch networking it supports only VKS clusters (VCF 9.0 docs).
- **vSphere Namespace** (gloss: your fenced-off plot with a spending limit): not a plain Kubernetes namespace only; it is a vCenter-managed boundary. The administrator sets resource quotas, user permissions, storage policies, VM classes and content libraries on it. VKS clusters, VMs and vSphere Pods are created inside it.
- **VM class** (gloss: a menu of machine sizes, some with a graphics card): a named VM size (CPU, memory, and optionally PCI devices such as a GPU). A class must be bound to the namespace before a cluster can use it.
- **Storage policy** (gloss: IT's named grades of disk space, such as fast or cheap): a vSphere VM Storage Policy assigned to the namespace shows up as a Kubernetes StorageClass in the Supervisor and is referenced by the cluster's `storageClass` variable. Persistent volumes in workload clusters use the vSphere CSI driver. (CSI driver is standard knowledge, not re-checked in a doc this session.)
- **Cluster API / ClusterClass** (gloss: the order form and its template for "build me a cluster"): the `Cluster` object (`cluster.x-k8s.io/v1beta1`) uses a topology section and a ClusterClass. The VKS 3.8.0 variable reference documents variables under `spec.topology.variables`: `vmClass` and `storageClass` are required; optional ones include `kubernetes` (API server, etcd, kubelet settings), `node` (labels, taints), `osConfiguration` (NTP, additional trusted CAs, sshd, proxy), `networks`, `volumes` (extra disks), and `bootstrapAddons`.
- **Kubernetes releases (VKr)** (gloss: the pre-approved Kubernetes versions you may choose from): Kubernetes versions are delivered as vSphere Kubernetes releases, VM templates distributed through a content library. VMware's VKS 3.5 announcement states each Kubernetes minor gets 24 months of support starting with VKr 1.34.
- **Load balancing** (gloss: a receptionist who spreads incoming visitors across your servers and gives them one front-door address): the VCF 9.0 docs list options for the Supervisor: VCF Networking with VPC (recommended), Foundation Load Balancer (vDS only, Layer 4), NSX with Edge load balancer, or Avi Load Balancer with NSX or vDS. A `Service` of type LoadBalancer in a workload cluster gets an address from this layer.
- **Supervisor Services** (gloss: optional extras IT can switch on for everyone, like a shared image library): add-on services installed on the Supervisor. The catalogue lists, among others: VKS, Cloud Native Registry (**Harbor** 2.12.4 to 2.14.3), Kubernetes Ingress (Contour), External DNS, Velero-based Backup & Recovery, ArgoCD Service (needs vSphere 8.0 U3g+ and a VCF entitlement), and Private AI Services (VCF 9 only).

## How you run it

Log in. On vSphere 8 with `kubectl vsphere` (KB 435399):

```bash
# Supervisor
kubectl vsphere login --server <supervisor-address> --vsphere-username <sso-user>
# A specific workload cluster
kubectl vsphere login --server <supervisor-address> --vsphere-username <sso-user> \
  --tanzu-kubernetes-cluster-namespace <vsphere-namespace> --tanzu-kubernetes-cluster-name <cluster>
kubectl config get-contexts          # contexts depend on your SSO permissions at login time
kubectl config use-context <name>
```

Broadcom's KB warns: do not give a cluster and its namespace the same name (context confusion), and always check the context's server IP before running commands.

On VCF 9 the KB says `kubectl vsphere login` is replaced by the **VCF CLI** (Broadcom VCF CLI docs):

```bash
vcf context create mysupervisor --endpoint https://<supervisor-fqdn> --type k8s   # create a context
vcf context use mysupervisor            # prompts for vCenter SSO credentials; also creates namespace contexts like supervisor:namespace1
vcf context list
vcf context use supervisor:namespace1
vcf cluster list
vcf cluster kubeconfig get <cluster-name> --export-file ./cluster.kubeconfig   # --export-file: from a Broadcom KB via search summary; UNVERIFIED on the flag
vcf plugin install package              # example plugin install shown in the docs
```

Create a cluster (applied to the Supervisor, in your namespace). This skeleton uses only fields confirmed in the VKS 3.8.0 variable reference; the ClusterClass name, Kubernetes version and `clusterNetwork` values are placeholders you must take from your environment (UNVERIFIED: exact `class` name and `version` string for your VKS release; Broadcom KBs mention `builtin-generic-v3.4.0` and later schemas):

```yaml
apiVersion: cluster.x-k8s.io/v1beta1
kind: Cluster
metadata:
  name: rag-gpu
  namespace: team-a
spec:
  clusterNetwork:            # required in v1beta1 (per search summary of Broadcom docs; UNVERIFIED in detail)
    pods:     {cidrBlocks: ["192.168.156.0/20"]}
    services: {cidrBlocks: ["10.96.0.0/12"]}
    serviceDomain: cluster.local
  topology:
    class: <clusterclass-name>        # e.g. builtin-generic-v3.x.y -- check `kubectl get clusterclass -n team-a`
    version: <vkr-version>            # check `kubectl get kubernetesreleases` (name UNVERIFIED)
    controlPlane: {replicas: 3}
    workers:
      machineDeployments:
        - class: node-pool
          name: gpu-pool
          replicas: 2
          variables:
            overrides:
              - name: vmClass
                value: gpu-h100-passthrough   # a custom class you or the vSphere admin created
    variables:
      - name: vmClass
        value: best-effort-medium
      - name: storageClass
        value: <storage-policy-name>
```

Why the worker override: a blog on VKS GPU passthrough (VCF 9.1, William Lam, June 2026) says you must apply the GPU VM class to workers only, otherwise deployment fails because VKS looks for a GPU for the control plane too.

How GPUs reach pods:

1. **Passthrough (Dynamic DirectPath I/O)**: the whole physical GPU is dedicated to one worker VM. The PCI device is marked for passthrough on the ESX host, a custom VM class includes it, and the cluster uses that class. The guest driver is installed in the worker VM, normally by the GPU Operator.
2. **vGPU**: the host runs NVIDIA's vGPU host driver and the GPU is split into profiles shared by several VMs; a VM class with a vGPU profile is used. NVIDIA's GPU Operator vGPU guide requires the NVIDIA License System (CLS or DLS), a `licensing-config` secret, a vGPU guest driver container built and pushed to a private registry (Docker only), and Helm values `driver.repository`, `driver.version`, `driver.imagePullSecrets`, `driver.licensingConfig.secretName` (GPU Operator v26.7.2 docs). Customers with an NVIDIA AI Enterprise entitlement use a prebuilt guest driver image instead.
3. **GPU Operator** inside the workload cluster:

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && helm repo update
helm install --wait --generate-name -n gpu-operator --create-namespace nvidia/gpu-operator --version=v26.7.2
# If Pod Security Admission is enforced, the namespace needs: pod-security.kubernetes.io/enforce=privileged
```

For a disconnected cluster the operator docs say to mirror `nvcr.io/nvidia/gpu-operator` and `nvcr.io/nvidia/driver:<ver>-<os>` (the driver tag must match the node OS) to a local registry, and set `repository`/`image`/`version`/`imagePullSecrets` per component in `values.yaml`; the driver container also needs a local OS package repository unless you use precompiled drivers (see file 12).

**VMware Private AI Foundation with NVIDIA** (VCF 9.0 blog): an add-on to VCF bundling a Private AI Package and NVIDIA AI Enterprise/NIM (NVIDIA licences bought separately). Private AI Services are Supervisor Services: a **Model Store** built on Harbor, a **Model Runtime** (vLLM for completion models, Infinity for embeddings) with an **API Gateway**, **Data Indexing and Retrieval** (chunk, embed, index into a vector DB), and an **Agent Builder** for RAG. Model endpoints run on nodes of a pre-built VKS cluster, with GPU access via pre-built VM classes. Whether your employer uses this bundle or plain VKS plus your own Helm charts is something to ask; they are different operating models. UNVERIFIED: any H100/H200 specifics (MIG on VKS, NVLink or multi-GPU passthrough, GPU count per VM class) -- I found no source for these.

## How it fits the stack

```
Harbor (images, NIM, models) --> VKS workload cluster <-- Volcano (scheduler)
                                   |   GPU Operator (driver, toolkit, device plugin, DCGM)
                                   |   VM class w/ H100/H200 passthrough or vGPU
                                   +-- ArgoCD/Helm  --> RAG: vector DB, embedder, LLM NIM, gateway
```

VKS gives you the cluster and the GPU nodes. Volcano (file 11) schedules pods onto those GPUs. Harbor (file 12) holds images; the Harbor Supervisor Service may be the registry you are given. Your GitOps practice carries over: ArgoCD manages workloads inside the workload cluster exactly as on RKE2.

## What differs from plain Kubernetes / RKE2

| Topic | RKE2 on Proxmox (you) | VKS |
|---|---|---|
| Who creates nodes | You (Terraform/cloud-init) | Cluster API via the Supervisor; you edit the `Cluster` object |
| Upgrades | You run RKE2 upgrades | Two layers: VKS service version (a Supervisor Service, upgraded by the vSphere admin) and the workload cluster's Kubernetes version (you change `topology.version`). Broadcom KBs: minor versions cannot be skipped; order is vCenter, then Supervisor, then VKS. A KB says upgrade VKS to 3.6.2+ before a Supervisor update (3.6.1 had topology reconciliation issues) -- read from search summaries; UNVERIFIED in detail |
| Node access | SSH as you like | UNVERIFIED: nodes are managed machines, SSH is via a Supervisor-provided key/jump, and changes should be made through the Cluster spec, not on the node. Nodes are replaced (rolling) rather than patched |
| Storage classes | Longhorn/local-path/NFS of your choice | vSphere storage policies assigned to the namespace become StorageClasses; vSphere CSI |
| Load balancer / ingress | MetalLB/ingress-nginx (yours) | LoadBalancer Services via NSX, Avi, or Foundation LB; Contour available as a Supervisor Service. Ingress controller inside your cluster is still yours to install |
| Pod security | You choose | UNVERIFIED: VKS applies Pod Security Admission defaults; the GPU Operator namespace needs `enforce=privileged` as above |
| Quotas | ResourceQuota only | vSphere Namespace limits at the infrastructure layer plus ResourceQuota inside |
| Certificates / CAs | cert-manager, your CA | Add private CAs through the `osConfiguration.trust.additionalTrustedCAs` cluster variable so node runtimes trust e.g. Harbor |
| Auth | Static kubeconfig or OIDC | vCenter SSO, short-lived tokens through `kubectl vsphere` or `vcf` |

## What goes wrong

- **Login works, then 401s**: tokens expire; permissions are captured at login. A KB reports 401 on some clusters after a Supervisor upgrade when legacy TKC and new Cluster objects mix. Re-login first.
- **Wrong context**: cluster and namespace with the same name; check the server IP in the context.
- **Cluster stuck creating**: the VM class is not bound to the namespace, the storage policy is not assigned, or the namespace quota is exhausted. Look at `kubectl describe cluster` and the Machine objects in the Supervisor, not the workload cluster.
- **Upgrade blocked / `TopologyReconciled` False**: ClusterClass/VKS version mismatch; KBs mention fixes in VKS 3.6.3+ and ClusterClass rebase notes. Do not hand-edit `spec.topology.class`.
- **GPU node shows no `nvidia.com/gpu`**: driver pod failing (vGPU licence not reachable, driver tag does not match node OS, image pull from nvcr.io blocked), or the GPU class landed on the control plane.
- **vGPU performance cliff after licence expiry**: unlicensed vGPU is throttled. UNVERIFIED: exact throttle behaviour.
- **Image pulls fail with x509**: workload nodes do not trust your Harbor CA; fix via cluster trust variable, not on the node.

## Check yourself

1. What were the previous names of the Supervisor and of VKS, and why does VKS upgrade independently of vCenter?
2. Which object do you apply, and to which cluster and namespace, to create a workload cluster?
3. Which two cluster variables are mandatory, and where do their values come from in vCenter?
4. Explain the difference between GPU passthrough and vGPU for a worker VM, and what each means for licensing and driver installation.
5. Why must the GPU VM class be applied to worker node pools only?
6. How does `vcf context use` differ from `kubectl vsphere login`, and when is each applicable?
7. List three things that are owned by the vSphere administrator rather than by you as a Kubernetes operator.
8. What happens to a node when you change `vmClass` in a node pool?

## References

- Supervisor Services catalogue, https://github.com/vsphere-tmm/Supervisor-Services (VKS 3.1.0 to 3.4.0, Harbor 2.12.4 to 2.14.3 listed), checked 2026-11-13
- VCF 9.0 vSphere Supervisor Installation and Configuration, https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-0/vsphere-supervisor-installation-and-configuration.html and its Concepts page, checked 2026-11-13
- VKS ClusterClass Variable Reference 3.8.0, https://developer.broadcom.com/xapis/vmware-vsphere-kubernetes-service/latest/variable-docs.html, checked 2026-11-13
- VCF CLI docs, https://developer.broadcom.com/xapis/vcf-cli-api/latest/api-docs.html, checked 2026-11-13
- Broadcom KB 435399, Troubleshooting Kubectl vSphere Contexts, https://knowledge.broadcom.com/external/article/435399/troubleshooting-kubectl-vsphere-contexts.html, checked 2026-11-13
- vSphere Supervisor 8.0 (TKG Service up to 3.3.3) landing page, https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere-supervisor/8-0/using-tkg-service-with-vsphere-supervisor.html, checked 2026-11-13
- VKS 3.5 announcement, https://blogs.vmware.com/cloud-foundation/2025/10/29/build-deploy-and-scale-with-confidence-vsphere-kubernetes-service-3-5-is-now-live-with-24-month-support/, checked 2026-11-13
- Private AI Services in VCF 9.0, https://blogs.vmware.com/cloud-foundation/2025/06/19/private-ai-services-new-in-vmware-private-ai-foundation-with-nvidia-in-vcf-9-0/, checked 2026-11-13
- NVIDIA GPU Operator v26.7.2: getting started, vGPU and air-gapped pages under https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/ , checked 2026-11-13
- William Lam, DirectPath passthrough to TKG (2023), https://williamlam.com/2023/10/nvidia-gpu-with-dynamic-directpath-io-passthrough-to-tanzu-kubernetes-grid-tkg-cluster-using-vsphere-with-tanzu.html; eGPU on VKS (VCF 9.1, 2026-06), https://williamlam.com/2026/06/vcf-9-1-oculink-external-graphics-egpu-passthrough-with-vsphere-kubernetes-service-vks.html, checked 2026-11-13
