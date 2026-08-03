"""Shared test configuration (architecture.md §11): guarantees no test path can reach the real
Anthropic API, even a regression that forgets to mock the LLM seam locally.
"""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _no_real_anthropic_client() -> Iterator[None]:
    """Patch `agent.llm.AsyncAnthropic` for every test. A test that patches it itself (a `with
    patch(...)` inside the test body) still overrides this outer patch locally -- `unittest.mock`
    patches nest, and the innermost one wins for the duration of its own `with` block.
    """
    with patch("agent.llm.AsyncAnthropic", return_value=MagicMock()):
        yield
