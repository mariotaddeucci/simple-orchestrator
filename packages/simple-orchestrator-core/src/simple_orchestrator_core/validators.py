"""Input validators for untrusted external inputs.

These validators are shared by the REST API and any auxiliary interfaces (e.g. MCP).
They implement a zero-trust policy: validate inputs before touching DB or filesystem.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator
from ulid import ULID

_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_AGENT_ID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_\\-]{0,127}$")
_ALIAS_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_\\-]{0,99}$")
_DEP_REF_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_\\-]{0,127}$")

MAX_PROMPT_LENGTH: int = 500_000
MAX_MEMORY_CONTENT_LENGTH: int = 1_000_000
MAX_DESCRIPTION_LENGTH: int = 200
MAX_WORKDIR_LENGTH: int = 4_096
MAX_NOTE_LENGTH: int = 10_000


def _check_ulid(v: str) -> str:
    if not _ULID_RE.match(v):
        raise ValueError("must be a 26-character ULID (Crockford base32 uppercase)")
    try:
        ULID.from_str(v)
    except ValueError as e:
        raise ValueError("must be a valid ULID") from e
    return v


def _check_agent_id(v: str) -> str:
    if not _AGENT_ID_RE.match(v):
        raise ValueError(
            "must start with an alphanumeric character and contain only "
            "letters, digits, hyphens, or underscores (max 128 chars)",
        )
    return v


def _check_alias(v: str) -> str:
    if not _ALIAS_RE.match(v):
        raise ValueError(
            "must start with an alphanumeric character and contain only "
            "letters, digits, hyphens, or underscores (max 100 chars)",
        )
    return v


def _check_dep_ref(v: str) -> str:
    if not _DEP_REF_RE.match(v):
        raise ValueError(
            "must start with an alphanumeric character and contain only "
            "letters, digits, hyphens, or underscores (max 128 chars)",
        )
    return v


def _check_workdir(v: str | None) -> str | None:
    if v is None:
        return v
    if "\x00" in v:
        raise ValueError("must not contain null bytes")
    if len(v) > MAX_WORKDIR_LENGTH:
        raise ValueError(f"must not exceed {MAX_WORKDIR_LENGTH} characters")
    parts = re.split(r"[/\\\\]", v)
    if ".." in parts:
        raise ValueError("must not contain path traversal sequences (..)")
    return v


ValidULID = Annotated[str, AfterValidator(_check_ulid)]
ValidAgentId = Annotated[str, AfterValidator(_check_agent_id)]
ValidAlias = Annotated[str, AfterValidator(_check_alias)]
ValidDepRef = Annotated[str, AfterValidator(_check_dep_ref)]
ValidWorkdir = Annotated[str | None, AfterValidator(_check_workdir)]
