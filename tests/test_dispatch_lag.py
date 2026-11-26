"""A run GitHub has just started is not at once visible: its id 404s for a while after the
dispatch reply named it, and the runs list may not show it yet. Neither lag may read as "no such
run" — that would end a stage that should wait, or start a second writer beside the first.
The fake stands in for GitHub's HTTP answers only; the stage and its reads are the real ones.
"""
from __future__ import annotations

import pytest

from bot import cli
from bot import gh as ghmod
from bot.attempt import Attempt

CAND = "c" * 40
BUILDER = {"id": 4242, "status": "in_progress", "html_url": "https://example.invalid/4242"}


class Dispatched(Exception):
    """A second image builder was started."""


class _ImageGh(ghmod.GitHub):
    """The images repository while `finish` resumes an incomplete image: the tag stands, the
    release is not complete. A builder (4242) is running; the runs list shows it only from list
    round `listed_from` on, and its own id 404s for its first `lag` reads."""

    def __init__(self, listed_from=1, lag=0):
        super().__init__("t")
        self.listed_from, self.lag, self.rounds, self.dispatched = listed_from, lag, 0, []

    def request(self, method, path, body=None, accept="application/vnd.github+json"):
        assert method == "GET", path
        if f"/actions/workflows/{cli.IMAGE_WORKFLOW}/runs?status=" in path:
            if "status=queued" in path:
                self.rounds += 1
            listed = "status=in_progress" in path and self.rounds >= self.listed_from
            return {"workflow_runs": [BUILDER] if listed else []}
        if path == f"/repos/{cli.IMG}/actions/runs/4242":
            if self.lag:
                self.lag -= 1
                raise ghmod.GitHubError(f"GET {path} -> 404: Not Found", status=404)
            return dict(BUILDER)
        raise AssertionError(path)

    def ref(self, repo, ref):
        return "a" * 40                     # the tag exists: this is the resume branch

    def release_by_tag(self, repo, tag):
        return {}                           # not published yet

    def tag_message(self, repo, tag):
        return f"lhpc-commit: {CAND}\n"

    def dispatch(self, repo, workflow, ref, inputs=None):
        self.dispatched.append(workflow)
        raise Dispatched(workflow)


class _Ctx:
    attempt_id = run_id = "100"

    def __init__(self, gh, runs=None):
        self.gh, self.summaries = gh, []
        self.att = Attempt(run_id="100", state="released", version="0.14.0", base_sha="b" * 40,
                           candidate_sha=CAND, branch="pins/0.14.0-100", runs=runs or {})

    def find_attempt(self, wanted=""):
        return 7, self.att

    def save_attempt(self, number, att):
        return number

    def summary(self, text):
        self.summaries.append(text)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(ghmod.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(ghmod.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    return now


def test_a_builder_not_yet_listed_is_still_found_and_no_second_one_starts():
    """The first list reads miss a builder started moments ago; a later one shows it."""
    gh = _ImageGh(listed_from=3)
    with pytest.raises(cli.Stop, match="still running"):
        cli.stage_image(_Ctx(gh))
    assert gh.dispatched == [] and gh.rounds == 3


def test_a_recorded_builder_still_running_is_asked_by_its_id_through_its_404_lag():
    gh = _ImageGh(listed_from=10**6, lag=2)
    with pytest.raises(cli.Stop, match="still running") as stop:
        cli.stage_image(_Ctx(gh, runs={"image": {"repo": cli.IMG, "id": 4242}}))
    assert gh.dispatched == [] and "4242" in stop.value.detail


def test_none_running_over_the_whole_lag_starts_the_builder_once(clock):
    gh = _ImageGh(listed_from=10**6)
    with pytest.raises(Dispatched):
        cli.stage_image(_Ctx(gh))
    assert gh.dispatched == [cli.IMAGE_WORKFLOW] and clock[0] == ghmod.RUN_VISIBLE_S


def test_any_other_error_on_a_dispatched_run_raises_at_once(clock):
    """Only a 404 is the lag; a refusal or a server error is not waited out here."""
    class Refusing(_ImageGh):
        def request(self, method, path, body=None, accept="application/vnd.github+json"):
            self.reads = getattr(self, "reads", 0) + 1
            raise ghmod.GitHubError(f"GET {path} -> 403: Resource not accessible", status=403)

    gh = Refusing()
    with pytest.raises(ghmod.GitHubError, match="403") as err:
        gh.dispatched_run(cli.IMG, 4242)
    assert err.value.status == 403 and gh.reads == 1 and clock[0] == 0
