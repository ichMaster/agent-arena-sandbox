"""Contract test pinning GameInterface (architecture.md §4.1).

A signature drift here means architecture.md §4.1 and this test must be updated together
in the same commit — the seam is one of the three contract-stability points.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from games.interface import GameInterface


def test_game_interface_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        GameInterface()  # type: ignore[abstract]


def test_get_state_signature() -> None:
    sig = inspect.signature(GameInterface.get_state)
    assert list(sig.parameters) == ["self"]
    assert sig.return_annotation in ("dict[str, Any]", dict[str, Any])


def test_get_valid_moves_signature() -> None:
    sig = inspect.signature(GameInterface.get_valid_moves)
    assert list(sig.parameters) == ["self"]
    assert sig.return_annotation in ("list[Any]", list[Any])


def test_apply_move_signature() -> None:
    sig = inspect.signature(GameInterface.apply_move)
    assert list(sig.parameters) == ["self", "player", "move"]
    assert sig.parameters["player"].annotation in ("str", str)
    assert sig.parameters["move"].annotation in ("Any", Any)
    assert sig.return_annotation in ("bool", bool)


def test_is_game_over_signature() -> None:
    sig = inspect.signature(GameInterface.is_game_over)
    assert list(sig.parameters) == ["self"]
    assert sig.return_annotation in ("str | None", str | None)
