from __future__ import annotations

_registered_keys: set[str] = set()


def ensure_agent_shell_harness_profiles(*, provider: str, model: str) -> None:
    """Disable the implicit general-purpose Subagent for one configured model."""
    from deepagents import (
        GeneralPurposeSubagentProfile,
        HarnessProfile,
        register_harness_profile,
    )

    profile = HarnessProfile(
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)
    )
    keys = {provider, f"{provider}:{model}"}

    for key in keys - _registered_keys:
        register_harness_profile(key, profile)
        _registered_keys.add(key)
