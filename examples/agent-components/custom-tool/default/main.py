"""One configuration-owned Python extension exports exactly one LangChain Tool.

Agent Shell calls the module-level ``create_tool()`` once while assembling each
Agent that references this configuration. The factory must take no arguments
and return one ``langchain_core.tools.BaseTool``. Decorating a typed function
with ``@tool`` is the usual LangChain form: the function name becomes the model-
visible tool name, its docstring becomes the description, and its parameters
become the input schema.

Keep this file focused on one Tool. Local helper modules may live beside it.
Add direct third-party dependencies to requirements.txt, one requirement per
line; leave that file empty when this extension needs only platform packages.
Tool functions can use LangChain's injected ToolRuntime parameters when they
need runtime context, state, store, streaming, or config. This code is trusted
server-side Python and does not run in a sandbox.
"""

from langchain.tools import tool
from langchain_core.tools import BaseTool


@tool
def word_count(text: str) -> int:
    """Count whitespace-separated words in text."""

    return len(text.split())


def create_tool() -> BaseTool:
    return word_count
