"""Go/no-go guard (session/gpu-go only). RED BY DESIGN until the profile placeholder is replaced (runbook 3.5)."""
from pathlib import Path

NIM = Path(__file__).resolve().parents[1] / "lab" / "gpu" / "nim"

def test_no_profile_placeholder_remains():
    left = [f.name for f in sorted(NIM.glob("*.yaml")) if "PENDING-GO-NO-GO" in f.read_text()]
    assert not left, f"go/no-go PR must pin the NIM profile before it can merge: {left}"
