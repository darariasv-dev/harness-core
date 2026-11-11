# CLAUDE.md — this project runs on harness-core

Resuming? Read `CHECKPOINT.md` first (the 8-field block at the top is the current state).

## Non-negotiable boundaries

- **Every model call goes through `myproject.router.call_model` with a named purpose.** Never
  a raw CLI or HTTP call. The purpose string is both the ledger row and the policy key.
- **Purposes in `PINNED_STRONG` cannot be moved by any policy edit or eval.** Adding one is a
  code change with a test. Anything a person outside this project reads belongs there.
- **Cache keys are complete.** If a change adds an input that can alter a model result, add a
  named, defaulted fingerprint component in `myproject/cache.py` and a test that it changes
  the key. Never reorder components.
- **Validation demotes unsupported claims and logs per provider.** Consult
  `demotions.should_escalate` before routing; never edit the policy to escalate.
- **Live calls only under `MYPROJECT_USE_LIVE_MODEL=1`,** local providers included. Tests run
  fully offline (autouse guard).
- **No paid API key, no retry into a rate limit, no quota percentage presented as fact.**
- **Private or personal data never goes under version control.** Runtime state lives in
  `data/` and `runs/` (gitignored).
- **Irreversible actions need a code-enforced approval gate,** never a prompt asking nicely.

## Commands

```
pytest -q
MYPROJECT_USE_LIVE_MODEL=1 python -m myproject.run run --run-dir runs/<stamp>
python -m myproject.run usage
```

## Moving a task to a cheaper tier

Record 30-50 real fixtures, run the harness's `scripts/eval_routing.py` with this project's
adapter, and only `--apply-flips` on a PROVEN (>= 0.90) result. Write the decision in
`CHECKPOINT.md`.
