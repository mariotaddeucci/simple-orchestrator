"""Tests for input validators used by MCP tools.

Covers zero-trust validation of all external inputs: ID formats, size limits,
path traversal, and whitelist constraints.
"""

import pytest
from pydantic import TypeAdapter, ValidationError
from ulid import ULID

from simple_orchestrator.mcp_server import _TaskSpec
from simple_orchestrator.validators import (
    MAX_DESCRIPTION_LENGTH,
    MAX_MEMORY_CONTENT_LENGTH,
    MAX_PROMPT_LENGTH,
    MAX_WORKDIR_LENGTH,
    ValidAgentId,
    ValidAlias,
    ValidDepRef,
    ValidULID,
    ValidWorkdir,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_ulid_ta = TypeAdapter(ValidULID)
_agent_id_ta = TypeAdapter(ValidAgentId)
_alias_ta = TypeAdapter(ValidAlias)
_dep_ref_ta = TypeAdapter(ValidDepRef)
_workdir_ta = TypeAdapter(ValidWorkdir)


def _valid_ulid(v: str) -> str:
    return _ulid_ta.validate_python(v)


def _valid_agent_id(v: str) -> str:
    return _agent_id_ta.validate_python(v)


def _valid_alias(v: str) -> str:
    return _alias_ta.validate_python(v)


def _valid_dep_ref(v: str) -> str:
    return _dep_ref_ta.validate_python(v)


def _valid_workdir(v: str | None) -> str | None:
    return _workdir_ta.validate_python(v)


# ── ValidULID ─────────────────────────────────────────────────────────────────


class TestValidULID:
    def test_valid_ulid_passes(self):
        ulid = "01JTEST0000000000000000001"  # 26 uppercase base32
        assert _valid_ulid(ulid) == ulid

    def test_real_ulid_passes(self):
        ulid = str(ULID())
        assert _valid_ulid(ulid) == ulid

    def test_too_short_rejected(self):
        with pytest.raises(ValidationError):
            _valid_ulid("01JTEST000000000000000000")  # 25 chars

    def test_too_long_rejected(self):
        with pytest.raises(ValidationError):
            _valid_ulid("01JTEST00000000000000000012")  # 27 chars

    def test_lowercase_rejected(self):
        with pytest.raises(ValidationError):
            _valid_ulid("01jtest0000000000000000001")

    def test_invalid_chars_rejected(self):
        with pytest.raises(ValidationError):
            _valid_ulid("01JTEST000000000000000000I")  # 'I' not in Crockford

    def test_sql_injection_rejected(self):
        with pytest.raises(ValidationError):
            _valid_ulid("'; DROP TABLE queue; --")

    def test_empty_string_rejected(self):
        with pytest.raises(ValidationError):
            _valid_ulid("")


# ── ValidAgentId ──────────────────────────────────────────────────────────────


class TestValidAgentId:
    def test_short_config_key_passes(self):
        assert _valid_agent_id("reviewer") == "reviewer"

    def test_ulid_passes(self):
        ulid = str(ULID())
        assert _valid_agent_id(ulid) == ulid

    def test_with_underscore_and_hyphen(self):
        assert _valid_agent_id("my-agent_v2") == "my-agent_v2"

    def test_starts_with_digit_passes(self):
        assert _valid_agent_id("1agent") == "1agent"

    def test_max_length_passes(self):
        v = "a" * 128
        assert _valid_agent_id(v) == v

    def test_over_max_length_rejected(self):
        with pytest.raises(ValidationError):
            _valid_agent_id("a" * 129)

    def test_empty_rejected(self):
        with pytest.raises(ValidationError):
            _valid_agent_id("")

    def test_starts_with_hyphen_rejected(self):
        with pytest.raises(ValidationError):
            _valid_agent_id("-bad-start")

    def test_starts_with_underscore_rejected(self):
        with pytest.raises(ValidationError):
            _valid_agent_id("_bad")

    def test_slash_rejected(self):
        with pytest.raises(ValidationError):
            _valid_agent_id("path/traversal")

    def test_null_byte_rejected(self):
        with pytest.raises(ValidationError):
            _valid_agent_id("agent\x00id")

    def test_sql_injection_rejected(self):
        with pytest.raises(ValidationError):
            _valid_agent_id("'; DROP TABLE agents; --")


# ── ValidAlias ────────────────────────────────────────────────────────────────


class TestValidAlias:
    def test_simple_alias_passes(self):
        assert _valid_alias("fetch") == "fetch"

    def test_alphanumeric_with_dash_passes(self):
        assert _valid_alias("step-1") == "step-1"

    def test_max_length_passes(self):
        v = "a" * 100
        assert _valid_alias(v) == v

    def test_over_max_length_rejected(self):
        with pytest.raises(ValidationError):
            _valid_alias("a" * 101)

    def test_starts_with_hyphen_rejected(self):
        with pytest.raises(ValidationError):
            _valid_alias("-bad")

    def test_special_chars_rejected(self):
        with pytest.raises(ValidationError):
            _valid_alias("alias with spaces")

    def test_empty_rejected(self):
        with pytest.raises(ValidationError):
            _valid_alias("")


# ── ValidDepRef ───────────────────────────────────────────────────────────────


class TestValidDepRef:
    def test_ulid_passes(self):
        assert _valid_dep_ref(str(ULID()))

    def test_alias_passes(self):
        assert _valid_dep_ref("fetch-data") == "fetch-data"

    def test_too_long_rejected(self):
        with pytest.raises(ValidationError):
            _valid_dep_ref("a" * 129)

    def test_special_chars_rejected(self):
        with pytest.raises(ValidationError):
            _valid_dep_ref("dep@ref!")


# ── ValidWorkdir ──────────────────────────────────────────────────────────────


class TestValidWorkdir:
    def test_none_passes(self):
        assert _valid_workdir(None) is None

    def test_absolute_path_passes(self):
        assert _valid_workdir("/workspace/project") == "/workspace/project"

    def test_relative_path_passes(self):
        assert _valid_workdir("project/src") == "project/src"

    def test_path_traversal_unix_rejected(self):
        with pytest.raises(ValidationError):
            _valid_workdir("/workspace/../../etc/passwd")

    def test_path_traversal_windows_style_rejected(self):
        with pytest.raises(ValidationError):
            _valid_workdir("workspace\\..\\..\\Windows\\system32")

    def test_path_traversal_leading_rejected(self):
        with pytest.raises(ValidationError):
            _valid_workdir("../escape")

    def test_null_byte_rejected(self):
        with pytest.raises(ValidationError):
            _valid_workdir("/workspace/\x00evil")

    def test_too_long_rejected(self):
        with pytest.raises(ValidationError):
            _valid_workdir("/workspace/" + "a" * MAX_WORKDIR_LENGTH)

    def test_max_length_passes(self):
        v = "/" + "a" * (MAX_WORKDIR_LENGTH - 1)
        assert _valid_workdir(v) == v


# ── Size constants ────────────────────────────────────────────────────────────


class TestSizeConstants:
    def test_prompt_max_length_defined(self):
        assert MAX_PROMPT_LENGTH == 500_000

    def test_memory_content_max_length_defined(self):
        assert MAX_MEMORY_CONTENT_LENGTH == 1_000_000

    def test_description_max_length_defined(self):
        assert MAX_DESCRIPTION_LENGTH == 200


# ── _TaskSpec model ───────────────────────────────────────────────────────────


class TestTaskSpec:
    """Validate the _TaskSpec Pydantic model used by enqueue_tasks."""

    def _make_spec(self, **kwargs):
        defaults = {"agent_id": "my-agent", "prompt": "Do something"}
        return _TaskSpec(**{**defaults, **kwargs})

    def test_valid_spec(self):
        spec = self._make_spec()
        assert spec.agent_id == "my-agent"
        assert spec.prompt == "Do something"

    def test_valid_alias(self):
        spec = self._make_spec(alias="step-1")
        assert spec.alias == "step-1"

    def test_invalid_alias_rejected(self):
        with pytest.raises(ValidationError):
            _TaskSpec(agent_id="ag", prompt="p", alias="-bad-alias")

    def test_prompt_too_long_rejected(self):
        with pytest.raises(ValidationError):
            _TaskSpec(agent_id="ag", prompt="x" * (MAX_PROMPT_LENGTH + 1))

    def test_path_traversal_workdir_rejected(self):
        with pytest.raises(ValidationError):
            _TaskSpec(agent_id="ag", prompt="p", workdir="../../etc")

    def test_too_many_deps_rejected(self):
        # Use valid aliases for the 101 dependency references
        deps = [f"step{i}" for i in range(101)]
        with pytest.raises(ValidationError):
            _TaskSpec(agent_id="ag", prompt="p", depends_on=deps)

    def test_invalid_dep_ref_rejected(self):
        with pytest.raises(ValidationError):
            _TaskSpec(agent_id="ag", prompt="p", depends_on=["bad dep!"])
