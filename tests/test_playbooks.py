"""Bootstrap playbooks: Phase A behaviour pinned, GPU-session mode isolated.

The mode-dependent values live in lab/bootstrap/vars/{phase-a,gpu-session}.yml. 02/03 are executed for real
(both modes) against fake kubectl/helm/stat on PATH, recording every command they run.
"""
import json, os, shutil, subprocess
from pathlib import Path
import pytest, yaml

ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT / "lab" / "bootstrap"
SELECTOR = "../vars/{{ 'gpu-session' if (gpu_session | default(false) | bool) else 'phase-a' }}.yml"
HAVE_ANSIBLE = shutil.which("ansible-playbook") is not None
if os.environ.get("CI") and not HAVE_ANSIBLE:
    def test_ansible_present_in_ci():
        pytest.fail("CI is set but ansible-playbook is not installed (uv run --with ansible-core)")
needs_ansible = pytest.mark.skipif(not HAVE_ANSIBLE, reason="ansible-playbook not installed")

PHASE_A_REQUIRED = ["argocd/raglab-root", "argocd/raglab-system", "raglab-apps/raglab-secrets",
                    "raglab-apps/raglab-dev", "raglab-apps/raglab-qa", "raglab-apps/raglab-prod",
                    "raglab-apps/raglab-nim-dev", "raglab-apps/raglab-nim-qa", "raglab-apps/raglab-nim-prod"]
GPU_REQUIRED = ["argocd/raglab-gpu-root", "argocd/raglab-gpu-operator", "argocd/raglab-nim-operator",
                "raglab-apps/raglab-gpu-secrets", "raglab-apps/raglab-dev-gpu"]

def mode_vars(name):
    return yaml.safe_load((BOOT / "vars" / f"{name}.yml").read_text())

def test_phase_a_values_pinned():
    assert mode_vars("phase-a") == {
        "kubeconfig_name": "kubeconfig", "rewrite_kubeconfig_server": True, "install_guest_agent": True,
        "gpu_host_prep": False, "k3s_exec": "server --secrets-encryption --write-kubeconfig-mode 0600",
        "hand_applied_dir": "argocd/hand-applied", "age_key_relpath": ".sops/raglab-age-key.txt",
        "app_projects": ["appproject-raglab.yaml", "appproject-raglab-platform.yaml"],
        "platform_apps": ["raglab-system.yaml"], "required_apps": PHASE_A_REQUIRED}

def test_gpu_values():
    v = mode_vars("gpu-session")
    assert set(v) == set(mode_vars("phase-a")), "both modes define the same variables"
    assert v["age_key_relpath"] == ".sops/raglab-gpu-session/age-key.txt"
    assert v["kubeconfig_name"] == "kubeconfig.gpu" and v["rewrite_kubeconfig_server"] is False
    assert "--disable traefik" in v["k3s_exec"] and "--secrets-encryption" in v["k3s_exec"]
    assert v["hand_applied_dir"] == "gpu/argocd/hand-applied" and v["required_apps"] == GPU_REQUIRED
    for f in v["app_projects"] + v["platform_apps"] + ["root-app.yaml", "namespaces.yaml", "cmp-plugin.yaml"]:
        assert (ROOT / "lab" / v["hand_applied_dir"] / f).is_file(), f

def test_every_play_that_needs_mode_vars_loads_them():
    for name, plays in (("01-platform.yml", [1, 2]), ("02-argocd.yml", [0]), ("03-handover.yml", [0])):
        doc = yaml.safe_load((BOOT / "playbooks" / name).read_text())
        for i in plays:
            assert doc[i]["vars_files"] == [SELECTOR], (name, i)

@needs_ansible
@pytest.mark.parametrize("mode", ["false", "true"])
@pytest.mark.parametrize("pb", ["01-platform.yml", "02-argocd.yml", "03-handover.yml", "04-gpu-prep.yml"])
def test_syntax_both_modes(mode, pb):
    r = subprocess.run(["ansible-playbook", "-i", "inventory.example.ini", "--syntax-check", "-e", f"gpu_session={mode}",
                        f"playbooks/{pb}"], cwd=BOOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def fake_env(tmp_path, apps):
    b = tmp_path / "bin"; b.mkdir()
    log = tmp_path / "log"; appsf = tmp_path / "apps.json"
    appsf.write_text(json.dumps({"items": [
        {"metadata": {"namespace": a.split("/")[0], "name": a.split("/")[1]},
         "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"},
                    "operationState": {"phase": "Succeeded"}}} for a in apps]}))
    (b / "kubectl").write_text(
        '#!/bin/sh\necho "$KUBECONFIG|$*" >> "$FAKE_LOG"\n'
        'case "$*" in\n'
        '  "get applications -A -o json") cat "$FAKE_APPS" ;;\n'
        '  "get secrets -A -o json") echo \'{"items": []}\' ;;\n'
        '  "-n argocd get secret sops-age-key") exit 1 ;;\n'
        'esac\nexit 0\n')
    (b / "helm").write_text('#!/bin/sh\necho "helm|$*" >> "$FAKE_LOG"\nexit 0\n')
    (b / "stat").write_text("#!/bin/sh\necho 600\n")
    for f in b.iterdir(): f.chmod(0o755)
    home = tmp_path / "home"
    for rel in (".sops/raglab-age-key.txt", ".sops/raglab-gpu-session/age-key.txt"):
        k = home / rel; k.parent.mkdir(parents=True, exist_ok=True)
        k.write_text("AGE-SECRET-" + "KEY-1" + "Q" * 58 + "\n"); k.chmod(0o600)   # fake, built at runtime
    kc = tmp_path / "kc"; kc.mkdir()
    (kc / "kubeconfig").write_text("clusters:\n- cluster:\n    server: https://192.168.0.50:6443\n")
    (kc / "kubeconfig.gpu").write_text("clusters:\n- cluster:\n    server: https://127.0.0.1:6443\n")
    env = {"KCDIR": str(kc), **os.environ, "PATH": f"{b}:{os.environ['PATH']}", "HOME": str(home), "FAKE_LOG": str(log),
           "FAKE_APPS": str(appsf), "ANSIBLE_LOCAL_TEMP": str(tmp_path / "ans"), "ANSIBLE_NOCOLOR": "1"}
    return env, log

def play(pb, mode, env):
    return subprocess.run(["ansible-playbook", "-i", "localhost,", "-c", "local", "-e", f"gpu_session={mode}",
                           "-e", f"kubeconfig_dir={env['KCDIR']}", "-e", "ansible_python_interpreter={{ ansible_playbook_python }}", f"playbooks/{pb}"],
                          cwd=BOOT, env=env, capture_output=True, text=True)

def logged(log):
    return [l.split("|", 1) for l in log.read_text().splitlines()]

@needs_ansible
@pytest.mark.parametrize("mode,apps,kc", [("false", PHASE_A_REQUIRED, "kubeconfig"), ("true", GPU_REQUIRED, "kubeconfig.gpu")])
def test_handover_runs_against_the_right_cluster_and_apps(tmp_path, mode, apps, kc):
    env, log = fake_env(tmp_path, apps)
    r = play("03-handover.yml", mode, env)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    calls = logged(log)
    assert calls and all(Path(k).resolve() == (Path(env["KCDIR"]) / kc).resolve() for k, _ in calls)

def expected_02(ha, key):
    return ([f"apply --server-side -f {ha}/namespaces.yaml", f"apply --server-side -f {ha}/cmp-plugin.yaml",
             f"apply --server-side -f {ha}/repo-server-egress.yaml", "-n argocd get secret sops-age-key",
             f"-n argocd create secret generic sops-age-key --from-file=keys.txt={key}"])

@needs_ansible
def test_argocd_phase_a_sequence_unchanged(tmp_path):
    env, log = fake_env(tmp_path, [])
    r = play("02-argocd.yml", "false", env)
    assert r.returncode == 0, r.stdout[-3000:]
    ha = (BOOT / "playbooks/../../argocd/hand-applied")
    got = [c for k, c in logged(log)]
    key = f"{env['HOME']}/.sops/raglab-age-key.txt"
    assert [c.replace(str(BOOT / "playbooks/../.."), "LAB") for c in got] == [
        c.replace(str(BOOT / "playbooks/../.."), "LAB") for c in expected_02(str(ha), key)] + [
        "upgrade --install argocd argo-cd --repo https://argoproj.github.io/argo-helm --version 10.18.3 -n argocd "
        "-f LAB/argocd/argocd-values.yaml --wait --timeout 10m",
        "apply --server-side --force-conflicts -f LAB/argocd/hand-applied/appproject-default-locked.yaml",
        "apply --server-side -f LAB/argocd/hand-applied/appproject-raglab.yaml",
        "apply --server-side -f LAB/argocd/hand-applied/appproject-raglab-platform.yaml",
        "apply --server-side -f LAB/argocd/hand-applied/raglab-system.yaml",
        "apply --server-side -f LAB/argocd/hand-applied/root-app.yaml"]
    assert all(Path(k).name == "kubeconfig" for k, c in logged(log) if k != "helm")
    assert "gpu" not in log.read_text()

@needs_ansible
def test_argocd_gpu_sequence(tmp_path):
    env, log = fake_env(tmp_path, [])
    r = play("02-argocd.yml", "true", env)
    assert r.returncode == 0, r.stdout[-3000:]
    got = [c.replace(str(BOOT / "playbooks/../.."), "LAB") for k, c in logged(log)]
    assert got[:5] == [c.replace(str(BOOT / "playbooks/../.."), "LAB") for c in expected_02(
        str(BOOT / "playbooks/../../gpu/argocd/hand-applied"), f"{env['HOME']}/.sops/raglab-gpu-session/age-key.txt")]
    assert got[6:] == [
        "apply --server-side --force-conflicts -f LAB/gpu/argocd/hand-applied/appproject-default-locked.yaml",
        "apply --server-side -f LAB/gpu/argocd/hand-applied/appproject-raglab-gpu.yaml",
        "apply --server-side -f LAB/gpu/argocd/hand-applied/appproject-raglab-gpu-platform.yaml",
        "apply --server-side -f LAB/gpu/argocd/hand-applied/raglab-gpu-operator.yaml",
        "apply --server-side -f LAB/gpu/argocd/hand-applied/raglab-nim-operator.yaml",
        "apply --server-side -f LAB/gpu/argocd/hand-applied/root-app.yaml"]
    assert all(Path(k).name == "kubeconfig.gpu" for k, c in logged(log) if k != "helm")
    assert "raglab-age-key.txt" not in log.read_text(), "the Phase A age key is never used in GPU mode"


def set_kc(env, name, server):
    (Path(env["KCDIR"]) / name).write_text(f"clusters:\n- cluster:\n    server: {server}\n")

@needs_ansible
@pytest.mark.parametrize("pb", ["02-argocd.yml", "03-handover.yml"])
@pytest.mark.parametrize("server", ["https://203.0.113.9:6443", "https://127.0.0.1:6443", "https://172.32.0.1:6443"])
def test_phase_a_refuses_a_kubeconfig_that_is_not_private(tmp_path, pb, server):
    env, log = fake_env(tmp_path, PHASE_A_REQUIRED)
    set_kc(env, "kubeconfig", server)
    r = play(pb, "false", env)
    assert r.returncode != 0 and "does not fit the mode" in r.stdout + r.stderr
    assert not log.exists() or log.read_text() == "", "no kubectl/helm ran"

@needs_ansible
@pytest.mark.parametrize("pb", ["02-argocd.yml", "03-handover.yml"])
@pytest.mark.parametrize("server", ["https://192.168.0.50:6443", "https://203.0.113.9:6443", "https://127.0.0.1.evil.example:6443"])
def test_gpu_mode_requires_the_tunnel_server(tmp_path, pb, server):
    env, log = fake_env(tmp_path, GPU_REQUIRED)
    set_kc(env, "kubeconfig.gpu", server)
    r = play(pb, "true", env)
    assert r.returncode != 0 and "does not fit the mode" in r.stdout + r.stderr

def inv(tmp_path, host):
    f = tmp_path / "inv.ini"; f.write_text(f"[raglab]\nraglab-vm ansible_host={host} ansible_user=ubuntu\n[local]\nlocalhost ansible_connection=local\n"); return f

def preflight(tmp_path, host, mode):
    env, _ = fake_env(tmp_path, [])
    boot = tmp_path / "boot"    # a copy: play 3 of 01 edits the kubeconfig, which must never be the real one
    shutil.copytree(BOOT, boot, ignore=shutil.ignore_patterns("kubeconfig*", "inventory.ini"))
    for n in ("kubeconfig", "kubeconfig.gpu"): (boot / n).write_text("server: https://127.0.0.1:6443\n")
    return subprocess.run(["ansible-playbook", "-i", str(inv(tmp_path, host)), "-l", "localhost", "-e", f"gpu_session={mode}",
                           "playbooks/01-platform.yml"], cwd=boot, env=env, capture_output=True, text=True)

@needs_ansible
@pytest.mark.parametrize("mode,host,ok", [("false", "192.168.0.50", True), ("false", "10.1.2.3", True), ("false", "172.20.1.1", True),
                                          ("false", "203.0.113.9", False), ("false", "172.32.0.1", False),
                                          ("true", "203.0.113.9", True), ("true", "192.168.0.50", False)])
def test_01_host_address_matches_mode(tmp_path, mode, host, ok):
    r = preflight(tmp_path, host, mode)
    assert (r.returncode == 0) == ok, r.stdout[-1500:] + r.stderr[-500:]
    if not ok:
        assert "mode/host mismatch" in r.stdout + r.stderr

def test_01_has_nvidia_smi_preflight_for_phase_a():
    text = (BOOT / "playbooks/01-platform.yml").read_text()
    assert "failed_when: smi_pre.stdout != 'absent'" in text and "when: not (gpu_host_prep | bool)" in text

def test_gpu_01_disables_jupyter_units():
    text = (BOOT / "playbooks/01-platform.yml").read_text()
    assert "jupyter" in text and "systemctl disable --now" in text

def test_k3s_not_bound_to_loopback_only():
    # in-cluster clients reach the apiserver on the node IP: --bind-address 127.0.0.1 would break Argo CD and the operators
    assert "--bind-address" not in mode_vars("gpu-session")["k3s_exec"]

def test_gpu_ansible_wrapper(tmp_path):
    b = tmp_path / "bin"; b.mkdir()
    (b / "ansible-playbook").write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$FAKE_ARGS"; pwd >> "$FAKE_ARGS"\n'); (b / "ansible-playbook").chmod(0o755)
    env = {**os.environ, "PATH": f"{b}:{os.environ['PATH']}", "RG": str(tmp_path / "rg"), "FAKE_ARGS": str(tmp_path / "args")}
    r = subprocess.run([str(ROOT / "scripts/gpu-ansible.sh"), "playbooks/03-handover.yml"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = (tmp_path / "args").read_text().split()
    assert got[:5] == ["-i", str(tmp_path / "rg/inventory.ini"), "-e", "gpu_session=true", "playbooks/03-handover.yml"]
    assert Path(got[-1]).resolve() == BOOT.resolve()
    for bad in (["-i", "x", "playbooks/01-platform.yml"], ["-e", "gpu_session=false", "playbooks/01-platform.yml"], []):
        assert subprocess.run([str(ROOT / "scripts/gpu-ansible.sh"), *bad], env=env, capture_output=True).returncode == 2
