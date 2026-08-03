"""Reset — deleting what a run created, from the run's own log.

Destructive, so most of these are refusals and guarantees. The mechanism itself is the
interesting part: nothing here names a directory, because the log names the commits and
git names the files. That is what makes it work unchanged in another product.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import reset as reset_mod


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message],
        cwd=repo, check=True,
    )
    return subprocess.run(
        ["git", "log", "-1", "--format=%h"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo with pre-existing source, then a 'generated' commit recorded in a log.

    Deliberately uses names from NO real product -- `widget/`, `thing.txt` -- because a
    reset that only works on server/ and games/ is not portable.
    """
    root = tmp_path / "repo"
    (root / "codegen" / "runs" / "run-20260803-142012").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "pre_existing.py").write_text("# predates the run\n")
    (root / "README.md").write_text("# readme\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    _commit(root, "before the run")

    # The run creates files in directories this tool has never heard of, and MODIFIES
    # one that already existed.
    (root / "widget").mkdir()
    (root / "widget" / "core.py").write_text("# generated\n")
    (root / "widget" / "helper.py").write_text("# generated\n")
    (root / "thing.txt").write_text("generated\n")
    (root / "src" / "pre_existing.py").write_text("# predates the run, now edited\n")
    sha = _commit(root, "the generated commit")
    subprocess.run(["git", "tag", "v01.01.00"], cwd=root, check=True)

    log = root / "codegen" / "runs" / "run-20260803-142012" / "events.jsonl"
    log.write_text(
        "\n".join(
            json.dumps(e) for e in [
                {"v": 1, "ts": "2026-08-03T14:20:12.000Z", "run_id": "run-20260803-142012",
                 "type": "issue.commit", "emitter": "skill:execute-issues",
                 "scope": {}, "data": {"sha": sha, "files": ["widget/core.py"]}},
                {"v": 1, "ts": "2026-08-03T14:30:00.000Z", "run_id": "run-20260803-142012",
                 "type": "release.tagged", "emitter": "skill:release-version",
                 "scope": {}, "data": {"tag": "v01.01.00"}},
            ]
        ) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(reset_mod, "REPO", root)
    return root


def _plan(repo: Path) -> reset_mod.Plan:
    plan = reset_mod.build_plan(repo / "codegen" / "runs", force=True)
    return plan


# ── the mechanism ────────────────────────────────────────────────────────────


def test_it_deletes_what_the_log_claims_without_knowing_any_directory_name(repo: Path) -> None:
    """`widget/` appears nowhere in the source -- git and the log supply it."""
    plan = _plan(repo)
    assert set(plan.manifest.files) == {"widget/core.py", "widget/helper.py", "thing.txt"}
    reset_mod.apply(plan, repo=repo)
    assert not (repo / "widget").exists()
    assert not (repo / "thing.txt").exists()


def test_a_modified_file_is_not_deleted(repo: Path) -> None:
    """The commit touched src/pre_existing.py; it predates the run and must survive.

    This is why the file list comes from `git show --diff-filter=A` rather than from the
    log's own `files` field, which does not distinguish added from modified.
    """
    reset_mod.apply(_plan(repo), repo=repo)
    assert (repo / "src" / "pre_existing.py").is_file()


def test_no_directory_name_is_hardcoded_in_the_module() -> None:
    """Portability, asserted: the next product has different directories."""
    source = Path(reset_mod.__file__).read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]  # skip the module docstring's examples
    for name in ("server", "games", "agent", "web", "profiles", "scripts"):
        assert f'"{name}"' not in body, f"{name} is hardcoded -- breaks in another product"


def test_tags_the_run_cut_are_deleted(repo: Path) -> None:
    """Left in place, they make the next run skip every version and look successful."""
    reset_mod.apply(_plan(repo), repo=repo)
    tags = subprocess.run(
        ["git", "tag"], cwd=repo, capture_output=True, text=True
    ).stdout.split()
    assert "v01.01.00" not in tags


# ── the three things it must never touch ─────────────────────────────────────


def test_the_run_logs_survive(repo: Path) -> None:
    """The logs ARE the product. Also: deleting them would destroy the manifest."""
    reset_mod.apply(_plan(repo), repo=repo)
    assert (repo / "codegen" / "runs" / "run-20260803-142012" / "events.jsonl").is_file()


def test_codegen_is_protected_even_against_a_lying_log(repo: Path) -> None:
    plan = _plan(repo)
    plan.manifest.files.append("codegen/tracker/emit.py")
    with pytest.raises(RuntimeError, match="protected"):
        reset_mod.apply(plan, repo=repo)


def test_it_never_invokes_gh() -> None:
    """GitHub issues carry the issue-id counter; wiping them restarts numbering."""
    source = Path(reset_mod.__file__).read_text(encoding="utf-8")
    assert '"gh"' not in source and "gh issue" not in source.replace("`gh`", "")


def test_unclaimed_files_are_reported_but_left_alone(repo: Path) -> None:
    """An unexplained deletion is worse than an unexplained leftover."""
    (repo / "stray").mkdir()
    (repo / "stray" / "orphan.py").write_text("# nobody claims me\n")
    _commit(repo, "a file no run recorded")

    plan = _plan(repo)
    assert "stray/orphan.py" in plan.manifest.unaccounted
    assert "stray/orphan.py" not in plan.manifest.files
    reset_mod.apply(plan, repo=repo)
    assert (repo / "stray" / "orphan.py").is_file()
    assert "LEFT ALONE" in plan.render()


# ── refusals ─────────────────────────────────────────────────────────────────


def test_a_dirty_tree_is_refused(repo: Path) -> None:
    (repo / "widget" / "uncommitted.py").write_text("work in progress\n")
    plan = reset_mod.build_plan(repo / "codegen" / "runs")
    assert any("dirty" in b for b in plan.blockers)
    with pytest.raises(RuntimeError):
        reset_mod.apply(plan, repo=repo)


def test_dry_run_deletes_nothing(repo: Path) -> None:
    reset_mod.main(["--runs", str(repo / "codegen" / "runs"), "--force"])
    assert (repo / "widget" / "core.py").is_file()


def test_a_commit_in_the_log_but_absent_from_git_is_skipped_not_fatal(repo: Path) -> None:
    log = repo / "codegen" / "runs" / "run-20260803-142012" / "events.jsonl"
    ghost = {"v": 1, "ts": "2026-08-03T14:40:00.000Z", "run_id": "run-20260803-142012",
             "type": "issue.commit", "emitter": "skill:execute-issues",
             "scope": {}, "data": {"sha": "deadbee", "files": []}}
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ghost) + "\n")
    plan = _plan(repo)
    assert "deadbee" in plan.manifest.missing_shas
    assert plan.manifest.files, "a ghost commit must not stop the real ones"


def test_a_torn_log_line_does_not_stop_a_reset(repo: Path) -> None:
    log = repo / "codegen" / "runs" / "run-20260803-142012" / "events.jsonl"
    with log.open("a", encoding="utf-8") as fh:
        fh.write('{"v":1,"ts":"2026-08-03T14:4')
    assert _plan(repo).manifest.files


def test_no_logs_means_no_manifest_and_no_deletion(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reset_mod, "REPO", tmp_path)
    plan = reset_mod.build_plan(tmp_path / "nope", force=True)
    assert plan.manifest.runs == [] and plan.manifest.files == []
    assert reset_mod.main(["--runs", str(tmp_path / "nope"), "--force", "--apply"]) == 1
