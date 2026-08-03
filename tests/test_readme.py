"""Doc-smoke test for README.md (ARENA-OPUS-037, v05 release gate). Never executes any live/paid
command -- only reads the README text and confirms the files/commands it references actually exist.
"""

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_references_the_real_entry_points() -> None:
    for token in (
        "uvicorn server.main:app",
        "/ui",
        "agent/agent.py",
        "profiles/aggressive.yml",
        "profiles/cautious.yml",
        "scripts/run_arena.sh",
        "ANTHROPIC_API_KEY",
        "pytest",
    ):
        assert token in README, f"README is missing a reference to {token!r}"


def test_referenced_files_actually_exist() -> None:
    for relative_path in (
        "agent/agent.py",
        "scripts/run_arena.sh",
        "profiles/aggressive.yml",
        "profiles/cautious.yml",
        ".env.example",
    ):
        assert (REPO_ROOT / relative_path).is_file(), f"{relative_path} referenced but missing"


def test_all_three_run_modes_are_documented() -> None:
    assert "Human vs. agent" in README
    assert "Agent vs. agent" in README
    assert "Observe" in README
    # Observe must be told apart from Join -- Join claims a player seat (web_ui_spec §5).
    assert "not Join" in README or "never Join" in README


def test_no_stale_vendor_names() -> None:
    for stale in ("Gemini", "GPT-4", "GPT-3"):
        assert stale not in README, f"README still names the stale vendor {stale!r}"


def test_uvicorn_is_a_declared_dependency() -> None:
    """The README's first command is `uvicorn server.main:app` (code review #1) -- a clean install
    must actually provide it; plain fastapi doesn't pull it in transitively."""
    manifest = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = manifest["project"]["dependencies"]
    assert any(dep.startswith("uvicorn") for dep in dependencies), (
        "pyproject.toml must declare uvicorn -- the README's `uvicorn server.main:app` needs it"
    )


def test_env_example_is_tracked_not_gitignored() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    lines = [line.strip() for line in gitignore.splitlines()]
    assert ".env" in lines  # the real secret file IS ignored
    assert ".env.example" not in lines  # the template is NOT
    assert (REPO_ROOT / ".env.example").is_file()
