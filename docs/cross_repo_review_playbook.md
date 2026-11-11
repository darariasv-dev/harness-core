# Cross-Repo Review & Remediation Playbook

**Standing instruction from the project owner. Applies to every project this user builds,
not specific to any one repo** — same status as the "every live Claude call routes through
`harness_core`" rule. Canonical copy lives here because every project already depends on
this package; each project's `CLAUDE.md` points at it.

Two things live here:

1. **Part A — the state-of-play review.** How to answer "where are we / what have we done /
   why are there so many failures / how do these repos connect?"
2. **Part B — the remediation review.** The template the owner wants run *immediately after*
   Part A, every time. Part A finds gaps; Part B turns them into an executable blueprint.

Part A is never the finished deliverable. **Unless the owner says otherwise, always
continue into Part B.**

---

## Part A — State-of-play review

### Phase 1. Inventory before interpreting

Run across **every** repo in scope, in parallel:

```
git log --oneline -25 ; git branch -a ; git status --short
git log --date=short --pretty=%ad | sort | uniq -c   # velocity per day
ls <repo>                                             # top-level shape
```

Read each repo's `CLAUDE.md` first — the non-negotiable boundaries are the real spec.

### Phase 2. Read the durable records, not memory

These projects keep unusually good written records. Read them directly:

| Record | Repo | What it gives you |
|---|---|---|
| `docs/gaps/README.md` + `docs/gaps/NNNN-*.md` | Opportunity-Engine | Every real defect, how found, whether truly fixed |
| `docs/TEAM_COORDINATION.md` | Opportunity-Engine | Peer-session roster, work board (WB-N), findings log |
| `VALIDATION_REPORT.md` | Opportunity-Engine | What is and is not actually validated |
| `docs/checkpoint.md` | agent-system | Current state / in-progress / blocker (read this, not `progress.md`) |
| `docs/operating-plan.md`, `docs/harness-review.md` | C-Suite-Agents | What Mission Control reviews and how |
| `docs/architecture.md`, `docs/adopting.md` | Harness_Pipeline | The shared contract every project depends on |

Also check for a formal owner-issued charter — it supersedes ad hoc practice.

### Phase 3. Verify; do not relay

**The single most important rule.** The records are self-reported by the sessions that wrote
the code. Treat every "FIXED" / "DONE" / "verified" as a claim to check, not a fact.

- Run each test suite yourself. Report real numbers.
- If the environment blocks a run (missing dep, wrong Python), **say so explicitly** and do
  not substitute the record's claimed number as if you had confirmed it.
- Prefer reproducing a claimed fix over re-reading the commit that claims it. A 10-line
  script that demonstrates the bug still fires is worth more than any amount of prose.
- Distinguish, in the output, **"I verified this"** from **"the record claims this."**

### Phase 4. Categorize the failures — the count is not the story

A long defect list found internally is a health signal, not a quality problem. What matters
is the *pattern*. The recurring ones in these repos:

1. **Built, tested, never wired in.** The component exists, has passing unit tests, and
   nothing calls it. Tests green, feature absent. Historically ~25% of all gaps here.
   *Always grep whether a new module is imported by anything in `src/` other than its tests.*
2. **Only breaks on contact with real data.** Masked by synthetic fixtures that are cleaner
   and better-behaved than reality.
3. **Missing safety rails.** No spend ceiling, no human gate, no diversity check.
4. **Concurrency / environment.** Multiple sessions sharing one working directory; stale
   already-imported code outliving a fix; "background" jobs that were never detached.
5. **Provenance.** Synthetic data reaching a production store, and headline numbers computed
   over it.

Correlate gaps-per-day against commits-per-day. They usually track, which means the gap count
measures how hard the team looked, not how badly it built.

### Phase 5. Report like a PM

Plain English, no jargon. Cover, in this order:
what each repo is *for* → how they interconnect (be specific about the *kind* of
connection) → why the failures happened (patterns, not a list) → the one or two that should
actually worry the owner → where things genuinely stand → the risk register.

State the uncomfortable findings plainly. Never smooth over an unexplained result.

---

## Part B — Remediation review (run right after Part A)

For **every** gap found, produce all ten fields. Do not collapse gaps into generic
recommendations. Treat each gap individually. Be exhaustive.

1. **Gap** — what is missing, outdated, weak, incomplete, inconsistent or suboptimal, and the
   exact section / component / workflow / requirement / logic affected (file and line).
2. **Why it matters** — impact of leaving it. Name the dimension: accuracy, performance,
   reliability, scalability, usability, security, maintainability, cost, compliance.
3. **Current state** — what exists today and why it is insufficient.
4. **Target state** — what the correct version looks like.
5. **Required fix** — implementation-level specifics. Never "improve this" / "optimize this" /
   "consider changing this." State exactly what changes and how.
6. **Updated version** — the actual corrected content: code, schema, config, spec or
   replacement text. Provide it wherever possible rather than describing it.
7. **Optimization opportunity** — after the fix, can it be simplified, automated,
   consolidated, made more efficient or more scalable?
8. **Dependencies / downstream impact** — what else must change; conflicts with other parts.
9. **Priority** — Critical / High / Medium / Low.
10. **Acceptance criteria** — concrete, testable verification that it is actually resolved.

Then, after all individual gaps:

- **Cross-Gap Analysis** — which gaps share a root cause or should be fixed together.
- **Prioritized Remediation Plan** — ordered by severity, dependencies, effort, impact, risk,
  quick wins.
- **Optimized End State** — what the system looks like once all major gaps are resolved.
- **Remaining Risks** — what is still uncertain, unverified or problematic afterwards.
- **Final Validation Checklist** — a concrete tick-list covering every gap.

### Two hard rules for Part B

- **Do not assume something has been fixed unless there is evidence that it has been fixed.**
  A gap doc marked FIXED is a claim. Re-verify against the code.
- **If information is missing, label it "Needs validation."** Never invent an answer to fill
  a field.

The goal is not to critique. The goal is an actionable blueprint for a corrected, updated,
optimized, production-ready version.
