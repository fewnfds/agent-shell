from typing import Annotated

from pydantic import Field


NodeId = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$"),
]


__all__ = ["NodeId"]
