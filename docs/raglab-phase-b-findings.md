# raglab Phase B findings (rented A100, standalone cluster)

Status (2026-11-26): **pre-rent work complete; GPU session BLOCKED before any spend.** No instance was created,
nothing was billed (`lambda.py instances`: 0 live, 0 file systems, after the attempt).

## OWNER TODOs

1. **Fix the Lambda account billing address** (console → Billing). The launch API refused with
   `HTTP 403 global/invalid-address: Your billing address is invalid`. This is account-level: another region or
   instance type will not help. Then say "rent" and the session restarts from the pre-rent gate (runbook section 1).
2. Copy the lab age key and the session age key into the password manager (open from Phase A).
3. Draft PRs #28 (`session/gpu-go`) and #29 (`session/gpu-cutover`) stay `do-not-merge`. Both are rebased onto
   `main`; #28's CI is red by design until the go/no-go fills the NIM profile.

## Done

- Spec rev 2 and fact-check, plan (21 tasks), and the pre-rent tasks 1-8 were built, reviewed and merged
  (PR #26, #27), with 245 tests and green CI.
- GPU secrets file encrypted to the session key only (PR #30): structural check passes, no plaintext `nvapi-`,
  decode probe 16 OK / 0 FAIL, and the Phase A key cannot decrypt it.
- Pre-rent gate (runbook section 1) on 2026-11-26: items 1-3 and 5-12 pass. Item 4 failed and was fixed (next
  section). A100 capacity was listed in us-east-1, us-west-2, asia-south-1 (SXM4) and us-south-2 (PCIe).

## Things that affect work (the Project investigation)

1. **Hosted model retirement breaks a catalogue silently.** `meta/llama-3.1-8b-instruct` disappeared from the NVIDIA
   hosted API between 2026-11-25 and 2026-11-26: `/v1/models` no longer lists it and chat returns **HTTP 410**. A
   catalogue that names hosted upstreams needs a scheduled check (list + one call per model), not just a check at
   deploy time. Fix here: a hosted stand-in for the baseline (PR #31), so the cutover is no longer like-for-like.
2. **A 200 from `/v1/models` proves nothing about a key.** The hosted model list answers regardless of key validity, so
   revocation and key checks must make an authenticated call (a chat completion). The key probe now reports
   INCONCLUSIVE without one.
3. **"Checks that pass when the thing is broken" was the dominant defect class in review** (8 Important findings
   across two reviews, all fixed before merge):
   - the recipient check silently skipped when `.sops.yaml` was absent (as in the pre-commit hook's temp copy);
   - it compared only age recipients, so an extra PGP/KMS decryptor passed;
   - `cmd | tee file; echo $?` reports `tee`'s exit code, so a failed terminate read as success;
   - HTTP clients forward `Authorization` across redirects, including to another host;
   - a crash exiting 1 read the same as "key rejected";
   - a draft PR meant to be red was green and mergeable.
   For the Project's promotion gates: test each gate's failure path, not only its pass path.
4. **Mode flags typed by hand are a credential-leak path.** Forgetting `-e gpu_session=true` on one playbook run
   would have run Phase A mode against the rented VM and could have placed the home lab age key on provider
   hardware. Fix: every playbook asserts it is pointed at the right kind of host, and a wrapper always sets the
   flags. Same lesson for Ansible-driven multi-environment deploys: assert the target, don't trust the flag.
5. **Cloud account readiness is a gate of its own.** A valid API key, firewall, SSH key and capacity were not enough:
   the account's billing profile blocked the launch. It is now in the pre-rent list (runbook item 8, "billing profile valid"), and for the Project, check the equivalent quota/approval state before booking
   a change window.

## Not yet verified live (needs the session)

GPU Operator on the NRI/CDI path, `list-model-profiles` on the A100, NIMCache download time, NIMService cold start,
NetworkPolicy probes, cutover and rollback through git, and teardown/revocation evidence. Plan Tasks 10-20.

## Process note

During the session prep, a chained shell command kept going after a `git rebase` conflict, and a text replacement
hit the first of two identical upstream strings (`chat/glm` instead of `chat/small`). It was caught before anything
reached the remote (the branch still pointed at the old commit), reset, and the cutover branch rebuilt with only the
three dev-gpu files changed. Lesson: stop chains on conflict, and edit structured files by key, not by string.
