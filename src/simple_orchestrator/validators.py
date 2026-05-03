"""Input validators for MCP tool inputs and API endpoints.

Defines reusable annotated types and validator functions following a zero-trust
policy: never trust the client.  All inputs arriving from external callers must
pass through these checks before touching the database or the file system.
"""

import re
from typing import Annotated

from pydantic import AfterValidator

# ── Regex patterns ────────────────────────────────────────────────────────────

# Crockford base32 alphabet used by ULID (no I, L, O, U among uppercase)
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

# Agent ID: ULID *or* a short config key composed of safe characters.
# Must start with alphanumeric; allows letters, digits, hyphens, underscores.
_AGENT_ID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_\-]{0,127}$")

# Batch-task alias (used inside enqueue_tasks as a local name)
_ALIAS_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_\-]{0,99}$")

# Dependency reference inside _TaskSpec: either an alias or a ULID.
# We allow the same safe charset as agent IDs (covers both cases).
_DEP_REF_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_\-]{0,127}$")

# ── Size constants ────────────────────────────────────────────────────────────

# Large task prompts are legitimate (code, documents…) but must be bounded.
MAX_PROMPT_LENGTH: int = 500_000

# Memory entries store full session context so we allow up to 1 MB.
MAX_MEMORY_CONTENT_LENGTH: int = 1_000_000

MAX_DESCRIPTION_LENGTH: int = 200
MAX_WORKDIR_LENGTH: int = 4_096

# ── Validator functions ───────────────────────────────────────────────────────


def _check_ulid(v: str) -> str:
    if not _ULID_RE.match(v):
        raise ValueError("must be a 26-character ULID (Crockford base32 uppercase)")
    return v


def _check_agent_id(v: str) -> str:
    if not _AGENT_ID_RE.match(v):
        raise ValueError(
            "must start with an alphanumeric character and contain only "
            "letters, digits, hyphens, or underscores (max 128 chars)"
        )
    return v


def _check_alias(v: str) -> str:
    if not _ALIAS_RE.match(v):
        raise ValueError(
            "must start with an alphanumeric character and contain only "
            "letters, digits, hyphens, or underscores (max 100 chars)"
        )
    return v


def _check_dep_ref(v: str) -> str:
    if not _DEP_REF_RE.match(v):
        raise ValueError(
            "must start with an alphanumeric character and contain only "
            "letters, digits, hyphens, or underscores (max 128 chars)"
        )
    return v


def _check_workdir(v: str | None) -> str | None:
    if v is None:
        return v
    if "\x00" in v:
        raise ValueError("must not contain null bytes")
    if len(v) > MAX_WORKDIR_LENGTH:
        raise ValueError(f"must not exceed {MAX_WORKDIR_LENGTH} characters")
    parts = re.split(r"[/\\]", v)
    if ".." in parts:
        raise ValueError("must not contain path traversal sequences (..)")
    return v


# ── Annotated type aliases ────────────────────────────────────────────────────

ValidULID = Annotated[str, AfterValidator(_check_ulid)]
ValidAgentId = Annotated[str, AfterValidator(_check_agent_id)]
ValidAlias = Annotated[str, AfterValidator(_check_alias)]
ValidDepRef = Annotated[str, AfterValidator(_check_dep_ref)]
ValidWorkdir = Annotated[str | None, AfterValidator(_check_workdir)]
