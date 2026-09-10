"""What counts as proof that THIS candidate is green.

A job name and a green tick are the easiest thing in the world to accept by mistake: the branch
is mutable, a run can be re-run, and a test lane that skipped everything reports success just as
loudly as one that proved something. Each case here is one of those mistakes.
"""
from __future__ import annotations

from bot.attempt import Attempt
from bot.cli import (
    LANE_JOB,
    REQUIRED_TESTLAB,
    _release_case_problems,
    _run_problems,
    required_release_cases,
)


def _all_problems(*a, **kw):
    """All three kinds together — what every case here means by "is this run evidence".
    The split into identity, offlane and outcome matters only where an attribution or a
    baseline verdict depends on it, which their own cases below cover."""
    identity, offlane, outcome = _run_problems(*a, **kw)
    return identity + offlane + outcome


CAND, OTHER = "c" * 40, "9" * 40
REQUIRED = ("test (3.11)", "testlab")


class FakeCtx:
    """Only what `_run_problems` reaches for."""

    def __init__(self, jobs):
        self._jobs = jobs
        self.gh = self

    def jobs(self, repo, run_id, attempt=0):
        return list(self._jobs)


def att():
    return Attempt(run_id="1", version="0.3.7", base_sha="b" * 40, candidate_sha=CAND,
                   branch="pins/0.3.7-1")


def rec(**kw):
    base = {"repo": "o/r", "id": 5, "workflow": 42, "attempt": 1, "sha": CAND}
    base.update(kw)
    return base


def run(**kw):
    base = {"head_sha": CAND, "workflow_id": 42, "run_attempt": 1, "conclusion": "success"}
    base.update(kw)
    return base


def jobs(**over):
    out = [{"name": n, "conclusion": "success", "head_sha": CAND} for n in REQUIRED]
    for job in out:
        job.update(over.get(job["name"], {}))
    return out


def test_a_run_on_the_candidate_with_every_required_job_green_is_proof():
    assert _all_problems(FakeCtx(jobs()), att(), "ci", rec(), run(), REQUIRED) == []


def test_green_jobs_on_another_commit_are_not_proof_of_this_candidate():
    """The counterexample: the branch moved, the checks are green, and they belong to a commit
    this attempt is not about to release."""
    problems = _all_problems(FakeCtx(jobs()), att(), "ci", rec(), run(head_sha=OTHER), REQUIRED)
    assert any("not on the candidate" in p for p in problems)


def test_a_job_that_ran_on_another_commit_is_caught_even_when_the_run_looks_right():
    ctx = FakeCtx(jobs(**{"testlab": {"head_sha": OTHER}}))
    assert any("ran on another commit" in p
               for p in _all_problems(ctx, att(), "ci", rec(), run(), REQUIRED))


def test_a_rerun_is_not_the_execution_this_attempt_started():
    problems = _all_problems(FakeCtx(jobs()), att(), "ci", rec(attempt=1), run(run_attempt=2),
                             REQUIRED)
    assert any("is not the attempt this run started" in p for p in problems)


def test_a_different_workflow_is_not_the_one_dispatched():
    problems = _all_problems(FakeCtx(jobs()), att(), "ci", rec(workflow=42),
                             run(workflow_id=99), REQUIRED)
    assert any("not the workflow" in p for p in problems)


def test_a_missing_required_job_is_not_a_pass():
    ctx = FakeCtx([j for j in jobs() if j["name"] != "testlab"])
    assert any("testlab: did not run" in p
               for p in _all_problems(ctx, att(), "ci", rec(), run(), REQUIRED))


def test_a_skipped_required_job_is_not_a_pass():
    ctx = FakeCtx(jobs(**{"testlab": {"conclusion": "skipped"}}))
    assert any("testlab: skipped" in p
               for p in _all_problems(ctx, att(), "ci", rec(), run(), REQUIRED))


def test_a_timed_out_run_says_so_and_nothing_else():
    assert _all_problems(FakeCtx(jobs()), att(), "ci", rec(), run(timed_out=True),
                         REQUIRED) == ["ci: did not finish within its bound"]


# ---------------------------------------------------------------- the lane's own cases


def junit(cases) -> bytes:
    body = "".join(cases)
    return f'<testsuites><testsuite>{body}</testsuite></testsuites>'.encode()


def case(name, inner=""):
    return f'<testcase name="{name}">{inner}</testcase>'


# The names the CANDIDATE declares. A release is judged against its own list, never a copy here.
REQUIRED_CASES = ["test_release_kiss", "test_release_meshcom", "test_release_meshtastic"]
ALL = [case(n) for n in REQUIRED_CASES]


def test_a_full_set_of_passing_cases_has_no_problems():
    assert _release_case_problems(junit(ALL), REQUIRED_CASES) == ([], [])


def test_a_lane_that_skipped_a_case_did_not_prove_it():
    """A skip is the quietest possible failure: the suite is green and the stack was never
    started."""
    cases = [*ALL[:-1], case("test_release_meshcom", "<skipped/>")]
    unreadable, red = _release_case_problems(junit(cases), REQUIRED_CASES)
    assert not unreadable and any("skipped" in p for p in red), \
        "the evidence was readable, so this is a measured failure, not an unmeasurable one"


def test_a_failed_case_is_reported_even_if_the_job_was_green():
    cases = [*ALL[:-1], case("test_release_meshcom", "<failure/>")]
    unreadable, red = _release_case_problems(junit(cases), REQUIRED_CASES)
    assert not unreadable and any("failed" in p for p in red)


def test_a_renamed_case_no_longer_satisfies_the_gate():
    """The counterexample the count could not see: the same NUMBER of cases, one of them
    replaced, so a stack silently stopped being proved while the lane stayed green."""
    cases = [*ALL[:-1], case("test_release_something_else")]
    unreadable, red = _release_case_problems(junit(cases), REQUIRED_CASES)
    assert not unreadable, "readable evidence that omits a case is a finding about the lane"
    assert any("test_release_meshtastic: the lane did not report it" in p for p in red)


def test_a_lane_that_lost_cases_is_not_proof():
    unreadable, red = _release_case_problems(junit(ALL[:1]), REQUIRED_CASES)
    assert not unreadable
    assert len(red) == 2 and all("did not report it" in p for p in red)


def test_a_candidate_that_states_no_required_cases_is_not_proof():
    """A candidate predating the list cannot be judged by it, and must not pass by default."""
    unreadable, red = _release_case_problems(junit(ALL), [])
    assert any("does not state its required cases" in p for p in unreadable), \
        "no list to judge by is 'could not check', not 'checked and bad'"
    assert red == []


def test_the_required_list_is_read_from_the_candidates_own_file():
    assert required_release_cases('{"required_cases": ["test_release_kiss"]}') == \
        ["test_release_kiss"]
    for junkish in ("", "not json", "{}", '{"required_cases": "kiss"}'):
        assert required_release_cases(junkish) == []


def test_no_junit_at_all_is_not_proof():
    assert _release_case_problems(b"", REQUIRED_CASES) == (
        ["the release lane produced no JUnit — its cases cannot be confirmed"], []), \
        "a missing artifact is unreadable evidence, and never names a red case"


def test_unreadable_junit_is_not_proof():
    unreadable, red = _release_case_problems(b"<not xml", REQUIRED_CASES)
    assert any("could not be read" in p for p in unreadable) and red == []


# ------------------------------------------------------- the credential a mutation needs


def _expiry(hours):
    import datetime as dt
    return (dt.datetime.now(dt.UTC)
            + dt.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S UTC")


def test_a_publishing_run_is_refused_when_the_token_cannot_outlast_it():
    """It is not enough to reach the commit point: a run must have credential left to undo
    itself if the proof fails after it published."""
    from bot.cli import _credential_problem
    assert "expires" in _credential_problem(_expiry(2), "full")
    assert _credential_problem(_expiry(24 * 30), "full") == ""


def test_a_read_only_run_is_never_refused_for_credential_time():
    from bot.cli import _credential_problem
    assert _credential_problem(_expiry(1), "watch-only") == ""
    assert _credential_problem(_expiry(1), "dry-run") == ""


def test_an_absent_or_unreadable_expiry_is_unknown_not_unlimited():
    """Both are allowed through — refusing on an unknown would block every run — but neither is
    reported as 'no expiry'."""
    from bot.cli import _credential_problem
    assert _credential_problem("", "full") == ""
    assert _credential_problem("not a date", "full") == ""


# --------------------------------------------------- the budget against the workflow's own bounds


def test_the_credential_budget_covers_the_workflow_it_is_checked_against():
    """A number that has to agree with a YAML file drifts the moment somebody raises a ceiling.

    This re-derives the serial worst case from the workflow itself: every stage a publishing run
    passes through, the binary build twice because the matrix is `max-parallel: 1` over the two
    stacks the bot can dispatch, and the recovery job, because the budget must cover undoing the
    run as well as finishing it.
    """
    import re
    from pathlib import Path

    from bot.cli import MUTATION_BUDGET_H

    text = (Path(__file__).resolve().parents[1]
            / ".github" / "workflows" / "release.yml").read_text()
    bounds, job = {}, ""
    for line in text.splitlines():
        named = re.fullmatch(r"  ([a-z][a-z-]*):", line)
        if named:
            job = named[1]
        limit = re.fullmatch(r"    timeout-minutes: (\d+)", line)
        if limit and job:
            bounds[job] = int(limit[1])

    # The build runs once per binary stack the bot may dispatch, serially. Two today, because
    # the sources the DAEMON artifact covers are `manual`; assert that rather than trust the
    # comment, since flipping one to `tip` would make the real worst case exceed the budget
    # silently. Named exactly, not matched on "daemon": `src/LoRaHAM_Daemon` is chat's source
    # and no artifact covers it, so tracking that one adds no build. A rename here is a KeyError,
    # which is the loud failure this check wants.
    import tomllib
    policy = tomllib.loads((Path(__file__).resolve().parents[1] / "policy.toml").read_text())
    daemon_artifact_sources = ("src/loraham-daemon", "src/RadioLib")
    movable_daemon = [p for p in daemon_artifact_sources
                      if policy["source"][p].get("track") != "manual"]
    assert not movable_daemon, (
        f"{movable_daemon} became movable, so the bot can dispatch a third binary stack — "
        f"the budget below assumes two")

    serial = ("plan", "prove", "release", "integrate", "image", "finalize", "recover")
    missing = [j for j in (*serial, "build") if j not in bounds]
    assert not missing, f"the workflow no longer declares a bound for {missing}"
    worst = sum(bounds[j] for j in serial) + 2 * bounds["build"]
    assert worst <= MUTATION_BUDGET_H * 60, (
        f"a publishing run can take {worst} min but the budget allows "
        f"{MUTATION_BUDGET_H * 60}: raise MUTATION_BUDGET_H")


def test_every_api_call_the_stages_make_exists():
    """A whole-module invariant with no driven path: `GitHub` is behind one seam, and a stage
    that names a method which is not there fails only when that stage actually runs — which for
    recovery means the one path it exists for. A rename that landed on one side shipped exactly
    that way.
    """
    import re
    from pathlib import Path

    from bot.gh import GitHub

    src = (Path(__file__).resolve().parents[1] / "bot" / "cli.py").read_text()
    called = set(re.findall(r"ctx\.(?:bot_)?gh\.([a-z_]+)\(", src))
    missing = sorted(n for n in called if not hasattr(GitHub, n))
    assert not missing, f"bot/cli.py calls GitHub methods that do not exist: {missing}"
    assert called, "the scan found no API calls at all — it has stopped checking anything"


# ------------------------------------------------- which problems may accompany an attribution
# A red lane is the EXPECTED shape of a stack regression. Anything that questions whether the run
# answers for this candidate is not, and must keep a stack from being named.


def _split(**over):
    ctx = FakeCtx(jobs(**over.pop("jobs", {})))
    return _run_problems(ctx, att(), over.pop("name", "testlab"), rec(), run(**over), REQUIRED)


# ------------------------------------------------- `stage_prove` itself, not only its helper
# The rule "an off-lane red may never permit a freeze" is a SAFETY rule: acting on it wrongly
# holds an upstream project's pin for a breakage it did not cause. It is worth driving the real
# stage for, rather than asserting on the text of the line that implements it.


class _ProveCtx:
    """Only what `stage_prove` reaches for. The GitHub seam is the only thing faked."""

    attempt_id = "1"
    run_url = "https://example.invalid/run/1"

    def __init__(self, *, jobs_by_run):
        from bot.attempt import Attempt
        self.gh = self
        self._jobs_by_run = jobs_by_run
        self.summaries, self.saved = [], []
        self.att = Attempt(run_id="1", version="0.3.7", base_sha="b" * 40, candidate_sha=CAND,
                           branch="pins/0.3.7-1",
                           runs={"ci": {"repo": "o/r", "id": 5, "workflow": 42,
                                        "attempt": 1, "sha": CAND}})

    # --- Ctx
    def find_attempt(self, wanted=""):
        return 7, self.att

    def record_run(self, repo, run_id):
        return {"repo": repo, "id": int(run_id), "workflow": 42, "attempt": 1, "sha": CAND}

    def save_attempt(self, number, att):
        self.saved.append(number)

    def summary(self, text):
        self.summaries.append(text)

    # --- Gh
    def dispatch(self, repo, workflow, ref, inputs=None):
        return 6

    def wait(self, repo, run_id, bound):
        # A run is red whenever any of its jobs is, which is what GitHub does.
        red = any(j["conclusion"] != "success" for j in self._jobs_by_run[int(run_id)])
        return {"head_sha": CAND, "workflow_id": 42, "run_attempt": 1,
                "conclusion": "failure" if red else "success", "html_url": "u"}

    def jobs(self, repo, run_id, attempt=1):
        return list(self._jobs_by_run[int(run_id)])

    def artifact_member(self, repo, run_id, name, member):
        cases = "".join(
            f'<testcase name="{c}">'
            + ('<failure>STACK-REGRESSION stack=kiss phase=start</failure>'
               if c == "test_release_kiss" else "")
            + "</testcase>"
            for c in REQUIRED_CASES)
        return f"<testsuite>{cases}</testsuite>".encode()

    def file_at(self, repo, path, sha):
        import json
        return json.dumps({"required_cases": REQUIRED_CASES})


def _prove(*, ordinary="success"):
    """Drive the real `stage_prove` with the lane red and its blame marker in the JUnit, and the
    ordinary `testlab` job at `ordinary`. Returns the attempt after the stop."""
    import pytest

    from bot import cli
    green = [{"name": n, "conclusion": "success", "head_sha": CAND} for n in cli.REQUIRED_CI]
    lane = [{"name": "testlab", "conclusion": ordinary, "head_sha": CAND},
            {"name": cli.LANE_JOB, "conclusion": "failure", "head_sha": CAND}]
    ctx = _ProveCtx(jobs_by_run={5: green, 6: lane})
    with pytest.raises(cli.Stop):
        cli.stage_prove(ctx)
    return ctx.att


def test_a_lane_regression_alone_names_the_stack_it_blamed():
    """The control. Without it the next case would pass for the wrong reason."""
    assert _prove(ordinary="success").regression == ["kiss"]


def test_an_ordinary_job_red_alongside_the_lane_names_nobody():
    """The safety rule, driven through the real stage. The lane blamed kiss and the marker is
    there to be read — but something outside the lane is broken too, so this run is not evidence
    about kiss, and no pin of anyone's may be held on it."""
    assert _prove(ordinary="failure").regression == [], \
        "a red that the release lane did not produce must never permit a freeze"


def test_the_lane_job_name_is_the_one_the_workflow_declares():
    """The split turns on this exact string. A typo would put the lane's own red into identity
    and silently suppress every attribution again, which no other case here would notice."""
    from pathlib import Path

    from bot.cli import LANE_JOB
    workflow = (Path(__file__).resolve().parents[2] / "lhpc-auto-release-docs"
                / ".github" / "workflows" / "testlab.yml")
    if workflow.exists():                      # the controller checkout is not always beside us
        assert f"\n  {LANE_JOB}:" in workflow.read_text(), \
            f"{LANE_JOB!r} is not a job in the controller's testlab workflow"
    assert LANE_JOB in REQUIRED_TESTLAB, \
        f"{LANE_JOB!r} is not among the required testlab jobs, so its red would never be seen"


def test_only_the_lane_may_be_an_outcome_and_only_when_it_failed():
    """Two rules in one place, because both were wrong once. A job that is not the lane going red
    must suppress attribution, and a CANCELLED lane must too — pytest still writes its JUnit on
    interrupt, so a cancelled run publishes a partial file with a marked failure in it."""
    identity, offlane, outcome = _split(conclusion="failure",
                                       jobs={LANE_JOB: {"conclusion": "failure"}})
    assert outcome and not identity and not offlane

    identity, _offlane, _ = _split(conclusion="cancelled",
                                   jobs={LANE_JOB: {"conclusion": "cancelled"}})
    assert identity, "a cancelled run must not look like a regression"

    _identity, offlane, _ = _split(conclusion="failure",
                                   jobs={"testlab": {"conclusion": "failure"}})
    assert any("testlab" in p for p in offlane), "a red job that is not the lane is not an outcome"


def test_a_red_lane_is_an_outcome_not_a_reason_to_distrust_the_run():
    """The defect this exists for: a failed lane always put a problem in the list, so the "no
    other problems" condition was never true and no failure could ever name its stack."""
    identity, offlane, outcome = _split(conclusion="failure",
                                       jobs={"release-verify": {"conclusion": "failure"}})
    assert identity == [] and offlane == [], (identity, offlane)
    assert outcome, "the lane's own red must still be reported"


def test_a_different_red_job_is_measured_but_never_an_outcome():
    """It is `offlane`, and the distinction is the whole point of the third list. As a MEASURED
    negative it must not make a baseline `unproven`; as a red the lane did not produce, it names
    no stack and so must still keep an attribution from being made."""
    identity, offlane, _outcome = _split(conclusion="failure",
                                         jobs={"test (3.11)": {"conclusion": "failure"}})
    assert any("test (3.11): failure" in p for p in offlane)
    assert identity == [], identity


def test_a_non_lane_job_that_is_merely_cancelled_measured_nothing():
    """`offlane` is for a job that RAN and concluded failure. Cancelled or timed out, it measured
    no more than a cancelled lane did, and must stay in identity or a cancellation would read as
    a broken composition."""
    identity, offlane, _outcome = _split(conclusion="failure",
                                         jobs={"testlab": {"conclusion": "cancelled"}})
    assert offlane == [], offlane
    assert any("testlab: cancelled" in p for p in identity)


def test_a_red_job_that_ran_on_another_commit_measured_nothing_here():
    """The order of the checks decides this, and it was wrong. `ran on another commit` was a later
    branch of the same chain as `conclusion != success`, so a RED job was classified by its
    conclusion and never reached the commit test at all — a job that failed on somebody else's
    commit counted as a measurement of this one. `_verify_baseline` would then have reported the
    held composition broken, and settled the parent, on evidence that answered for nothing."""
    identity, offlane, outcome = _split(
        jobs={"testlab": {"conclusion": "failure", "head_sha": OTHER}})
    assert offlane == [] and outcome == [], (offlane, outcome)
    assert any("testlab: ran on another commit" in p for p in identity), identity


def test_a_timeout_or_a_wrong_commit_stays_identity():
    for over in ({"timed_out": True}, {"head_sha": OTHER}):
        identity, offlane, _outcome = _split(**over)
        assert identity and offlane == [], over


def test_the_artifact_download_never_replays_the_credential_at_the_storage_host(monkeypatch):
    """Two live failures in one path, neither of which a fake can show.

    The artifact endpoint refuses an `Accept` it does not know — `application/zip` is a 415
    before any redirect — and it answers 302 to an ALREADY SIGNED storage URL. Following that
    redirect the ordinary way re-sends `Authorization: Bearer ...`, and the storage host rejects
    it with 401 `InvalidAuthenticationInfo`. So the request itself is what is asserted here: the
    API call must not ask for zip, and the signed fetch must carry no credential at all.
    """
    import io
    import json as _json
    import urllib.error
    import urllib.request

    from bot.gh import GitHub

    api_headers, signed_headers = [], []

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        """The plain opener: the artifacts listing, and the signed download."""
        if req.full_url.endswith("/artifacts?per_page=100"):
            api_headers.append({k.lower(): v for k, v in req.headers.items()})
            return _Resp(_json.dumps({"artifacts": [
                {"name": "out", "archive_download_url": "https://api.example/dl"}]}).encode())
        signed_headers.append({k.lower(): v for k, v in req.headers.items()})
        return _Resp(b"PK\x03\x04zipbytes")

    class _Opener:
        def open(self, req, timeout=None):
            api_headers.append({k.lower(): v for k, v in req.headers.items()})
            raise urllib.error.HTTPError(
                req.full_url, 302, "Found",
                {"Location": "https://storage.example/signed?sig=secret"}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: _Opener())

    blob = GitHub("t" * 20).artifact("o/r", 1, "out")

    assert blob == b"PK\x03\x04zipbytes", "the zip must come back as bytes, not parsed"
    assert all(h.get("accept") != "application/zip" for h in api_headers), \
        "application/zip is exactly what the endpoint refuses"
    assert signed_headers, "the redirect was never followed"
    assert all("authorization" not in h for h in signed_headers), \
        "the signed URL is already a credential; ours must not be replayed at that host"


def test_every_job_after_release_survives_a_skipped_build():
    """`build` is SKIPPED on every release that moves no binary-covered pin, and GitHub
    propagates a skip down the chain to any job whose `if` keeps the implicit `success()`.

    v0.3.14 proved it the expensive way: the controller released, the image was cut, and `dev`
    was silently left behind because `integrate` never ran. Every job after `release` therefore
    needs a status function — and `!cancelled()` rather than `always()`, so a cancelled run does
    not fast-forward `dev` or close an attempt behind the operator's back.
    """
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1]
            / ".github" / "workflows" / "release.yml").read_text()
    jobs = dict(re.findall(r"^  ([a-z][a-z-]*):\n(.*?)(?=^  [a-z][a-z-]*:\n|\Z)",
                           text, re.S | re.M))
    for name in ("integrate", "image", "finalize"):
        body = jobs[name]
        cond = re.search(r"^    if: (.+)$", body, re.M)
        assert cond, f"{name} has no `if`, so a skipped `build` will skip it"
        assert "!cancelled()" in cond[1], (
            f"{name} must survive a SKIPPED build without also running on a CANCELLED run — "
            f"`always()` does the first and the second: {cond[1]}")
        assert "needs.release.result == 'success'" in cond[1], (
            f"{name} must still refuse to run when the release itself did not happen")


def test_the_held_baseline_is_dispatched_at_a_ref_not_a_commit():
    """`workflow_dispatch` resolves a branch or a tag and refuses a bare commit with
    `No ref found for: …`. Dispatching the captured SHA meant the frozen-only proof could not
    start — which only showed the first time that branch ran against real GitHub, because every
    test here fakes the dispatch.

    The binding is unaffected: the run is still checked against the SHA captured before it.
    """
    import inspect

    from bot import cli
    src = inspect.getsource(cli._verify_baseline)
    call = src[src.index("ctx.gh.dispatch("):]
    call = call[:call.index(")") + 1]
    assert "baseline" not in call, f"a commit SHA cannot be dispatched: {call}"
    assert "ref," in call, f"dispatch at the ref that was passed in: {call}"
    assert 'Attempt(run_id=ctx.run_id, candidate_sha=baseline)' in src, \
        "the identity must still be asked of the captured commit, not of whatever the ref is now"
    assert "def _verify_baseline(ctx: Ctx, frozen, ref: str)" in inspect.getsource(cli), \
        "the ref is passed in from the parent's record, not resolved from this run's environment"


def test_unreadable_and_red_are_never_both_reported():
    """The contract every caller leans on: reading has to succeed before there is anything to
    judge, so a non-empty `red` is by itself proof that the evidence was readable. Without it,
    `lane_only` would need its own guard to keep an unreadable artifact from blaming upstream."""
    for xml, required in ((b"", REQUIRED_CASES), (b"<not xml", REQUIRED_CASES),
                          (junit(ALL), []), (junit(ALL), REQUIRED_CASES),
                          (junit([*ALL[:-1], case("test_release_meshcom", "<failure/>")]),
                           REQUIRED_CASES)):
        unreadable, red = _release_case_problems(xml, required)
        assert not (unreadable and red), f"both reported for {xml[:20]!r}"
