import pytest

from myproject import cache, router

FREE_EVERYTHING = {
    "providers": {"claude_cli": {"type": "claude_cli"}, "ollama": {"type": "ollama", "base_url": "http://127.0.0.1:11434"}},
    "tiers": {"free": {"provider": "ollama", "model": "local"}, "cheap": {"provider": "claude_cli", "model": "cheap-model"},
              "strong": {"provider": "claude_cli", "model": "strong-model"}},
    "tasks": {p: "free" for p in router.PINNED_STRONG} | {"example_assessment": "free"},
    "default_tier": "free",
}


@pytest.mark.parametrize("purpose", sorted(router.PINNED_STRONG))
def test_pinned_purposes_resolve_strong_despite_policy_and_override(purpose):
    assert router.resolve_route(purpose, FREE_EVERYTHING).tier == "strong"
    assert router.resolve_route(purpose, FREE_EVERYTHING, tier_override="free").model == "strong-model"


def test_unpinned_purposes_follow_the_policy():
    route = router.resolve_route("example_assessment", FREE_EVERYTHING)
    assert (route.provider, route.tier) == ("ollama", "free")


def test_real_policy_builds_the_cli_with_restricted_flags():
    built = router.build_providers()
    flags = built["claude_cli"].extra_flags
    assert flags[flags.index("--tools") + 1] == ""
    assert "--restricted" in flags and "--strict-mcp-config" in flags
    assert "ollama" not in built  # disabled in the shipped policy until you enable it


def test_provider_hash_tracks_the_effective_route_and_changes_the_cache_key():
    base = router.provider_hash_for("example_assessment", FREE_EVERYTHING)
    escalated = router.provider_hash_for("example_assessment", FREE_EVERYTHING, tier_override="strong")
    assert base != escalated
    assert cache.compute_cache_key("c", provider_hash=base) != cache.compute_cache_key("c", provider_hash=escalated)
    assert cache.compute_cache_key("c") == cache.compute_cache_key("c", provider_hash="")
