"""The attempt record: what a run owes the world, and what a recovery is allowed to undo.

This is the part that decides whether a failed run leaves the last release intact. Each case
here is a way the run could lose track of what it already did: a lost reply, a cancelled job, a
released controller whose image never came, a record that has to survive longer than any run
artifact does, or a record nobody can read.
"""
from __future__ import annotations

import pytest

from bot.attempt import Attempt, Unreadable, blocks_new_release, recovery_decision

CAND, OTHER = "c" * 40, "9" * 40
ENTRY = {"sha256": "a" * 64, "filename": "meshtastic-x.tar.zst"}


def att(**kw) -> Attempt:
    base = {"run_id": "1", "version": "0.3.6", "base_sha": "b" * 40, "candidate_sha": CAND,
            "branch": "pins/0.3.6-1"}
    base.update(kw)
    return Attempt(**base)


def test_a_record_survives_a_round_trip_through_an_issue_body():
    """The record lives in an issue because an issue never expires — a run artifact does, and a
    recovery may happen long after the run that needs it."""
    a = att(state="mutated", published={"meshtastic": ENTRY}, dispatched=["meshtastic"],
            index_snapshot={"schema": 2, "stacks": {}},
            runs={"ci": {"repo": "o/r", "id": 1, "workflow": 2, "attempt": 1, "sha": CAND}})
    assert Attempt.from_body(a.to_body()) == a


def test_a_body_with_no_record_is_absent_but_an_unreadable_one_raises():
    """The distinction the whole recovery rests on: nothing was written here, versus something
    was written and cannot be read. The second must never be treated as the first."""
    assert Attempt.from_body("just a human wrote here") is None
    assert Attempt.from_body("") is None
    with pytest.raises(Unreadable):
        Attempt.from_body("<!--attempt\nnot json\n-->")
    with pytest.raises(Unreadable):
        Attempt.from_body('<!--attempt\n{"state": "mutated", "run_id": "7"}\n-->')


def test_a_record_must_carry_what_its_own_state_needs():
    with pytest.raises(Unreadable, match="index_snapshot"):
        att(state="mutated").validate()
    with pytest.raises(Unreadable, match="branch"):
        att(state="prepared", branch="").validate()
    with pytest.raises(Unreadable, match="image_tag"):
        att(state="image-published").validate()
    with pytest.raises(Unreadable, match="not a commit sha"):
        att(candidate_sha="abc").validate()
    with pytest.raises(Unreadable, match="unknown attempt state"):
        att(state="halfway").validate()


@pytest.mark.parametrize("state,unresolved", [
    ("prepared", True), ("mutated", True), ("released", True), ("integrated", True),
    ("image-published", True), ("complete", False), ("restored", False)])
def test_only_a_finished_attempt_stops_blocking_the_next_release(state, unresolved):
    """`released` is NOT finished: the image is still owed, and the image builder resolves
    `main` — so another release would make that image impossible to cut."""
    a = att(state=state, index_snapshot={"stacks": {}}, image_tag="v0.3.6")
    assert a.unresolved is unresolved
    assert blocks_new_release(a) is unresolved


def test_a_released_attempt_owes_both_integration_and_the_image():
    """Neither stage may declare the attempt finished on its own. An image that succeeded over
    a failed integration would close the only record the repair path can find."""
    assert att(state="released").owes == ["dev integration", "the image"]
    assert att(state="released", integration="fast-forward").owes == ["the image"]
    assert att(state="image-published", image_tag="v0.3.6").owes == ["dev integration"]
    assert att(state="image-published", image_tag="v0.3.6", integration="pr:12").owes == []
    assert att(state="prepared").owes == []          # nothing is owed before the commit point


def test_an_accepted_push_whose_reply_was_lost_is_still_a_release():
    """The job died before it could record `released`, but `main` is the candidate. Rolling the
    binaries back here would point every self-updating box at an index that cannot satisfy the
    release they just took."""
    a = att(state="mutated", published={"meshtastic": ENTRY}, dispatched=["meshtastic"],
            index_snapshot={"stacks": {}})
    assert recovery_decision(a, CAND, "", released_here=False) == "released"
    assert recovery_decision(a, OTHER, CAND, released_here=True) == "released"


def test_a_tag_of_the_same_name_on_another_commit_is_a_conflict_not_a_release():
    """Somebody else took the version. Neither undoing our binaries nor claiming their release
    is right; the attempt stays open for a person."""
    a = att(state="mutated", published={"meshtastic": ENTRY}, dispatched=["meshtastic"],
            index_snapshot={"stacks": {}})
    assert recovery_decision(a, OTHER, OTHER, released_here=False) == "conflict"


def test_a_dispatch_with_no_recorded_outcome_still_means_restore():
    """A publish was STARTED. That its result was never written down is not evidence that it
    did not happen, so the recovery must go and look rather than take the clean path."""
    a = att(state="mutated", dispatched=["meshtastic"], index_snapshot={"stacks": {}})
    assert recovery_decision(a, OTHER, "", released_here=False) == "restore"


def test_a_run_that_started_no_publish_only_has_a_branch_to_remove():
    assert recovery_decision(att(state="prepared"), OTHER, "", released_here=False) == "clean"


def test_an_open_attempt_names_the_two_commands_that_close_it():
    """The issue is what a maintainer reads at 22:00 on a Monday. Assert the command tokens it
    must offer, not the prose around them."""
    body = att(state="mutated", index_snapshot={"stacks": {}}).to_body()
    human = body.split("<!--attempt")[0]
    assert "finish" in human and "recover" in human
    assert "finish" not in att(state="complete").to_body().split("<!--attempt")[0]


def test_the_body_says_what_a_released_attempt_still_owes():
    human = att(state="released").to_body().split("<!--attempt")[0]
    assert "dev integration" in human and "the image" in human


def test_a_labelled_issue_with_no_readable_record_is_not_silence():
    """The label IS the assertion that a record was written. Dropping such an issue as "nothing
    here" defeated the distinction the design rests on: nothing was written is not the same as
    something was written and cannot be read. Dropped, it blocked no release and could be
    addressed by neither repair mode."""
    from bot.attempt import record_of_labelled_issue
    for body in ("", "a person opened this by hand", "<!--attempt {\"run_id\": \"1\"}"):
        with pytest.raises(Unreadable, match="label but no attempt record"):
            record_of_labelled_issue(7, body)


def test_a_mutated_record_must_say_what_it_dispatched():
    """"Mutated" MEANS a publish was started, so an empty `dispatched` describes something that
    cannot have happened. Such a record used to validate and then recover as "clean" — a publish
    that was started, undone as if it never was."""
    att = Attempt(run_id="1", state="mutated", version="0.3.9", base_sha="a" * 40,
                  candidate_sha="b" * 40, branch="pins/x", index_snapshot={"stacks": {}})
    with pytest.raises(Unreadable, match="dispatched"):
        att.validate()
    att.dispatched = ["meshtastic"]
    att.validate()


# ---- the automatic `finish` of a released attempt that owes only integration and the image ----

class _PlanCtx:
    """Only what `stage_plan` reaches for before the blocking check."""
    token, mode, retry_of, run_id = "t" * 20, "full", "", "5000"

    def __init__(self, att, dispatch_error=None, finish=None):
        self.att, self.saved, self.sent, self.summaries = att, [], [], []
        self.gh = self.bot_gh = self
        self._error, self._finish = dispatch_error, finish or {"status": "in_progress"}

    # Ctx
    def open_attempts(self):
        return [(7, self.att)]

    def save_attempt(self, number, att):
        self.saved.append(att.finish_run)
        return number

    def summary(self, text):
        self.summaries.append(text)

    def out(self, **kv):
        pass

    # GitHub
    def whoami(self):
        return {"login": "bot"}

    def token_expiry(self):
        return ""

    def get(self, path):
        return {}

    def run(self, repo, run_id):
        return dict(self._finish, id=run_id)

    def dispatch(self, repo, workflow, ref, inputs=None):
        self.sent.append(inputs)
        if self._error:
            raise self._error
        return 8123


def _owing(**over):
    base = {"run_id": "4000", "state": "released", "version": "0.12.10", "base_sha": "b" * 40,
            "candidate_sha": "c" * 40, "branch": "pins/0.12.10-4000", "image_tag": "",
            "integration": ""}
    return Attempt(**{**base, **over})


def test_an_attempt_owing_only_integration_and_image_is_finished_once():
    from bot import cli
    ctx = _PlanCtx(_owing())
    assert cli.stage_plan(ctx) == 0
    assert ctx.sent == [{"mode": "finish", "attempt": "4000"}]
    assert ctx.saved == ["dispatching:5000", "8123"]          # claimed before the send
    second = _PlanCtx(ctx.att)                                 # the next scheduled run
    assert cli.stage_plan(second) == 0 and second.sent == []


def test_a_claim_without_a_run_id_stops_naming_its_claimant_and_sends_nothing():
    # A green weekly run beside a claim nobody will ever resolve would hide it for good.
    from bot import cli
    ctx = _PlanCtx(_owing(finish_run="dispatching:4999"))
    with pytest.raises(cli.Stop) as stop:
        cli.stage_plan(ctx)
    assert ctx.sent == [] and "4999" in stop.value.observed


@pytest.mark.parametrize("conclusion", ["failure", "success", "cancelled"])
def test_a_finish_run_that_ended_with_the_attempt_still_owing_stops(conclusion):
    from bot import cli
    ctx = _PlanCtx(_owing(finish_run="8123"),
                   finish={"status": "completed", "conclusion": conclusion})
    with pytest.raises(cli.Stop) as stop:
        cli.stage_plan(ctx)
    assert ctx.sent == [] and "8123" in stop.value.observed and conclusion in stop.value.observed


def test_a_refused_finish_dispatch_releases_its_claim():
    from bot import cli
    from bot.gh import GitHubError
    ctx = _PlanCtx(_owing(), dispatch_error=GitHubError("POST /repos/o/r/… -> 422: bad input"))
    with pytest.raises(cli.Stop):
        cli.stage_plan(ctx)
    assert ctx.att.finish_run == "" and ctx.saved == ["dispatching:5000", ""]


@pytest.mark.parametrize("said", ["POST /repos/o/r/… -> <urlopen error timed out>",
                                  "POST /repos/o/r/… -> 502: bad gateway"])
def test_a_finish_dispatch_that_may_have_been_accepted_keeps_its_claim(said):
    # The request may have started a run whose reply was lost: never send a second one.
    from bot import cli
    from bot.gh import GitHubError
    ctx = _PlanCtx(_owing(), dispatch_error=GitHubError(said))
    with pytest.raises(cli.Stop):
        cli.stage_plan(ctx)
    assert ctx.att.finish_run == "dispatching:5000"
    later = _PlanCtx(ctx.att)
    with pytest.raises(cli.Stop):
        cli.stage_plan(later)
    assert later.sent == []

# ---- one unreachable upstream does not stop the others from moving ----

class _Reached(Exception):
    """Raised where the plan goes on to claim and build: it got past the fault gate."""


def test_an_unreachable_source_beside_a_move_is_reported_and_the_plan_goes_on(tmp_path,
                                                                              monkeypatch):
    from bot import cli
    from bot.upstream import examine
    from tests.test_upstream import A, B, FakeRemote, _Unreadable, src
    unreachable = _Unreadable("git -C x fetch -q --tags origin main: fatal: unable to access "
                              "'https://h/': Could not resolve host: h")
    found = [examine(src(A, path="src/a"), {"track": "tip"}, unreachable),
             examine(src(A, path="src/b"), {"track": "tip"}, FakeRemote([A, B]))]
    (tmp_path / "loraham-pi-control").mkdir()
    (tmp_path / "loraham-pi-control" / cli.MANIFEST.split("/")[-1]).write_text("")
    monkeypatch.setattr(cli, "MANIFEST", cli.MANIFEST.split("/")[-1])
    monkeypatch.setattr(cli, "git", lambda *a, **k: "b" * 40)
    monkeypatch.setattr(cli, "_findings", lambda ctx, text, policy: (found, None))
    def note(ctx, kind, seen, examined):
        ctx.degraded.append((kind, sorted(seen), sorted(examined)))
    monkeypatch.setattr(cli, "_degraded", note, raising=False)       # absent before the change
    monkeypatch.setattr(cli, "_check_parent", lambda ctx, frozen: (_ for _ in ()).throw(_Reached))
    ctx = _PlanCtx(_owing(state="complete"))
    ctx.degraded = []
    ctx.clone = lambda repo, ref="", token="": tmp_path / "loraham-pi-control"
    ctx.ref = lambda repo, ref: "d" * 40
    with pytest.raises(_Reached):
        cli.stage_plan(ctx)
    assert any("Not reachable this run" in s and "`src/a`" in s for s in ctx.summaries)
    assert ctx.degraded == [("source", ["src/a"], ["src/a", "src/b"])]
