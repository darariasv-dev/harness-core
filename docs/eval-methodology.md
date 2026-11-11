# Agreement-study methodology

A routing decision (which tier answers a purpose) is made from measurement, not preference.

1. **Real inputs.** 30-50 recorded fixtures per task, never synthetic. Store them under
   `tests/fixtures/routing_eval/`; the adapter's `load_fixtures()` reads them.
2. **Same input, two tiers.** `evals.run_agreement_eval` sends each fixture through the
   candidate tier and the reference tier via `router.call_model` with `tier_override`.
   `pinned_tiers` still wins, so a pinned purpose is never evaluated for a cheaper tier.
3. **Outcome agreement, not text agreement.** The project supplies `outputs_agree(a, b)`.
   Compare decisions and counts within tolerance; two tiers paraphrasing the same content
   must not count as disagreement (an exact-text comparison produced false disagreements in
   the source project).
4. **Every comparison persisted.** One `spot_check_NNN.json` per fixture plus
   `summary.json`, under `<out>/<task>/` for the baseline candidate and `<out>/<task>--<tier>/`
   for any other. A run interrupted halfway resumes from disk; a call failure is recorded and
   excluded from the rate, never counted as agreement.
5. **Reference reuse.** `evals.load_reference_outputs` loads the reference tier's stored
   answers so evaluating a new candidate (a free local model) spends zero reference calls.
6. **Decision rule.** `>= 0.90` proven, `0.75-0.90` borderline, `< 0.75` escalated; no
   comparisons at all is treated as escalated.
7. **Apply to policy.** `apply_to_policy` only ever moves a task UP to the reference tier on
   evidence; `apply_tier_result_to_policy` moves a task DOWN only with `--apply-flips`, only on
   proven, and never for a pinned purpose. Both always record the measurement in the policy
   file (`eval_status`, `eval_status_by_tier`), pass or fail.
