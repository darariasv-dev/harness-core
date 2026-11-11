# How the harness keeps model spend down

Every mechanism below is code in this repo, and every number is from the ledger of the
project the harness was extracted from (a personal pipeline that ran to a real, confirmed
end-to-end result on 2026-09-13). See `docs/case-study.md`.

| # | Mechanism | Where | Measured effect |
|---|---|---|---|
| 1 | Deterministic stages first; the model stage is one of six | `runner`, project `screen`/gates | 19 model calls total across 22 pipeline runs |
| 2 | One combined call per item instead of two | project prompt design | one assessed item = one call |
| 3 | Gates before the call, plus a per-run cap on live calls | `GateResult`, `Budget`, `MAX_LIVE_CALLS_PER_RUN` | closed / out-of-scope items never reach a model |
| 4 | Composite-fingerprint cache (item, context, exclusions, taxonomy, scoring version, prompt, routing policy, effective provider) | `cache`, project `cache.py` | re-runs on unchanged inputs cost 0; the one input change after new context cost exactly 1 call |
| 5 | Prompt caching on the strong tier, recorded as measured usage | `ledger` (`cache_read_input_tokens`) | 142k tokens read from cache vs 236k created -- most of that volume was Claude Code's own agent context (see #9), not prompt |
| 9 | Lean CLI flags by default: no tools, a one-line system prompt, no settings/CLAUDE.md/MCP/skills (`LEAN_CLI_FLAGS`, 0.3.0) | `router.ClaudeCLIProvider` | one-line prompt on Haiku, measured 2026-09-23: ~20,000 input tokens with no flags, ~14,300 with `--restricted --strict-mcp-config`, 422 with the lean set |
| 10 | Optional call-level cache: `call_model(cache_conn=...)` keyed on prompt, effective provider+model, CLI flags and schema | `router`, `cache` | an identical repeat call costs 0 and writes no ledger row |
| 6 | Tiers chosen by measurement: a task moves to a cheaper tier only at >= 0.90 outcome agreement over 30-50 real inputs; reference outputs are reused so a new candidate costs 0 reference calls | `evals`, `scripts/eval_routing.py` | cheap tier proven for one task (0.914), escalated for the other (0.367); a free local model measured 0.20 / 0.34 and was rejected at 0 new strong calls for 65 of 70 comparisons |
| 7 | Fabrication demotion in code, logged per provider, auto-escalation above 15% | `demotions`, project `_validate` | 0 of 19 claims demoted on the strong tier; the rule is what makes a cheap tier safe to try |
| 8 | Human-facing purposes pinned to the strong tier in code | project `PINNED_STRONG` | no setting can cost-optimize what a person outside the project reads |

Honest ceiling: the source project measured about 27k input tokens per item, but only about
4.5k of that was its prompt (prompt_chars / 4) -- the rest was the CLI's agent context, which
#9 removes. After #9, cost per item is dominated by prompt size, and the next real saving is
retrieval: send only the context relevant to the item. That is not built.

What the harness deliberately does not do: no dollar or quota-percentage figure is ever
presented as settled (a subscription has no programmatic quota), no automatic retry into a
rate limit, no fallback to a paid API key.
