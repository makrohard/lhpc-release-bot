"""The web-client stage: which channel needs a build, and what a failure leaves behind.

The decision is the controller's own reader (the FIRST entry of the channel on the daemon's pin),
so an entry farther down the history never counts as built. A failure is a `degraded web` issue
under one of four keys, closed only by a run that examined that key and found it healthy.
"""
from __future__ import annotations

import json

import pytest

from bot import cli, web
from bot import manifest as mf

P, Q = "1" * 40, "2" * 40                  # meshtasticd pins
A, B, C = "a" * 40, "b" * 40, "c" * 40     # web commits
MAIN = "f" * 40


def _e(channel, commit, pin=P):
    return {"channel": channel, "components": {"meshtastic-web": commit, "meshtastic": pin}}


# ---- the decision ----

@pytest.mark.parametrize("want, entries, expected", [
    ({"dev": A, "stable": B}, [_e("dev", A), _e("stable", B)], []),                       # nothing to do
    ({"dev": C, "stable": B}, [_e("dev", A), _e("stable", B)], ["dev"]),                  # head moved
    ({"dev": A, "stable": C}, [_e("dev", A), _e("stable", B)], ["stable"]),               # new release
    ({"dev": A, "stable": B}, [_e("dev", A, Q), _e("stable", B, Q)], ["dev", "stable"]),  # pin moved
    ({"dev": A, "stable": A}, [_e("dev", A)], ["stable"]),                # release == head: per channel
    ({"dev": A, "stable": B}, [_e("dev", C), _e("dev", A), _e("stable", B)], ["dev"]),    # SHADOWED
    ({"dev": A, "stable": B}, [_e("dev", C, Q), _e("dev", A), _e("stable", B)], []),      # other pin ahead
    ({"dev": A}, [_e("dev", A)], []),                                     # stable not read: undecided
    ({}, [], []),                                                         # nothing read
], ids=["nothing", "head-moved", "new-release", "pin-moved", "release-is-head", "shadowed",
        "other-pin-ahead", "stable-unread", "none-read"])
def test_a_channel_is_built_when_the_entry_boxes_select_is_not_the_wanted_one(want, entries, expected):
    assert web.web_dispatches(P, want, entries, True) == expected


def test_a_shadowed_build_is_not_already_built():
    # The wanted composition IS in the history, behind a newer same-channel, same-pin entry: an
    # "any entry matches" rule says nothing to do, while every box keeps taking the newer one.
    entries = [_e("dev", C), _e("dev", A)]
    assert any(e["components"]["meshtastic-web"] == A for e in entries)
    assert web.selected(entries, "dev", P)["components"]["meshtastic-web"] == C
    assert web.web_dispatches(P, {"dev": A}, entries, True) == ["dev"]


def test_no_daemon_entry_builds_nothing():
    assert web.web_dispatches(P, {"dev": A, "stable": B}, [], False) == []
    assert web.has_daemon_entry([{"components": {"meshtastic": P}}], P)
    assert not web.has_daemon_entry([{"components": {"meshtastic": Q}}], P)


def test_the_read_back_wants_exactly_the_composition():
    assert web.is_current([_e("dev", A)], "dev", P, A)
    extra = {"channel": "dev", "components": {"meshtastic-web": A, "meshtastic": P, "x": B}}
    assert not web.is_current([extra], "dev", P, A)
    assert not web.is_current([_e("stable", A)], "dev", P, A)


@pytest.mark.parametrize("out, expected", [
    (f"{A}\trefs/tags/v2.7.2\n{B}\trefs/tags/v2.7.2^{{}}\n", B),       # annotated: the peeled commit
    (f"{A}\trefs/tags/v2.7.2\n", A),                                    # lightweight
    (f"{A}\trefs/tags/v2.7.20\n", None),                                # a longer tag name only
    ("", None),
])
def test_the_release_commit_is_the_peeled_tag(out, expected):
    assert web.peeled_commit(out, "v2.7.2") == expected


def test_the_daemon_pin_is_read_from_the_manifest():
    text = (f'[[stack]]\nid = "meshtastic"\n[[stack.component]]\nid = "meshtastic"\n'
            f'[stack.component.source]\npin_commit = "{P}"\n')
    assert mf.component_pin(text, "meshtastic") == P
    with pytest.raises(mf.Unreadable):
        mf.component_pin(text, "meshtastic-web")


# ---- the stage: dispatch, read-back and the four keys ----

MANIFEST = (f'[[stack]]\nid = "meshtastic"\n[[stack.component]]\nid = "meshtastic"\n'
            f'[stack.component.source]\npin_commit = "{P}"\n')


class _GH:
    def __init__(self, web_entries, daemon=True, index_ok=True, publish=None, conclusion="success"):
        self.index = {"schema": 3, "stacks": {
            "meshtastic": [{"components": {"meshtastic": P}}] if daemon else [],
            "meshtastic-web": list(web_entries)}}
        self.index_ok, self.publish, self.conclusion = index_ok, publish or {}, conclusion
        self.dispatched, self.release_tag = [], "v2.7.2"

    def ref(self, repo, ref):
        return MAIN

    def file_at(self, repo, path, ref):
        assert ref == MAIN
        return MANIFEST

    def release_asset(self, repo, tag, name):
        if not self.index_ok:
            raise cli.GitHubError("GET index-v3.json -> 502")
        return json.dumps(self.index).encode()

    def get(self, path):
        if self.release_tag is None:
            raise cli.GitHubError("GET releases/latest -> 503")
        return {"tag_name": self.release_tag}

    def dispatch(self, repo, workflow, ref, inputs):
        self.dispatched.append(inputs)
        return 100 + len(self.dispatched)

    def wait(self, repo, run_id, timeout_s):
        ch = self.dispatched[run_id - 101]["channel"]
        if self.conclusion == "success" and ch in self.publish:
            self.index["stacks"]["meshtastic-web"].insert(0, _e(ch, self.publish[ch]))
        return {"conclusion": self.conclusion, "status": "completed", "html_url": f"run/{run_id}"}


class _Ctx:
    def __init__(self, gh, store=None):
        self.gh, self.bot_gh = gh, store
        self.run_id, self.run_url = "r1", "https://example.invalid/run/r1"

    def summary(self, text):
        print(text)


@pytest.fixture
def upstream(monkeypatch):
    """Upstream `main` = A, newest release v2.7.2 = B (annotated); `fail` names a read that fails."""
    state = {"fail": ""}

    def ls_remote(ref):
        if state["fail"] and state["fail"] in ref:
            raise RuntimeError("could not resolve host")
        if ref == "refs/heads/main":
            return f"{A}\trefs/heads/main\n"
        return f"{C}\trefs/tags/v2.7.2\n{B}\trefs/tags/v2.7.2^{{}}\n"
    monkeypatch.setattr(cli, "_ls_remote", ls_remote)
    return state


@pytest.fixture
def degraded(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_degraded", lambda ctx, kind, seen, examined:
                        calls.append((kind, dict(seen), set(examined))))
    return calls


def test_a_moved_channel_is_dispatched_on_mains_sha_and_read_back(upstream, degraded):
    gh = _GH([_e("dev", C), _e("stable", B)], publish={"dev": A})
    assert cli.stage_web(_Ctx(gh)) == 0
    assert gh.dispatched == [{"stack": "meshtastic-web", "source_commit": "", "lhpc_ref": MAIN,
                              "smoke_test": "true", "channel": "dev"}]
    assert degraded == [("web", {}, {"web/index", "web/upstream", "web/dev", "web/stable"})]


def test_a_shadowed_composition_is_rebuilt(upstream, degraded):
    gh = _GH([_e("dev", C), _e("dev", A), _e("stable", B)], publish={"dev": A})
    cli.stage_web(_Ctx(gh))
    assert [d["channel"] for d in gh.dispatched] == ["dev"]
    assert degraded[0][1] == {}


def test_nothing_to_do_dispatches_nothing_and_clears_every_key(upstream, degraded):
    gh = _GH([_e("dev", A), _e("stable", B)])
    cli.stage_web(_Ctx(gh))
    assert gh.dispatched == []
    assert degraded == [("web", {}, {"web/index", "web/upstream", "web/dev", "web/stable"})]


@pytest.mark.parametrize("gh", [
    _GH([], index_ok=False), _GH([], daemon=False),
    _GH([{"channel": "dev", "components": ["bad"]}, _e("dev", A), _e("stable", B)]),   # before a valid one
    _GH([_e("dev", A), _e("stable", B), {"channel": "dev", "components": ["bad"]}]),   # after: still refused
    _GH([{"channel": "dev"}, _e("dev", A), _e("stable", B)]),                          # no components at all
], ids=["index-unreadable", "no-daemon-entry", "malformed-before", "malformed-after", "no-components"])
def test_an_index_problem_is_web_index_and_leaves_the_channels_unexamined(upstream, degraded, gh):
    cli.stage_web(_Ctx(gh))
    assert gh.dispatched == []
    kind, seen, examined = degraded[0]
    assert set(seen) == {"web/index"} and examined == {"web/index", "web/upstream"}


@pytest.mark.parametrize("fail, unread", [("heads/main", "dev"), ("tags/", "stable")])
def test_an_upstream_problem_is_web_upstream_and_leaves_that_channel_unexamined(
        upstream, degraded, fail, unread):
    upstream["fail"] = fail
    gh = _GH([_e("dev", A), _e("stable", B)])
    cli.stage_web(_Ctx(gh))
    kind, seen, examined = degraded[0]
    assert set(seen) == {"web/upstream"}
    assert f"web/{unread}" not in examined and examined >= {"web/index", "web/upstream"}


@pytest.mark.parametrize("gh, why", [
    (_GH([_e("dev", C), _e("stable", B)], conclusion="failure"), "ended failure"),
    (_GH([_e("dev", C), _e("stable", B)], publish={}), "select is not"),          # read-back missing
    (_GH([_e("dev", C), _e("stable", B)], publish={"dev": C}), "select is not"),  # another commit
], ids=["red-build", "nothing-published", "wrong-commit"])
def test_a_failed_build_or_read_back_is_that_channels_key(upstream, degraded, gh, why):
    cli.stage_web(_Ctx(gh))
    kind, seen, examined = degraded[0]
    assert set(seen) == {"web/dev"} and why in seen["web/dev"]
    assert "web/stable" in examined


def test_a_dry_run_dispatches_nothing_and_writes_no_issue(upstream, degraded):
    gh = _GH([_e("dev", C), _e("stable", B)])
    assert cli.stage_web(_Ctx(gh), dry=True) == 0
    assert gh.dispatched == [] and degraded == []


# ---- closure: the real `_degraded` over successive runs ----

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

    def open_titles(self):
        return sorted(i["title"] for i in self.issues.values() if i["state"] == "open")


def test_each_key_closes_on_its_next_healthy_examined_run_only(upstream):
    store = _Store()
    gh = _GH([_e("dev", C), _e("stable", B)], conclusion="failure")
    cli.stage_web(_Ctx(gh, store))                                 # run 1: the dev build is red
    assert store.open_titles() == ["degraded web: web/dev"]
    cli.stage_web(_Ctx(_GH([], index_ok=False), store))            # run 2: index unreadable
    assert store.open_titles() == ["degraded web: web/dev", "degraded web: web/index"]
    upstream["fail"] = "heads/main"                                # run 3: index back, main unread
    cli.stage_web(_Ctx(_GH([_e("dev", C), _e("stable", B)]), store))
    assert store.open_titles() == ["degraded web: web/dev", "degraded web: web/upstream"]
    upstream["fail"] = ""                                          # run 4: all healthy, dev rebuilt
    cli.stage_web(_Ctx(_GH([_e("dev", C), _e("stable", B)], publish={"dev": A}), store))
    assert store.open_titles() == []
