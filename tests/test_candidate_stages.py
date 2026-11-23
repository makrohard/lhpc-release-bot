"""The two stages that write the release's commits, driven end to end against a local origin.

`stage_plan` must push the candidate as the moves, then the changelog section alone (LHPC's house rules
cap a commit at two changelog bullets unless it changes CHANGELOG.md alone inside its top section), and
`stage_integrate` must bring all of it back to a `dev` that moved on, its version merge read against the
attempt's base. The upstream scan, LHPC's pin contract and its Python checks are stubbed: they decide
whether a candidate exists, not how its commits are shaped. Real git, a real bare origin."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bot import cli
from bot.attempt import Attempt
from bot.upstream import Finding


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def write(repo: Path, name: str, text: str):
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)


def pyproject(version: str, dep: str) -> str:
    return f'[project]\nname = "lhpc"\nversion = "{version}"\ndependencies = ["{dep}"]\n'


MOVES = [Finding(key=f"src/{n}", track="tip", status="move", current="a" * 40, candidate="b" * 40,
                 tag="1.0", consumers=(n,)) for n in ("reticulum", "lxmf", "nomadnet")]


@pytest.fixture
def origin(tmp_path):
    """A bare LHPC origin: main = dev = 0.3.6."""
    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "-q", "-b", "main", ".", cwd=seed)
    git("config", "user.email", "t@example.invalid", cwd=seed)
    git("config", "user.name", "t", cwd=seed)
    write(seed, "pyproject.toml", pyproject("0.3.6", "example>=1"))
    write(seed, "lhpc/version.py", '__version__ = "0.3.6"\n')
    write(seed, cli.MANIFEST, 'pin_commit = "a"\n')
    write(seed, "CHANGELOG.md", "# Changelog\n\n## 0.3.6\n\n- the released one\n")
    write(seed, "tools/manifest_pin.py", "")
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "0.3.6", cwd=seed)
    git("branch", "dev", cwd=seed)
    bare = tmp_path / "origin.git"
    git("clone", "-q", "--bare", str(seed), str(bare), cwd=tmp_path)
    return bare


class _Ctx:
    token, retry_of, run_id, attempt_id = "t" * 20, "", "5000", "5000"

    def __init__(self, origin: Path, work: Path, mode="full", att=None):
        self.origin, self.work, self.mode, self.version = origin, work, mode, ""
        self.gh = self.bot_gh = self
        self.att, self.prs, self.dispatched, self.summaries = att, [], [], []

    # Ctx
    def clone(self, repo, ref="", token=""):
        dest = self.work / repo.split("/")[-1]
        if not dest.exists():
            git("clone", "-q", str(self.origin), str(dest), cwd=self.work)
            git("checkout", "-q", ref or "main", cwd=dest)
            git("config", "user.name", "bot", cwd=dest)
            git("config", "user.email", "bot@example.invalid", cwd=dest)
        return dest

    def open_attempts(self):
        return []

    def find_attempt(self, run_id=""):
        return 7, self.att

    def save_attempt(self, number, att):
        self.att = att
        return number or 7

    def record_run(self, repo, run_id):
        return {"repo": repo, "id": run_id, "attempt": 1}

    def summary(self, text):
        self.summaries.append(text)

    def out(self, **kv):
        pass

    # GitHub
    def whoami(self):
        return {"login": "bot"}

    def token_expiry(self):
        return ""

    def get(self, path):
        return {}

    def ref(self, repo, ref):
        return git("rev-parse", ref.replace("heads/", "refs/heads/"), cwd=self.origin)

    def is_ancestor(self, repo, ancestor, descendant):
        return subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant],
                              cwd=self.origin).returncode == 0

    def dispatch(self, repo, workflow, ref, inputs=None):
        self.dispatched.append((workflow, ref))
        return 9000 + len(self.dispatched)

    def pull_request(self, repo, head, base, title, body):
        self.prs.append((head, base))
        return {"number": 41}


@pytest.fixture
def planned(origin, tmp_path, monkeypatch):
    """stage_plan run for 0.3.7 with three moves; the stubs stand for the upstream scan and LHPC's checks."""
    def edit(text, moved, web):
        return text.replace('"a"', '"b"')
    monkeypatch.setattr(cli, "_findings", lambda *a, **k: (MOVES, None))
    monkeypatch.setattr(cli, "tag_problems", lambda *a, **k: [])
    monkeypatch.setattr(cli, "_degraded", lambda *a, **k: None)
    monkeypatch.setattr(cli, "edit_manifest", edit)
    monkeypatch.setattr(cli.mf, "pinned_sources", lambda text: [])
    monkeypatch.setattr(cli.mf, "binary_index", lambda text: "index-v3.json")
    monkeypatch.setattr(cli.pins, "check_lock", lambda *a, **k: "lock ok")
    monkeypatch.setattr(cli.pins, "check_constraints", lambda *a, **k: "constraints ok")
    monkeypatch.setattr(cli, "binary_rebuilds", lambda *a, **k: [])
    work = tmp_path / "plan"
    work.mkdir()
    ctx = _Ctx(origin, work)
    assert cli.stage_plan(ctx) == 0
    return ctx


def test_stage_plan_pushes_the_moves_then_the_changelog_section_alone(planned, origin):
    att = planned.att
    base, cand = att.base_sha, att.candidate_sha
    assert git("rev-parse", f"refs/heads/{att.branch}", cwd=origin) == cand
    assert git("rev-list", "--count", f"{base}..{cand}", cwd=origin) == "2"
    assert "CHANGELOG.md" not in git("diff", "--name-only", base, f"{cand}^", cwd=origin).split()
    assert git("diff", "--name-only", f"{cand}^", cand, cwd=origin).split() == ["CHANGELOG.md"]
    top = git("show", f"{cand}:CHANGELOG.md", cwd=origin).split("## ")[1]
    assert top.startswith("0.3.7") and top.count("\n- ") == len(MOVES)
    assert [ref for _, ref in planned.dispatched] == [att.branch]      # LHPC CI, on the candidate


def test_stage_integrate_brings_the_whole_release_to_a_dev_that_moved_on(planned, origin, tmp_path):
    # dev moves on (an unrelated commit), then the release stands on main
    att = planned.att
    side = tmp_path / "side"
    git("clone", "-q", str(origin), str(side), cwd=tmp_path)
    git("config", "user.email", "t@example.invalid", cwd=side)
    git("config", "user.name", "t", cwd=side)
    git("checkout", "-q", "dev", cwd=side)
    write(side, "notes.txt", "dev moved on\n")
    git("add", "-A", cwd=side)
    git("commit", "-q", "-m", "an unrelated dev commit", cwd=side)
    git("push", "-q", "origin", "dev", "--force", cwd=side)
    git("push", "-q", "origin", f"{att.candidate_sha}:refs/heads/main", "--force", cwd=side)
    released = Attempt(**{**att.__dict__, "state": "released"})
    work = tmp_path / "integrate"
    work.mkdir()
    ctx = _Ctx(origin, work, att=released)
    assert cli.stage_integrate(ctx) == 0
    branch = f"integrate/{att.version}"
    head = git("rev-parse", f"refs/heads/{branch}", cwd=origin)
    assert ctx.prs == [(branch, "dev")]
    assert git("show", f"{head}:{cli.MANIFEST}", cwd=origin) == 'pin_commit = "b"'
    assert "## 0.3.7" in git("show", f"{head}:CHANGELOG.md", cwd=origin)
    assert git("show", f"{head}:pyproject.toml", cwd=origin) == pyproject("0.3.7", "example>=1").strip()
    assert git("show", f"{head}:notes.txt", cwd=origin) == "dev moved on"


def test_a_dev_that_conflicts_gets_the_candidate_itself_as_the_pull_request(planned, origin, tmp_path):
    # Not a version collision: dev changed the same manifest line. The bot resolves nothing else, so
    # the branch is the candidate (both commits) and a person sees the conflict on the PR.
    att = planned.att
    side = tmp_path / "side"
    git("clone", "-q", str(origin), str(side), cwd=tmp_path)
    git("config", "user.email", "t@example.invalid", cwd=side)
    git("config", "user.name", "t", cwd=side)
    git("checkout", "-q", "dev", cwd=side)
    write(side, cli.MANIFEST, 'pin_commit = "z"\n')
    git("add", "-A", cwd=side)
    git("commit", "-q", "-m", "dev moved the same pin", cwd=side)
    git("push", "-q", "origin", "dev", "--force", cwd=side)
    git("push", "-q", "origin", f"{att.candidate_sha}:refs/heads/main", "--force", cwd=side)
    work = tmp_path / "integrate"
    work.mkdir()
    ctx = _Ctx(origin, work, att=Attempt(**{**att.__dict__, "state": "released"}))
    assert cli.stage_integrate(ctx) == 0
    branch = f"integrate/{att.version}"
    assert ctx.prs == [(branch, "dev")]
    assert git("rev-parse", f"refs/heads/{branch}", cwd=origin) == att.candidate_sha
    assert ctx.att.integration == "pr:41"

