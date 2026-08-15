"""Contract test pinning GameInterface (architecture.md §4.1).

Must change in the same commit as any future change to this seam.
"""

from __future__ import annotations

import inspect
from abc import ABC

import pytest

from games.interface import GameInterface


def test_game_interface_is_abstract() -> None:
    assert issubclass(GameInterface, ABC)
    with pytest.raises(TypeError):
        GameInterface()  # type: ignore[abstract]


def test_game_interface_pinned_methods() -> None:
    expected = {
        "get_state": ["self"],
        "get_valid_moves": ["self"],
        "apply_move": ["self", "player", "move"],
        "is_game_over": ["self"],
    }
    for name, params in expected.items():
        method = getattr(GameInterface, name)
        assert getattr(method, "__isabstractmethod__", False), f"{name} must be abstract"
        sig = inspect.signature(method)
        assert list(sig.parameters) == params, f"{name} signature drifted: {sig}"


def test_apply_move_return_annotation_is_bool() -> None:
    sig = inspect.signature(GameInterface.apply_move)
    assert sig.return_annotation == "bool"


def test_is_game_over_return_annotation() -> None:
    sig = inspect.signature(GameInterface.is_game_over)
    assert sig.return_annotation == "str | None"
