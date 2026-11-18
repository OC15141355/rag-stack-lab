# Investigation best practices (personal)

How to run a technical investigation that people actually use, especially
when you're new to the platform.

## Before you start

- **Restate the question in one sentence** and check it with whoever asked:
  "You want to know what it would take to move X to Y, across DEV/QA/PROD, so
  you can decide whether and how to do it. Right?" Half of all wasted
  investigations answer a slightly different question.
- **Find the decision.** Who decides, by when, based on what? Your document
  serves that decision.
- **Timebox it.** Agree how long and what "done" looks like (doc, meeting,
  demo).

## While investigating

- **Current state before future state.** You can't do a gap analysis against
  something you haven't described.
- **Evidence over memory.** For every claim, write where it came from (file at
  commit, command output, person and date). This protects you when someone
  disagrees.
- **Primary sources, dated.** Vendor docs move. "NVIDIA docs, checked
  2026-11-19, say…" ages honestly; "NVIDIA recommends…" doesn't.
- **Read-only first.** Inspect before you ask; ask to confirm and to learn
  *why*, not *what*.
- **Batch your questions per person.** One message with five good questions
  beats five interruptions.
- **Keep a journal** ([template](working-journal-template.md)): what you
  checked, what you found, what's still unknown. It becomes your appendix.
- **Write unknowns down, visibly.** An honest "unknown, asked X" is more
  useful than a guess.
- **Watch for requirements that assume features.** "Via the operator API",
  "the entity store holds users": check every assumed capability against the
  real component.

## When analysing

- **Map each requirement to an owner.** Operator, gateway, pipeline, database,
  portal. Many "operator" requirements belong elsewhere.
- **Always include the baseline option** (stay as-is with fixes) and at least
  two alternatives.
- **Estimate in ranges with assumptions.** "M (4–10 days), assuming GPU
  Operator present and cluster-scope approval" can be checked; "about a week"
  can't.
- **Risk of doing and risk of not doing.** Both belong in the doc.
- **Phase so each step delivers something usable** and can be stopped
  safely.

## When writing it up

- One-page summary first; detail after. Lead with the recommendation.
- Tables for comparisons, prose for reasoning.
- Separate facts from opinions in the wording.
- Name an owner and a date for every decision and open question.
- **Be generous to the existing setup.** It was built under constraints you
  may not see. "This made sense because…; it now costs us…; here's a
  low-friction next step" lands well. "This is wrong" doesn't.

## When sharing

- Pre-review with one or two people, including someone who built the
  current setup. Fix what they find before the wider share.
- Share with a short message: the bottom line, what you need from people
  (decisions, by when), and a link.
- Offer a 20-minute walkthrough. Most people prefer it to reading.
- After the decision, update the doc's status and link the tickets.

## Things that build trust when you're new

- Small, accurate claims you can back up.
- Asking "why is it like this?" before "why isn't it like that?"
- Finding a real issue (a deprecation, a security gap) and bringing a
  practical fix, privately first if it's sensitive.
- Writing down what you learned so the next person doesn't have to ask.
