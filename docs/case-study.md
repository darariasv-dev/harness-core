# Case study: the project this harness came from

A personal, local-first pipeline (FastAPI + SQLite, one user, a hard $0-extra-spend rule: all
model calls through the headless `claude -p` CLI on an existing subscription). Six stations:
search, assess, decide, draft, fill, submit. The harness modules here were extracted from it
after the pipeline reached its first real, externally confirmed end-to-end outcome on
2026-09-13. No personal data from that project is in this repository.

## What was proven

| Claim | Evidence |
|---|---|
| Deterministic stages carry most of the work | 19 model calls total across 22 runs; search, screening, drafting, rendering, checks, and the final action made none |
| The cache works | second runs over unchanged inputs: 0 calls; one context change: exactly 1 call |
| Measurement decides tiers | cheap tier 0.914 agreement (proven) on one task, 0.367 (escalated) on the other, 35 real fixtures each |
| A free local model was tried and rejected on evidence | 0.20 and 0.34 agreement, and it tended to assert unsupported claims; 0 new strong-tier calls thanks to reference reuse |
| Fabrication is caught in code | claims marked supported with no valid evidence id are demoted; 0 of 19 on the strong tier that day |
| Failures become tests | 1,105 offline tests in the source project; every live failure that day (stale lock after SIGTERM, a pause that did not block, a wrong field target) got a pinned test |
| Cost | 9 subscription calls plus 70 free local calls for the confirmed outcome; $0 extra |

## What the harness did not solve there

Prompt size (about 27k tokens per assessment) dominated cost; retrieval of only the relevant
context was the identified next step and is not built. Irreversible actions still require a
person's fresh, package-specific approval every time; that gate is the project's, not the
harness's, by design.
