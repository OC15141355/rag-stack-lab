"""Section 13 item 7 (the GitLab CI file, linted structurally) plus the Argo CD layout of section 7 and the
template's own documents (section 3)."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from conftest import TEMPLATE

ENVS = ("dev", "qa", "prod")
CI = TEMPLATE / ".gitlab-ci.yml"


def ci():
    return yaml.safe_load(CI.read_text())


def resolved(doc, name):
    """A job merged with its `extends` parents (GitLab semantics: later parents and the job itself win)."""
    job = {}
    for parent in doc[name].get("extends", []):
        job.update(resolved(doc, parent))
    job.update({k: v for k, v in doc[name].items() if k != "extends"})
    return job


# ---------------------------------------------------------------- .gitlab-ci.yml
def test_gitlab_ci_states_it_is_a_translation():
    first = CI.read_text().splitlines()[0]
    assert first.startswith("# TRANSLATION of the CI proven in rag-stack-lab's GitHub Actions")


def test_gitlab_ci_job_names():
    doc = ci()
    want = {"gates:render-check", "gates:checks", "gates:pr-checks", "gates:secrets", "gates:tests"}
    for env in ENVS:
        want |= {f"{k}:{env}" for k in ("platform", "weights", "verify", "services", "prune", "drift")}
    jobs = {k for k in doc if not k.startswith(".") and isinstance(doc[k], dict) and "stage" in resolved(doc, k)}
    assert jobs == want
    for j in jobs:
        assert resolved(doc, j)["stage"] in doc["stages"]
    assert doc["stages"] == ["gates", "deploy-platform", "deploy-weights", "verify-weights", "deploy-services", "prune", "drift"]
    assert not [j for j in jobs if "needs" in resolved(doc, j)], "stage order is the deploy order: no `needs` shortcuts"


def test_gitlab_gates_run_the_same_commands_as_github():
    doc = ci()
    assert "python3 tools/render.py --check" in doc["gates:render-check"]["script"]
    assert "python3 tools/checks.py" in doc["gates:checks"]["script"]
    assert any("pytest" in l and "REQUIRE_HELM=1" in l for l in doc["gates:tests"]["script"])
    pr = " ".join(doc["gates:pr-checks"]["script"])
    assert "--base" in pr and "CI_MERGE_REQUEST_LABELS" in pr and "evidence-fresh" in pr
    assert doc["gates:pr-checks"]["rules"] == [{"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'}]


def deploy_rule(job):
    rules = job["rules"]
    assert rules[0] == {"if": '$CI_PIPELINE_SOURCE == "merge_request_event"', "when": "never"}, "MR pipelines never deploy"
    assert "$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH" in rules[1]["if"]
    return rules[1]


def test_gitlab_deploy_jobs_protected_ordered_and_scoped():
    doc = ci()
    for env in ENVS:
        jobs = {k: resolved(doc, f"{k}:{env}") for k in ("platform", "weights", "verify", "services", "prune")}
        for j in jobs.values():
            assert j["tags"] == [f"{env}-runner"], "each env deploys only from its own protected runner"
            assert j["environment"]["name"].startswith(env), "protected environment"
            assert j["variables"]["ENV"] == env
        # platform: manual everywhere, blocks the pipeline, only when its folders changed; ordered CRD pass
        r = deploy_rule(jobs["platform"])
        assert r["when"] == "manual" and r["allow_failure"] is False
        assert r["changes"] == [f"clusters/{env}/00-crds/**/*", f"clusters/{env}/10-platform/**/*"]
        assert jobs["platform"]["variables"]["KUBECONFIG_PLATFORM"] == f"$KUBECONFIG_{env.upper()}_PLATFORM"
        s = jobs["platform"]["script"]
        i_crd = next(i for i, l in enumerate(s) if "00-crds" in l and "apply" in l)
        i_wait = next(i for i, l in enumerate(s) if "condition=established" in l)
        i_plat = next(i for i, l in enumerate(s) if "10-platform" in l)
        assert i_crd < i_wait < i_plat
        assert all("--server-side" in l for l in s if "kubectl apply" in l)
        # weights then verify: verify is a separate manual blocking step, fails fast
        assert "verify/" not in " ".join(jobs["weights"]["script"])
        rv = deploy_rule(jobs["verify"])
        assert rv["when"] == "manual" and rv["allow_failure"] is False
        assert any("wait_jobs.py" in l and "20-weights/verify/" in l for l in jobs["verify"]["script"])
        # services: namespace-scoped creds + this env's age key; secrets first; automatic only in DEV
        sv = jobs["services"]
        assert sv["variables"]["KUBECONFIG_SERVICES"] == f"$KUBECONFIG_{env.upper()}_SERVICES"
        assert sv["variables"]["SOPS_AGE_KEY"] == f"$SOPS_AGE_KEY_{env.upper()}"
        rs = deploy_rule(sv)
        assert rs["when"] == ("on_success" if env == "dev" else "manual")
        text = "\n".join(sv["script"])
        assert sv["script"][0] == "set -o pipefail"
        assert "sops --decrypt" in text and "| kubectl apply --server-side -f -" in text
        assert text.index("sops --decrypt") < text.index("30-services") < text.index("40-gateway")
        assert text.index("weights-verify") < text.index("30-services"), "unverified weights never start"
        assert "10-platform" not in text and "00-crds" not in text
        # prune: manual, previous commit vs this one, weights only on request
        rp = deploy_rule(jobs["prune"])
        assert rp["when"] == "manual"
        pt = " ".join(jobs["prune"]["script"])
        assert "tools/prune.py --base" in pt and "DELETE_WEIGHTS" in pt and "CI_COMMIT_BEFORE_SHA" in pt
        # drift: schedules only; Secret values never written
        d = resolved(doc, f"drift:{env}")
        assert d["rules"] == [{"if": '$CI_PIPELINE_SOURCE == "schedule"'}]
        dt = "\n".join(d["script"])
        assert "tools/drift.py --env" in dt and "kubectl diff --server-side" in dt
        for line in d["script"]:
            if "kubectl get" in line and "secrets" in line:
                assert "--strip-secret-data" in line.split("|", 1)[1], line
        assert not [l for l in d["script"] if "kubectl get" in l and "secrets" in l.split("|")[0] and "|" not in l]


def test_gitlab_ci_names_no_image_reference():
    doc = ci()
    assert doc["default"]["image"] == "${PLATFORM_TOOLS_IMAGE}"
    assert not re.search(r"@sha256:|nvcr\.io|registry\.", CI.read_text().split("stages:")[1])


# ---------------------------------------------------------------- argocd/
def load(p):
    return [d for d in yaml.safe_load_all((TEMPLATE / p).read_text()) if d]


def test_argocd_projects_default_locked_and_services_namespace_scoped():
    for env in ENVS:
        projects = {d["metadata"]["name"]: d["spec"] for d in load(f"argocd/{env}/projects.yaml")}
        assert projects["default"] == {"sourceRepos": [], "destinations": [], "clusterResourceWhitelist": [],
                                       "namespaceResourceBlacklist": [{"group": "*", "kind": "*"}]}
        assert projects["services"]["clusterResourceWhitelist"] == []
        assert {d["namespace"] for d in projects["services"]["destinations"]} == {"models", "gateway"}
        windows = [bool(projects[p].get("syncWindows")) for p in ("platform", "services")]
        assert windows == ([False, False] if env == "dev" else [True, True])


CHAIN = ("crds", "platform", "secrets", "services", "gateway")
APP_FILE = {"secrets": "sops"}   # the repo-level .gitignore drops any path containing "secret"


def test_argocd_app_of_apps_dev_waves_manual_qa_prod_without_waves():
    for env in ENVS:
        (root,) = load(f"argocd/{env}/root.yaml")
        assert root["spec"]["source"]["path"] == f"argocd/{env}/apps"
        assert ("automated" in root["spec"]["syncPolicy"]) is (env == "dev"), "QA/PROD root is manual"
        waves = {}
        for name in CHAIN:
            (app,) = load(f"argocd/{env}/apps/{APP_FILE.get(name, name)}.yaml")
            sp = app["spec"]["syncPolicy"]
            waves[name] = (app["metadata"].get("annotations") or {}).get("argocd.argoproj.io/sync-wave")
            path = app["spec"]["source"]["path"]
            assert path.startswith((f"clusters/{env}/", f"secrets/{env}")), "one Argo per cluster: own folder only"
            assert "ServerSideApply=true" in sp["syncOptions"]
            assert ("automated" in sp) is (env == "dev"), "QA and PROD sync manually"
            if env == "prod":
                assert sp["retry"]["limit"] == 0
        if env == "dev":
            assert waves == {"crds": "0", "platform": "1", "secrets": "2", "services": "3", "gateway": "4"}
        else:
            assert set(waves.values()) == {None}, "manual children carry no waves (a wave would wait on an unsynced child)"
            assert "crds -> platform -> secrets -> weights" in (TEMPLATE / f"argocd/{env}/root.yaml").read_text()
        (crds,) = load(f"argocd/{env}/apps/crds.yaml")
        assert crds["spec"]["syncPolicy"].get("automated", {}).get("prune") in (None, False)


def test_argocd_secrets_app_uses_the_guarded_cmp():
    (cm,) = load("argocd/config/cmp-plugin.yaml")
    script = cm["data"]["sops-kustomize.yaml"]
    for env in ENVS:
        (app,) = load(f"argocd/{env}/apps/sops.yaml")
        assert app["spec"]["source"] == {"repoURL": app["spec"]["source"]["repoURL"], "targetRevision": "main",
                                         "path": f"secrets/{env}", "plugin": {"name": "sops-kustomize"}}
        assert app["spec"]["project"] == "services"
        assert f"{env}-secrets:secrets/{env}" in script
    assert "exit 1" in script and "not permitted" in script


def test_argocd_weights_and_verify_are_outside_the_chain():
    for env in ENVS:
        w, v = load(f"argocd/{env}/weights.yaml")
        assert w["spec"]["source"]["path"] == f"clusters/{env}/20-weights"
        assert w["spec"]["source"]["directory"] == {"recurse": False}, "verify/ is NOT part of the weights app"
        assert v["spec"]["source"]["path"] == f"clusters/{env}/20-weights/verify"
        assert "automated" not in v["spec"]["syncPolicy"], "verify runs only when a person says the transfer is done"
        for a in (w, v):
            assert "argocd.argoproj.io/sync-wave" not in (a["metadata"].get("annotations") or {})
            assert a["spec"]["syncPolicy"].get("automated", {}).get("prune", False) is False
        assert not (TEMPLATE / f"argocd/{env}/apps/weights.yaml").exists()


def test_argocd_health_checks_cover_the_custom_kinds():
    (cm,) = load("argocd/config/argocd-cm.yaml")
    keys = {k for k in cm["data"] if k.startswith("resource.customizations.health.")}
    assert keys == {f"resource.customizations.health.{k}" for k in
                    ("argoproj.io_Application", "apps.nvidia.com_NIMCache", "apps.nvidia.com_NIMService",
                     "nvidia.com_ClusterPolicy")}
    assert 'replicas == 0' in cm["data"]["resource.customizations.health.apps.nvidia.com_NIMService"]


# ---------------------------------------------------------------- documents
def test_readme_walkthroughs_and_docs_exist():
    text = (TEMPLATE / "README.md").read_text()
    for h in ("## Layout", "## How to promote", "## How to add a model", "## How to upgrade a platform component",
              "## How to retire a model"):
        assert h in text
    assert "EXAMPLE" in text
    assert "Ansible" in (TEMPLATE / "bootstrap/README.md").read_text()
    assert "fail loudly" in (TEMPLATE / "tools/lifecycle-checklist.md").read_text()


def test_codeowners_routes_shared_inputs_and_prod_to_prod_approvers():
    rules = dict(l.split() for l in (TEMPLATE / "CODEOWNERS").read_text().splitlines() if l and not l.startswith("#"))
    for p in ("/catalogue/", "/platform/", "/services/", "/tools/", "/clusters/prod/", "/secrets/prod/"):
        assert rules[p] == "@platform-prod-approvers", p
    assert rules["/clusters/dev/"] != "@platform-prod-approvers"


def test_nothing_names_an_employer_or_a_real_internal_host():
    pattern = re.compile(r"\b(defence|defense|department|\.gov\b|gov\.au)", re.I)
    for p in TEMPLATE.rglob("*"):
        if p.is_file() and p != Path(__file__) and p.suffix in (".md", ".yaml", ".yml", ".py", ".json") \
                and "clusters" not in p.parts \
                and "schemas" not in p.parts:
            assert not pattern.search(p.read_text()), p
