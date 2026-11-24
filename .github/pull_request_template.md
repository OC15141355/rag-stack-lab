## What changes
<!-- one paragraph -->

## Promotion evidence (only for PRs into env/qa or env/prod)
- Source branch SHA being promoted: `<sha>`
- Smoke report from the **previous** env for that exact SHA (redacted: no IPs/hostnames):
  ```
  <paste: kubectl -n raglab-<env> logs job/smoke | tail -40>   # must show revision=<sha> and 0 failed
  ```
- [ ] Revision in the report equals the SHA above
- [ ] Report shows auth-negative PASS and limit-429 PASS
- [ ] I understand this gate is **attested, not enforced**; prod smoke detects, it doesn't prevent

## Secrets
- [ ] No plaintext keys, IPs or tailnet names added (hook + CI green)
