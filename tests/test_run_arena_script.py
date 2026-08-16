"""scripts/run_arena.sh -- ordered launch, Observe link, log tail, clean
shutdown (ARENA-106, roadmap.md §v04.02, architecture.md §5.2/§12).

Per the roadmap's own Tests note for this phase: "script checks -- valid
bash, references both real profiles and the lobby endpoint, waits for the
first agent before the second, and tells users to Observe (not Join)."
This never executes the script (that needs a running server and a live
Anthropic API call, both opt-in per CLAUDE.md) -- it's a syntax check plus
static content assertions, the same testing shape used for web/app.js.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_arena.sh"


def _script() -> str:
    return SCRIPT.read_text()


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111, "run_arena.sh must be executable (chmod +x)"


def test_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr


def test_references_both_real_profiles() -> None:
    text = _script()
    assert (SCRIPT.parent.parent / "profiles" / "aggressive.yml").is_file()
    assert (SCRIPT.parent.parent / "profiles" / "cautious.yml").is_file()
    assert "profiles/aggressive.yml" in text
    assert "profiles/cautious.yml" in text


def test_references_the_real_lobby_endpoint() -> None:
    text = _script()
    assert "/api/v1/lobby/match" in text


def test_health_checks_before_creating_a_match() -> None:
    text = _script()
    health_index = text.find("/api/v1/health")
    match_index = text.find("/api/v1/lobby/match")
    assert health_index != -1
    assert match_index != -1
    assert health_index < match_index


def test_waits_for_agent_one_before_launching_agent_two() -> None:
    """The core ordering guarantee (architecture.md §5.2): connection order
    is the only way seats end up distinct, since there is no --symbol flag."""
    text = _script()
    agent_one_launch = text.index('--profile "$PROFILE_1"')
    join_wait = text.index('grep -q "joined as"')
    agent_two_launch = text.index('--profile "$PROFILE_2"')
    assert agent_one_launch < join_wait < agent_two_launch


def test_join_wait_has_a_bounded_timeout_not_an_infinite_loop() -> None:
    text = _script()
    assert "JOIN_MAX_POLLS" in text
    assert "JOIN_TIMEOUT_S" in text
    wait_loop = text.split('until grep -q "joined as"')[1].split("\ndone")[0]
    assert "JOIN_MAX_POLLS" in wait_loop


def test_agent_one_dying_before_join_is_treated_as_a_failure() -> None:
    text = _script()
    wait_loop = text.split('until grep -q "joined as"')[1].split("\ndone")[0]
    assert "kill -0 \"$PID1\"" in wait_loop
    assert "exit 1" in wait_loop


def test_instructs_observe_not_join() -> None:
    text = _script()
    printed_instructions = text.split('echo "Both agents launched')[1]
    assert "Observe" in printed_instructions
    # "Join" only appears warning the user away from it, not as an instruction.
    assert "not Join" in printed_instructions or "never Join" in printed_instructions


def test_prefers_the_project_venv_python() -> None:
    """A bare `python3` on an unactivated shell's PATH has none of this
    project's dependencies installed -- agent/agent.py's own imports (httpx,
    websockets, ...) fail immediately. Demonstrated live during ARENA-106's
    own validation."""
    text = _script()
    assert ".venv/bin/python3" in text
    assert 'PYTHON="python3"' in text  # the fallback, when no venv exists


def test_cleanup_runs_at_most_once() -> None:
    """A signal fires the TERM/INT trap, then the script falling off its own
    end afterward fires the EXIT trap a second time -- without a guard,
    "Shutting down agents..." (and the kill/wait loops) would run twice."""
    text = _script()
    body = text.split("cleanup() {")[1].split("\n}")[0]
    assert "CLEANED_UP" in body


def test_tail_runs_in_background_not_as_the_final_foreground_command() -> None:
    """bash defers trap execution until a foreground pipeline returns, and
    `tail -f` never returns on its own -- a non-interactive stop (kill on
    just this script's PID, not the whole process group) would never reach
    the trap if tail -f were the last foreground command. Demonstrated live:
    a directly-killed script hung indefinitely before this fix."""
    text = _script()
    assert "tail -f \"$LOG1\" \"$LOG2\" &" in text
    assert 'wait "$TAIL_PID"' in text


def test_traps_both_interactive_and_signal_termination() -> None:
    text = _script()
    assert "trap cleanup EXIT INT TERM" in text
