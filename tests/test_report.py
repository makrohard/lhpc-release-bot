"""What a failure issue says: who stopped, where, and which inputs it was moving.

The issue is what a maintainer reads weeks later. Each case is one way it used to mislead: a
retry reported as "the scheduled run", and an empty Inputs table on a stop after the plan.
"""
from __future__ import annotations

from dataclasses import asdict

import pytest

from bot import cli
from bot.attempt import Attempt
from bot.upstream import Finding

MOVED = Finding(key="src/meshcom-qemu-raspi", track="tip", status="move", current="a" * 40,
                candidate="b" * 40, remote="https://github.com/makrohard/meshcom-qemu-raspi.git")


class _Issues:
    def __init__(self):
        self.created = []

    def open_issues(self, repo, label):
        return []

    def create_issue(self, repo, title, body, labels):
        self.created.append(body)
        return {"number": 1}

    def comment(self, repo, number, body):
        raise AssertionError("no issue was open, so nothing is commented")


class _Ctx:
    run_url, run_id, attempt_id, token = "https://example.invalid/run/9", "9", "9", ""

    def __init__(self, retry_of=""):
        self.retry_of = retry_of
        self.gh, self.bot_gh = None, _Issues()
        self.att = Attempt(run_id="9", state="prepared", version="0.12.10", base_sha="b" * 40,
                           candidate_sha="c" * 40, branch="pins/0.12.10-9",
                           moved_keys=[MOVED.key])
        # Set after construction, so this file also runs against a record without the field.
        self.att.inputs = [asdict(MOVED)]

    def find_attempt(self, wanted=""):
        return 3, self.att

    def summary(self, text):
        pass


def test_a_stop_after_the_plan_lists_the_inputs_the_attempt_was_moving():
    ctx = _Ctx()
    cli._report_stop(ctx, cli.Stop("prove", "the candidate is not proven", "Recovery restores."))
    body = ctx.bot_gh.created[0]
    rows = [ln for ln in body.splitlines() if ln.startswith("| → |")]
    assert len(rows) == 1 and f"`{MOVED.key}`" in rows[0]


@pytest.mark.parametrize("retry_of, event, word", [
    ("", "schedule", "scheduled"),
    ("", "workflow_dispatch", "dispatched"),
    ("1234", "workflow_dispatch", "retry of attempt 1234"),
])
def test_the_opening_names_the_event_that_started_the_run(monkeypatch, retry_of, event, word):
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    ctx = _Ctx(retry_of=retry_of)
    cli._report_stop(ctx, cli.Stop("prove", "the candidate is not proven", "Recovery restores."))
    assert word in ctx.bot_gh.created[0].splitlines()[0]


# ---- a degraded state that persists is visible, never blocking ----

class _Store:
    def __init__(self):
        self.issues, self.notes, self.n = {}, {}, 0

    def open_issues(self, repo, label):
        return [{"number": n, "title": i["title"], "body": i["body"]}
                for n, i in self.issues.items() if i["state"] == "open"]

    def create_issue(self, repo, title, body, labels):
        self.n += 1
        self.issues[self.n] = {"title": title, "state": "open", "body": body}
        self.notes[self.n] = []
        return {"number": self.n}

    def comment(self, repo, number, body):
        self.notes[number].append(body)

    def comments(self, repo, number):
        return [{"body": b} for b in self.notes[number]]

    def update_issue(self, repo, number, **fields):
        self.issues[number].update(fields)


class _RunCtx:
    def __init__(self, store, run_id):
        self.bot_gh, self.run_id = store, run_id
        self.run_url = f"https://example.invalid/run/{run_id}"


def test_a_skipped_source_is_persistent_from_its_third_run_and_closes_when_seen_no_more():
    store = _Store()
    seen, examined = {"src/x": "not reachable this run, pin kept"}, {"src/x", "src/y"}
    titles = []
    for run in ("r1", "r2", "r2", "r3"):           # r2 twice: one run counts once
        cli._degraded(_RunCtx(store, run), "source", seen, examined)
        titles.append(store.issues[1]["title"])
    assert [t.startswith("PERSISTENT ") for t in titles] == [False, False, False, True]
    assert len(store.issues) == 1                      # one issue, not one per run
    cli._degraded(_RunCtx(store, "r4"), "source", {}, set())     # never examined src/x
    assert store.issues[1]["state"] == "open"
    cli._degraded(_RunCtx(store, "r5"), "source", {}, examined)  # examined, and recovered
    assert store.issues[1]["state"] == "closed"


def test_a_persons_comment_is_not_an_occurrence():
    store = _Store()
    seen = {"src/x": "not reachable"}
    cli._degraded(_RunCtx(store, "r1"), "source", seen, {"src/x"})
    store.comment("o/r", 1, "I looked at this; the host is down for maintenance.")
    store.comment("o/r", 1, "Still down.")
    cli._degraded(_RunCtx(store, "r2"), "source", seen, {"src/x"})
    assert not store.issues[1]["title"].startswith("PERSISTENT ")


def test_a_re_run_of_the_opening_run_is_not_a_second_occurrence():
    store = _Store()
    titles = []
    for run in ("r1", "r1", "r2", "r3"):           # GitHub re-runs keep the run id
        cli._degraded(_RunCtx(store, run), "source", {"src/x": "not reachable"}, {"src/x"})
        titles.append(store.issues[1]["title"].startswith("PERSISTENT "))
    assert titles == [False, False, False, True]


def test_an_expiring_incident_promises_renewal_only_on_an_attributable_regression():
    # The same rule as the README: an unmarked red writes no hold, so it renews nothing.
    from bot import report as rp
    att = Attempt(run_id="9", version="0.12.10", base_sha="b" * 40, candidate_sha="c" * 40,
                  regression=["meshcore"])
    body = rp.incident(att, {"src/openhop-core": "holds meshcore"}, "https://example.invalid/r/9",
                       until="2026-10-23")
    assert "attributable regression that holds them again renews" in body
    assert "an unmarked red leaves it expired" in body and "a red one renews" not in body


# ---- one open issue per problem: a stop with no attempt, by stage, version and reason ----

class _StopStore(_Store):
    """`_Store`, plus a listing that can lag: each set in `hides` is consumed by one
    `open_issues` call and keeps those numbers out of it, the way another run's issue, or one just
    created, can be missing from a listing."""

    def __init__(self):
        super().__init__()
        self.hides = []

    def open_issues(self, repo, label):
        hide = self.hides.pop(0) if self.hides else set()
        return [i for i in super().open_issues(repo, label) if i["number"] not in hide]

    def put(self, number, body):                   # an issue some other run created
        self.issues[number] = {"title": "t", "state": "open", "body": body}
        self.notes[number] = []


class _StopCtx:
    run_url, token = "https://example.invalid/run/9", ""

    def __init__(self, store, run_id="9", attempt_id="", version="", record=None, lookup=None):
        self.bot_gh, self.gh, self.retry_of = store, None, ""
        self.run_id, self.attempt_id, self.version = run_id, attempt_id or run_id, version
        self._record, self._lookup = record, lookup

    def find_attempt(self, wanted=""):
        if self._lookup:
            raise self._lookup
        return (3, self._record) if self._record else (0, None)

    def summary(self, text):
        pass


def _plan_stop(code="version-taken"):
    return cli.Stop("plan", "version 0.12.11 cannot be released from this `main`",
                    "Tag main's version on main, then re-run.", code=code)


def _open(store):
    return {n: i for n, i in store.issues.items() if i["state"] == "open"}


def test_two_runs_stopped_for_the_same_reason_share_one_issue():
    store = _StopStore()
    cli._report_stop(_StopCtx(store, "101", version="0.12.11"), _plan_stop())
    cli._report_stop(_StopCtx(store, "102", version="0.12.11"), _plan_stop())
    assert list(_open(store)) == [1]
    assert "<!--auto-release:stop:plan:0.12.11:version-taken-->" in store.issues[1]["body"]
    assert len(store.notes[1]) == 1 and "/run/9" in store.notes[1][0]


def test_another_version_or_another_reason_is_another_issue():
    store = _StopStore()
    cli._report_stop(_StopCtx(store, "101", version="0.12.11"), _plan_stop())
    cli._report_stop(_StopCtx(store, "102", version="0.12.12"), _plan_stop())
    cli._report_stop(_StopCtx(store, "103", version="0.12.12"), _plan_stop("baseline-red"))
    assert list(_open(store)) == [1, 2, 3] and not any(store.notes.values())


def test_the_blocked_release_stop_is_keyed_as_observe_with_no_version():
    from tests.test_attempt import _PlanCtx
    blocker = Attempt(run_id="4000", state="mutated", version="0.12.10", base_sha="b" * 40,
                      candidate_sha="c" * 40, branch="pins/0.12.10-4000", dispatched=["meshcom"])
    with pytest.raises(cli.Stop) as raised:
        cli.stage_plan(_PlanCtx(blocker))
    store = _StopStore()
    for run in ("201", "202"):
        cli._report_stop(_StopCtx(store, run), raised.value)
    assert list(_open(store)) == [1] and len(store.notes[1]) == 1
    assert "<!--auto-release:stop:observe:-:attempt-unresolved-->" in store.issues[1]["body"]
    other = cli.Stop("observe", "the release token cannot authenticate", "Rotate.",
                     code="token-auth")
    cli._report_stop(_StopCtx(store, "203"), other)
    assert list(_open(store)) == [1, 2], "another reason never joins the blocked issue"


def test_the_untagged_version_stop_carries_the_version_the_plan_computed(tmp_path, monkeypatch):
    from tests.test_changelog import _tagged_plan
    stop, ctx = _tagged_plan(tmp_path, monkeypatch, {})
    assert stop.code == "version-taken" and ctx.version == "0.12.11"
    store = _StopStore()
    cli._report_stop(_StopCtx(store, "101", version=ctx.version), stop)
    assert "<!--auto-release:stop:plan:0.12.11:version-taken-->" in store.issues[1]["body"]


def test_a_stop_whose_attempt_could_not_be_looked_up_is_never_merged():
    store = _StopStore()
    cli._report_stop(_StopCtx(store, "101", version="0.12.11"), _plan_stop())
    cli._report_stop(_StopCtx(store, "102", version="0.12.11", lookup=RuntimeError("HTTP 502")),
                     _plan_stop())
    assert list(_open(store)) == [1, 2] and not store.notes[1]
    assert "<!--auto-release:102-->" in store.issues[2]["body"]


def test_a_stop_that_found_its_attempt_or_names_one_keeps_the_attempt_issue():
    store = _StopStore()
    record = Attempt(run_id="777", state="prepared", version="0.12.11", base_sha="b" * 40,
                     candidate_sha="c" * 40, branch="pins/0.12.11-777")
    cli._report_stop(_StopCtx(store, "777", version="0.12.11", record=record), _plan_stop())
    cli._report_stop(_StopCtx(store, "778", attempt_id="555"), _plan_stop())
    assert "<!--auto-release:777-->" in store.issues[1]["body"]
    assert "<!--auto-release:555-->" in store.issues[2]["body"]


def test_a_stop_without_a_reason_code_keeps_its_own_run_issue():
    store = _StopStore()
    for run in ("101", "102"):
        cli._report_stop(_StopCtx(store, run, version="0.12.11"), _plan_stop(code=""))
    assert list(_open(store)) == [1, 2]
    assert "<!--auto-release:102-->" in store.issues[2]["body"]


def test_a_closed_issue_is_not_reopened_by_comment():
    store = _StopStore()
    cli._report_stop(_StopCtx(store, "101", version="0.12.11"), _plan_stop())
    store.update_issue("bot", 1, state="closed")
    cli._report_stop(_StopCtx(store, "102", version="0.12.11"), _plan_stop())
    assert list(_open(store)) == [2] and not store.notes[1]


KEY = "<!--auto-release:stop:plan:0.12.11:version-taken-->"


def _report(store, run="102"):
    cli._report_stop(_StopCtx(store, run, version="0.12.11"), _plan_stop())


def test_a_race_where_the_new_issue_is_not_listed_yet_still_leaves_one_open():
    # The verdict's sequence: the first look misses #1, the look after the create misses #2.
    store = _StopStore()
    store.put(1, f"other run\n{KEY}\n")
    store.n = 1
    store.hides = [{1}, {2}]
    _report(store)
    assert list(_open(store)) == [1], "the newer issue is closed as the duplicate"
    assert store.notes[1] and "/run/9" in store.notes[1][0], "the report went to the survivor"
    assert "Duplicate of #1" in store.notes[2][-1]


def test_three_runs_that_race_leave_the_lowest_open():
    store = _StopStore()
    store.put(1, f"run a\n{KEY}\n")
    store.put(2, f"run b\n{KEY}\n")
    store.n = 2
    store.hides = [{1, 2}, {3}]
    _report(store, "103")
    assert list(_open(store)) == [1]
    assert all("Duplicate of #1" in store.notes[n][-1] for n in (2, 3))


def test_when_the_new_issue_is_the_lowest_it_survives_and_carries_its_own_report():
    store = _StopStore()
    store.put(5, f"run a\n{KEY}\n")
    store.hides = [{5}, {1}]                       # own becomes #1, unlisted after the create
    _report(store)
    assert list(_open(store)) == [1] and not store.notes[1], "its body is the report"
    assert "Duplicate of #1" in store.notes[5][-1]


def test_duplicates_left_by_an_earlier_run_are_settled_by_the_next_report():
    store = _StopStore()
    store.put(1, f"run a\n{KEY}\n")
    store.put(2, f"run b\n{KEY}\n")
    store.n = 2
    _report(store)
    assert list(_open(store)) == [1] and len(store.notes[1]) == 1
    assert "Duplicate of #1" in store.notes[2][-1] and store.n == 2, "nothing new was created"
