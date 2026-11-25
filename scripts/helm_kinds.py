#!/usr/bin/env python3
"""Summarise `helm template --include-crds` output (stdin) for an AppProject whitelist review.

Prints, sorted and de-duplicated:
  CLUSTER <group>/<kind>/<name>     cluster-scoped objects (each must be name-whitelisted)
  NS      <group>/<kind>            namespaced kinds (namespaceResourceWhitelist)
  HOOK    <hook>  <group>/<kind>/<name>   Helm hooks (Argo maps them to its own phases)
  UNKNOWN <group>/<kind>/<name>     kinds whose scope this script does not know: decide by hand
followed by `SHA256 <hex>` of the raw rendered input (the Helm repo is mutable; record it).
"""
from __future__ import annotations
import hashlib, sys
import yaml

CLUSTER_KINDS = {
    ("", "Namespace"), ("", "PersistentVolume"), ("", "Node"),
    ("apiextensions.k8s.io", "CustomResourceDefinition"),
    ("rbac.authorization.k8s.io", "ClusterRole"), ("rbac.authorization.k8s.io", "ClusterRoleBinding"),
    ("scheduling.k8s.io", "PriorityClass"), ("node.k8s.io", "RuntimeClass"),
    ("storage.k8s.io", "StorageClass"), ("storage.k8s.io", "CSIDriver"),
    ("admissionregistration.k8s.io", "ValidatingWebhookConfiguration"),
    ("admissionregistration.k8s.io", "MutatingWebhookConfiguration"),
    ("admissionregistration.k8s.io", "ValidatingAdmissionPolicy"),
    ("admissionregistration.k8s.io", "ValidatingAdmissionPolicyBinding"),
    ("apiregistration.k8s.io", "APIService"),
    ("nvidia.com", "ClusterPolicy"), ("nfd.k8s-sigs.io", "NodeFeatureRule"),
}
NS_KINDS = {
    ("", "ServiceAccount"), ("", "Service"), ("", "ConfigMap"), ("", "Secret"), ("", "Pod"),
    ("", "PersistentVolumeClaim"), ("apps", "Deployment"), ("apps", "DaemonSet"), ("apps", "StatefulSet"),
    ("batch", "Job"), ("batch", "CronJob"), ("rbac.authorization.k8s.io", "Role"),
    ("rbac.authorization.k8s.io", "RoleBinding"), ("networking.k8s.io", "NetworkPolicy"),
    ("policy", "PodDisruptionBudget"), ("monitoring.coreos.com", "ServiceMonitor"),
    ("monitoring.coreos.com", "PrometheusRule"), ("nfd.k8s-sigs.io", "NodeFeature"),
    ("nfd.k8s-sigs.io", "NodeFeatureGroup"),
}


def main() -> int:
    raw = sys.stdin.read()
    lines = set()
    for d in yaml.safe_load_all(raw):
        if not isinstance(d, dict) or "kind" not in d:
            continue
        api = d.get("apiVersion", "")
        group = api.split("/")[0] if "/" in api else ""
        kind, name = d["kind"], (d.get("metadata") or {}).get("name", "?")
        hook = ((d.get("metadata") or {}).get("annotations") or {}).get("helm.sh/hook")
        if hook:
            lines.add(f"HOOK    {hook}  {group}/{kind}/{name}")
        if (group, kind) in CLUSTER_KINDS:
            lines.add(f"CLUSTER {group}/{kind}/{name}")
        elif (group, kind) in NS_KINDS:
            lines.add(f"NS      {group}/{kind}")
        else:
            lines.add(f"UNKNOWN {group}/{kind}/{name}")
    for l in sorted(lines):
        print(l)
    print(f"SHA256 {hashlib.sha256(raw.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
