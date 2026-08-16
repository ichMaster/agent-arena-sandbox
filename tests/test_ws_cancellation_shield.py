"""Regression-guard the cancellation-safe cleanup primitive (ARENA-109,
architecture.md §10, roadmap.md §v05.01 DoD).

architecture.md §10 names a specific hazard: a client-initiated drop can
surface as async cancellation rather than WebSocketDisconnect. v01.04 found
this the hard way -- asyncio.shield() deadlocked here; anyio.CancelScope
(shield=True) is what actually protects server/main.py's finally-block
seat-release write. Every existing disconnect test (test_ws_connect.py) only
exercises the graceful-close path. This test targets the primitive itself, so
a future regression -- reverting to asyncio.shield(), or dropping the shield
entirely -- fails fast and deterministically, with no real socket involved.
"""

from __future__ import annotations

import anyio
import pytest


async def test_shielded_cleanup_survives_the_cancellation_that_triggered_it() -> None:
    """Mirrors server/main.py's finally block: a handler blocked on a
    long-running operation (receive_text(), here anyio.sleep) is cancelled --
    simulating a client-initiated drop -- and its finally block's shielded
    cleanup (simulating the seat-release write) must still complete."""
    cleanup_completed = False

    async def slow_cleanup() -> None:
        nonlocal cleanup_completed
        with anyio.CancelScope(shield=True):
            await anyio.sleep(0.05)
            cleanup_completed = True

    async def handler() -> None:
        try:
            await anyio.sleep(10)  # stands in for a blocking receive_text()
        finally:
            await slow_cleanup()

    async with anyio.create_task_group() as tg:
        tg.start_soon(handler)
        await anyio.sleep(0.01)  # let the handler reach its blocking await
        tg.cancel_scope.cancel()  # simulates the client-initiated drop

    assert cleanup_completed


async def test_unshielded_cleanup_is_cut_off_by_the_same_cancellation() -> None:
    """The control case: without the shield, the same cancellation that
    triggers cleanup also cuts the cleanup itself short -- proving the shield
    in the test above is actually doing something, not a no-op given how
    anyio's cancel scopes propagate."""
    cleanup_completed = False

    async def unshielded_cleanup() -> None:
        nonlocal cleanup_completed
        await anyio.sleep(0.05)
        cleanup_completed = True

    async def handler() -> None:
        try:
            await anyio.sleep(10)
        finally:
            await unshielded_cleanup()

    async with anyio.create_task_group() as tg:
        tg.start_soon(handler)
        await anyio.sleep(0.01)
        tg.cancel_scope.cancel()

    assert not cleanup_completed


async def test_asyncio_shield_deadlocks_where_anyio_cancel_scope_does_not() -> None:
    """The exact regression v01.04 found: asyncio.shield() does not protect a
    coroutine from a cancellation delivered via an anyio cancel scope (as
    opposed to a raw asyncio.Task.cancel()) -- it still gets cancelled, unlike
    anyio.CancelScope(shield=True) above. This is *why* the fix had to be
    anyio's own primitive, not asyncio's."""
    import asyncio

    cleanup_completed = False

    async def slow_cleanup() -> None:
        nonlocal cleanup_completed
        await asyncio.sleep(0.05)
        cleanup_completed = True

    async def handler() -> None:
        try:
            await anyio.sleep(10)
        finally:
            with pytest.raises(anyio.get_cancelled_exc_class()):
                await asyncio.shield(slow_cleanup())

    async with anyio.create_task_group() as tg:
        tg.start_soon(handler)
        await anyio.sleep(0.01)
        tg.cancel_scope.cancel()

    assert not cleanup_completed
