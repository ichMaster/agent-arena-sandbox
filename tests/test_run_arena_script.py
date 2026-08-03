"""Static checks for scripts/run_arena.sh (ARENA-OPUS-033, v04 release gate).

The script launches real agent processes against a live server and makes real (paid) model
calls when actually run -- so this test never executes it. It only asserts on the script's
source: valid bash, references the right endpoints/profiles, and preserves the wait-for-agent-1
ordering that makes seat assignment deterministic. No server started, no paid call.
"""

import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_arena.sh"


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file()
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "run_arena.sh must be executable"


def test_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr


def test_script_references_both_profiles_and_the_lobby_endpoint() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "profiles/aggressive.yml" in text
    assert "profiles/cautious.yml" in text
    assert "/api/v1/lobby/match" in text
    assert "agent/agent.py" in text


def test_script_waits_for_agent_one_before_launching_agent_two() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    wait_idx = text.index("joined as")
    second_launch_idx = text.index("launching agent 2")
    assert wait_idx < second_launch_idx, "must wait for agent 1's join before starting agent 2"


def test_script_tells_the_human_to_observe_not_join() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Observe" in text
    assert "NOT Join" in text or "not Join" in text or "never Join" in text


def test_script_has_cleanup_trap() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "trap cleanup" in text
    assert "INT" in text and "TERM" in text and "EXIT" in text


def test_script_uses_set_euo_pipefail() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
