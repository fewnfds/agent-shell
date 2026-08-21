from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import langsmith as ls
from langsmith import Client

if TYPE_CHECKING:
    from agent_shell.settings import Settings


_TRACING_ENVIRONMENT = (
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_TRACING",
)


class LangSmithConnectionError(RuntimeError):
    pass


def _client(settings: Settings, *, report_upload_errors: bool) -> Client:
    def report_error(exc: Exception) -> None:
        logging.getLogger("agent_shell.langsmith").error(
            "LangSmith trace upload failed error_type=%s",
            type(exc).__name__,
        )

    return Client(
        api_url=settings.langsmith_endpoint,
        api_key=(
            settings.langsmith_api_key.get_secret_value()
            if settings.langsmith_api_key is not None
            else None
        ),
        workspace_id=settings.langsmith_workspace_id,
        tracing_error_callback=report_error if report_upload_errors else None,
    )


def configure_project_langsmith_tracing(settings: Settings) -> Client | None:
    """Configure the process-wide LangSmith client before building any graphs."""
    value = "true" if settings.langsmith_tracing_enabled else "false"
    for name in _TRACING_ENVIRONMENT:
        os.environ[name] = value
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    optional = {
        "LANGSMITH_API_KEY": (
            settings.langsmith_api_key.get_secret_value()
            if settings.langsmith_api_key is not None
            else None
        ),
        "LANGSMITH_WORKSPACE_ID": settings.langsmith_workspace_id,
    }
    for name, item in optional.items():
        if item is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = item

    client = _client(settings, report_upload_errors=True) if settings.langsmith_tracing_enabled else None
    ls.configure(
        client=client,
        enabled=settings.langsmith_tracing_enabled,
        project_name=settings.langsmith_project,
    )
    return client


def validate_langsmith_connection(settings: Settings) -> None:
    """Verify that the configured key can access the configured LangSmith region."""
    client = _client(settings, report_upload_errors=False)
    try:
        next(client.list_projects(limit=1), None)
    except Exception as exc:
        raise LangSmithConnectionError from exc
    finally:
        client.close()
