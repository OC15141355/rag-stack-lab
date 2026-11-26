"""Section 13 item 7 (the GitLab CI file, linted structurally) plus the Argo CD layout of section 7 and the
template's own documents (section 3)."""
from __future__ import annotations

import re

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
    want = {"gates:render-check", "gates:checks", "gates:pr-checks", "gates:secrets"}
    for env in ENVS:
        want |= {f"platform:{env}", f"weights:{env}", f"services:{env}", f"drift:{env}"}
    jobs = {k for k in doc if not k.startswith(".") and isinstance(doc[k], dict) and "stage" in resolved(doc, k)}
    assert jobs == want
    for j in jobs:
        assert resolved(doc, j)["stage"] in doc["stages"]


def test_gitlab_gates_run_the_same_commands_as_github():
    doc = ci()
    assert "python3 tools/render.py --check" in doc["gates:render-check"]["script"]
    assert "python3 tools/checks.py" in doc["gates:checks"]["script"]
    pr = " ".join(doc["gates:pr-checks"]["script"])
    assert "--base" in pr and "CI_MERGE_REQUEST_LABELS" in pr
    assert doc["gates:pr-checks"]["rules"] == [{"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'}]


def deploy_rules(job):
    rules = job["rules"]
    assert rules[0] == {"if": '$CI_PIPELINE_SOURCE == "merge_request_event"', "when": "never"}, "MR pipelines never deploy"
    assert "$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH" in rules[1]["if"]
    return rules[1]["when"]


def test_gitlab_deploy_jobs_protected_manual_and_scoped():
    doc = ci()
    for env in ENVS:
        plat, svc, wts = (resolved(doc, f"{k}:{env}") for k in ("platform", "services", "weights"))
        for j in (plat, svc, wts):
            assert j["tags"] == [f"{env}-runner"], "each env deploys only from its own protected runner"
            assert j["environment"]["name"].startswith(env), "protected environment"
            assert j["variables"]["ENV"] == env
        # platform: manual everywhere, cluster-scoped credentials, CRDs established before the rest
        assert deploy_rules(plat) == "manual"
        assert plat["variables"]["KUBECONFIG_PLATFORM"] == f"$KUBECONFIG_{env.upper()}_PLATFORM"
        s = plat["script"]
        i_crd = next(i for i, l in enumerate(s) if "00-crds" in l and "apply" in l)
        i_wait = next(i for i, l in enumerate(s) if "condition=established" in l)
        i_plat = next(i for i, l in enumerate(s) if "10-platform" in l)
        assert i_crd < i_wait < i_plat
        assert all("--server-side" in l for l in s if "kubectl apply" in l)
        # services: namespace-scoped credentials; automatic only in DEV
        assert svc["variables"]["KUBECONFIG_SERVICES"] == f"$KUBECONFIG_{env.upper()}_SERVICES"
        assert deploy_rules(svc) == ("on_success" if env == "dev" else "manual")
        assert deploy_rules(wts) == ("on_success" if env == "dev" else "manual")
        text = " ".join(svc["script"])
        assert "30-services" in text and "40-gateway" in text and "10-platform" not in text and "00-crds" not in text
        assert text.index("weights-verify") < text.index("30-services"), "unverified weights never start"
        # drift: schedules only
        d = resolved(doc, f"drift:{env}")
        assert d["rules"] == [{"if": '$CI_PIPELINE_SOURCE == "schedule"'}]
        assert any("tools/drift.py" in l for l in d["script"]) and any("kubectl diff --server-side" in l for l in d["script"])


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


def test_argocd_app_of_apps_waves_manual_sync_and_prod_retry_zero():
    for env in ENVS:
        (root,) = load(f"argocd/{env}/root.yaml")
        assert root["spec"]["source"]["path"] == f"argocd/{env}/apps"
        waves = {}
        for name in ("crds", "platform", "services", "gateway"):
            (app,) = load(f"argocd/{env}/apps/{name}.yaml")
            sp = app["spec"]["syncPolicy"]
            waves[name] = int(app["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"])
            assert app["spec"]["source"]["path"].startswith(f"clusters/{env}/"), "one Argo per cluster: own folder only"
            assert "ServerSideApply=true" in sp["syncOptions"]
            assert ("automated" in sp) is (env == "dev"), "QA and PROD sync manually"
            if env == "prod":
                assert sp["retry"]["limit"] == 0
        assert waves == {"crds": 0, "platform": 1, "services": 2, "gateway": 3}
        assert load(f"argocd/{env}/apps/crds.yaml")[0]["spec"]["syncPolicy"].get("automated", {}).get("prune") in (None, False)
        # weights: outside the chain (not under apps/), never pruned, no wave
        (w,) = load(f"argocd/{env}/weights.yaml")
        assert w["spec"]["source"]["path"] == f"clusters/{env}/20-weights"
        assert "argocd.argoproj.io/sync-wave" not in (w["metadata"].get("annotations") or {})
        assert w["spec"]["syncPolicy"].get("automated", {}).get("prune", False) is False


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
        if p.is_file() and p.suffix in (".md", ".yaml", ".yml", ".py", ".json") and "clusters" not in p.parts \
                and "schemas" not in p.parts:
            assert not pattern.search(p.read_text()), p


def test_no_template_or_fixture_file_is_gitignored():
    """The repo ignores *secret* paths; a template file it silently drops would vanish from the PR."""
    import shutil
    import subprocess
    if not shutil.which("git"):
        return
    root = TEMPLATE.parents[1]
    files = [str(p.relative_to(root)) for base in (TEMPLATE, root / "tests/reference") for p in base.rglob("*")
             if p.is_file() and not {"__pycache__", ".pytest_cache", ".ruff_cache"} & set(p.parts)]
    r = subprocess.run(["git", "-C", str(root), "check-ignore", "--no-index", "--stdin"], input="\n".join(files),
                       capture_output=True, text=True)
    assert r.stdout.strip() == "", f"gitignored: {r.stdout}"
