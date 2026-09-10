"""Which upstream commit this bot is allowed to move a pin to — and when it must refuse.

Every case here is a way a pin could move to something nobody proved: a prerelease, a tag that
left the branch, a rewritten history, an orphaned pin. The remote is a fake, so the rules are
tested rather than GitHub.
"""
from __future__ import annotations

import pytest

from bot.manifest import Source
from bot.upstream import Finding, examine, examine_extra, newest_version_tag, policy_gaps


class FakeRemote:
    """A branch as a straight line of commits, plus tags and releases on it."""

    def __init__(self, line, tags=None, releases=None, side=None):
        self.line = list(line)
        self.tag_map = dict(tags or {})
        self.releases = list(releases or [])
        # A side branch: commits that descend from a point on the line but are not ON it.
        self.side = dict(side or {})       # sha -> the line commit it forked from

    def branch_tip(self, remote, branch):
        return self.line[-1]

    def tags(self, remote, branch):
        return list(self.tag_map)

    def commit_of_tag(self, remote, branch, tag):
        return self.tag_map[tag]

    def has_commit(self, remote, branch, sha):
        return sha in self.line or sha in self.side

    def is_ancestor(self, remote, branch, a, b):
        if b in self.side:                      # only its fork point precedes a side commit
            return a in self.line and self.line.index(a) <= self.line.index(self.side[b])
        if a in self.side or a not in self.line or b not in self.line:
            return False
        return self.line.index(a) <= self.line.index(b)

    def describe(self, remote, branch, sha):
        return f"g{sha[:7]}"

    def latest_release(self, repo):
        return self.releases[0] if self.releases else {}

    def latest_pypi(self, package):
        return "9.9.9"


def src(pin, **kw):
    return Source(path=kw.get("path", "src/thing"), pin=pin, tag=kw.get("tag", ""),
                  remote=kw.get("remote", "https://github.com/o/r.git"),
                  branch=kw.get("branch", "main"), consumers=("thing",))


A, B, C = "a" * 40, "b" * 40, "c" * 40
OFF = "d" * 40


def test_newest_version_tag_ignores_snapshots_and_prereleases():
    tags = ["v1.2", "v2.7.26.54e0d8d", "1.5.2", "1.8.2-pre", "v112", "nightly"]
    assert newest_version_tag(tags) == "v112"
    assert newest_version_tag(["1.5.1", "1.5.2", "1.4.9"]) == "1.5.2"
    assert newest_version_tag(["nightly", "latest"]) == ""


def test_tip_tracking_moves_forward_only():
    r = FakeRemote([A, B, C])
    f = examine(src(A), {"track": "tip"}, r)
    assert f.status == "move" and f.candidate == C


def test_a_pin_already_at_the_tip_is_not_a_move():
    r = FakeRemote([A, B, C])
    assert examine(src(C), {"track": "tip"}, r).status == "at-pin"


def test_a_rewritten_history_is_a_fault_not_a_move():
    """The pin is no longer on the branch: a force-push orphaned it. Building a release on a
    commit nobody can fetch is exactly what CI's pin validation exists to stop."""
    r = FakeRemote([B, C])                       # A is gone
    f = examine(src(A), {"track": "tip"}, r)
    assert f.status == "fault" and "not on its branch" in f.detail


def test_a_candidate_that_is_not_a_descendant_is_a_fault():
    f = examine(src(C), {"track": "tag"}, FakeRemote([A, B, C], tags={"v1.0": A}))
    assert f.status == "fault" and "descendant" in f.detail


def test_a_tag_on_a_side_branch_is_a_fault_even_though_it_descends_from_the_pin():
    """The candidate is a real descendant of the pin, so the first guard passes — but it is not
    on the branch the manifest declares, and installing it would install something the declared
    branch never carried."""
    r = FakeRemote([A, B, C], tags={"v2.0": OFF}, side={OFF: A})
    f = examine(src(A), {"track": "tag"}, r)
    assert f.status == "fault" and "not on the declared branch" in f.detail


def test_release_tracking_uses_the_newest_non_prerelease():
    r = FakeRemote([A, B, C], tags={"v2.7.26": B, "v2.8.0": C},
                   releases=[{"tag": "v2.7.26"}])
    f = examine(src(A), {"track": "release"}, r)
    assert f.status == "move" and f.candidate == B and f.tag == "v2.7.26"


def test_no_release_at_all_is_a_fault_never_a_silent_tip_move():
    r = FakeRemote([A, B, C], releases=[])
    assert examine(src(A), {"track": "release"}, r).status == "fault"


def test_manual_reports_movement_without_moving():
    r = FakeRemote([A, B, C])
    f = examine(src(A), {"track": "manual", "why": "needs a radio"}, r)
    assert f.status == "manual" and not f.moves
    assert "needs a radio" in f.detail and "has moved" in f.detail


def test_an_unknown_track_is_a_fault():
    assert examine(src(A), {"track": "whatever"}, FakeRemote([A])).status == "fault"


def test_policy_must_cover_exactly_the_pinned_sources():
    policy = {"source": {"src/a": {}, "src/gone": {}}}
    gaps = policy_gaps(policy, ["src/a", "src/new"])
    assert any("src/new" in g and "absent from policy" in g for g in gaps)
    assert any("src/gone" in g and "no longer pinned" in g for g in gaps)
    assert policy_gaps({"source": {"src/a": {}}}, ["src/a"]) == []


def test_an_extra_input_marked_manual_is_reported_not_moved():
    f = examine_extra("meshtastic-cli", {"kind": "pypi", "package": "meshtastic",
                                         "track": "manual", "why": "by hand"},
                      "2.7.11", FakeRemote([A]))
    assert f.status == "manual" and f.candidate == "9.9.9" and not f.moves


def test_an_extra_release_input_moves_when_it_tracks_releases():
    f = examine_extra("graywolf", {"kind": "github-release", "repo": "o/r",
                                   "track": "release"}, "0.14.12",
                      FakeRemote([A], releases=[{"tag": "v0.14.13"}]))
    assert f.status == "move" and f.candidate == "0.14.13"


def test_an_older_release_than_the_pin_is_a_fault_not_a_downgrade():
    """GitHub lists releases newest-CREATED first, so a hotfix cut on an older line after a
    newer major is the first non-draft entry. A git source gets a hard fault for the same shape
    (the candidate must descend from the pin); this one had no such rule and would have written
    the downgrade into the manifest as an ordinary move."""
    f = examine_extra("graywolf", {"kind": "github-release", "repo": "o/r",
                                   "track": "release"}, "0.15.0",
                      FakeRemote([A], releases=[{"tag": "v0.14.13"}]))
    assert f.status == "fault" and not f.moves
    assert "behind the pinned 0.15.0" in f.detail


def test_a_version_that_cannot_be_ordered_is_a_fault():
    """A pin the bot cannot compare is a pin it must not move on its own."""
    f = examine_extra("graywolf", {"kind": "github-release", "repo": "o/r",
                                   "track": "release"}, "0.14.12",
                      FakeRemote([A], releases=[{"tag": "nightly"}]))
    assert f.status == "fault" and "not a dotted numeric version" in f.detail


def test_a_newer_release_is_still_an_ordinary_move():
    f = examine_extra("graywolf", {"kind": "github-release", "repo": "o/r",
                                   "track": "release"}, "0.14.13",
                      FakeRemote([A], releases=[{"tag": "v0.15.0"}]))
    assert f.status == "move" and f.candidate == "0.15.0"


def test_an_input_owned_by_another_pin_is_never_moved_on_its_own():
    f = examine_extra("qemu-esp", {"kind": "owned-by-pin", "owner": "src/x"}, "", FakeRemote([A]))
    assert f.status == "manual" and "src/x" in f.detail


@pytest.mark.parametrize("status", ["at-pin", "manual", "fault"])
def test_only_a_move_is_a_move(status):
    assert not Finding(key="k", track="tip", status=status).moves
