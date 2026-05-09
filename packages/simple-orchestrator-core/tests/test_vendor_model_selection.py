from __future__ import annotations

import pytest
from simple_orchestrator_core.api import AgentUpsertRequest
from simple_orchestrator_core.vendor_selector import parse_vendor_model_selection


def test_parse_vendor_model_selection_normalizes_aliases():
    sel = parse_vendor_model_selection("claude-code/claude-sonnet-4-6")
    assert sel.vendor == "claude_code"
    assert sel.model == "claude-sonnet-4-6"

    sel = parse_vendor_model_selection("github-copilot/gpt-4.1")
    assert sel.vendor == "github_copilot"
    assert sel.model == "gpt-4.1"


def test_agent_settings_accepts_combined_vendor_model_in_vendor_field():
    agent = AgentUpsertRequest(id="reviewer", name="Reviewer", prompt="hi", vendor="claude-code/claude-sonnet-4-6")
    assert agent.vendor == "claude_code"
    assert agent.model == "claude-sonnet-4-6"


def test_agent_settings_accepts_combined_vendor_model_in_model_field():
    agent = AgentUpsertRequest(id="reviewer", name="Reviewer", prompt="hi", model="github-copilot/gpt-4.1")
    assert agent.vendor == "github_copilot"
    assert agent.model == "gpt-4.1"


def test_agent_settings_normalizes_vendor_alias_without_combining():
    agent = AgentUpsertRequest(id="reviewer", name="Reviewer", prompt="hi", vendor="github-copilot", model="gpt-4.1")
    assert agent.vendor == "github_copilot"
    assert agent.model == "gpt-4.1"


def test_agent_settings_requires_vendor_when_model_not_combined():
    with pytest.raises(ValueError, match="requires a vendor"):
        AgentUpsertRequest(id="reviewer", name="Reviewer", prompt="hi", model="gpt-4.1")
