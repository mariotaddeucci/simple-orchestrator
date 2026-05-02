from typing import Annotated, Literal
from pydantic import BaseModel, Field


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


McpConfig = Annotated[
    McpStdioConfig | McpSseConfig | McpHttpConfig,
    Field(discriminator="type"),
]
