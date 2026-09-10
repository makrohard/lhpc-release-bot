"""Holding one input while the rest keep moving.

A freeze exists for one situation: an upstream regression is unresolved, a tested revision is
already pinned, and the maintainer wants everything else to carry on releasing. So the cases that
matter are the ones where a hold must NOT spread — it must not stop unrelated changes, and it must
not quietly become a fault when upstream is unreachable.
"""
from __future__ import annotations

import pytest

from bot.cli import binary_rebuilds
from bot.upstream import Finding, examine, examine_extra, freeze_of, policy_gaps

from .test_upstream import A, B, FakeRemote, src

HELD = "Upstream startup regression; hold the tested revision."


# ------------------------------------------------------------------ what a hold may say

@pytest.mark.parametrize("rule,problem", [
    ({"track": "tip", "freeze": True}, "nonblank reason"),
    ({"track": "tip", "freeze": ""}, "nonblank reason"),
    ({"track": "tip", "freeze": "   "}, "nonblank reason"),
    ({"track": "manual", "freeze": HELD}, "never moved anyway"),
    ({"kind": "owned-by-pin", "owner": "src/o", "freeze": HELD}, "freeze its owner"),
])
def test_a_hold_that_would_hold_nothing_is_refused(rule, problem):
    """`freeze = true` tells a maintainer nothing months later, and a hold on a manual or a
    derived input reads as though it were doing something while it is not."""
    assert problem in freeze_of(rule, "src/x")[1]


def test_a_malformed_hold_stops_the_run_before_any_mutation():
    """It decides whether an input moves, so it is never guessed at — the same gate that stops a
    pin with no rule at all."""
    gaps = policy_gaps({"source": {"src/a": {"track": "tip", "freeze": 1}}}, ["src/a"])
    assert any("nonblank reason" in g for g in gaps)


def test_an_ordinary_policy_still_reports_no_gap():
    assert policy_gaps({"source": {"src/a": {"track": "tip", "freeze": HELD}}}, ["src/a"]) == []


# ------------------------------------------------------------------ what a hold does

def test_a_frozen_source_with_an_update_waiting_is_never_a_move():
    f = examine(src(A), {"track": "tip", "freeze": HELD}, FakeRemote([A, B]))
    assert f.status == "frozen" and not f.moves
    assert HELD in f.detail and "has moved" in f.detail


def test_a_frozen_source_keeps_its_track_so_thawing_is_one_deleted_line():
    f = examine(src(A), {"track": "tip", "freeze": HELD}, FakeRemote([A, B]))
    assert f.track == "tip"


def test_removing_the_hold_restores_the_ordinary_candidate():
    f = examine(src(A), {"track": "tip"}, FakeRemote([A, B]))
    assert f.status == "move" and f.candidate == B


def test_an_unreadable_upstream_keeps_the_hold_instead_of_becoming_a_fault():
    """A transient lookup failure on a held input must not block every unrelated change in the
    same run."""
    class Broken(FakeRemote):
        def branch_tip(self, remote, branch):
            raise RuntimeError("network down")

    f = examine(src(A), {"track": "tip", "freeze": HELD}, Broken([A]))
    assert f.status == "frozen" and HELD in f.detail and "not readable" in f.detail


def test_a_frozen_extra_with_a_newer_release_is_held_not_moved():
    """A newer release is information, not evidence that the problem being waited on is fixed."""
    f = examine_extra("graywolf", {"kind": "github-release", "repo": "o/r", "track": "release",
                                   "freeze": HELD}, "0.14.12",
                      FakeRemote([A], releases=[{"tag": "v0.14.13"}]))
    assert f.status == "frozen" and not f.moves and "0.14.13" in f.detail


def test_a_frozen_extra_survives_an_unreadable_upstream():
    class Broken(FakeRemote):
        def latest_release(self, repo):
            raise RuntimeError("rate limited")

    f = examine_extra("graywolf", {"kind": "github-release", "repo": "o/r", "track": "release",
                                   "freeze": HELD}, "0.14.12", Broken([A]))
    assert f.status == "frozen" and HELD in f.detail


# ------------------------------------------------------------------ what a hold must not spread to

def test_a_held_input_drives_no_binary_rebuild():
    """The whole point: only eligible movement causes work. A frozen web client must not
    republish an artifact, because nothing about it changed."""
    held = Finding(key="extra.meshtastic-web", track="release", status="frozen",
                   current="2.7.2", candidate="2.7.3")
    assert not held.moves
    assert binary_rebuilds({"meshtastic": ("meshtastic",)}, [f for f in [held] if f.moves]) == []


def test_only_the_unfrozen_input_of_a_mixed_run_is_eligible():
    findings = [examine(src(A, path="src/held"), {"track": "tip", "freeze": HELD},
                        FakeRemote([A, B])),
                examine(src(A, path="src/free"), {"track": "tip"}, FakeRemote([A, B]))]
    moved = [f for f in findings if f.moves]
    assert [f.key for f in moved] == ["src/free"]
