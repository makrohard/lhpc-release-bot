"""The candidate is two commits, and the merge-back to a moved `dev` still brings all of it.

LHPC's house rules cap a commit at two changelog bullets unless it changes CHANGELOG.md alone,
inside its top section (the release section, written once). A candidate that put the moves and the
section in one commit failed CI for every release with more than two moves. Real git, real history.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bot import changelog as cl
from bot.cli import _resolve_version_conflicts, commit_candidate, release_commit


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def write(repo: Path, name: str, text: str):
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)


def pyproject(version: str, dep: str) -> str:
    return f'[project]\nname = "lhpc"\nversion = "{version}"\ndependencies = ["{dep}"]\n'


BULLETS = ["reticulum: a -> b", "lxmf: c -> d", "nomadnet: e -> f"]


@pytest.fixture
def released(tmp_path):
    """main at 0.3.6; the bot's edit of 0.3.7 (three moves, a raised floor) committed as the candidate."""
    r = tmp_path / "repo"
    r.mkdir()
    git("init", "-q", "-b", "main", ".", cwd=r)
    git("config", "user.email", "t@example.invalid", cwd=r)
    git("config", "user.name", "t", cwd=r)
    write(r, "pyproject.toml", pyproject("0.3.6", "example>=1"))
    write(r, "lhpc/version.py", '__version__ = "0.3.6"\n')
    write(r, "lhpc/data/manifest.example.toml", 'pin_commit = "a"\n')
    write(r, "CHANGELOG.md", "# Changelog\n\n## 0.3.6\n\n- the released one\n")
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "0.3.6", cwd=r)
    base = git("rev-parse", "HEAD", cwd=r)
    git("checkout", "-q", "-b", "dev", cwd=r)
    write(r, "notes.txt", "dev moved on\n")
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "an unrelated dev commit", cwd=r)
    git("update-ref", "refs/remotes/origin/dev", "dev", cwd=r)
    git("checkout", "-q", "-b", "pins/0.3.7-1", base, cwd=r)
    write(r, "lhpc/data/manifest.example.toml", 'pin_commit = "b"\n')
    write(r, "pyproject.toml", pyproject("0.3.7", "example>=2"))
    write(r, "lhpc/version.py", '__version__ = "0.3.7"\n')
    write(r, "CHANGELOG.md", cl.insert_section((r / "CHANGELOG.md").read_text(), "0.3.7", BULLETS))
    candidate = commit_candidate(r, "0.3.7", BULLETS)
    return r, base, candidate


def _added(r, sha):
    """(line number in the new file, text) of each line `sha` adds to CHANGELOG.md."""
    out, n = [], 0
    for ln in git("diff", "-U0", f"{sha}^", sha, "--", "CHANGELOG.md", cwd=r).splitlines():
        if ln.startswith("@@"):
            n = int(ln.split("+")[1].split(",")[0].split(" ")[0])
        elif ln.startswith("+") and not ln.startswith("+++"):
            out.append((n, ln[1:]))
            n += 1
    return out


def test_the_candidate_is_the_moves_then_the_changelog_section_alone(released):
    r, base, candidate = released
    assert git("rev-list", "--count", f"{base}..{candidate}", cwd=r) == "2"
    moves = git("diff", "--name-only", base, f"{candidate}^", cwd=r).split()
    assert "CHANGELOG.md" not in moves and "lhpc/data/manifest.example.toml" in moves
    assert git("diff", "--name-only", f"{candidate}^", candidate, cwd=r).split() == ["CHANGELOG.md"]
    lines = (r / "CHANGELOG.md").read_text().splitlines()
    heads = [i + 1 for i, t in enumerate(lines) if t.startswith("## ")]
    added = _added(r, candidate)
    assert lines[heads[0] - 1] == "## 0.3.7"
    assert all(heads[0] <= n < heads[1] for n, _ in added)          # inside the top section only
    assert sum(t.startswith("- ") for _, t in added) == len(BULLETS)
    assert git("log", "-1", "--format=%s", f"{candidate}^", cwd=r) == "0.3.7"
    assert git("log", "-1", "--format=%s", candidate, cwd=r) == "0.3.7: changelog"


def test_the_merge_back_to_a_moved_dev_brings_the_moves_and_the_section(released):
    r, base, candidate = released
    one = release_commit(r, candidate, base, "0.3.7")
    assert git("rev-parse", f"{one}^{{tree}}", cwd=r) == git("rev-parse", f"{candidate}^{{tree}}", cwd=r)
    assert git("rev-list", "--parents", "-n", "1", one, cwd=r).split()[1:] == [base]
    git("checkout", "-q", "-B", "integrate/0.3.7", "origin/dev", cwd=r)
    subprocess.run(["git", "cherry-pick", "-n", one], cwd=r, capture_output=True, check=False)
    _resolve_version_conflicts(r, "0.3.7", candidate, base)
    assert (r / "lhpc/data/manifest.example.toml").read_text() == 'pin_commit = "b"\n'
    assert "## 0.3.7" in (r / "CHANGELOG.md").read_text()
    assert (r / "notes.txt").read_text() == "dev moved on\n"


def test_the_version_merge_reads_the_attempts_base_not_the_candidates_parent(released):
    # With two commits the candidate's parent already holds the raised floor; merging against it
    # would call the floor "unchanged" and drop it on `dev`.
    r, base, candidate = released
    git("checkout", "-q", "-B", "integrate/0.3.7", "origin/dev", cwd=r)
    _resolve_version_conflicts(r, "0.3.7", candidate, base)
    assert (r / "pyproject.toml").read_text() == pyproject("0.3.7", "example>=2")
