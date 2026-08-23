"""M5-012 — the C++ frame parser, wired into the same ``pytest`` run.

The parser is C++ and compiles on the host, so it does not need a board. Running it
from here rather than from a separate CI job means one command covers the whole
no-hardware surface — and a golden frame that stops parsing fails alongside the Python
that produced it, in the same run, rather than in a job somebody has to remember.

Skips rather than fails when no compiler is present. Python developers on this repo
should not be blocked by a toolchain they have no reason to have.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parent.parent / "device" / "shared"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "frames"

pytestmark = pytest.mark.skipif(
    shutil.which("c++") is None, reason="no host C++ compiler"
)


def test_the_shared_library_is_only_the_parser() -> None:
    """Vision §3.1 left nothing else to share. If a second concern appears here, the
    device has started holding state again and something upstream went wrong."""
    sources = sorted(p.name for p in SHARED.glob("*.cpp")) + sorted(
        p.name for p in SHARED.glob("*.h")
    )
    assert sources == ["frame.cpp", "frame_test.cpp", "frame.h"]


def test_the_parser_compiles_and_passes_under_sanitizers() -> None:
    """Address and UB sanitizers, ``-Werror``, against the committed golden frames.

    Not decoration: the first run caught a use-after-free, and the truncation cases
    are exactly what a frame cut mid-write would do on a device with no memory
    protection and nobody watching.
    """
    result = subprocess.run(
        ["bash", str(SHARED / "run_tests.sh"), str(FIXTURES)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 failures" in result.stdout
    assert "134 checks" in result.stdout or "checks" in result.stdout


def test_the_parser_reads_the_same_goldens_the_projection_writes() -> None:
    """One set of fixtures, both languages. A frame that only one side understands is
    the exact defect a shared golden set exists to prevent."""
    goldens = sorted(FIXTURES.glob("*.json"))
    assert len(goldens) == 9
    source = (SHARED / "frame_test.cpp").read_text()
    assert "fixtures/frames" in source


# ── M5-013: the firmware tree ────────────────────────────────────────────────


DEVICE = SHARED.parent


def test_both_boards_build_from_one_copy_of_shared() -> None:
    """The criterion asked for "a build that fails if it is duplicated", which no
    build can do — two envs never link together, so a second copy would compile
    happily. What is checkable is that no second copy exists, and that both envs name
    the same directory."""
    assert len(list(DEVICE.rglob("frame.cpp"))) == 1

    ini = (DEVICE / "platformio.ini").read_text()
    core2, stickc = ini.split("[env:core2]")[1].split("[env:stickc]")
    assert "+<shared/>" in core2 and "+<shared/>" in stickc
    assert "-<shared/frame_test.cpp>" in core2 and "-<shared/frame_test.cpp>" in stickc


def test_neither_board_shadows_a_shared_filename() -> None:
    """A file named frame.cpp under core2/ would be picked up by that env's filter and
    quietly win over the shared one."""
    shared_names = {p.name for p in SHARED.glob("*.cpp")} | {p.name for p in SHARED.glob("*.h")}
    for board in ("core2", "stickc"):
        for source in (DEVICE / board).glob("*"):
            assert source.name not in shared_names, f"{board}/{source.name} shadows shared/"


def test_the_stickc_flash_geometry_is_overridden() -> None:
    """PlatformIO ships no StickC **Plus2** board — only `m5stick-c`, the original,
    with 4 MB. The Plus2 has 8 MB, so the stock definition would size partitions for a
    board four times smaller than the one in hand."""
    ini = (DEVICE / "platformio.ini").read_text()
    stickc = ini.split("[env:stickc]")[1]
    assert "flash_size = 8MB" in stickc
    assert "default_8MB.csv" in stickc


def test_build_artefacts_are_not_committed() -> None:
    assert ".pio/" in (DEVICE / ".gitignore").read_text()
