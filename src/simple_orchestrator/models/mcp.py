import re
import sys
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

_IMPORT_PATH_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*:[a-zA-Z_][a-zA-Z0-9_]*$")


class McpStdioConfig(BaseModel):
    type: Literal["stdio"] = "stdio"
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class McpSseConfig(BaseModel):
    type: Literal["sse"] = "sse"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class McpHttpConfig(BaseModel):
    type: Literal["http"] = "http"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class McpLocalConfig(BaseModel):
    """Local FastMCP app loaded via importlib and served over stdio.

    The ``import_path`` must use the ``"module.path:attribute"`` notation,
    e.g. ``"my_tools.server:mcp"``.  The attribute must be a
    :class:`fastmcp.FastMCP` instance (or any object whose ``.run()`` method
    accepts ``transport="stdio"``).

    At runtime the config is converted to an equivalent :class:`McpStdioConfig`
    that spawns ``sys.executable -c "..."`` and communicates over stdio.
    """

    type: Literal["local"] = "local"
    import_path: str  # "module.path:attribute"

    @model_validator(mode="after")
    def _validate_import_path(self) -> "McpLocalConfig":
        if not _IMPORT_PATH_RE.match(self.import_path):
            raise ValueError(
                f"import_path {self.import_path!r} must be in 'module:attribute' format "
                "using only valid Python identifiers (e.g. 'my_tools.server:mcp')",
            )
        return self

    def to_stdio(self) -> McpStdioConfig:
        """Return an :class:`McpStdioConfig` that runs this FastMCP app via importlib."""
        module, attr = self.import_path.split(":")
        script = f"import importlib; getattr(importlib.import_module({module!r}), {attr!r}).run(transport='stdio')"
        return McpStdioConfig(command=sys.executable, args=["-c", script])


McpConfig = Annotated[
    McpStdioConfig | McpSseConfig | McpHttpConfig | McpLocalConfig,
    Field(discriminator="type"),
]
