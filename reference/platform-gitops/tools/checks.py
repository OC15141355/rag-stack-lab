#!/usr/bin/env python3
"""Every offline CI gate of the design (section 10), one function each. Needs PyYAML + jsonschema (+ helm for
render-check). Each check has a failure fixture under tests/reference/fixtures/<check>/ (a meta-test enforces it).

    python3 tools/checks.py                       all tree checks on this template
    python3 tools/checks.py --base OLD_TREE --labels multi-env,delete-weights
                                                  also the PR checks that compare against the target branch's tree
    python3 tools/checks.py --only evidence,digests-only --today 2026-11-26

Levels: FAIL blocks the merge; WARN is printed and never blocks (support_ends within 90 days, unknown support).
Exit 0 = no FAIL, 1 = at least one FAIL, 2 = usage error.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import render  # noqa: E402  (the one generator: loaders, constants, render-to-temp)

ROOT = render.ROOT
ENVS = render.ENVS
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DIGEST_REF = render.REF
# an image reference with a registry host (has a dot), a path, and a tag or digest
IMAGE_REF_TEXT = re.compile(r"(?<![\w./-])[a-z0-9-]+(?:\.[a-z0-9-]+)+(?::[0-9]+)?(?:/[a-z0-9._-]+)+"
                            r"(?::[A-Za-z0-9._-]+(?:@sha256:[0-9a-f]{64})?|@sha256:[0-9a-f]{64})(?![\w.-])")
# a YAML image/repository key whose value starts with a registry host (charts split refs into repository + tag)
IMAGE_KEY_TEXT = re.compile(r"(?:^|[{,\s])(?:image|repository)\s*:\s*[\"']?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?::[0-9]+)?/")
REVISION_KEY = re.compile(r"(revision|commit|git[-_.]?sha|restartedAt)", re.I)
WORKLOADS = ("Deployment", "DaemonSet", "StatefulSet", "Job")
WARN_DAYS = 90


@dataclass
class Finding:
    level: str  # FAIL | WARN
    check: str
    message: str

    def __str__(self):
        return f"{self.level} [{self.check}] {self.message}"


@dataclass
class Ctx:
    root: Path
    base: Path | None = None
    labels: frozenset = frozenset()
    today: dt.date = dt.date.today()


CHECKS: dict[str, dict] = {}


def check(name: str, needs_base: bool = False, needs_helm: bool = False):
    def deco(fn):
        CHECKS[name] = {"fn": fn, "needs_base": needs_base, "needs_helm": needs_helm, "doc": (fn.__doc__ or "").strip()}
        return fn
    return deco


# ---------------------------------------------------------------- helpers
def catalogue(root: Path):
    return render.load_catalogue(root)


_CACHE: dict = {}


def rendered(root: Path, env: str) -> list[tuple[str, dict]]:
    """[(relative file, object)] for one env's committed clusters/<env>/ (parsed once per file content)."""
    out = []
    d = root / "clusters" / env
    for f in sorted(d.rglob("*.yaml")):
        st = f.stat()
        key = (str(f), st.st_mtime_ns, st.st_size)
        if key not in _CACHE:
            _CACHE[key] = render.load_yaml_docs(f)
        out += [(str(f.relative_to(d)), copy.deepcopy(o)) for o in _CACHE[key]]
    return out


def objs(root: Path, env: str, kind: str | None = None, folder: str | None = None) -> list[dict]:
    return [o for f, o in rendered(root, env)
            if (kind is None or o.get("kind") == kind) and (folder is None or f.startswith(folder + "/"))]


def gateway_config(root: Path, env: str) -> tuple[dict, dict]:
    for o in objs(root, env, "ConfigMap", "40-gateway"):
        if o["metadata"]["name"] == "bifrost-config":
            return json.loads(o["data"]["config.json"]), json.loads(o["data"]["models.json"])
    raise FileNotFoundError(f"clusters/{env}/40-gateway has no bifrost-config ConfigMap")


def pod_specs(o: dict) -> list[dict]:
    if o.get("kind") in WORKLOADS:
        return [o.get("spec", {}).get("template", {}).get("spec", {})]
    return []


def container_images(o: dict) -> list[str]:
    out = []
    for ps in pod_specs(o):
        for c in (ps.get("containers") or []) + (ps.get("initContainers") or []):
            out.append(c.get("image", ""))
    if o.get("kind") == "NIMService":
        img = o["spec"]["image"]
        out.append(f"{img['repository']}:{img['tag']}")
        for c in o["spec"].get("initContainers") or []:
            i = c.get("image") or {}
            out.append(f"{i.get('repository')}:{i.get('tag')}" if isinstance(i, dict) else str(i))
    if o.get("kind") == "NIMCache":
        out.append(((o["spec"].get("source") or {}).get("ngc") or {}).get("modelPuller", ""))
    return out


def svc_blocks(svcs: dict):
    for s in svcs["services"]:
        for env, b in (s.get("envs") or {}).items():
            yield s, env, b or {}


def triple(b: dict) -> tuple:
    img = render.parse_ref(b["image"])
    return (img["digest"], b.get("profile_id"), (b.get("weights") or {}).get("revision"))


def strict(schema):
    """Copy of an OpenAPI schema where every object with declared properties rejects unknown fields
    (the API server would silently prune them; we want the PR to fail instead)."""
    if isinstance(schema, dict):
        s = {k: strict(v) for k, v in schema.items()}
        if ("properties" in s and "additionalProperties" not in s
                and not s.get("x-kubernetes-preserve-unknown-fields")):
            s["additionalProperties"] = False
        return s
    if isinstance(schema, list):
        return [strict(v) for v in schema]
    return schema


# ---------------------------------------------------------------- tree checks
@check("render-check", needs_helm=True)
def c_render(ctx):
    """clusters/ equals a fresh render of the catalogue, templates and vendored charts (render.py --check)."""
    try:
        out = render.render_all(ctx.root)
    except render.RenderError as e:
        return [f"render failed: {e}"]
    with tempfile.TemporaryDirectory() as tmp:
        render.write_tree(Path(tmp), out)
        diffs = render.diff_trees(ctx.root / "clusters", Path(tmp))
    return [f"clusters/{d} differs from a fresh render (never hand-edit clusters/; re-render and commit)" for d in diffs]


@check("chart-checksums")
def c_charts(ctx):
    """Every vendored chart archive is listed in platform/charts/SHA256SUMS with its true sha256, and vice versa."""
    import hashlib
    d = ctx.root / "platform/charts"
    sums = render.checksums(ctx.root)
    out = []
    for p in sorted(d.glob("*.tgz")):
        if p.name not in sums:
            out.append(f"platform/charts/{p.name} is not in SHA256SUMS")
        elif hashlib.sha256(p.read_bytes()).hexdigest() != sums[p.name]:
            out.append(f"platform/charts/{p.name} does not match its SHA256SUMS line")
    for name in sums:
        if not (d / name).is_file():
            out.append(f"SHA256SUMS lists {name} but the archive is missing")
    return out


@check("catalogue-schema")
def c_catalogue_schema(ctx):
    """services.yaml, platform.yaml and every evidence record validate against catalogue/schema/*.json."""
    import jsonschema
    out = []
    sdir = ctx.root / "catalogue/schema"
    pairs = [(ctx.root / "catalogue/services.yaml", "services"), (ctx.root / "catalogue/platform.yaml", "platform")]
    pairs += [(f, "evidence") for f in sorted((ctx.root / "catalogue/evidence").rglob("*.yaml"))]
    for f, name in pairs:
        schema = json.loads((sdir / f"{name}.schema.json").read_text())
        data = copy.deepcopy(render.load_yaml(f))
        for e in sorted(jsonschema.Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path)):
            out.append(f"{f.relative_to(ctx.root)}: {'/'.join(map(str, e.path)) or '<root>'}: {e.message[:200]}")
    return out


@check("crd-schema")
def c_crd_schema(ctx):
    """Every rendered custom resource validates against its CRD from the vendored charts (00-crds), with unknown
    fields REJECTED (the API server would prune them silently). NIMCache and NIMService must have a CRD."""
    import jsonschema
    out = []
    for env in ENVS:
        schemas = {}
        for crd in objs(ctx.root, env, "CustomResourceDefinition", "00-crds"):
            g = crd["spec"]["group"]
            for v in crd["spec"]["versions"]:
                schemas[(f"{g}/{v['name']}", crd["spec"]["names"]["kind"])] = strict(v["schema"]["openAPIV3Schema"])
        for f, o in rendered(ctx.root, env):
            if f.startswith("00-crds/"):
                continue
            key = (o.get("apiVersion"), o.get("kind"))
            if key not in schemas:
                if o.get("kind") in ("NIMService", "NIMCache"):
                    out.append(f"{env}/{f}: {o['kind']} {key[0]} has no CRD in 00-crds")
                continue
            for e in jsonschema.Draft7Validator(schemas[key]).iter_errors(o):
                out.append(f"{env}/{f}: {o['kind']}/{o['metadata'].get('name')}: "
                           f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message[:160]}")
    return out


@check("gateway-schema")
def c_gateway_schema(ctx):
    """Each env's generated Bifrost config.json validates against the vendored Bifrost schema; models.json lists
    every model the config routes."""
    import jsonschema
    schema = json.loads((ctx.root / "platform/schemas/bifrost-config.schema.json").read_text())
    out = []
    for env in ENVS:
        try:
            cfg, models = gateway_config(ctx.root, env)
        except FileNotFoundError as e:
            out.append(str(e)); continue
        for e in jsonschema.Draft202012Validator(schema).iter_errors(cfg):
            out.append(f"{env}: config.json {'/'.join(map(str, e.path)) or '<root>'}: {e.message[:160]}")
        routed = {m for p in cfg.get("providers", {}).values() for k in p.get("keys", []) for m in k.get("models", [])}
        listed = {m.get("alias") for m in models.get("models", [])}
        if routed != listed:
            out.append(f"{env}: models.json aliases {sorted(listed)} != routed models {sorted(routed)}")
    return out


@check("digests-only")
def c_digests(ctx):
    """Every image in the catalogues, and every image in rendered pod specs and NIM objects, is pinned by digest."""
    plat, svcs = catalogue(ctx.root)
    out = []
    for s, env, b in svc_blocks(svcs):
        if "image" in b and not DIGEST_REF.match(b["image"]):
            out.append(f"services.yaml {s['id']}.envs.{env}.image is not pinned by digest: {b['image']}")
    for c in plat["components"]:
        for env, b in (c.get("envs") or {}).items():
            for k, ref in ((b or {}).get("images") or {}).items():
                if not DIGEST_REF.match(ref or ""):
                    out.append(f"platform.yaml {c['id']}.envs.{env}.images.{k} is not pinned by digest: {ref}")
    for env in ENVS:
        for f, o in rendered(ctx.root, env):
            for img in container_images(o):
                if not re.search(r"@sha256:[0-9a-f]{64}$", img):
                    out.append(f"{env}/{f}: {o['kind']}/{o['metadata'].get('name')} image not digest-pinned: {img}")
    return out


@check("profile-ids")
def c_profiles(ctx):
    """LLM profile IDs are the 64-hex ID (never the versioned name), and NIMCache and NIMService pin the same one."""
    _, svcs = catalogue(ctx.root)
    out = []
    for s, env, b in svc_blocks(svcs):
        if s["kind"] == "nim-llm" and b.get("enabled") and not HEX64.match(str(b.get("profile_id", ""))):
            out.append(f"services.yaml {s['id']}.envs.{env}.profile_id is not a 64-hex profile ID: {b.get('profile_id')}")
    for env in ENVS:
        caches = {c["metadata"]["name"]: c for c in objs(ctx.root, env, "NIMCache")}
        for svc in objs(ctx.root, env, "NIMService"):
            ref = svc["spec"].get("storage", {}).get("nimCache", {})
            prof = ref.get("profile", "")
            if not HEX64.match(str(prof)):
                out.append(f"{env}: NIMService/{svc['metadata']['name']} profile is not 64-hex: {prof}")
            cache = caches.get(ref.get("name"))
            if cache is None:
                out.append(f"{env}: NIMService/{svc['metadata']['name']} names NIMCache {ref.get('name')!r}, not rendered")
                continue
            profs = cache["spec"]["source"]["ngc"].get("model", {}).get("profiles", [])
            if profs != [prof]:
                out.append(f"{env}: NIMCache/{cache['metadata']['name']} profiles {profs} != NIMService profile {prof}")
    return out


@check("evidence")
def c_evidence(ctx):
    """Promotion evidence: an enabled QA block's (image digest, profile_id, weights revision) has a DEV smoke pass
    recorded in catalogue/evidence/dev/, and an enabled PROD block's has a QA pass in catalogue/evidence/qa/."""
    _, svcs = catalogue(ctx.root)
    passes = set()
    out = []
    for f in sorted((ctx.root / "catalogue/evidence").rglob("*.yaml")):
        r = render.load_yaml(f)
        if f.parent.name != r.get("env"):
            out.append(f"{f.relative_to(ctx.root)}: env {r.get('env')!r} does not match its folder")
            continue
        if r.get("result") == "pass":
            passes.add((r["service"], r["env"], (r["image_digest"], r.get("profile_id"), r.get("weights_revision"))))
    for s in svcs["services"]:
        for env, prev in (("qa", "dev"), ("prod", "qa")):
            b = render.enabled_block(s, env)
            if not b:
                continue
            t = triple(b)
            if (s["id"], prev, t) not in passes:
                out.append(f"{s['id']}: {env} block (image {t[0][:19]}..., profile {str(t[1])[:12]}..., weights {t[2]}) "
                           f"has no {prev} smoke pass in catalogue/evidence/{prev}/")
    return out


@check("weights-complete")
def c_weights(ctx):
    """Every enabled LLM block has complete weights (source_uri, revision, manifest_sha256, pvc, size), and a PVC
    name always means one (service, revision): a new revision is a new PVC, never an overwrite."""
    _, svcs = catalogue(ctx.root)
    out, seen = [], {}
    for s, env, b in svc_blocks(svcs):
        if s["kind"] != "nim-llm" or not b.get("enabled"):
            continue
        w = b.get("weights") or {}
        missing = [k for k in ("source_uri", "revision", "manifest_sha256", "pvc", "size") if not w.get(k)]
        if missing:
            out.append(f"{s['id']}.envs.{env}.weights missing {missing}")
            continue
        if not HEX64.match(str(w["manifest_sha256"])):
            out.append(f"{s['id']}.envs.{env}.weights.manifest_sha256 is not 64-hex")
        key = (s["id"], w["revision"], w["manifest_sha256"], w["source_uri"])
        if seen.setdefault(w["pvc"], key) != key:
            out.append(f"PVC {w['pvc']} is used for two different (service, revision, manifest): {seen[w['pvc']]} vs {key}")
    return out


@check("deprecated-replacement")
def c_deprecated(ctx):
    """A deprecated service names a replacement that exists, is not itself, and is not retired."""
    _, svcs = catalogue(ctx.root)
    by_id = {s["id"]: s for s in svcs["services"]}
    out = []
    for s in svcs["services"]:
        d = s.get("deprecated") or {}
        if d.get("after"):
            r = d.get("replacement")
            if not r:
                out.append(f"{s['id']} is deprecated after {d['after']} but names no replacement")
            elif r == s["id"] or r not in by_id or by_id[r].get("retired"):
                out.append(f"{s['id']}: replacement {r!r} is missing, itself, or retired")
    return out


@check("retired-disabled")
def c_retired(ctx):
    """A retired service has no enabled environment block (retire = disable everywhere, then set retired)."""
    _, svcs = catalogue(ctx.root)
    return [f"{s['id']} is retired but envs.{env} is still enabled"
            for s, env, b in svc_blocks(svcs) if s.get("retired") and b.get("enabled")]


@check("no-revision-annotations")
def c_revision(ctx):
    """No revision/commit annotation or label in any pod template (or NIMService pod labels/annotations): an
    unrelated merge must not roll PROD pods. Content hashes (config-hash, secret-hash) are allowed."""
    out = []
    for env in ENVS:
        for f, o in rendered(ctx.root, env):
            metas = [o.get("spec", {}).get("template", {}).get("metadata", {})] if o.get("kind") in WORKLOADS else []
            if o.get("kind") == "NIMService":
                metas.append({"annotations": o["spec"].get("annotations") or {}, "labels": o["spec"].get("labels") or {}})
            for md in metas:
                for k in list((md.get("annotations") or {})) + list((md.get("labels") or {})):
                    if REVISION_KEY.search(k):
                        out.append(f"{env}/{f}: {o['kind']}/{o['metadata'].get('name')} pod template carries {k!r}")
    return out


@check("image-refs-location")
def c_image_refs(ctx):
    """Image references appear only in catalogue/ and the generated clusters/ (not in values, templates, docs, CI)."""
    out = []
    skip = ("catalogue/", "clusters/", "platform/charts/", "secrets/")
    for p in sorted(ctx.root.rglob("*")):
        rel = p.relative_to(ctx.root).as_posix()
        if not p.is_file() or rel.startswith(skip) or "__pycache__" in rel or p.suffix in (".tgz", ".pyc"):
            continue
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in IMAGE_REF_TEXT.finditer(line):
                out.append(f"{rel}:{i}: image reference {m.group(0)} outside catalogue/ and clusters/")
            if p.suffix in (".yaml", ".yml") and IMAGE_KEY_TEXT.search(line):
                out.append(f"{rel}:{i}: image repository outside catalogue/ (put the ref in the catalogue)")
    return out


@check("nim-cache-writable")
def c_cache_rw(ctx):
    """Every NIMService mounts its cache read-write, explicitly (NIM refuses a read-only cache: lab, found live)."""
    return [f"{env}: NIMService/{o['metadata']['name']} storage.readOnly is {o['spec'].get('storage', {}).get('readOnly')!r}, must be false"
            for env in ENVS for o in objs(ctx.root, env, "NIMService")
            if o["spec"].get("storage", {}).get("readOnly") is not False]


@check("gateway-key-ids")
def c_key_ids(ctx):
    """Every Bifrost virtual-key provider config has explicit, non-empty key_ids (config v2: empty denies all)."""
    out = []
    for env in ENVS:
        try:
            cfg, _ = gateway_config(ctx.root, env)
        except FileNotFoundError as e:
            out.append(str(e)); continue
        for vk in cfg.get("governance", {}).get("virtual_keys", []):
            for pc in vk.get("provider_configs", []):
                if not pc.get("key_ids"):
                    out.append(f"{env}: virtual key {vk.get('id')} provider {pc.get('provider')} has empty key_ids")
    return out


@check("airgap-auth")
def c_airgap_auth(ctx):
    """No NGC credentials in air-gapped environments: no authSecret on NIMService/NIMCache, no ngc-* Secret files."""
    plat, _ = catalogue(ctx.root)
    out = []
    for env in ENVS:
        if not plat["environments"][env]["air_gapped"]:
            continue
        for o in objs(ctx.root, env, "NIMService"):
            if o["spec"].get("authSecret"):
                out.append(f"{env} is air-gapped but NIMService/{o['metadata']['name']} has authSecret")
        for o in objs(ctx.root, env, "NIMCache"):
            if (o["spec"].get("source", {}).get("ngc") or {}).get("authSecret"):
                out.append(f"{env} is air-gapped but NIMCache/{o['metadata']['name']} has source.ngc.authSecret")
        for f in sorted((ctx.root / "secrets" / env).glob("ngc*")):
            out.append(f"{env} is air-gapped but secrets/{env}/{f.name} exists")
    return out


def _selects(policy: dict, labels: dict) -> bool:
    sel = policy["spec"].get("podSelector", {}).get("matchLabels", {})
    return all(labels.get(k) == v for k, v in sel.items())


def _ingress_from(policy: dict, ns: str, label: tuple[str, str], port: int) -> bool:
    for rule in policy["spec"].get("ingress", []) or []:
        ports = {p.get("port") for p in rule.get("ports", [])}
        if ports and port not in ports:
            continue
        for peer in rule.get("from", []):
            nsl = peer.get("namespaceSelector", {}).get("matchLabels", {})
            pl = peer.get("podSelector", {}).get("matchLabels", {})
            if nsl.get("kubernetes.io/metadata.name") == ns and pl.get(label[0]) == label[1]:
                return True
    return False


@check("nim-ingress-rules")
def c_nim_ingress(ctx):
    """Every NIMService's pods are reachable on 8000 from the gateway AND from the NIM Operator (which decides
    Ready by calling the NIM: without its rule the NIMService stays NotReady forever, lab)."""
    out = []
    for env in ENVS:
        pols = objs(ctx.root, env, "NetworkPolicy")
        for svc in objs(ctx.root, env, "NIMService"):
            ns, labels = svc["metadata"]["namespace"], svc["spec"].get("labels") or {}
            mine = [p for p in pols if p["metadata"].get("namespace") == ns and _selects(p, labels)]
            if not any(_ingress_from(p, "nim-operator", ("app.kubernetes.io/name", "k8s-nim-operator"), 8000) for p in mine):
                out.append(f"{env}: NIMService/{svc['metadata']['name']} has no NetworkPolicy ingress from the NIM Operator")
            if not any(_ingress_from(p, "gateway", ("app", "bifrost"), 8000) for p in mine):
                out.append(f"{env}: NIMService/{svc['metadata']['name']} has no NetworkPolicy ingress from the gateway")
    return out


@check("airgap-egress")
def c_airgap_egress(ctx):
    """In air-gapped envs, service egress goes only to the declared internal ranges (no 0.0.0.0/0 rule)."""
    plat, _ = catalogue(ctx.root)
    out = []
    for env in ENVS:
        e = plat["environments"][env]
        if not e["air_gapped"]:
            continue
        allowed = set(e["internal_ranges"])
        for p in objs(ctx.root, env, "NetworkPolicy"):
            for rule in p["spec"].get("egress", []) or []:
                for peer in rule.get("to", []):
                    cidr = (peer.get("ipBlock") or {}).get("cidr")
                    if cidr and cidr not in allowed:
                        out.append(f"{env}: NetworkPolicy/{p['metadata']['name']} egress to {cidr} (not an internal range)")
    return out


@check("weights-storage")
def c_weights_storage(ctx):
    """NIMCache never creates its PVC; it names a rendered weights PVC (20-weights) whose StorageClass has
    reclaimPolicy Retain and which Argo never prunes."""
    out = []
    for env in ENVS:
        pvcs = {p["metadata"]["name"]: p for p in objs(ctx.root, env, "PersistentVolumeClaim", "20-weights")}
        classes = {c["metadata"]["name"]: c for c in objs(ctx.root, env, "StorageClass")}
        for c in objs(ctx.root, env, "NIMCache"):
            pvc = c["spec"].get("storage", {}).get("pvc", {})
            n = c["metadata"]["name"]
            if pvc.get("create") is not False:
                out.append(f"{env}: NIMCache/{n} storage.pvc.create must be false (weights PVC is managed separately)")
            claim = pvcs.get(pvc.get("name"))
            if claim is None:
                out.append(f"{env}: NIMCache/{n} names PVC {pvc.get('name')!r}, not rendered in 20-weights")
                continue
            sc = classes.get(claim["spec"].get("storageClassName"))
            if sc is None or sc.get("reclaimPolicy") != "Retain":
                out.append(f"{env}: PVC/{claim['metadata']['name']} StorageClass is not a rendered Retain class")
            if "Prune=false" not in (claim["metadata"].get("annotations") or {}).get("argocd.argoproj.io/sync-options", ""):
                out.append(f"{env}: PVC/{claim['metadata']['name']} lacks argocd sync-options Prune=false,Delete=false")
    return out


@check("scope-placement")
def c_scope(ctx):
    """00-crds holds only CRDs; cluster-scoped objects live only in 00-crds/10-platform; every object carries
    managed-by=platform-gitops (the drift job's orphan detection keys on it)."""
    out = []
    for env in ENVS:
        scopes = {c["spec"]["names"]["kind"]: c["spec"]["scope"]
                  for c in objs(ctx.root, env, "CustomResourceDefinition", "00-crds")}
        for f, o in rendered(ctx.root, env):
            k, folder = o.get("kind"), f.split("/")[0]
            cluster = k in render.CLUSTER_KINDS or scopes.get(k) == "Cluster"
            if folder == "00-crds" and k != "CustomResourceDefinition":
                out.append(f"{env}/{f}: {k} in 00-crds")
            if cluster and folder not in ("00-crds", "10-platform"):
                out.append(f"{env}/{f}: cluster-scoped {k}/{o['metadata'].get('name')} outside 10-platform")
            if not cluster and not o["metadata"].get("namespace"):
                out.append(f"{env}/{f}: namespaced {k}/{o['metadata'].get('name')} has no namespace")
            if (o["metadata"].get("labels") or {}).get(render.MANAGED_BY[0]) != render.MANAGED_BY[1]:
                out.append(f"{env}/{f}: {k}/{o['metadata'].get('name')} lacks label managed-by=platform-gitops")
    return out


@check("envfrom-hash")
def c_secret_hash(ctx):
    """Every pod template that takes a Secret through envFrom carries platform-gitops/secret-hash.<name>
    (Secret changes via envFrom do not restart pods)."""
    out = []
    for env in ENVS:
        for f, o in rendered(ctx.root, env):
            for ps in pod_specs(o):
                ann = o["spec"]["template"].get("metadata", {}).get("annotations") or {}
                for c in ps.get("containers", []):
                    for ef in c.get("envFrom", []) or []:
                        n = (ef.get("secretRef") or {}).get("name")
                        if n and f"platform-gitops/secret-hash.{n}" not in ann:
                            out.append(f"{env}/{f}: {o['kind']}/{o['metadata']['name']} envFrom Secret {n} without secret-hash")
    return out


@check("sops-recipients")
def c_sops(ctx):
    """Every secrets/<env>/ file is SOPS-encrypted (ENC values, ENC mac) to exactly that env's age recipient, and
    no two environments share a recipient."""
    out = []
    rules = render.load_yaml(ctx.root / ".sops.yaml").get("creation_rules", [])
    recips = {}
    for env in ENVS:
        rule = next((r for r in rules if re.search(r["path_regex"], f"secrets/{env}/x.sops.yaml")), None)
        if rule is None:
            out.append(f".sops.yaml has no creation rule for secrets/{env}/"); continue
        recips[env] = {a.strip() for a in str(rule.get("age", "")).split(",") if a.strip()}
    for a, b in ((a, b) for a in recips for b in recips if a < b):
        if recips[a] & recips[b]:
            out.append(f".sops.yaml: {a} and {b} share an age recipient")
    enc = re.compile(r"^ENC\[[A-Z0-9_]+,data:.*\]$")
    for p in sorted((ctx.root / "secrets").rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ctx.root).as_posix()
        env = p.parent.name
        if env not in ENVS or not p.name.endswith(".sops.yaml"):
            out.append(f"{rel}: secrets/ holds only secrets/<env>/*.sops.yaml"); continue
        d = render.load_yaml(p) or {}
        sops = d.get("sops") or {}
        if not enc.match(str(sops.get("mac", ""))):
            out.append(f"{rel}: not a SOPS file (no ENC mac)"); continue
        for k in ("data", "stringData"):
            for key, v in (d.get(k) or {}).items():
                if not enc.match(str(v)):
                    out.append(f"{rel}: {k}.{key} is plaintext")
        got = {a.get("recipient") for a in sops.get("age", []) or []}
        if got != recips.get(env):
            out.append(f"{rel}: age recipients do not equal the {env} rule's")
    return out


# ---------------------------------------------------------------- PR checks (compare with the target branch)
def changed_envs(base: Path, head: Path) -> dict[str, list[str]]:
    out = {}
    for env in ENVS:
        d = render.diff_trees(base / "clusters" / env, head / "clusters" / env)
        if d:
            out[env] = d
    return out


@check("one-env-per-pr", needs_base=True)
def c_one_env(ctx):
    """A PR whose regenerated output changes more than one environment needs the multi-env label (and PROD
    approval through CODEOWNERS): a shared template change shows up in every env and is gated accordingly."""
    ch = changed_envs(ctx.base, ctx.root)
    if len(ch) > 1 and "multi-env" not in ctx.labels:
        return [f"this change renders differently in {sorted(ch)}; split it per environment or add the multi-env label"]
    return []


def _identities(root: Path, env: str, pred) -> set[tuple]:
    if not (root / "clusters" / env).exists():
        return set()
    return {(f.split("/")[0], o["kind"], o["metadata"].get("namespace", ""), o["metadata"]["name"])
            for f, o in rendered(root, env) if pred(f, o)}


@check("weights-delete-guard", needs_base=True)
def c_delete_weights(ctx):
    """A PR that removes a NIMCache, a PVC or anything in 20-weights needs the delete-weights label (and PROD
    approval): weights are the slowest thing to restore."""
    pred = lambda f, o: o["kind"] in ("NIMCache", "PersistentVolumeClaim") or f.startswith("20-weights/")  # noqa: E731
    out = []
    for env in ENVS:
        gone = _identities(ctx.base, env, pred) - _identities(ctx.root, env, pred)
        gone = {g for g in gone if g[1] != "Job"}   # verify Jobs are recreated freely
        if gone and "delete-weights" not in ctx.labels:
            out += [f"{env}: removes {k}/{n} ({folder}) without the delete-weights label" for folder, k, _, n in sorted(gone)]
    return out


# ---------------------------------------------------------------- warnings
@check("support-ends")
def w_support(ctx):
    """WARNING only: a component or service whose support_ends is within 90 days (or past), or unknown (null)."""
    plat, svcs = catalogue(ctx.root)
    out = []
    for kind, items in (("component", plat["components"]), ("service", svcs["services"])):
        for it in items:
            if it.get("retired") or (kind == "component" and not it.get("envs")):
                continue
            se = it.get("support_ends")
            if se is None:
                out.append(Finding("WARN", "support-ends", f"{kind} {it['id']}: support end unknown (owner "
                                   f"{it.get('owner')}, review by {it.get('review_by')})"))
                continue
            days = (dt.date.fromisoformat(se) - ctx.today).days
            if days <= WARN_DAYS:
                out.append(Finding("WARN", "support-ends", f"{kind} {it['id']}: support ends {se} "
                                   f"({'PAST' if days < 0 else f'in {days} days'}); plan the move (owner {it.get('owner')})"))
    return out


# ---------------------------------------------------------------- runner
def run(ctx: Ctx, only=None, skip=()) -> list[Finding]:
    findings = []
    for name, spec in CHECKS.items():
        if (only and name not in only) or name in skip:
            continue
        if spec["needs_base"] and ctx.base is None:
            continue
        try:
            res = spec["fn"](ctx)
        except Exception as e:  # a crashing check is a failing check, never a silent pass
            res = [f"check crashed: {e!r}"]
        for r in res:
            findings.append(r if isinstance(r, Finding) else Finding("FAIL", name, r))
    return findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--base", type=Path, help="the target branch's template tree (enables the PR checks)")
    ap.add_argument("--labels", default="", help="comma-separated PR labels (multi-env, delete-weights)")
    ap.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    ap.add_argument("--only", default="", help="comma-separated check names")
    ap.add_argument("--skip", default="", help="comma-separated check names")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    if a.list:
        for n, s in CHECKS.items():
            print(f"{n:24} {s['doc'].splitlines()[0]}")
        return 0
    only = {x for x in a.only.split(",") if x}
    unknown = (only | {x for x in a.skip.split(",") if x}) - set(CHECKS)
    if unknown:
        print(f"unknown checks: {sorted(unknown)}", file=sys.stderr)
        return 2
    ctx = Ctx(a.root, a.base, frozenset(x for x in a.labels.split(",") if x), a.today)
    findings = run(ctx, only, set(a.skip.split(",")))
    for f in findings:
        print(f)
    fails = [f for f in findings if f.level == "FAIL"]
    ran = [n for n in CHECKS if (not only or n in only) and not (CHECKS[n]["needs_base"] and a.base is None)]
    print(f"checks: {len(ran)} run, {len(fails)} failures, {len(findings) - len(fails)} warnings")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
