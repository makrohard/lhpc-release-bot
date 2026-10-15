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
