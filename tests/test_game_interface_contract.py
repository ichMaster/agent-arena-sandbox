"""ARENA-002 -- contract test pinning the `GameInterface` seam.

This pins architecture.md §4.1. It is deliberately written against the *signature*,
not against any game: the seam is what the server, the agent and the UI all depend
on, so it must only change when the seam is changed on purpose -- in the same commit
as architecture.md.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from games.interface import GameInterface

#: name -> (parameters after self, return annotation), exactly as pinned in §4.1.
SEAM: dict[str, tuple[list[str], str]] = {
    "get_state": ([], "dict[str, Any]"),
    "get_valid_moves": ([], "list[Any]"),
    "apply_move": (["player", "move"], "bool"),
    "is_game_over": ([], "str | None"),
}


class _Stub(GameInterface):
    """A minimal complete implementation -- the seam must be implementable as-is."""

    def get_state(self) -> dict[str, Any]:
        return {"board": [None] * 9}

    def get_valid_moves(self) -> list[Any]:
        return []

    def apply_move(self, player: str, move: Any) -> bool:
        return False

    def is_game_over(self) -> str | None:
        return None


def test_the_seam_has_exactly_the_four_pinned_methods() -> None:
    """No method may be added or removed without changing this pin."""
    declared = {
        name
        for name, value in vars(GameInterface).items()
        if callable(value) and not name.startswith("_")
    }
    assert declared == set(SEAM)


@pytest.mark.parametrize("name", sorted(SEAM))
def test_each_method_is_abstract(name: str) -> None:
    assert name in GameInterface.__abstractmethods__


@pytest.mark.parametrize(("name", "expected"), sorted(SEAM.items()))
def test_each_method_signature_matches_architecture_4_1(
    name: str, expected: tuple[list[str], str]
) -> None:
    params, return_annotation = expected
    signature = inspect.signature(getattr(GameInterface, name))
    assert [p for p in signature.parameters if p != "self"] == params
    assert str(signature.return_annotation) == return_annotation


def test_the_move_payload_is_opaque() -> None:
    """`move` must stay `Any`: narrowing it pushes game knowledge into transport."""
    signature = inspect.signature(GameInterface.apply_move)
    assert str(signature.parameters["move"].annotation) == "Any"
    assert str(signature.parameters["player"].annotation) == "str"


def test_the_interface_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        GameInterface()  # type: ignore[abstract]


@pytest.mark.parametrize("missing", sorted(SEAM))
def test_a_subclass_missing_any_method_cannot_be_instantiated(missing: str) -> None:
    """Every one of the four is required -- a partial game is not a game."""
    body = {name: getattr(_Stub, name) for name in SEAM if name != missing}
    partial = type("Partial", (GameInterface,), body)
    with pytest.raises(TypeError):
        partial()


def test_a_complete_subclass_instantiates() -> None:
    game = _Stub()
    assert isinstance(game, GameInterface)
    assert game.get_state() == {"board": [None] * 9}
    assert game.get_valid_moves() == []
    assert game.apply_move("X", 0) is False
    assert game.is_game_over() is None
