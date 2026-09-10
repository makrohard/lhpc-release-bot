"""Bringing a released patch back to a `dev` that has moved on.

`dev` starts every cycle by bumping the version, so a patch released from `main` ALWAYS collides
with it on the version scalars and the changelog heading. That collision is the only one this
bot resolves. Everything else the patch changed has to survive, or a hotfix can be released and
then quietly un-made on the integration branch.

Real git, real conflicts, real temporary history.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bot.cli import _resolve_version_conflicts


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def write(repo: Path, name: str, text: str):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def pyproject(version: str, dep: str) -> str:
    return f'[project]\nname = "lhpc"\nversion = "{version}"\ndependencies = ["{dep}"]\n'


def changelog(*sections: str) -> str:
    return "# Changelog\n\n" + "\n".join(sections)


@pytest.fixture
def repo(tmp_path):
    """A controller whose `dev` has moved on while a patch was released from `main`.

    main:  0.3.6 -> the released patch 0.3.7, which ALSO raises a dependency floor
    dev:   0.3.6 -> 0.4.0 with its own unreleased section
    """
    r = tmp_path / "repo"
    r.mkdir()
    git("init", "-q", "-b", "main", ".", cwd=r)
    git("config", "user.email", "t@example.invalid", cwd=r)
    git("config", "user.name", "t", cwd=r)

    write(r, "pyproject.toml", pyproject("0.3.6", "example>=1"))
    write(r, "lhpc/version.py", '__version__ = "0.3.6"\n')
    write(r, "CHANGELOG.md", changelog("## 0.3.6\n\n- the released one\n"))
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.3.6", cwd=r)

    git("checkout", "-q", "-b", "dev", cwd=r)
    write(r, "pyproject.toml", pyproject("0.4.0", "example>=1"))
    write(r, "lhpc/version.py", '__version__ = "0.4.0"\n')
    write(r, "CHANGELOG.md", changelog("## 0.4.0\n\n- the next feature\n",
                                       "## 0.3.6\n\n- the released one\n"))
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.4.0 cycle", cwd=r)

    git("checkout", "-q", "main", cwd=r)
    write(r, "pyproject.toml", pyproject("0.3.7", "example>=2"))     # the hotfix's own change
    write(r, "lhpc/version.py", '__version__ = "0.3.7"\n')
    write(r, "CHANGELOG.md", changelog("## 0.3.7\n\n- a hotfix that also raises a floor\n",
                                       "## 0.3.6\n\n- the released one\n"))
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.3.7", cwd=r)
    candidate = git("rev-parse", "HEAD", cwd=r)

    # `origin/dev` is what the resolver reads; a local ref of that name is enough.
    git("update-ref", "refs/remotes/origin/dev", "dev", cwd=r)
    git("checkout", "-q", "-B", "integrate/0.3.7", "dev", cwd=r)
    subprocess.run(["git", "cherry-pick", "-n", candidate], cwd=r, capture_output=True,
                   check=False)
    return r, candidate


def test_the_hotfix_survives_the_version_resolution(repo):
    """The counterexample this exists for: writing dev's whole `pyproject.toml` over the
    candidate's silently reverted the dependency the hotfix raised, and produced a branch that
    looked cleanly resolved."""
    r, candidate = repo
    _resolve_version_conflicts(r, "0.3.7", candidate)
    text = (r / "pyproject.toml").read_text()
    assert "<<<<<<<" not in text, "a conflicted file was left for the commit"
    assert 'example>=2' in text, "the hotfix's own change was reverted"
    assert 'example>=1' not in text
    assert 'version = "0.4.0"' in text, "dev keeps its own version scalar"
    assert '__version__ = "0.4.0"' in (r / "lhpc" / "version.py").read_text()


def test_devs_unreleased_section_stays_first_and_the_patch_goes_under_it(repo):
    r, candidate = repo
    _resolve_version_conflicts(r, "0.3.7", candidate)
    log = (r / "CHANGELOG.md").read_text()
    assert "<<<<<<<" not in log
    assert log.index("## 0.4.0") < log.index("## 0.3.7") < log.index("## 0.3.6")
    assert "- the next feature" in log
    assert "- a hotfix that also raises a floor" in log


def test_it_reports_exactly_what_it_resolved(repo):
    r, candidate = repo
    resolved = _resolve_version_conflicts(r, "0.3.7", candidate)
    assert any("pyproject.toml" in line and "0.4.0" in line for line in resolved)
    assert any("CHANGELOG.md" in line for line in resolved)


def test_nothing_outside_those_three_files_is_touched(repo):
    r, candidate = repo
    write(r, "docs/note.md", "the patch also wrote this\n")
    git("add", "-A", cwd=r)
    _resolve_version_conflicts(r, "0.3.7", candidate)
    assert (r / "docs" / "note.md").read_text() == "the patch also wrote this\n"


# --- the other direction: what DEV changed must survive too --------------------------------
# The previous resolver rebuilt each file from the candidate's own content. That kept the
# hotfix's change (above) and silently dropped dev's, which is the same defect facing the other
# way. A merge has to survive both, and has to still refuse when the remainder really collides.


@pytest.fixture
def repo_dev_also_changed(tmp_path):
    """As `repo`, but `dev` has substantive changes of its own in the same two files."""
    r = tmp_path / "repo2"
    r.mkdir()
    git("init", "-q", "-b", "main", ".", cwd=r)
    git("config", "user.email", "t@example.invalid", cwd=r)
    git("config", "user.name", "t", cwd=r)
    write(r, "pyproject.toml", pyproject("0.3.6", "example>=1"))
    write(r, "lhpc/version.py", '__version__ = "0.3.6"\n')
    write(r, "CHANGELOG.md", changelog("## 0.3.6\n\n- the released one\n"))
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.3.6", cwd=r)

    git("checkout", "-q", "-b", "dev", cwd=r)
    write(r, "pyproject.toml",
          '[project]\nname = "lhpc"\nversion = "0.4.0"\n'
          'dependencies = ["example>=1", "devonly>=3"]\n')          # dev's own dependency
    write(r, "lhpc/version.py", '__version__ = "0.4.0"\nBUILD_CHANNEL = "dev"\n')
    write(r, "CHANGELOG.md", changelog("## 0.4.0\n\n- the next feature\n",
                                       "## 0.3.6\n\n- the released one\n"))
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.4.0 cycle", cwd=r)

    git("checkout", "-q", "main", cwd=r)
    write(r, "pyproject.toml", pyproject("0.3.7", "example>=1"))
    write(r, "lhpc/version.py", '__version__ = "0.3.7"\n')
    write(r, "CHANGELOG.md", changelog("## 0.3.7\n\n- a hotfix\n",
                                       "## 0.3.6\n\n- the released one\n"))
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.3.7", cwd=r)
    candidate = git("rev-parse", "HEAD", cwd=r)

    git("update-ref", "refs/remotes/origin/dev", "dev", cwd=r)
    git("checkout", "-q", "-B", "integrate/0.3.7", "dev", cwd=r)
    subprocess.run(["git", "cherry-pick", "-n", candidate], cwd=r, capture_output=True,
                   check=False)
    return r, candidate


def test_devs_own_changes_survive_the_version_resolution(repo_dev_also_changed):
    """Reproduced by the auditor against real git: dev's dependency and its extra version-module
    line were both discarded, and the pull request said everything else was unchanged."""
    r, candidate = repo_dev_also_changed
    _resolve_version_conflicts(r, "0.3.7", candidate)
    text = (r / "pyproject.toml").read_text()
    assert "<<<<<<<" not in text
    assert "devonly>=3" in text, "dev's own dependency was dropped"
    assert 'version = "0.4.0"' in text
    module = (r / "lhpc" / "version.py").read_text()
    assert 'BUILD_CHANNEL = "dev"' in module, "dev's own line was dropped"
    assert '__version__ = "0.4.0"' in module


def test_a_real_collision_is_left_for_a_person(tmp_path):
    """When both sides changed the SAME line, there is no answer the bot may pick. The file must
    stay conflicted and unstaged, which is what routes it into the pull request."""
    r = tmp_path / "repo3"
    r.mkdir()
    git("init", "-q", "-b", "main", ".", cwd=r)
    git("config", "user.email", "t@example.invalid", cwd=r)
    git("config", "user.name", "t", cwd=r)
    write(r, "pyproject.toml", pyproject("0.3.6", "example>=1"))
    write(r, "lhpc/version.py", '__version__ = "0.3.6"\n')
    write(r, "CHANGELOG.md", changelog("## 0.3.6\n\n- x\n"))
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.3.6", cwd=r)

    git("checkout", "-q", "-b", "dev", cwd=r)
    write(r, "pyproject.toml", pyproject("0.4.0", "example>=9"))     # dev raised it to 9
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "dev floor", cwd=r)

    git("checkout", "-q", "main", cwd=r)
    write(r, "pyproject.toml", pyproject("0.3.7", "example>=2"))     # the patch raised it to 2
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.3.7", cwd=r)
    candidate = git("rev-parse", "HEAD", cwd=r)

    git("update-ref", "refs/remotes/origin/dev", "dev", cwd=r)
    git("checkout", "-q", "-B", "integrate/0.3.7", "dev", cwd=r)
    subprocess.run(["git", "cherry-pick", "-n", candidate], cwd=r, capture_output=True,
                   check=False)

    resolved = _resolve_version_conflicts(r, "0.3.7", candidate)
    assert not any("pyproject.toml" in line for line in resolved)
    # The exact signal `stage_integrate` routes on: still UNMERGED in the index.
    unmerged = [ln[3:] for ln in git("status", "--porcelain", cwd=r).splitlines()
                if ln.startswith(("UU ", "AA ", "DU ", "UD "))]
    assert "pyproject.toml" in unmerged, "a genuine collision was resolved away"


# ------------------------------------- R7-3: the ordinary case, where `dev` has NOT moved at all


@pytest.fixture
def repo_dev_not_moved(tmp_path):
    """The real timeline that produced PR #4, and the one no fixture had.

    main: 0.3.14 -> the released patch 0.3.15
    dev:  0.3.14, unchanged — nobody has opened a new cycle since the last release
    """
    r = tmp_path / "repo"
    r.mkdir()
    git("init", "-q", "-b", "main", ".", cwd=r)
    git("config", "user.email", "t@example.invalid", cwd=r)
    git("config", "user.name", "t", cwd=r)

    write(r, "pyproject.toml", pyproject("0.3.14", "example>=1"))
    write(r, "lhpc/version.py", '__version__ = "0.3.14"\n')
    write(r, "CHANGELOG.md", changelog("## 0.3.14\n\n- the previous release\n"))
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.3.14", cwd=r)

    # `dev` exists and carries unrelated work, but never touched the version or the changelog.
    git("checkout", "-q", "-b", "dev", cwd=r)
    write(r, "docs/backlog.md", "a deferral somebody wrote down\n")
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "docs only", cwd=r)

    git("checkout", "-q", "main", cwd=r)
    write(r, "pyproject.toml", pyproject("0.3.15", "example>=1"))
    write(r, "lhpc/version.py", '__version__ = "0.3.15"\n')
    write(r, "CHANGELOG.md", changelog("## 0.3.15\n\n- kiss + bridge\n",
                                       "## 0.3.14\n\n- the previous release\n"))
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.3.15", cwd=r)
    candidate = git("rev-parse", "HEAD", cwd=r)

    git("update-ref", "refs/remotes/origin/dev", "dev", cwd=r)
    git("checkout", "-q", "-B", "integrate/0.3.15", "dev", cwd=r)
    subprocess.run(["git", "cherry-pick", "-n", candidate], cwd=r, capture_output=True,
                   check=False)
    return r, candidate


def test_a_stale_dev_gets_the_released_version_and_an_ordered_changelog(repo_dev_not_moved):
    """R7-3 end to end, on the timeline that shipped the defect.

    `dev` never opened a cycle, so keeping "dev's own scalar" kept the OLD one: the PR carried
    `0.3.14` scalars with a `0.3.15` section, out of order, and the controller's own consistency
    gate — newest changelog section must equal the version scalar — accepted that and would have
    rejected an ordering-only fix. Both halves have to move together.
    """
    from bot import cli
    r, candidate = repo_dev_not_moved
    cli._resolve_version_conflicts(r, "0.3.15", candidate)

    assert 'version = "0.3.15"' in (r / "pyproject.toml").read_text(), \
        "a dev that never opened a cycle must take the released version"
    assert '__version__ = "0.3.15"' in (r / "lhpc" / "version.py").read_text()

    log = (r / "CHANGELOG.md").read_text()
    order = [line[3:].strip() for line in log.splitlines() if line.startswith("## ")]
    assert order == ["0.3.15", "0.3.14"], f"out of order: {order}"

    # The scalar and the newest section agree, which is what the controller's gate requires.
    assert order[0] == "0.3.15"
    assert (r / "docs" / "backlog.md").exists(), "dev's unrelated work must survive"


def test_a_real_dev_cycle_is_still_preserved(repo):
    """The control, restated at this level: 0.4.0 on dev is a decision, not a stale scalar."""
    from bot import cli
    r, candidate = repo
    cli._resolve_version_conflicts(r, "0.3.7", candidate)
    assert 'version = "0.4.0"' in (r / "pyproject.toml").read_text()
    assert '__version__ = "0.4.0"' in (r / "lhpc" / "version.py").read_text()


@pytest.fixture
def repo_dev_behind(tmp_path):
    """`dev` is BEHIND: the previous merge-back PR has not been merged yet.

    This is the ordinary state, not an exotic one — the bot opens a PR for a person to merge, so
    between releases `dev` sits at the version before last while `main` moves on.

    main: 0.3.14 -> 0.3.15 -> the released patch 0.3.16
    dev:  0.3.14, still waiting for the 0.3.15 PR
    """
    r = tmp_path / "repo"
    r.mkdir()
    git("init", "-q", "-b", "main", ".", cwd=r)
    git("config", "user.email", "t@example.invalid", cwd=r)
    git("config", "user.name", "t", cwd=r)

    write(r, "pyproject.toml", pyproject("0.3.14", "example>=1"))
    write(r, "lhpc/version.py", '__version__ = "0.3.14"\n')
    write(r, "CHANGELOG.md", changelog("## 0.3.14\n\n- two releases ago\n"))
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.3.14", cwd=r)

    git("checkout", "-q", "-b", "dev", cwd=r)          # dev branches here and stays
    git("checkout", "-q", "main", cwd=r)

    write(r, "pyproject.toml", pyproject("0.3.15", "example>=1"))
    write(r, "lhpc/version.py", '__version__ = "0.3.15"\n')
    write(r, "CHANGELOG.md", changelog("## 0.3.15\n\n- last one\n",
                                       "## 0.3.14\n\n- two releases ago\n"))
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.3.15", cwd=r)

    write(r, "pyproject.toml", pyproject("0.3.16", "example>=1"))
    write(r, "lhpc/version.py", '__version__ = "0.3.16"\n')
    write(r, "CHANGELOG.md", changelog("## 0.3.16\n\n- this one\n",
                                       "## 0.3.15\n\n- last one\n",
                                       "## 0.3.14\n\n- two releases ago\n"))
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.3.16", cwd=r)
    candidate = git("rev-parse", "HEAD", cwd=r)

    git("update-ref", "refs/remotes/origin/dev", "dev", cwd=r)
    git("checkout", "-q", "-B", "integrate/0.3.16", "dev", cwd=r)
    subprocess.run(["git", "cherry-pick", "-n", candidate], cwd=r, capture_output=True,
                   check=False)
    return r, candidate


def test_a_dev_that_is_behind_is_not_mistaken_for_a_newer_cycle(repo_dev_behind):
    """The trap in comparing `dev` against the BASE instead of the released version.

    Here `dev` (0.3.14) differs from the base (0.3.15) — but because it is BEHIND, not ahead.
    Reading that difference as "dev opened its own cycle" left the scalars at 0.3.14 under a
    0.3.16 changelog section, which is the inconsistency the whole resolution exists to remove,
    and reported it as "dev's own newer cycle kept". Comparing against the released version is
    right in all three cases: ahead, level, and behind.
    """
    from bot import cli
    r, candidate = repo_dev_behind
    resolved = cli._resolve_version_conflicts(r, "0.3.16", candidate)

    assert 'version = "0.3.16"' in (r / "pyproject.toml").read_text(), \
        "a dev that is BEHIND must take the released version, not keep its stale one"
    assert '__version__ = "0.3.16"' in (r / "lhpc" / "version.py").read_text()
    order = [line[3:].strip() for line in (r / "CHANGELOG.md").read_text().splitlines()
             if line.startswith("## ")]
    assert order[0] == "0.3.16", f"newest section must match the scalar: {order}"
    assert not any("newer cycle kept" in line for line in resolved), \
        f"and it must not be reported as dev's own cycle: {resolved}"


def _dev_at(r, candidate, scalar):
    """Put `scalar` on `dev`'s two version files and rebuild the integration branch."""
    git("checkout", "-qf", "dev", cwd=r)            # drop the fixture's staged cherry-pick
    for path, old, sub in (("pyproject.toml", 'version = "0.3.14"', 'version = "%s"'),
                           ("lhpc/version.py", '__version__ = "0.3.14"', '__version__ = "%s"')):
        f = r / path
        f.write_text(f.read_text().replace(old, sub % scalar))
    git("commit", "-aqm", f"dev at {scalar}", cwd=r)
    git("update-ref", "refs/remotes/origin/dev", "dev", cwd=r)
    git("checkout", "-q", "-B", "integrate/0.3.15", "dev", cwd=r)
    subprocess.run(["git", "cherry-pick", "-n", candidate], cwd=r, capture_output=True,
                   check=False)


def test_a_prerelease_scalar_on_dev_is_a_newer_cycle_and_is_kept(repo_dev_not_moved):
    """`_resolve_version_conflicts` runs AFTER the release is pushed, so a `dev` version it cannot
    parse used to raise `ValueError` out of `version_tuple` and leave the release standing with no
    integration branch at all. The first fix caught the exception and advanced — which does not
    raise, but silently downgrades a cycle somebody deliberately opened.

    `0.4.0rc1` IS newer than `0.3.15`. Ordering by the numbers in front says so, and dev keeps it.
    """
    from bot import cli
    r, candidate = repo_dev_not_moved
    _dev_at(r, candidate, "0.4.0rc1")

    resolved = cli._resolve_version_conflicts(r, "0.3.15", candidate)

    assert 'version = "0.4.0rc1"' in (r / "pyproject.toml").read_text(), \
        "a pre-release marker is a newer cycle, not an unreadable string to be overwritten"
    assert '__version__ = "0.4.0rc1"' in (r / "lhpc" / "version.py").read_text()
    assert any("newer cycle kept" in line for line in resolved), resolved


def test_a_scalar_with_no_version_in_it_advances_and_says_what_it_replaced(repo_dev_not_moved):
    """The genuine unparsable case. Nothing can be inferred from it, so the released patch wins —
    but it must not raise, and the PR must show a person the value that was replaced."""
    from bot import cli
    r, candidate = repo_dev_not_moved
    _dev_at(r, candidate, "unreleased")

    resolved = cli._resolve_version_conflicts(r, "0.3.15", candidate)

    assert 'version = "0.3.15"' in (r / "pyproject.toml").read_text(), "it must resolve, not raise"
    assert any("unreleased" in line for line in resolved), \
        f"the value it replaced must be visible to whoever reviews the PR: {resolved}"


def test_the_resolution_note_says_nothing_was_inserted_when_nothing_was(repo_dev_not_moved):
    """`merge_back` is idempotent: if `dev` already carries a section for the released version it
    keeps ITS text and inserts nothing. The note said "inserted in version order" regardless, and
    `stage_integrate` prints these lines verbatim into the pull-request body — so a reviewer was
    told the released notes had been placed when dev's, possibly different, text was kept and the
    cherry-picked one discarded. A resolution note has to report what happened."""
    from bot import cli
    r, candidate = repo_dev_not_moved
    git("checkout", "-qf", "dev", cwd=r)
    log = r / "CHANGELOG.md"
    log.write_text(log.read_text().replace(
        "## 0.3.14\n", "## 0.3.15\n\n- dev wrote its own words for this one\n\n## 0.3.14\n", 1))
    git("commit", "-aqm", "dev already has a 0.3.15 section", cwd=r)
    git("update-ref", "refs/remotes/origin/dev", "dev", cwd=r)
    git("checkout", "-q", "-B", "integrate/0.3.15", "dev", cwd=r)
    subprocess.run(["git", "cherry-pick", "-n", candidate], cwd=r, capture_output=True,
                   check=False)

    resolved = cli._resolve_version_conflicts(r, "0.3.15", candidate)

    note = next(line for line in resolved if line.startswith("CHANGELOG.md"))
    assert "inserted" not in note, f"nothing was inserted, so the note must not claim it: {note}"
    assert "already has" in note and "NOT merged" in note, note
    assert "dev wrote its own words" in log.read_text(), "dev's own section must be what survives"
