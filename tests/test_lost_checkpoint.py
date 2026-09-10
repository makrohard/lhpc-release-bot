"""A release that was really pushed but never recorded — the R8-A1 boundary.

The commit point is two writes to two different systems: an atomic push to GitHub, then a
journal write to the attempt issue. Between them the job can die. Every case here is about a
record that is BEHIND THE WORLD, and the rule that follows from that: when the remote refs say
this attempt's release exists, the refs are right and the record is what must move.

The push here is a real `git push --atomic` into a real bare repository, and the refs are read
back out of it with `git`, because the defect this file exists for is precisely a disagreement
between what the remote holds and what the journal says. Faking the push would assume away the
thing under test.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bot import cli
from bot.attempt import Attempt, record_of_labelled_issue

CHANGELOG = """# Changelog

## 0.3.16

- moved a pin

## 0.3.15

- the previous release
"""


class _Interrupted(RuntimeError):
    """The injected journal-write failure, and ONLY that.

    A distinct type on purpose: `cli.git` also raises `RuntimeError`, so catching the bare class
    let a real git failure stand in for the interruption. That is exactly how the first version
    of this file passed locally and failed on CI — the clone had no git identity there, `git tag`
    died, and the test reported "the atomic push was accepted" as the mismatch instead of saying
    git had never got that far.
    """


def git(*args, cwd):
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin", "HOME": str(cwd)}
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


class _Remote:
    """A real bare repository standing in for the controller, plus the working clone the stage
    is handed. `sha_of` is `gh.ref`: production peels an annotated tag to its commit, so this
    does too — a tag object sha would compare unequal to the candidate for the wrong reason."""

    def __init__(self, tmp_path: Path):
        self.bare = tmp_path / "controller.git"
        seed = tmp_path / "seed"
        seed.mkdir(parents=True)
        git("init", "-q", "-b", "main", ".", cwd=seed)
        (seed / "CHANGELOG.md").write_text(CHANGELOG)
        git("add", "-A", cwd=seed)
        git("commit", "-qm", "0.3.15", cwd=seed)
        self.base = git("rev-parse", "HEAD", cwd=seed)
        (seed / "pin.txt").write_text("moved\n")
        git("checkout", "-q", "-b", "pins/0.3.16-100", cwd=seed)
        git("add", "-A", cwd=seed)
        git("commit", "-qm", "0.3.16", cwd=seed)
        self.candidate = git("rev-parse", "HEAD", cwd=seed)

        self.bare.mkdir()
        git("init", "-q", "--bare", ".", cwd=self.bare)
        git("remote", "add", "origin", str(self.bare), cwd=seed)
        git("push", "-q", "origin", "main", "pins/0.3.16-100", cwd=seed)
        git("push", "-q", "origin", f"{self.base}:refs/heads/dev", cwd=seed)
        self.work = tmp_path / "work"
        subprocess.run(["git", "clone", "-q", str(self.bare), str(self.work)], check=True,
                       capture_output=True)
        git("checkout", "-q", "pins/0.3.16-100", cwd=self.work)

    def sha_of(self, ref: str) -> str:
        out = subprocess.run(["git", "-C", str(self.bare), "rev-parse", "--verify", "-q",
                              f"{ref}^{{commit}}"], capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 else ""


class _Ctx:
    """Only what the release and recovery stages reach for. The issue store is a dict written
    through the real `Attempt` serialisation, so a record that could not round-trip fails here."""

    attempt_id = "100"
    run_id = "100"
    retry_of = ""
    retry_incident = ""
    bot_token = token = "t" * 20
    run_url = "https://example.invalid/run/1"

    def __init__(self, remote: _Remote, att: Attempt, *, die_on_released: bool = False):
        self.remote, self.att, self.gh = remote, att, self
        self.die_on_released = die_on_released
        self.saved, self.summaries, self.outs = [], [], []
        self.body = att.to_body()

    # --- the journal -----------------------------------------------------------------
    def find_attempt(self, wanted=""):
        return 7, self.att

    def save_attempt(self, number, att):
        if self.die_on_released and att.state == "released":
            # The interruption: the push is already accepted upstream, and THIS is the write
            # that never lands. Raising here rather than after leaves exactly the record the
            # world disagrees with.
            self.die_on_released = False
            raise _Interrupted("the runner died before the journal write landed")
        att.validate()                       # a state this record cannot support is a failure
        self.body = att.to_body()            # the ISSUE is the journal, and it is what survives
        self.saved.append((number, att.state, list(att.notes)))
        return number

    def stored(self) -> Attempt:
        """The record as a LATER RUN would find it — parsed back out of the issue body.

        This matters and is not ceremony: `stage_release` sets `state` on its in-memory object
        before it writes, so reusing that object would carry a `released` that was never
        persisted anywhere, and the test would assert against a world the next run cannot see.
        """
        return record_of_labelled_issue(7, self.body)

    # --- the seams -------------------------------------------------------------------
    def ref(self, repo, ref):
        return self.remote.sha_of(ref.replace("heads/", "").replace("tags/", ""))

    def is_ancestor(self, repo, a, b):
        return subprocess.run(["git", "-C", str(self.remote.bare), "merge-base",
                               "--is-ancestor", a, b], capture_output=True).returncode == 0

    def unfinished_runs(self, repo, workflow=""):
        return []

    def clone(self, repo, ref="", token=""):
        # Production's `clone` configures the committer identity here (`bot/cli.py`), and the
        # release stage makes an ANNOTATED tag, which needs one. Omitting it is invisible on a
        # developer machine with a global gitconfig and fatal on a bare CI runner.
        git("config", "user.name", "lhpc-release-bot", cwd=self.remote.work)
        git("config", "user.email", "bot@example.invalid", cwd=self.remote.work)
        return self.remote.work

    def summary(self, text):
        self.summaries.append(text)

    # --- the bot's own issue store, for the one stage that closes an attempt
    @property
    def bot_gh(self):
        return self

    def update_issue(self, repo, number, **kw):
        self.issue_state = kw.get("state", "open")
        return {"number": number}

    def open_attempts(self):
        return []

    def out(self, **kw):
        self.outs.append(kw)


def _att(**over) -> Attempt:
    base = dict(run_id="100", state="prepared", version="0.3.16",
                branch="pins/0.3.16-100")
    return Attempt(**{**base, **over})


def _interrupted_release(tmp_path, **over):
    """Run the REAL release stage against the real remote and lose the journal write."""
    remote = _Remote(tmp_path)
    att = _att(base_sha=remote.base, candidate_sha=remote.candidate, **over)
    ctx = _Ctx(remote, att, die_on_released=True)
    with pytest.raises(_Interrupted):
        cli.stage_release(ctx)
    # What the next run inherits is the PERSISTED record, not this process's object.
    return remote, ctx.stored(), ctx


# ---------------------------------------------------------------- the defect itself


def test_a_no_binary_release_that_lost_its_checkpoint_is_recovered_as_released(tmp_path):
    """R8-A1. A candidate needing no binary publish stays `prepared` through its whole proof,
    so this is the ordinary shape of a source-only release — an OpenHop pin move, say.

    Recovery normalised only from `mutated`. A `prepared` record was written back unchanged, and
    because `owes` is empty before the commit point it reported that nothing was outstanding —
    about a release that had genuinely happened. The attempt then stayed open and blocked every
    later release, while the finish guards correctly refused it for not being past the commit
    point. Neither recover nor finish could resolve it, ever.
    """
    remote, att, _ = _interrupted_release(tmp_path)

    # The world moved even though the journal did not: this is the precondition, asserted and
    # not assumed. Both refs, because a tagless main is a different (and worse) failure.
    assert remote.sha_of("main") == remote.candidate, "the atomic push was accepted"
    assert remote.sha_of("v0.3.16") == remote.candidate, "and the tag peels to the candidate"
    assert att.state == "prepared", "while the record still says nothing was released"

    ctx = _Ctx(remote, att)
    assert cli.stage_recover(ctx, "100") == 0

    assert att.state == "released", "the remote is right and the record is what moves"
    assert att.past_commit_point
    assert att.owes == ["dev integration", "the image"], \
        "and what it still owes must be accurate, not empty"
    assert any(state == "released" for _n, state, _notes in ctx.saved), \
        "the normalisation has to be PERSISTED, not only held in memory"


def test_after_that_recovery_the_ordinary_finish_completes_the_owed_work(tmp_path):
    """The consequence that makes it a P1 rather than a cosmetic state bug: before the fix the
    guards added in round 7 refused this attempt for ever, so the work it owed could never be
    done and the attempt could never stop blocking.

    This runs the real integration stage afterwards, against the real remote, and requires it to
    actually fast-forward `dev` — not merely to get past the guard.
    """
    remote, att, _ = _interrupted_release(tmp_path)
    recovered = _Ctx(remote, att)
    cli.stage_recover(recovered, "100")

    # Through the journal, not by reference: `recover` and `finish` are two separate runs, and
    # what the second inherits is the issue body the first wrote. Handing it the same in-memory
    # object would prove less than this test claims.
    att = recovered.stored()
    assert att.state == "released", "and that is what the finish run reads"
    assert cli.stage_integrate(_Ctx(remote, att)) == 0
    assert att.integration == "fast-forward"
    assert att.state == "integrated"
    assert remote.sha_of("dev") == remote.candidate, "`dev` really moved, on the real remote"
    assert att.owes == ["the image"], "and the only thing left is the image"


def test_a_genuinely_unreleased_attempt_is_still_refused(tmp_path):
    """The control for the case above, and the rule the guards exist for. Nothing was pushed
    here, so `finish` must still refuse before it touches `dev` or cuts an image."""
    remote = _Remote(tmp_path)
    att = _att(base_sha=remote.base, candidate_sha=remote.candidate)
    with pytest.raises(cli.Stop) as stop:
        cli.stage_integrate(_Ctx(remote, att))
    assert "never reached the commit point" in str(stop.value.observed)


# ---------------------------------------------------------------- the four other cases


def test_a_binary_publish_attempt_with_the_same_interruption_still_recovers(tmp_path):
    """The control that the fix did not narrow the case that already worked, and that nothing
    is rolled back beneath a release that stands."""
    remote, att, _ = _interrupted_release(
        tmp_path, state="mutated", index_snapshot={"stacks": {}},
        dispatched=["meshtastic"], published={"meshtastic": {"filename": "x"}})

    ctx = _Ctx(remote, att)
    assert cli.stage_recover(ctx, "100") == 0
    assert att.state == "released"
    assert att.published == {"meshtastic": {"filename": "x"}}, \
        "a released attempt's binaries are never rolled back — boxes install from them"


def test_recovery_on_an_advanced_record_regresses_nothing(tmp_path):
    """Recovery is re-runnable, so it must never walk a record BACKWARDS. An attempt that has
    already integrated and published its image keeps both facts and its later state."""
    remote = _Remote(tmp_path)
    subprocess.run(["git", "-C", str(remote.work), "push", "-q", "origin",
                    f"{remote.candidate}:refs/heads/main"], check=True, capture_output=True)
    att = _att(state="image-published", base_sha=remote.base, candidate_sha=remote.candidate,
               integration="pr:4", image_tag="v0.3.16")

    ctx = _Ctx(remote, att)
    assert cli.stage_recover(ctx, "100") == 0
    # REPEATED, as the audit asks: recovery is re-runnable by an operator who is not sure it
    # took, so running it twice must be indistinguishable from running it once.
    again = _Ctx(remote, ctx.stored())
    assert cli.stage_recover(again, "100") == 0
    att = again.stored()
    assert att.state == "image-published", "not walked back to `released`"
    assert att.integration == "pr:4" and att.image_tag == "v0.3.16", "evidence preserved"
    assert att.published == {}, "and nothing was published a second time"
    assert att.owes == [], att.owes      # integration recorded and image published: nothing left


def test_a_version_held_by_another_candidate_is_still_a_conflict(tmp_path):
    """The promotion must key on THIS attempt's release existing, never on a tag of the same
    name. Somebody else's release of the same version may not be adopted."""
    remote = _Remote(tmp_path)
    # Somebody else tags 0.3.16 at the BASE, and main never moved to our candidate.
    git("tag", "-a", "v0.3.16", "-m", "theirs", remote.base, cwd=remote.work)
    git("push", "-q", "origin", "refs/tags/v0.3.16", cwd=remote.work)
    att = _att(base_sha=remote.base, candidate_sha=remote.candidate)

    ctx = _Ctx(remote, att)
    with pytest.raises(cli.Stop):
        cli.stage_recover(ctx, "100")
    assert att.state == "prepared", "no false promotion from a foreign tag"
    assert not att.past_commit_point


def test_a_reopened_restored_attempt_is_never_promoted_to_released(tmp_path):
    """`restored` is not past the commit point either, so a negation alone would promote it.

    This is reached on the bot's OWN path, not only by an operator reopening an issue. When a
    recovery writes a hold, `stage_recover` sets `restored` and then deliberately leaves the issue
    OPEN while the retry is unclaimed, because that issue is the durable record of the obligation
    — so `open_attempts` returns it and a later `recover` finds it. The consequence of promoting
    it is the worst available: a rolled-back attempt recorded as a standing release, after which
    `finish` integrates and cuts an image for a candidate whose binaries are no longer in the
    index. The ref coincidence below is all it would take — somebody else releasing this same
    commit is enough for `recovery_decision` to answer `released`.
    """
    remote = _Remote(tmp_path)
    subprocess.run(["git", "-C", str(remote.work), "push", "-q", "origin",
                    f"{remote.candidate}:refs/heads/main"], check=True, capture_output=True)
    att = _att(state="restored", base_sha=remote.base, candidate_sha=remote.candidate)

    ctx = _Ctx(remote, att)
    assert cli.stage_recover(ctx, "100") == 0
    assert att.state == "restored", "a rolled-back attempt is not a release, whatever main says"
    assert not att.past_commit_point
    assert att.owes == []


def test_the_recovered_attempt_can_be_driven_out_of_the_blocking_set(tmp_path):
    """The audit's row 1 in full: ordinary finish must not only complete, it must **unblock the
    next plan**. That is the whole cost of R8-A1 — the deadlock was not that one attempt looked
    wrong, it was that no later release could start while it sat there.

    `blocking_attempts` keys on `unresolved`, which is true for every OPEN state. So the attempt
    leaves the blocking set only by reaching `complete`, and before the fix it could not reach any
    state at all: `finish` refused it for not being past the commit point and `recover` wrote
    `prepared` back unchanged, for ever.
    """
    remote, att, _ = _interrupted_release(tmp_path)

    # The pathology, stated as two facts at once: it blocks, AND it says nothing is owed.
    assert cli.blocking_attempts([(7, att)], "") != [], "a stuck attempt blocks the next release"
    assert att.owes == [], "while claiming there is nothing to do about it"

    recovered = _Ctx(remote, att)
    cli.stage_recover(recovered, "100")
    att = recovered.stored()
    assert cli.blocking_attempts([(7, att)], "") != [], "still blocks — but now it owes something"
    assert att.owes == ["dev integration", "the image"]

    integrated = _Ctx(remote, att)
    assert cli.stage_integrate(integrated) == 0
    att = integrated.stored()
    assert att.owes == ["the image"]
    assert cli.blocking_attempts([(7, att)], "") != [], "an owed image still blocks, by design"

    # The image stage itself is GitHub-bound and out of scope here, so this records what it
    # records. What is being proved is the release of the LOCK, not the image build.
    att.state, att.image_tag = "image-published", "v0.3.16"
    final = _Ctx(remote, att)
    assert cli.stage_finalize(final) == 0
    att = final.stored()

    assert att.state == "complete"
    assert final.issue_state == "closed", "the one place an attempt is closed did close it"
    assert cli.blocking_attempts([(7, att)], "") == [], \
        "and the next release is free — which is what R8-A1 took away"
