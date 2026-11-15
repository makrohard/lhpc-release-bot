"""No two stop reports ever run at the same time, so one key never gets two open issues by a race.

`_report_stop` is reached only from `main`'s error path, for every stage but `web` and `heartbeat`.
These tests pin the facts that make two reporters at once impossible, read from the parsed
workflow files (yaml.safe_load), never from line patterns:
1. of all workflows (*.yml and *.yaml), only release.yml invokes a reporting stage, in any `run:`
   string, multiline ones included;
2. release.yml is ONE concurrency group, `release`, never cancelled in progress, which no job
   overrides: one release run at a time;
3. inside one run, the reporting jobs' `needs` and their WHOLE `if:` expressions are exactly the
   reviewed ones below. With them, two reporting jobs either depend on each other or cannot both
   run: a `finish-*` job runs only in `finish` mode, where `plan` (the root of every other chain)
   never runs; integrate/image/finalize need `release` to have SUCCEEDED, while `recover` runs only
   in `recover` mode (no plan, so no release) or when a stage before them failed or was cancelled.
   Any change to one of these expressions fails here and must be reviewed against that argument.
4. `web` and `heartbeat`, which may run beside them, return before the report path, whatever they
   raise; every `_report_stop` call is in `main` (bot/cli.py's AST).
`_file_report` still reconciles on every report, so a duplicate left by anything else (an issue
opened by hand, an interrupted cleanup) converges at the next report.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

from bot import cli

ROOT = Path(__file__).resolve().parents[1]
FLOWS = ROOT / ".github" / "workflows"
NOT_REPORTING = {"web", "heartbeat"}
INVOKE = re.compile(r"bot[./]cli(?:\.py)?\s+([a-z][a-z-]*)")

EXPECTED = {   # reporting job: (needs, whole `if:`, whitespace normalised)
    "plan": ([], "${{ (github.event_name != 'schedule' || vars.SCHEDULE_ENABLED == 'true') && "
                 "((inputs.mode || 'full') == 'full' || inputs.mode == 'watch-only' || "
                 "inputs.mode == 'dry-run') }}"),
    "build": (["plan"], "${{ needs.plan.outputs.proceed == 'true' && "
                        "needs.plan.outputs.binary_stacks != '' }}"),
    "prove": (["plan", "build"], "${{ always() && needs.plan.outputs.proceed == 'true' && "
                                 "needs.build.result != 'failure' && "
                                 "needs.build.result != 'cancelled' }}"),
    "release": (["plan", "prove"], "${{ always() && needs.plan.outputs.proceed == 'true' && "
                                   "needs.prove.result == 'success' }}"),
    "integrate": (["plan", "release"], "${{ !cancelled() && needs.release.result == 'success' }}"),
    "image": (["plan", "release", "integrate"],
              "${{ !cancelled() && needs.release.result == 'success' }}"),
    "finalize": (["plan", "release", "integrate", "image"],
                 "${{ !cancelled() && needs.release.result == 'success' }}"),
    "recover": (["plan", "build", "prove", "release"],
                "${{ always() && (inputs.mode == 'recover' || needs.plan.result == 'failure' || "
                "needs.plan.result == 'cancelled' || needs.build.result == 'failure' || "
                "needs.build.result == 'cancelled' || needs.prove.result == 'failure' || "
                "needs.prove.result == 'cancelled' || needs.release.result == 'failure' || "
                "needs.release.result == 'cancelled') }}"),
    "finish-integrate": ([], "${{ inputs.mode == 'finish' }}"),
    "finish-image": (["finish-integrate"], "${{ always() && inputs.mode == 'finish' }}"),
    "finish-close": (["finish-integrate", "finish-image"],
                     "${{ always() && inputs.mode == 'finish' }}"),
}


def _flows() -> dict:
    found = sorted([*FLOWS.glob("*.yml"), *FLOWS.glob("*.yaml")])
    assert found, "no workflow found"
    return {p.name: yaml.safe_load(p.read_text()) for p in found}


def _stages(job: dict) -> set:
    runs = "\n".join(str(s.get("run", "")) for s in job.get("steps") or [])
    assert ("bot.cli" in runs or "bot/cli" in runs) <= bool(INVOKE.search(runs)), \
        f"a bot invocation this test cannot read: {runs!r}"
    return set(INVOKE.findall(runs))


def _needs(job: dict) -> list:
    n = job.get("needs") or []
    return [n] if isinstance(n, str) else list(n)


def _reporting(flow: dict) -> dict:
    return {n: j for n, j in (flow.get("jobs") or {}).items() if _stages(j) - NOT_REPORTING}


def test_only_release_yml_invokes_a_reporting_stage():
    assert [name for name, flow in _flows().items() if _reporting(flow)] == ["release.yml"]


def test_the_release_workflow_is_one_uncancelled_group_that_no_job_overrides():
    flow = _flows()["release.yml"]
    assert flow["concurrency"] == {"group": "release", "cancel-in-progress": False}
    assert [n for n, j in flow["jobs"].items() if "concurrency" in j] == []


def test_the_reporting_jobs_and_their_conditions_are_exactly_the_reviewed_ones():
    rep = _reporting(_flows()["release.yml"])
    assert sorted(rep) == sorted(EXPECTED)
    for name, (needs, cond) in EXPECTED.items():
        assert _needs(rep[name]) == needs, name
        assert " ".join(str(rep[name].get("if", "")).split()) == cond, name


@pytest.mark.parametrize("stage", sorted(NOT_REPORTING))
@pytest.mark.parametrize("error", [cli.Stop("x", "boom", "nothing"), RuntimeError("boom")],
                         ids=["stop", "unexpected"])
def test_web_and_heartbeat_return_before_the_report_path(monkeypatch, stage, error):
    reported = []
    monkeypatch.setattr(cli, "_report_stop", lambda ctx, stop: reported.append(stop))

    def fails(*a, **k):
        raise error
    monkeypatch.setattr(cli, f"stage_{stage}", fails)
    with pytest.raises(type(error)):
        cli.main([stage])
    assert reported == []


def test_an_unexpected_error_in_a_stage_takes_the_generic_report_and_is_raised(monkeypatch):
    reported = []
    monkeypatch.setattr(cli, "_report_stop", lambda ctx, stop: reported.append(stop))
    monkeypatch.setattr(cli, "report_retry_outcome", lambda ctx, text: None)

    def fails(ctx):
        raise RuntimeError("boom")
    monkeypatch.setattr(cli, "stage_plan", fails)
    with pytest.raises(RuntimeError):
        cli.main(["plan"])
    assert len(reported) == 1 and "unexpected RuntimeError" in reported[0].observed
    assert reported[0].code == "", "an unnamed cause is never merged"


def test_every_report_call_is_in_main():
    callers = []
    for path in sorted((ROOT / "bot").glob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for call in [c for c in ast.walk(fn) if isinstance(c, ast.Call)]:
                name = getattr(call.func, "id", getattr(call.func, "attr", ""))
                if name == "_report_stop":
                    callers.append((path.name, fn.name))
    assert callers == [("cli.py", "main")] * 3
