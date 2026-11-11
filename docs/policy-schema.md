# `policy/model_routing.v1.yaml`

```yaml
version: v2
providers:                       # backends; `enabled` defaults to true
  claude_cli: {type: claude_cli}                                   # headless `claude -p`, subscription
  ollama:     {type: ollama, base_url: http://127.0.0.1:11434,     # loopback only, enforced
               num_ctx: 32768, think: false, enabled: false}       # set num_ctx: default 4096 truncates
  hosted_free: {type: openai_compatible, base_url: '', api_key_env: HOSTED_FREE_API_KEY, enabled: false}
tiers:                           # name -> {provider, model}; the legacy `name: model-id` form still works
  free:   {provider: ollama,     model: qwen2.5:7b-instruct}
  cheap:  {provider: claude_cli, model: claude-haiku-4-5-20251001}
  strong: {provider: claude_cli, model: claude-sonnet-5-5}
  top:    {provider: claude_cli, model: claude-opus-5-5}           # only for purposes that name it
tasks:                           # purpose -> tier; unlisted purposes use default_tier
  example_assessment: cheap      # moved down by a proven agreement study
default_tier: strong             # Sonnet unless a purpose is moved down, or up to `top`
eval_status: {}                  # written by the study (cheap vs strong)
eval_status_by_tier: {}          # written by the study (any candidate tier)
```

Resolution order in `router.resolve_route`: `pinned_tiers[purpose]` > `tier_override` >
`tasks[purpose]` > `default_tier` > a hardcoded safe default (the `strong` tier on Sonnet,
since 0.5.0). A purpose therefore runs on Sonnet unless something names another tier for it:
down to `cheap`/`free` on measured evidence, up to `top` because it needs the higher model.
A tier naming a provider that
is disabled or missing fails the call with `HeadlessCallFailed`; it never silently uses
another backend.

The file's sha256 (`policy.load_yaml_policy`) belongs in every cache key as `routing_hash`;
the effective `Route.provider_hash` belongs there too, because a runtime escalation can answer
from a different backend than the file names.
