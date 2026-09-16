"""Translate one External Agent preset into the native Antigravity CLI files.

The CLI reads its persona from ``<home>/.gemini/config/agents/<name>.md`` and
its permission posture from ``<home>/.gemini/antigravity-cli/settings.json``.
Every run therefore materializes a content-addressed agent file plus a merged
settings document, and hands the runner a complete process environment.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from agent_shell.contracts import ExternalAgentProfile
from agent_shell.external_agents.errors import materialization_failed
from agent_shell.external_agents.layout import AntigravityLifecycleLayout
from agent_shell.storage.atomic_files import write_text_atomic


AGENT_DIRECTORY = Path(".gemini") / "config" / "agents"
SETTINGS_FILE = Path(".gemini") / "antigravity-cli" / "settings.json"
HOME_ENVIRONMENT_VARIABLES = ("USERPROFILE", "HOME", "XDG_CONFIG_HOME")
SYSTEM_PROMPT_HEADING = "# System Prompt"


@dataclass(frozen=True)
class MaterializedExternalAgent:
    """Everything a run needs on disk, plus the child process environment."""

    definition_name: str
    definition_revision: str
    definition_file: Path
    settings_file: Path
    layout: AntigravityLifecycleLayout
    environment: Mapping[str, str]

    @property
    def home(self) -> Path:
        return self.layout.home

    @property
    def workspace(self) -> Path:
        return self.layout.workspace


def definition_revision(profile: ExternalAgentProfile) -> str:
    """Return the content address of one preset's prompt payload."""

    payload = "\0".join(
        (profile.agent_name, profile.system_prompt, profile.tool_guidance)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


def definition_name(profile: ExternalAgentProfile) -> str:
    return f"{profile.agent_name}-{definition_revision(profile)}"


def render_definition(profile: ExternalAgentProfile) -> str:
    """Render the agent Markdown the CLI selects with ``--agent``."""

    name = definition_name(profile)
    frontmatter = [
        "---",
        f"name: {name}",
        f"description: {json.dumps(profile.description, ensure_ascii=False)}",
        "subagent: false",
        "mainAgent: true",
    ]
    if profile.model:
        frontmatter.append(f"model: {json.dumps(profile.model, ensure_ascii=False)}")
    if profile.exclude_default_components:
        # The CLI treats ``tools`` as a strict allow-list. Omitting the key and
        # listing nothing both mean "no built-in tool", so an empty list is
        # never written.
        frontmatter.append("excludeDefaultComponents: true")
        if profile.tools:
            frontmatter.append(f"tools: [{', '.join(profile.tools)}]")
    frontmatter.append("---")

    body = [SYSTEM_PROMPT_HEADING, "", profile.system_prompt]
    if profile.tool_guidance:
        body.extend(["", profile.tool_guidance])
    return "\n".join([*frontmatter, "", *body, ""])


def build_environment(
    profile: ExternalAgentProfile,
    layout: AntigravityLifecycleLayout,
    host_environment: Mapping[str, str],
) -> dict[str, str]:
    """Layer the preset's variables over the host, then own the HOME trio."""

    environment = dict(host_environment)
    environment.update(profile.env)
    home = str(layout.home)
    environment["USERPROFILE"] = home
    environment["HOME"] = home
    environment["XDG_CONFIG_HOME"] = str(layout.home / ".config")
    return environment


def merge_settings(
    profile: ExternalAgentProfile,
    existing: Mapping[str, object],
) -> dict[str, object]:
    """Write only the settings keys this preset owns."""

    document = dict(existing)
    document["toolPermission"] = profile.tool_permission
    permissions = document.get("permissions")
    permissions = dict(permissions) if isinstance(permissions, Mapping) else {}
    if profile.permission_allow:
        permissions["allow"] = list(profile.permission_allow)
    else:
        permissions.pop("allow", None)
    if permissions:
        document["permissions"] = permissions
    else:
        document.pop("permissions", None)
    return document


def _read_settings(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise materialization_failed(
            f"The Antigravity CLI settings file could not be read: {exc}",
            path=path,
        ) from exc
    if not isinstance(document, dict):
        raise materialization_failed(
            "The Antigravity CLI settings file must contain a JSON object.",
            path=path,
        )
    return document


def materialize_external_agent(
    profile: ExternalAgentProfile,
    layout: AntigravityLifecycleLayout,
    *,
    host_environment: Mapping[str, str],
) -> MaterializedExternalAgent:
    """Create the isolated HOME and workspace for one External Agent run."""

    layout.create()
    settings_file = layout.home / SETTINGS_FILE
    settings = merge_settings(profile, _read_settings(settings_file))
    try:
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        definition_file = (
            layout.home / AGENT_DIRECTORY / f"{definition_name(profile)}.md"
        )
        write_text_atomic(definition_file, render_definition(profile))
        write_text_atomic(
            settings_file,
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        )
    except OSError as exc:
        raise materialization_failed(
            f"The External Agent environment could not be written: {exc}",
            path=layout.root,
        ) from exc
    return MaterializedExternalAgent(
        definition_name=definition_name(profile),
        definition_revision=definition_revision(profile),
        definition_file=definition_file,
        settings_file=settings_file,
        layout=layout,
        environment=build_environment(profile, layout, host_environment),
    )


__all__ = [
    "AGENT_DIRECTORY",
    "HOME_ENVIRONMENT_VARIABLES",
    "MaterializedExternalAgent",
    "SETTINGS_FILE",
    "SYSTEM_PROMPT_HEADING",
    "build_environment",
    "definition_name",
    "definition_revision",
    "materialize_external_agent",
    "merge_settings",
    "render_definition",
]
