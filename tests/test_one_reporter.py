"""No two stop reports ever run at the same time, so one key never gets two open issues by a race.

1. At run time, `_report_stop` files only in a job of the release workflow (GITHUB_WORKFLOW is its
   `name:`); a report from any other workflow, which could run beside a release run, is refused.
2. release.yml is ONE concurrency group, `release`, never cancelled in progress, which no job
   overrides; its one matrix (`build`) runs one instance at a time: one release run, and in it
   one instance of each job at a time.
3. Inside one run, the reporting jobs' `needs` and their WHOLE `if:` expressions are exactly the
   reviewed ones below, and release.yml has no job but these and `web`/`heartbeat`. With them, two
   reporting jobs either depend on each other or cannot both run: a `finish-*` job runs only in
   `finish` mode, where `plan` (the root of every other chain) never runs; integrate/image/finalize
   need `release` to have SUCCEEDED, while `recover` runs only in `recover` mode (no plan, so no
   release) or when a stage before them failed or was cancelled. Any change to one of these fails
   here and must be reviewed against that argument.
4. `web` and `heartbeat`, which may run beside them, return before the report path, whatever they
   raise.
`_file_report` still reconciles on every report, so a duplicate left by anything else (an issue
opened by hand, an interrupted cleanup) converges at the next report.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bot import cli
from tests.test_report import _plan_stop, _StopCtx, _StopStore

RELEASE_YML = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
NOT_REPORTING = {"web", "heartbeat"}

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


def _release() -> dict:
    return yaml.safe_load(RELEASE_YML.read_text())


@pytest.mark.parametrize("workflow", ["", "ci", "release-copy", "Release"])
def test_a_report_outside_the_release_workflow_files_nothing(monkeypatch, workflow):
    if workflow:
        monkeypatch.setenv("GITHUB_WORKFLOW", workflow)
    else:
        monkeypatch.delenv("GITHUB_WORKFLOW")
    store = _StopStore()
    cli._report_stop(_StopCtx(store, "101", version="0.12.11"), _plan_stop())
    assert store.issues == {} and store.notes == {}


def test_a_report_in_the_release_workflow_files_its_issue():
    store = _StopStore()
    cli._report_stop(_StopCtx(store, "101", version="0.12.11"), _plan_stop())
    assert list(store.issues) == [1]


def test_the_reporting_workflow_is_release_yml_by_its_name():
    assert _release()["name"] == cli.REPORTING_WORKFLOW


def test_one_release_run_at_a_time_with_one_instance_of_each_job_at_a_time():
    flow = _release()
    assert flow["concurrency"] == {"group": "release", "cancel-in-progress": False}
    assert [n for n, j in flow["jobs"].items() if "concurrency" in j] == []
    # The one matrix, `build`, runs its instances one after another: max-parallel 1.
    assert {n: j["strategy"] for n, j in flow["jobs"].items() if "strategy" in j} == {
        "build": {"max-parallel": 1, "fail-fast": True,
                  "matrix": {"stack": "${{ fromJSON(needs.plan.outputs.binary_stacks_json) }}"}}}


def test_the_jobs_and_the_reporting_conditions_are_exactly_the_reviewed_ones():
    jobs = _release()["jobs"]
    assert sorted(jobs) == sorted({*EXPECTED, *NOT_REPORTING})
    for name, (needs, cond) in EXPECTED.items():
        got = jobs[name].get("needs") or []
        assert ([got] if isinstance(got, str) else list(got)) == needs, name
        assert " ".join(str(jobs[name].get("if", "")).split()) == cond, name


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
