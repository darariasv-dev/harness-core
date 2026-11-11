# Adopting the harness in a new project

1. **Install.** `pip install "git+https://github.com/darariasv-dev/harness-core"` (or `pip install -e` a local clone).
2. **Copy `template/`** to your project root and rename `myproject/` everywhere. Read
   `template/CLAUDE.md`; it is your project's working agreement.
3. **Name your purposes.** Each model-touching call gets one string used for both the ledger
   and the policy lookup. Add them to `policy/model_routing.v1.yaml`, all on `strong` to begin.
4. **Pin.** Put every purpose whose output a person outside the project reads, or that decides
   something irreversible, in `myproject/router.py::PINNED_STRONG`. Write the test.
5. **Fingerprint.** Decide what can change a result: item text, context, exclusions, vocabulary,
   scoring version, prompt, routing policy, effective provider. Keep the component set fixed;
   append with defaults.
6. **Validate.** In your assess stage, demote every claim that cites no valid evidence; call
   `demotions.record(...)`; consult `demotions.should_escalate(provider)` before routing.
7. **Gate first.** Everything deterministic runs before the model stage; cap live calls per run.
8. **One live switch.** Real calls only when `MYPROJECT_USE_LIVE_MODEL=1`; local providers too.
9. **Record fixtures.** Save 30-50 real inputs per purpose, then run
   `scripts/eval_routing.py --adapter myproject.routing_eval_adapter --tasks <purpose>` and let
   the measurement, not a guess, move a task to `cheap` or `free`.
10. **Checkpoint.** End every run by printing `checkpoint.format_checkpoint_block(...)` and keep
    the latest block at the top of `CHECKPOINT.md`. An agent resuming reads that first.
