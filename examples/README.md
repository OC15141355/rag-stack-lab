# examples/ (superseded)

Early sketches written before the lab existed (2026-11-19). **Superseded by
[`reference/platform-gitops/`](../reference/platform-gitops/)**, which is tested in CI and incorporates the defects
found live in the lab ([Phase B findings](../docs/raglab-phase-b-findings.md)).

Known problems here, kept as-is for history:
- `nim-operator/`: read-only cache mount and a NetworkPolicy that blocks the NIM Operator's readiness check.
- `model-catalogue/`: a second, diverging generator; the reference has the single one (`tools/render.py`).
- `gitlab-ci/`: promotion by environment branches; the reference promotes by folder on `main`.
