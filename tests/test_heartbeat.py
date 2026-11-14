"""The heartbeat: GitHub switches off the weekly schedule of a public repository after 60 days
without activity, so a `main` with no commit for 28 days gets one empty commit.

Real git (a bare remote and a clone) because the behaviour is about git: which commit is the
newest, and what reaches the remote's `main`.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

NOW = 1_800_000_000                 # a fixed "now"; the commits are dated relative to it
DAY = 86_400


def _git(*args, cwd, env=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, **(env or {})}).stdout.strip()


class _Ctx:
    """`stage_heartbeat` needs a clone of this repository's main, as `Ctx.clone` makes it."""
    bot_token = token = ""

    def __init__(self, tmp: Path, remote: Path):
        self.tmp, self.remote, self.summaries = tmp, remote, []

    def clone(self, repo, ref="", token=""):
        dest = self.tmp / "work"
        _git("clone", "-q", "-b", ref, str(self.remote), str(dest), cwd=self.tmp)
        _git("config", "user.name", "lhpc-release-bot", cwd=dest)
        _git("config", "user.email", "bot@example.invalid", cwd=dest)
        return dest

    def summary(self, text):
        self.summaries.append(text)


def _remote_with_main_dated(tmp: Path, days_old: int) -> Path:
    remote, seed = tmp / "remote.git", tmp / "seed"
    _git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp)
    _git("init", "-q", "-b", "main", str(seed), cwd=tmp)
    stamp = f"@{NOW - days_old * DAY} +0000"
    _git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q",
         "--allow-empty", "-m", "the last landing", cwd=seed,
         env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
    _git("push", "-q", str(remote), "main", cwd=seed)
    return remote


@pytest.mark.parametrize("days_old,pushed", [(29, True), (27, False)],
                         ids=["older-than-28-days", "younger"])
def test_an_old_main_gets_one_empty_commit_and_a_young_one_nothing(tmp_path, days_old, pushed):
    from bot import cli
    remote = _remote_with_main_dated(tmp_path, days_old)
    before = _git("rev-parse", "main", cwd=remote)
    assert cli.stage_heartbeat(_Ctx(tmp_path, remote), now=NOW) == 0
    log = _git("log", "--format=%H %s", "main", cwd=remote).splitlines()
    if pushed:
        assert [line.split(" ", 1)[1] for line in log] == [
            "heartbeat: keep the weekly schedule active", "the last landing"]
        assert _git("rev-parse", "main^", cwd=remote) == before
        assert _git("diff", "--stat", before, "main", cwd=remote) == ""      # empty
    else:
        assert log == [f"{before} the last landing"]


def _job(workflow: str, name: str) -> str:
    m = re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  [a-z][a-z-]*:\n|\Z)", workflow)
    assert m, f"no job {name}"
    return m.group(1)


def test_the_heartbeat_is_a_schedule_only_job_that_may_write_contents():
    """It must run on the Monday schedule alone (a dispatched run is somebody's choice and
    resets nothing), whatever SCHEDULE_ENABLED says, and it is the job that may push."""
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
                / "release.yml").read_text()
    job = _job(workflow, "heartbeat")
    assert "    if: ${{ github.event_name == 'schedule' }}\n" in job
    assert re.search(r"(?m)^    permissions:\n      contents: write\b", job)
    assert "needs:" not in job                                     # nothing can skip it
    assert re.search(r"(?m)^      - run: python -m bot\.cli heartbeat$", job)
    assert workflow.count("bot.cli heartbeat") == 1
