"""Proves the autouse conftest.py guard is active (ARENA-OPUS-035, architecture.md §11): even a test
that does NOT patch the Anthropic SDK itself still can't build a real client. No paid call, ever.
"""

from unittest.mock import MagicMock

from agent.llm import AnthropicHaikuClient, create_llm_client


def test_unmocked_create_llm_client_still_gets_the_guarded_dummy() -> None:
    """No local `patch(...)` here -- relies entirely on the autouse conftest.py fixture."""
    client = create_llm_client("haiku", "sk-fake", 0.5)
    assert isinstance(client, AnthropicHaikuClient)
    # The guard patches agent.llm.AsyncAnthropic itself, so the constructed SDK object is the
    # patched dummy's return value -- a MagicMock, never a real network-capable AsyncAnthropic.
    assert isinstance(client._client, MagicMock)  # noqa: SLF001 -- verifying the guard, not the API
