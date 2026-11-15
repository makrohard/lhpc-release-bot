"""No two stop reports ever run at the same time, so one key never gets two open issues by a race.

`_report_stop` is reached only from `main`'s error path, for every stage but `web` and `heartbeat`.
These tests pin the three facts that make two reporters at once impossible:
1. only release.yml runs a reporting stage, and that whole workflow is ONE concurrency group,
   `release`, never cancelled in progress, which no job overrides: one release run at a time;
2. inside one run, two reporting jobs either depend on each other or can never both run (their
   `if`s exclude each other: by the dispatched mode, or by the result of `release`);
3. `web` and `heartbeat`, which may run beside the others, return before the report path.
`_file_report` still reconciles on every report, so a duplicate left by anything else (an issue
opened by hand, an interrupted cleanup) converges at the next report.
"""
from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

import pytest

from bot import cli

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
NOT_REPORTING = {"web", "heartbeat"}
STAGE = re.compile(r"(?m)^\s+(?:- )?run: python -m bot\.cli ([a-z-]+)")


def _jobs(text: str) -> dict:
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([a-z][a-z-]*):\n", body)[1:]
    return dict(zip(parts[::2], parts[1::2], strict=True))


def _needs(job: str) -> set:
    m = re.search(r"(?m)^    needs: (\[[^\]]*\]|\S+)$", job)
    return set(re.findall(r"[a-z][a-z-]*", m.group(1))) if m else set()


def _reporting(jobs: dict) -> dict:
    return {n: j for n, j in jobs.items() if set(STAGE.findall(j)) - NOT_REPORTING}


def _ancestors(jobs: dict, name: str) -> set:
    seen, todo = set(), list(_needs(jobs[name]))
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo += _needs(jobs[n])
    return seen


def _if(job: str) -> str:
    m = re.search(r"(?ms)^    if: (.*?)(?=^    [a-z-]+:)", job)
    return " ".join(m.group(1).split()) if m else ""


def _runs_only_after_plan_ran(jobs: dict, name: str) -> bool:
    """`plan` itself, a job that needs plan's own go-ahead or release's success, a job with the
    default `success()` gate under plan, or recover, which fires only in `recover` mode or on a
    failed or cancelled stage (and in `finish` mode every stage it needs is skipped)."""
    cond = _if(jobs[name])
    if name == "plan" or "needs.plan.outputs.proceed == 'true'" in cond or RELEASE_EXCLUSIVE in cond:
        return True
    if name == "recover":
        results = re.findall(r"needs\.[a-z]+\.result == '([a-z]+)'", cond)
        return ("inputs.mode == 'recover'" in cond and results
                and set(results) <= {"failure", "cancelled"})
    return "always()" not in cond and "!cancelled()" not in cond and "plan" in _ancestors(jobs, name)


def test_only_release_yml_runs_a_stage_that_reports():
    running = [w.name for w in WORKFLOWS if set(STAGE.findall(w.read_text())) - NOT_REPORTING]
    assert running == ["release.yml"]


def test_the_whole_release_workflow_is_one_uncancelled_group_no_job_overrides():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert re.search(r"(?m)^concurrency:\n  group: release\n  cancel-in-progress: false\b", text)
    assert text.count("concurrency:") == 1, "a job-level group would let that job run beside a run"


# Pairs of reporting jobs that are not ordered by `needs`, and why both can never run in one run.
MODE_EXCLUSIVE = ("inputs.mode == 'finish'", "(inputs.mode || 'full') == 'full'")
RELEASE_EXCLUSIVE = "needs.release.result == 'success'"


def test_two_reporting_jobs_of_one_run_never_run_side_by_side():
    jobs = _jobs((ROOT / ".github" / "workflows" / "release.yml").read_text())
    rep = _reporting(jobs)
    assert set(rep) >= {"plan", "recover", "finish-integrate"}
    for a, b in combinations(sorted(rep), 2):
        if a in _ancestors(jobs, b) or b in _ancestors(jobs, a):
            continue
        ia, ib = _if(rep[a]), _if(rep[b])
        finish = [n for n, i in ((a, ia), (b, ib)) if n.startswith("finish-")]
        if len(finish) == 1:
            # A finish job runs only in `finish` mode; the other chain's root, `plan`, never does.
            other = b if finish[0] == a else a
            assert MODE_EXCLUSIVE[0] in _if(rep[finish[0]])
            assert MODE_EXCLUSIVE[1] in _if(jobs["plan"]) and "finish" not in _if(jobs["plan"])
            assert _runs_only_after_plan_ran(jobs, other), f"{other} could run in finish mode"
            continue
        # The only other unordered pairs: recover beside the post-release chain. The chain needs
        # release to have SUCCEEDED; recover runs only when release (or a stage before it)
        # failed or was cancelled, or in `recover` mode, where plan, and so release, never run.
        pair = {a, b}
        assert "recover" in pair, f"{a} and {b} could run side by side"
        chain = (pair - {"recover"}).pop()
        assert "release" in _ancestors(jobs, chain) and RELEASE_EXCLUSIVE in _if(rep[chain])
        rec = _if(rep["recover"])
        assert "needs.release.result == 'success'" not in rec and "always()" in rec
        assert "recover" not in _if(jobs["plan"])


@pytest.mark.parametrize("stage", sorted(NOT_REPORTING))
def test_web_and_heartbeat_return_before_the_report_path(monkeypatch, stage):
    reported = []
    monkeypatch.setattr(cli, "_report_stop", lambda ctx, stop: reported.append(stop))

    def stops(*a, **k):
        raise cli.Stop(stage, "boom", "nothing")
    monkeypatch.setattr(cli, f"stage_{stage}", stops)
    with pytest.raises(cli.Stop):
        cli.main([stage])
    assert reported == []


def test_the_report_path_is_reached_only_from_main():
    calls = [ln for p in sorted((ROOT / "bot").glob("*.py"))
             for ln in p.read_text().splitlines() if "_report_stop(" in ln and "def " not in ln]
    assert len(calls) == 3                       # Stop, Unreadable, anything else: all in main
