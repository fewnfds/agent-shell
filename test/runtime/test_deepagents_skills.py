from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_shell.contracts import FilesystemBlock, SkillBlock
from agent_shell.runtime.capabilities import build_deepagents_capabilities
from agent_shell.runtime.capabilities import deepagents as deepagents_capability
from agent_shell.runtime.capabilities.deepagents import DeepAgentsCapabilityError

def test_skill_requires_an_owned_private_package_reference() -> None:
    owner = "11111111-1111-4111-8111-111111111111"
    skill = SkillBlock.model_validate(
        {"name": "Packaged skills", "skill_package": {"folder": owner}}
    )
    assert skill.skill_package.folder == owner
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SkillBlock.model_validate(
            {"name": "Removed list", "skill_package": {"folder": owner}, "skills": ["old"]}
        )

def test_selected_skill_with_invalid_current_metadata_is_not_materialized(
    tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"
    owner = "11111111-1111-4111-8111-111111111111"
    skill_dir = skills_dir / owner / "invalid-metadata"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: invalid-metadata\n---\n",
        encoding="utf-8",
    )
    filesystem = FilesystemBlock.model_validate({"name": "Thread files"})
    skill = SkillBlock.model_validate(
        {"name": "Invalid metadata", "skill_package": {"folder": owner}}
    )

    capabilities = build_deepagents_capabilities(
        filesystem, skill, filesystem_mode="composite",
        skills_dir=skills_dir, skill_owner_id=owner,
    )
    assert capabilities.skill_sources == ("/skills/",)


def test_skill_runtime_rejects_links_inside_private_package(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    owner = "11111111-1111-4111-8111-111111111111"
    skill_dir = skills_dir / owner / "linked"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: linked\ndescription: Linked instructions.\n---\n",
        encoding="utf-8",
    )
    outside = tmp_path / "outside.txt"
    outside.write_text("outside sentinel", encoding="utf-8")
    try:
        os.symlink(outside, skill_dir / "outside.txt")
    except OSError as exc:
        pytest.skip(f"symbolic links are unavailable in this environment: {exc}")
    skill = SkillBlock.model_validate(
        {"name": "Linked Skill", "skill_package": {"folder": owner}}
    )

    with pytest.raises(DeepAgentsCapabilityError, match="link, reparse point"):
        build_deepagents_capabilities(
            FilesystemBlock.model_validate({"name": "Linked Skill workspace"}),
            skill,
            filesystem_mode="composite",
            skills_dir=skills_dir,
            skill_owner_id=owner,
        )

def test_skill_prompt_supports_default_override_and_disabled_modes(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    owner = "11111111-1111-4111-8111-111111111111"
    skill_dir = skills_dir / owner / "outline"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: outline\ndescription: Outline a document.\n---\n",
        encoding="utf-8",
    )
    filesystem = FilesystemBlock.model_validate({"name": "Thread files"})
    default_skill = SkillBlock.model_validate(
        {"name": "Default skills", "skill_package": {"folder": owner}}
    )
    custom_prompt = (
        "Locations: {skills_locations}\n"
        "Warnings: {skills_load_warnings}\n"
        "Skills: {skills_list}"
    )
    custom_skill = SkillBlock.model_validate(
        {
            "name": "Custom skills",
            "skill_package": {"folder": owner},
            "instruction_override": custom_prompt,
        }
    )
    disabled_skill = SkillBlock.model_validate(
        {
            "name": "Silent skills",
            "skill_package": {"folder": owner},
            "system_prompt_enabled": False,
        }
    )
    with pytest.raises(ValidationError, match="instruction_override must be null"):
        SkillBlock.model_validate(
            {
                "name": "Ambiguous skills",
                "skill_package": {"folder": owner},
                "system_prompt_enabled": False,
                "instruction_override": custom_prompt,
            }
        )

    default_capabilities = build_deepagents_capabilities(
        filesystem,
        default_skill,
        filesystem_mode="composite",
        skills_dir=skills_dir,
        skill_owner_id=owner,
    )
    custom_capabilities = build_deepagents_capabilities(
        filesystem,
        custom_skill,
        filesystem_mode="composite",
        skills_dir=skills_dir,
        skill_owner_id=owner,
    )
    disabled_capabilities = build_deepagents_capabilities(
        filesystem,
        disabled_skill,
        filesystem_mode="composite",
        skills_dir=skills_dir,
        skill_owner_id=owner,
    )

    assert default_capabilities.middleware[0].system_prompt_template != custom_prompt
    assert custom_capabilities.middleware[0].system_prompt_template == custom_prompt
    assert disabled_capabilities.middleware[0].system_prompt_template is None

def test_default_workspace_keeps_consumer_skill_overlays_read_only_and_isolated(
    tmp_path: Path,
) -> None:
    from deepagents.backends import StateBackend

    skills_dir = tmp_path / "skills"
    alpha_owner = "11111111-1111-4111-8111-111111111111"
    beta_owner = "22222222-2222-4222-8222-222222222222"
    for owner, name in ((alpha_owner, "alpha"), (beta_owner, "beta")):
        folder = skills_dir / owner / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {name} instructions.\n---\n",
            encoding="utf-8",
        )
    alpha = SkillBlock.model_validate(
        {"name": "Alpha only", "skill_package": {"folder": alpha_owner}}
    )
    beta = SkillBlock.model_validate(
        {"name": "Beta only", "skill_package": {"folder": beta_owner}}
    )

    alpha_capabilities = build_deepagents_capabilities(
        FilesystemBlock.model_validate({"name": "Alpha workspace"}),
        alpha,
        filesystem_mode="composite",
        skills_dir=skills_dir,
        skill_owner_id=alpha_owner,
    )
    beta_capabilities = build_deepagents_capabilities(
        FilesystemBlock.model_validate({"name": "Beta workspace"}),
        beta,
        filesystem_mode="composite",
        skills_dir=skills_dir,
        skill_owner_id=beta_owner,
        workspace=alpha_capabilities.workspace,
    )

    alpha_filesystem = alpha_capabilities.middleware[-1]
    assert "read_file" in {tool.name for tool in alpha_filesystem.tools}
    assert alpha_filesystem._tool_token_limit_before_evict == 20_000
    assert isinstance(alpha_capabilities.backend.default, StateBackend)
    assert alpha_capabilities.backend is not beta_capabilities.backend
    assert alpha_capabilities.workspace is not beta_capabilities.workspace
    assert (
        alpha_capabilities.workspace.default_backend
        is beta_capabilities.workspace.default_backend
    )
    assert alpha_capabilities.backend.default is beta_capabilities.backend.default
    assert alpha_capabilities.skill_sources == ("/skills/",)
    assert beta_capabilities.skill_sources == ("/skills/",)
    assert alpha_capabilities.backend.read(
        "/skills/alpha/SKILL.md"
    ).error is None
    assert "not found" in alpha_capabilities.backend.read(
        "/skills/beta/SKILL.md"
    ).error.lower()
    assert beta_capabilities.backend.read(
        "/skills/beta/SKILL.md"
    ).error is None
    assert "not found" in beta_capabilities.backend.read(
        "/skills/alpha/SKILL.md"
    ).error.lower()
    denied = alpha_capabilities.backend.write(
        "/skills/alpha/created.md", "must not be written"
    )
    assert "read-only" in denied.error
    assert not (skills_dir / alpha_owner / "alpha" / "created.md").exists()

def test_configured_workspace_routes_entire_skill_namespace_away_from_state(
    tmp_path: Path,
) -> None:
    from deepagents.backends import StateBackend

    skills_dir = tmp_path / "skills"
    owner = "11111111-1111-4111-8111-111111111111"
    selected_folder = skills_dir / owner / "selected"
    selected_folder.mkdir(parents=True)
    manifest = selected_folder / "SKILL.md"
    manifest.write_text(
        "---\nname: selected\ndescription: Selected instructions.\n---\n",
        encoding="utf-8",
    )
    filesystem = FilesystemBlock.model_validate({"name": "Shared workspace"})
    skill = SkillBlock.model_validate(
        {"name": "Selected Skill", "skill_package": {"folder": owner}}
    )

    capabilities = build_deepagents_capabilities(
        filesystem,
        skill,
        filesystem_mode="composite",
        skills_dir=skills_dir,
        skill_owner_id=owner,
    )

    assert isinstance(capabilities.backend.default, StateBackend)
    skills_backend = capabilities.backend.routes["/skills/"]
    routed_backend, routed_path = capabilities.backend._get_backend_and_key(
        "/skills/unselected/SKILL.md"
    )
    assert routed_backend is skills_backend
    assert routed_path == "/unselected/SKILL.md"
    assert "not found" in capabilities.backend.read(
        "/skills/unselected/SKILL.md"
    ).error.lower()
    denied = capabilities.backend.edit(
        "/skills/selected/SKILL.md",
        "Selected instructions.",
        "Changed instructions.",
    )
    assert "read-only" in denied.error
    assert "Selected instructions." in manifest.read_text(encoding="utf-8")
