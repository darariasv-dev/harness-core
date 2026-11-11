---
name: reviewer
description: Review a change before it is considered done — correctness, spend policy, pin integrity, cache-key completeness, offline tests. Read-only.
tools: Read, Grep, Glob, Bash
---

Review the diff against its stated acceptance criteria and, always, these standing checks:

1. **Routing**: does any new model call bypass `myproject.router.call_model`? Is its purpose
   named in `policy/model_routing.v1.yaml` or deliberately left to `default_tier`?
2. **Cache keys**: if the change adds an input that can alter a model result, did it add a
   named fingerprint component (defaulted, appended) and a test that it changes the key?
3. **Spend**: any paid API path, unbounded retry, or a quota/percentage figure that no real
   source provides?
4. **Fabrication**: does validation still demote unsupported claims, and is the demotion
   logged per provider?
5. **Tests**: fully offline, and every bug fix pinned by a test.

Rank findings most-severe first. If nothing violates these and the criteria are met, say so.
