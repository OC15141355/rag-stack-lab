# Day-one notes (template)

Copy this file somewhere **private** before filling it in. Do not commit a
filled-in copy to a public repo.

## Access checklist

- [ ] Repo access (list them below)
- [ ] Dev container builds and opens
- [ ] `kubectl` context works: `kubectl auth can-i --list -n <ns>` saved below
- [ ] Registry login works (`podman login <registry>`)
- [ ] Gateway key issued
- [ ] Endpoint probes pass (doc 15, steps 1–6)
- [ ] Cline connected and completing a read-only task

## The request path, as it really is

Fill in each hop as you confirm it. Write "?" where you don't know yet.

| Hop | Hostname / Service | Port | Auth | Timeout / buffering | Owner (repo) |
|---|---|---|---|---|---|
| Edge (Traefik) | | | | | |
| Portal backend | | | | | |
| Gateway (Bifrost) | | | | | |
| NIM: model A | | | | | |
| NIM: model B | | | | | |

## Models as served

| Gateway model name | Backend model | Profile / GPUs | Max context (measured) | Tool calls OK? (x/10) |
|---|---|---|---|---|
| | | | | |

## Per repo (one block each)

### <repo name>

- What it is (one sentence):
- How it starts:
- Routes / entry points:
- Calls out to:
- Config / env vars that matter:
- Path (request / delivery / observation):
- One thing I don't understand:
- Who to ask:

## Questions log

| Date | Question | Asked who | Answer |
|---|---|---|---|

## Candidate things I could own

(See section 6 of [how it fits together](../docs/prereading/20-how-it-fits-together.md).)

-
