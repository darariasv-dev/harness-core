# myproject (Harness_Pipeline template)

A complete starter project on `harness_core`. Rename `myproject/`, then replace the stage
bodies in `myproject/stages.py`. Everything else is already wired:

| File | What it does |
|---|---|
| `myproject/router.py` | `call_model` with in-code `PINNED_STRONG`, CLI safety flags, `provider_hash_for` |
| `myproject/cache.py` | fixed eight-component fingerprint set; append with defaults, never reorder |
| `myproject/stages.py` | `discover` -> `screen` (gates) -> `assess` (cache-first, capped, demotion-logged, escalating) |
| `myproject/run.py` | verbs under the workflow lock; one live switch `MYPROJECT_USE_LIVE_MODEL=1`; checkpoint block at the end |
| `myproject/routing_eval_adapter.py` | what the agreement study needs: fixtures, prompt per task, outcome agreement |
| `policy/model_routing.v1.yaml` | providers / tiers / tasks; evidence written back by the study |
| `tests/` | autouse offline guard + path isolation; pins, cache keys, cache hits, demotion, escalation, CLI refusal |
| `.claude/agents/` | architect / implementer / reviewer roles for build-time work |
| `CHECKPOINT.md` | the 8-field block an agent resumes from |

```
pip install -e /path/to/Harness_Pipeline && pip install -e . && pytest -q
MYPROJECT_USE_LIVE_MODEL=1 python -m myproject.run run
python -m myproject.run usage
python /path/to/Harness_Pipeline/scripts/eval_routing.py --adapter myproject.routing_eval_adapter --tasks example_assessment
```
