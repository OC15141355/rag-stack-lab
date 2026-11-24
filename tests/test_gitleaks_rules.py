import os, shutil, subprocess
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
HAVE = shutil.which("gitleaks") is not None
if os.environ.get("CI") and not HAVE:
    # in CI a missing gitleaks must fail loudly, never skip
    def test_gitleaks_present_in_ci():
        pytest.fail("CI is set but the gitleaks binary is not installed")
needs_gitleaks = pytest.mark.skipif(not HAVE, reason="gitleaks not installed")

def scan(tmp_path: Path, name: str, body: str) -> int:
    d = tmp_path / "scan"; d.mkdir(exist_ok=True)
    (d / name).write_text(body)
    # no .gitleaksignore in the scan dir: nothing is suppressed
    return subprocess.run(["gitleaks", "dir", str(d), "--config", str(REPO / ".gitleaks.toml"),
                           "--no-banner", "--redact", "--no-color"],
                          capture_output=True, text=True).returncode

FAKES = {
    "nvapi": 'token = "nvapi-' + "A" * 48 + '"\n',
    "bifrost": 'key = "sk-bf-' + "a1b2c3d4" * 3 + '"\n',
    "age": "AGE-SECRET-KE" + "Y-1" + "Q" * 58 + "\n",
    "age_lower": "age-secret-ke" + "y-1" + "q" * 58 + "\n",
    "pem": "-----BEGIN " + "OPENSSH PRIVATE KEY-----\n",
}

@needs_gitleaks
@pytest.mark.parametrize("kind", sorted(FAKES))
def test_fake_secret_detected(tmp_path, kind):
    assert scan(tmp_path, f"{kind}.txt", FAKES[kind]) == 1

@needs_gitleaks
def test_doc_placeholders_not_globally_allowed(tmp_path):
    # the two historical placeholders are suppressed ONLY by exact fingerprints,
    # so the same strings in a fresh file must still be flagged
    assert scan(tmp_path, "a.md", "-H 'x-bf-vk: sk-" + "bf-not-real'\n") == 1
    assert scan(tmp_path, "b.md", 'curl -H "Authorization: Bearer sk-' + 'bf-wrong"\n') == 1

@needs_gitleaks
def test_pycache_not_globally_skipped(tmp_path):
    d = tmp_path / "scan" / "__pycache__"; d.mkdir(parents=True)
    assert scan(tmp_path, "__pycache__/x.txt", FAKES["nvapi"]) == 1

@needs_gitleaks
def test_repo_gitleaksignore_has_only_fingerprints():
    lines = [l for l in (REPO / ".gitleaksignore").read_text().splitlines()
             if l.strip() and not l.startswith("#")]
    assert lines and all(l.count(":") >= 2 for l in lines)
