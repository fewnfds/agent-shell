from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


_REQUEST_ID: ContextVar[str] = ContextVar("agent_shell_request_id", default="")
_ACTOR: ContextVar[str] = ContextVar("agent_shell_actor", default="system")


def current_request_id() -> str:
    return _REQUEST_ID.get()


def current_actor() -> str:
    return _ACTOR.get()


@contextmanager
def bind_request_context(request_id: str, actor: str) -> Iterator[None]:
    request_token = _REQUEST_ID.set(request_id)
    actor_token = _ACTOR.set(actor)
    try:
        yield
    finally:
        _ACTOR.reset(actor_token)
        _REQUEST_ID.reset(request_token)
