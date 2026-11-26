# Monthly lifecycle check (human-owned, ~30 minutes)

Owner: the platform team's on-call for the month. First Monday of the month. Output: one PR that updates
`support_ends`, `review_by` and `notes` in `catalogue/platform.yaml` and `catalogue/services.yaml` (or a note in the
PR description that nothing changed). CI then prints a WARNING for every `support_ends` within 90 days and for
every unknown (`null`) one; warnings never block a merge, this checklist is what acts on them.

## 1. Read NVIDIA's notices

- [ ] NVIDIA AI Enterprise **EOL Notices** page: any component or NIM in our catalogues listed? Copy the date into
      `support_ends` and the replacement into `notes`.
- [ ] **EOL Branches** / lifecycle page: current Production Branch, its last planned release and EOL; Infrastructure
      Branch for the GPU Operator; LTSB dates. Update `nim-production-branch` and `gpu-operator`.
- [ ] Release notes for the GPU Operator, NIM Operator and each NIM we run: breaking changes (renamed DCGM metrics,
      CRD changes, removed env vars). Note them on the entry; they become the upgrade PR's checklist.
- [ ] Anything NVIDIA sunsets that we depend on (the NeMo Microservices sunset of 2026-10-01 is the example)?
      Open a deprecation: set `deprecated.after` and `replacement` on the service, or `state` on the component.

An optional helper may extract dates from those pages on a connected host. It must **fail loudly** if it finds no
dates (a page layout change must not look like "nothing ends"), it is never a CI gate, and it never writes to the
repository: a person copies what it found into the PR.

## 2. Act on what CI already warns about

- [ ] `python3 tools/checks.py --only support-ends`: for each entry within 90 days, is there an open PR or a plan?
- [ ] For each `support_ends: null`: is `review_by` in the future? If not, ask the vendor (the NIM Operator's support
      window is not on a public page) and either record a date or move `review_by` with a reason in `notes`.
- [ ] `deprecated` services: is the replacement promoted at least to QA? Is traffic moving (gateway logs)?

## 3. Keep the evidence honest

- [ ] Every enabled PROD block has a QA pass in `catalogue/evidence/qa/` (CI enforces; check nothing was waived).
- [ ] Nightly drift job: no ORPHAN or UNMANAGED findings older than a day; no Argo app still paused (break-glass).
- [ ] Retired services: env blocks disabled, `retired: true`, orphan report clean, weights PVCs released by a
      `delete-weights` PR only after the replacement has run in PROD for an agreed period.

## 4. Record

- [ ] Open the PR (`lifecycle: YYYY-MM`), one environment-neutral catalogue change; CODEOWNERS routes it to a PROD
      approver because `catalogue/` is shared.
