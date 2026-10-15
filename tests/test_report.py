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
