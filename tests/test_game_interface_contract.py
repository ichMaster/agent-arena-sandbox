"""Contract test pinning the GameInterface seam (architecture.md §4.1).

This test IS the seam's source of truth alongside architecture.md §4.1: a change to either the
method names or their signatures must update both together in the same commit.
"""

import inspect
from abc import ABC
from typing import Any

import pytest

from games.interface import GameInterface

EXPECTED_METHODS = {
    "get_state": ["self"],
    "get_valid_moves": ["self"],
    "apply_move": ["self", "player", "move"],
    "is_game_over": ["self"],
}


def test_is_an_abstract_base_class() -> None:
    assert issubclass(GameInterface, ABC)


def test_cannot_instantiate_directly() -> None:
    with pytest.raises(TypeError):
        GameInterface()  # type: ignore[abstract]


def test_defines_exactly_the_four_seam_methods() -> None:
    assert GameInterface.__abstractmethods__ == frozenset(EXPECTED_METHODS)


@pytest.mark.parametrize("name,params", EXPECTED_METHODS.items())
def test_method_signature_pinned(name: str, params: list[str]) -> None:
    method = getattr(GameInterface, name)
    signature = inspect.signature(method)
    assert list(signature.parameters) == params


def test_partial_subclass_cannot_be_instantiated() -> None:
    """A subclass implementing only some methods stays abstract (abstractness enforced)."""

    class PartialGame(GameInterface):
        def get_state(self) -> dict[str, Any]:
            return {}

        def get_valid_moves(self) -> list[Any]:
            return []

        # apply_move and is_game_over deliberately left unimplemented.

    with pytest.raises(TypeError):
        PartialGame()  # type: ignore[abstract]


def test_full_subclass_is_instantiable() -> None:
    class CompleteGame(GameInterface):
        def get_state(self) -> dict[str, Any]:
            return {"board": []}

        def get_valid_moves(self) -> list[Any]:
            return []

        def apply_move(self, player: str, move: Any) -> bool:
            return False

        def is_game_over(self) -> str | None:
            return None

    game = CompleteGame()
    assert game.get_state() == {"board": []}
    assert game.apply_move("X", 0) is False
    assert game.is_game_over() is None
