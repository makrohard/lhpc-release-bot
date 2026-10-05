"""When a red run is re-run, and when it is not.

A first attempt whose failed jobs either lost their runner or failed only for want of a job that
did never measured anything, so its failed jobs are re-run once and the same run id is waited on
again. Anything else — a real red, a real red beside a lost runner, a second attempt, a job
cancelled for no reason GitHub names, a workflow file that cannot be read — comes back as it is.
The fake stands in for GitHub's HTTP answers only; the decisions are the real ones.
"""
from __future__ import annotations

import base64

import pytest

from bot import gh as ghmod
from bot.attempt import Attempt
from bot.cli import _run_problems

CAND = "c" * 40
SHUTDOWN = ("The runner has received a shutdown signal. This can happen when the runner service "
            "is stopped, or a manually started runner is canceled.")
LOST = "The self-hosted runner: lhpc-1 lost communication with the server."
NOT_ACQUIRED = "The job was not acquired by Runner of type hosted even after multiple attempts"
# The shape of the images workflow: publish-tag needs build, which ran as a matrix.
IMAGES = """\
on: workflow_dispatch
jobs:
  lint:
    runs-on: ubuntu-latest
  precheck:
    runs-on: ubuntu-latest
  build:
    needs: [lint, precheck]
    strategy:
      matrix:
        variant: [lite, desktop]
  publish-tag:
    needs:
      - precheck
      - build   # both variants or none
    if: ${{ always() }}
  publish-refresh:
    needs: build
  unrelated:
    name: "release notes"
    needs: lint
"""


def job(name, conclusion="success", steps=3, jid=None, started="T10", completed="T20"):
    return {"id": jid or abs(hash(name)) % 10**6, "name": name, "conclusion": conclusion,
            "head_sha": CAND, "steps": [{}] * steps, "started_at": started,
            "completed_at": completed}


class FakeGitHub(ghmod.GitHub):
    """GitHub's answers for ONE run: attempt 1 as given, attempt 2 (if re-run) as given."""

    def __init__(self, first, jobs1, second=None, jobs2=None, annotations=None, logs=None,
                 stale_reads=1, workflow=IMAGES):
        super().__init__("t")
        self.first, self.jobs1 = first, jobs1
        self.second, self.jobs2 = second, jobs2 or []
        self.annotations = annotations or {}
        self.logs = logs if logs is not None else {1: f"##[error]{SHUTDOWN}\n{LOST}"}
        self.stale_reads = stale_reads      # finished-attempt-1 answers after the re-run POST
        self.workflow, self.posts = workflow, []

    def request(self, method, path, body=None, accept="application/vnd.github+json"):
        if method == "POST":
            self.posts.append(path)
            return None
        if "/contents/" in path:
            assert path == f"/repos/o/r/contents/.github/workflows/x.yml?ref={CAND}"
            if self.workflow is None:
                raise ghmod.GitHubError(f"GET {path} -> 500")
            return {"encoding": "base64",
                    "content": base64.b64encode(self.workflow.encode()).decode()}
        if "/annotations" in path:
            jid = int(path.split("/check-runs/")[1].split("/")[0])
            return [{"message": m} for m in self.annotations.get(jid, [])]
        if path.endswith("/logs"):
            jid = int(path.split("/jobs/")[1].split("/")[0])
            if jid not in self.logs:
                raise ghmod.GitHubError(f"GET {path} -> 404")
            return self.logs[jid].encode()
        if "/attempts/" in path:
            n = int(path.split("/attempts/")[1].split("/")[0])
            return {"jobs": self.jobs1 if n == 1 else self.jobs2}
        if "/actions/runs/" in path:
            if not any(p.endswith("/rerun-failed-jobs") for p in self.posts):
                return dict(self.first)
            if self.stale_reads:
                self.stale_reads -= 1
                return dict(self.first)
            return dict(self.second)
        raise AssertionError(path)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """A clock that moves only when the wait sleeps."""
    now = [0.0]
    monkeypatch.setattr(ghmod.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(ghmod.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    return now


def run(attempt=1, conclusion="failure", status="completed"):
    return {"id": 77, "status": status, "conclusion": conclusion, "run_attempt": attempt,
            "head_sha": CAND, "workflow_id": 42, "path": ".github/workflows/x.yml"}


RERUN = "/repos/o/r/actions/runs/77/rerun-failed-jobs"


@pytest.mark.parametrize("said", [SHUTDOWN, LOST, NOT_ACQUIRED],
                         ids=["shutdown", "lost-communication", "not-acquired"])
def test_a_first_attempt_that_lost_its_runner_is_re_run_once_and_judged_on_attempt_2(said):
    g = FakeGitHub(run(), [job("lint"), job("testlab", "failure", jid=1)],
                   second=run(2, "success"), annotations={1: ["exit code 143", said]})
    got = g.wait("o/r", 77, 60)
    assert g.posts == [RERUN]
    assert got["run_attempt"] == 2 and got["conclusion"] == "success"
    assert got["rerun"] == {"attempt": 1, "jobs": ["testlab"]}


@pytest.mark.parametrize("failed", [
    # the 0.12.2 image build: lite never got a runner, publish-tag ran after it and refused
    [job("build (lite)", "cancelled", 0, jid=1, completed="T20"),
     job("publish-tag", "failure", jid=2, started="T21", completed="T30")],
    # two dependants, both started once the lost job had ended
    [job("build (lite)", "failure", jid=1, completed="T20"),
     job("publish-refresh", "failure", jid=2, started="T20"),
     job("publish-tag", "failure", jid=3, started="T25")],
], ids=["needs-directly", "two-dependants"])
def test_jobs_that_failed_for_want_of_a_lost_job_are_re_run_with_it(failed):
    g = FakeGitHub(run(), [job("lint"), job("precheck"), *failed],
                   second=run(2, "success"), annotations={1: [NOT_ACQUIRED]})
    got = g.wait("o/r", 77, 60)
    assert g.posts == [RERUN]
    assert got["rerun"] == {"attempt": 1, "jobs": ["build (lite)"]}


def test_the_second_attempt_is_returned_even_when_it_loses_its_runner_again():
    """Once per run: attempt 2 red for the same reason comes back red."""
    g = FakeGitHub(run(), [job("testlab", "failure", jid=1)], second=run(2, "failure"),
                   jobs2=[job("testlab", "failure", jid=1)], annotations={1: [SHUTDOWN]})
    got = g.wait("o/r", 77, 60)
    assert g.posts == [RERUN]
    assert (got["run_attempt"], got["conclusion"]) == (2, "failure")


@pytest.mark.parametrize("first, jobs1, annotations, workflow", [
    # a real red: today's behaviour
    (run(), [job("testlab", "failure", jid=1)], {1: ["Process completed with exit code 1."]},
     IMAGES),
    # one job lost its runner, another failed for real: the real red stands
    (run(), [job("testlab", "failure", jid=1), job("test (3.11)", "failure", jid=2)],
     {1: [SHUTDOWN], 2: ["Process completed with exit code 1."]}, IMAGES),
    # a failed job that does NOT need the lost one
    (run(), [job("build (lite)", "cancelled", 0, jid=1), job("release notes", "failure", jid=2)],
     {1: [NOT_ACQUIRED]}, IMAGES),
    # the matrix sibling of the lost job failed for real: a sibling is not a dependant
    (run(), [job("build (lite)", "failure", jid=1), job("build (desktop)", "failure", jid=2)],
     {1: [NOT_ACQUIRED]}, IMAGES),
    # the needs cannot be read, or cannot be understood: fail closed
    (run(), [job("build (lite)", "failure", jid=1), job("publish-tag", "failure", jid=2)],
     {1: [NOT_ACQUIRED]}, None),
    (run(), [job("build (lite)", "failure", jid=1), job("publish-tag", "failure", jid=2)],
     {1: [NOT_ACQUIRED]}, IMAGES.replace("needs: [lint, precheck]", "needs: ${{ x }}")),
    # a dependant that started BEFORE the lost job ended did not fail on the loss
    (run(), [job("build (lite)", "failure", jid=1, completed="T20"),
             job("publish-tag", "failure", jid=2, started="T19")], {1: [NOT_ACQUIRED]}, IMAGES),
    # cancelled before any step, with no runner-loss text: a person may have cancelled it
    (run(conclusion="cancelled"), [job("build (lite)", "cancelled", 0, jid=1)], {}, IMAGES),
    # the words only in the log: a real failure can print them, so they do not count
    (run(), [job("testlab", "failure", jid=1)], {1: ["Process completed with exit code 1."]},
     IMAGES),
    # a timeout a workflow sets: cancelled, steps ran, and GitHub says why
    (run(conclusion="cancelled"), [job("testlab", "cancelled", jid=1)],
     {1: ["The job running on runner lhpc-1 has exceeded the maximum execution time of 280 "
          "minutes."]}, IMAGES),
    # a second attempt never re-runs
    (run(2), [job("testlab", "failure", jid=1)], {1: [SHUTDOWN]}, IMAGES),
    # green needs nothing
    (run(conclusion="success"), [job("testlab")], {}, IMAGES),
], ids=["real-red", "lost-plus-real-red", "not-a-dependant", "matrix-sibling",
        "workflow-unreadable", "workflow-not-understood", "started-before-the-loss",
        "cancelled-no-text", "log-only", "our-timeout",
        "attempt-2", "green"])
def test_anything_else_comes_back_as_it_is(first, jobs1, annotations, workflow):
    g = FakeGitHub(first, jobs1, annotations=annotations, workflow=workflow)
    got = g.wait("o/r", 77, 60)
    assert g.posts == []
    assert got == first and "rerun" not in got


def test_a_wait_that_settles_a_run_never_re_runs_it():
    g = FakeGitHub(run(), [job("testlab", "failure", jid=1)], annotations={1: [SHUTDOWN]})
    assert g.wait("o/r", 77, 60, rerun=False)["run_attempt"] == 1
    assert g.posts == []


def test_the_finished_first_attempt_read_after_the_re_run_request_is_not_the_result():
    """GitHub keeps answering with the old attempt until the new one starts."""
    g = FakeGitHub(run(), [job("testlab", "failure", jid=1)], second=run(2, "success"),
                   annotations={1: [SHUTDOWN]}, stale_reads=3)
    assert g.wait("o/r", 77, 600)["run_attempt"] == 2


class Ctx:
    def __init__(self, g):
        self.gh, self.summaries, self.saved = g, [], []

    def summary(self, text):
        self.summaries.append(text)

    def save_attempt(self, number, att):
        self.saved.append((number, list(att.notes)))
        return number


def test_the_judges_accept_the_re_run_and_the_attempt_issue_says_so():
    """The record moves to the attempt that was judged; without that every judge reads the
    re-run as somebody else's execution."""
    jobs = [job("testlab"), job("test (3.11)")]
    g = FakeGitHub(run(), [job("testlab", "failure", jid=1), job("test (3.11)")],
                   second=run(2, "success"), jobs2=jobs, annotations={1: [SHUTDOWN]})
    ctx = Ctx(g)
    at = Attempt(run_id="1", version="0.12.2", base_sha="b" * 40, candidate_sha=CAND,
                 branch="pins/0.12.2-1")
    rec = {"repo": "o/r", "id": 77, "workflow": 42, "attempt": 1, "sha": CAND}
    from bot.cli import _wait
    got = _wait(ctx, rec, 60, at, 9)
    assert rec["attempt"] == 2
    assert _run_problems(ctx, at, "testlab", rec, got, ("testlab", "test (3.11)")) == ([], [], [])
    assert len(at.notes) == 1 and "re-run once" in at.notes[0] and "testlab" in at.notes[0]
    assert ctx.saved == [(9, at.notes)]
    assert ctx.summaries == ["\n" + at.notes[0]]


def test_one_bound_covers_both_attempts(clock):
    """No fresh bound for attempt 2: the stage job's own timeout is around this wait."""
    g = FakeGitHub(run(), [job("testlab", "failure", jid=1)], annotations={1: [SHUTDOWN]},
                   second=run(2, status="in_progress"), stale_reads=0)
    first = g.run
    calls = []

    def slow_first(repo, run_id):
        calls.append(1)
        got = first(repo, run_id)
        return {**got, "status": "in_progress"} if len(calls) < 3 else got
    g.run = slow_first
    got = g.wait("o/r", 77, 200, poll_s=30)       # attempt 1 ends at 60 s: 140 s are left
    assert g.posts == [RERUN]
    assert clock[0] == 210        # the first poll at or past 200 s, not 60 + 200
    assert got.get("timed_out") and got["run_attempt"] == 2 and got["rerun"]["attempt"] == 1


def test_no_re_run_when_less_time_is_left_than_was_already_spent():
    g = FakeGitHub(run(), [job("testlab", "failure", jid=1)], annotations={1: [SHUTDOWN]},
                   second=run(2, "success"))
    first, calls = g.run, []

    def slow_first(repo, run_id):
        calls.append(1)
        got = first(repo, run_id)
        return {**got, "status": "in_progress"} if len(calls) < 5 else got
    g.run = slow_first
    got = g.wait("o/r", 77, 200, poll_s=30)       # attempt 1 ends at 120 s: 80 s are left
    assert g.posts == []
    assert got["run_attempt"] == 1 and "rerun" not in got


def test_a_third_attempt_somebody_else_started_is_not_the_one_judged():
    g = FakeGitHub(run(), [job("testlab", "failure", jid=1)], annotations={1: [SHUTDOWN]},
                   second=run(3, "success"), jobs2=[job("testlab"), job("test (3.11)")])
    rec = {"repo": "o/r", "id": 77, "workflow": 42, "attempt": 1, "sha": CAND}
    at = Attempt(run_id="1", version="0.12.2", base_sha="b" * 40, candidate_sha=CAND,
                 branch="pins/0.12.2-1")
    from bot.cli import _wait
    got = _wait(Ctx(g), rec, 60, at, 9)
    assert rec["attempt"] == 2
    identity, _offlane, _outcome = _run_problems(Ctx(g), at, "testlab", rec, got, ("testlab",))
    assert any("attempt 3" in p for p in identity)


class ArtifactGitHub(ghmod.GitHub):
    """A run's artifact list across attempts, when each attempt started, and what `artifact`
    downloads from it."""

    def __init__(self, starts, artifacts, jobs1=()):
        super().__init__("t")
        self.starts, self.arts, self.jobs1 = starts, artifacts, jobs1

    def get(self, path):
        if path.endswith("/artifacts?per_page=100"):
            return {"artifacts": [{"name": n, "created_at": c, "archive_download_url": c}
                                  for n, c in self.arts]}
        if "/attempts/1/jobs" in path:
            return {"jobs": list(self.jobs1)}
        if "/runs/77/attempts/" in path:
            n = int(path.rsplit("/", 1)[1])
            if n not in self.starts:
                raise ghmod.GitHubError(f"GET {path} -> 404: Not Found")
            return {"id": 77, "run_attempt": n, "run_started_at": self.starts[n]}
        if path.endswith("/runs/77"):
            # What GitHub reports NOW. Never the answer to "which attempt is judged".
            return {"id": 77, "run_attempt": max(self.starts)}
        raise AssertionError(path)

    def _signed_download(self, url):
        return url.encode()           # which upload was taken: its creation time


# attempt 1 of build.yml: build passed at T10-T20 and uploaded at T19; runtime-test lost its
# runner (started T21); publish never ran. Attempt 2 started at T40.
BUILD_ATTEMPT_1 = [job("build", started="T10", completed="T20"),
                   job("runtime-test", "failure", started="T21", completed="T30")]
ONE, TWO, THREE = {1: "T05"}, {1: "T05", 2: "T40"}, {1: "T05", 2: "T40", 3: "T70"}


@pytest.mark.parametrize("starts, judged, arts, taken", [
    (ONE, 1, [("out", "T19")], b"T19"),
    # the re-run job uploaded anew: the newest is attempt 2's
    (TWO, 2, [("out", "T29"), ("out", "T45")], b"T45"),
    # carried over: build was not re-run, its upload predates every failed job
    (TWO, 2, [("out", "T19")], b"T19"),
    # the lost job's own last-moment upload, and no new one: refused
    (TWO, 2, [("out", "T29")], b""),
    # a parallel job that passed but uploaded after a failed job started: unproven, as today
    (TWO, 2, [("out", "T22")], b""),
    (TWO, 2, [("other", "T45")], b""),
    # somebody started attempt 3: the judged attempt 2 keeps its own upload, never attempt 3's
    (THREE, 2, [("out", "T19"), ("out", "T45"), ("out", "T75")], b"T45"),
    (THREE, 2, [("out", "T75")], b""),
    # and attempt 1, judged while attempt 2 exists, is attempt 1's
    (TWO, 1, [("out", "T19"), ("out", "T45")], b"T19"),
], ids=["first-attempt", "re-uploaded", "carried-over", "lost-job-grace-upload",
        "parallel-after-the-loss", "absent", "foreign-attempt-3", "only-attempt-3-uploaded",
        "attempt-1-while-2-exists"])
def test_an_artifact_is_the_judged_attempts_or_absent(starts, judged, arts, taken):
    g = ArtifactGitHub(starts, arts, BUILD_ATTEMPT_1)
    assert g.artifact("o/r", 77, "out", judged) == taken


def test_the_build_evidence_is_read_for_the_attempt_the_record_pins():
    from bot.cli import _candidate_entry

    class Gh:
        def artifact_member(self, repo, run_id, artifact, suffix, attempt):
            self.asked = attempt
            return b""

    class C:
        gh = Gh()
    _candidate_entry(C, {"id": 77, "attempt": 2}, "kiss", CAND)
    assert C.gh.asked == 2


def test_an_unreadable_workflow_re_runs_nothing_even_when_every_failed_job_was_lost():
    for workflow in (None, IMAGES.replace("needs: [lint, precheck]", "needs: ${{ x }}")):
        g = FakeGitHub(run(), [job("build (lite)", "failure", jid=1)],
                       annotations={1: [NOT_ACQUIRED]}, workflow=workflow)
        assert g.wait("o/r", 77, 60)["run_attempt"] == 1
        assert g.posts == []


def test_the_time_spent_classifying_counts_against_the_bound(clock):
    """Attempt 1 ends at 60 s of 200: 140 s left. Reading the annotations then takes 50 s, so
    at the moment of the request 90 s are left against 110 s spent — no re-run."""
    g = FakeGitHub(run(), [job("testlab", "failure", jid=1)], annotations={1: [SHUTDOWN]},
                   second=run(2, "success"))
    first, calls, request = g.run, [], g.request

    def slow_first(repo, run_id):
        calls.append(1)
        got = first(repo, run_id)
        return {**got, "status": "in_progress"} if len(calls) < 3 else got

    def slow_annotations(method, path, *a, **kw):
        if "/annotations" in path:
            clock[0] += 50
        return request(method, path, *a, **kw)
    g.run, g.request = slow_first, slow_annotations
    got = g.wait("o/r", 77, 200, poll_s=30)
    assert g.posts == []
    assert got["run_attempt"] == 1 and "rerun" not in got
