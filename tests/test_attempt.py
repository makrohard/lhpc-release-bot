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
