"""The attempt record: what this run has already changed in the world.

A run publishes binaries before it can prove them, and pushes a controller release before it can
cut an image. Between those points the world is in a state only this run knows about, so that
state has to survive the run — including a run that is cancelled, or whose last job never starts.

It lives in an ISSUE in the bot's own repository, for three reasons: an issue never expires (run
artifacts do), it can be written with the workflow's own token even when the release credential
is the thing that failed, and a person can read it. Per-stage artifacts carry the bulky logs;
this carries only what a recovery needs.

The lifecycle, and what each state permits:

    prepared        a candidate branch exists                  -> delete the branch
    mutated         a publish was STARTED: its outcome may be unknown
    released        main + tag are pushed: THE COMMIT POINT    -> never roll binaries back
    integrated      dev fast-forwarded, or its PR opened
    image-published the image release is public
    complete        integration AND image are both done; nothing is owed
    restored        everything this run changed is undone

`released` is not `complete`: a controller release whose image failed still owes an image, and
starting another release would make that image impossible to cut (the builder resolves main).
Nor is a published image complete on its own — integration is owed too, and only a finalizer
that has seen both may close the attempt.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

LABEL = "attempt"
OPEN_STATES = ("prepared", "mutated", "released", "integrated", "image-published")
BLOCK = re.compile(r"<!--attempt\n(.*?)\n-->", re.S)
SHA = re.compile(r"^[0-9a-f]{40}$")

# What each state's record must carry for a recovery to be possible from it alone.
REQUIRED = {
    "prepared": ("run_id", "version", "base_sha", "candidate_sha", "branch"),
    # `dispatched` too: "mutated" MEANS a publish was started, so a record in that state with an
    # empty list describes a thing that cannot have happened. Without it such a record validated
    # and then recovered as "clean" — a publish that was started, recovered as if it never was.
    "mutated": ("run_id", "version", "base_sha", "candidate_sha", "branch", "index_snapshot",
                "dispatched"),
    "released": ("run_id", "version", "base_sha", "candidate_sha"),
    "integrated": ("run_id", "version", "candidate_sha"),
    "image-published": ("run_id", "version", "candidate_sha", "image_tag"),
    "complete": ("run_id", "version", "candidate_sha"),
    "restored": ("run_id",),
}


class Unreadable(RuntimeError):
    """An attempt record that is present but cannot be trusted.

    Never treated as absent: an unreadable record is the one case where the bot knows something
    happened and cannot say what, so it must block rather than proceed.
    """


@dataclass
class Attempt:
    run_id: str = ""
    state: str = "prepared"
    version: str = ""
    base_sha: str = ""          # main as this run captured it
    candidate_sha: str = ""     # the release commit
    branch: str = ""
    dev_sha: str = ""           # dev as this run captured it
    index_snapshot: dict = field(default_factory=dict)   # the binary index before any publish
    published: dict = field(default_factory=dict)        # stack -> the entry THIS run published
    dispatched: list = field(default_factory=list)       # stacks a publish was STARTED for
    runs: dict = field(default_factory=dict)             # name -> {id, workflow, attempt, sha}
    image_tag: str = ""
    integration: str = ""       # "" | "fast-forward" | "pr:<number>"
    # Which stack the failure NAMED, if any, and what was held for it. Recorded by the stage
    # that saw the failure, acted on only after recovery has confirmed the index is back.
    moved_keys: list = field(default_factory=list)       # policy keys this run set out to move
    regression: list = field(default_factory=list)       # stack ids the evidence blamed
    evidence: str = ""                                   # where that attribution came from
    frozen: list = field(default_factory=list)           # policy keys this run actually held
    incident: int = 0           # the auto-freeze issue that carries the hold
    retry_run: str = ""         # the ONE child this attempt dispatched, claimed before sending
    retry_of: str = ""          # the parent run id, when this run IS the one retry
    # The controller ref this attempt was PLANNED from. "main" for every real release. Recorded
    # here, not re-read from the environment, because a later recovery or finish runs with its
    # own dispatch inputs: an attempt that was a rehearsal must stay one no matter who re-enters
    # it. It is also not derived from comparing SHAs — a rehearsal branch may point at exactly
    # the same commit as `main`, and that is still a rehearsal.
    base_ref: str = "main"
    notes: list = field(default_factory=list)

    @property
    def rehearsal(self) -> bool:
        """Planned from something other than `main`, so it may never publish anything."""
        return self.base_ref != "main"

    @property
    def unresolved(self) -> bool:
        # A restored attempt that wrote a HOLD still owes the retry that hold was written for.
        # Without this an interrupted freeze read as settled: the policy carried the hold, the
        # incident said a retry was owed, and nothing was owed by anybody.
        #
        # `incident`, not only `frozen`: the incident is opened BEFORE the policy is pushed, so a
        # run lost in between wrote an issue asserting a retry is owed while `frozen` was still
        # empty. Keying only on `frozen` called that settled and closed it.
        return (self.state in OPEN_STATES
                or bool((self.frozen or self.incident) and not self.retry_run))

    @property
    def past_commit_point(self) -> bool:
        return self.state in ("released", "integrated", "image-published", "complete")

    @property
    def owes(self) -> list:
        """What a released attempt still has to finish before it may be closed."""
        if not self.past_commit_point:
            return []
        missing = []
        if not self.integration:
            missing.append("dev integration")
        if self.state not in ("image-published", "complete"):
            missing.append("the image")
        return missing

    def validate(self) -> None:
        """Raise `Unreadable` when this record cannot support a recovery from its own state."""
        if self.state not in (*OPEN_STATES, "complete", "restored"):
            raise Unreadable(f"unknown attempt state {self.state!r}")
        for name in REQUIRED[self.state]:
            if not getattr(self, name):
                raise Unreadable(f"attempt {self.run_id or '?'} in state {self.state!r} has no "
                                 f"{name}")
        for name in ("base_sha", "candidate_sha"):
            value = getattr(self, name)
            if value and not SHA.match(value):
                raise Unreadable(f"attempt {self.run_id or '?'}: {name} is not a commit sha")
        if not isinstance(self.published, dict) or not isinstance(self.dispatched, list):
            raise Unreadable(f"attempt {self.run_id or '?'}: malformed publish record")

    def to_body(self) -> str:
        """The issue body: a human summary, with the record embedded verbatim beneath it."""
        head = [f"**Attempt {self.run_id}** — state `{self.state}`",
                "",
                f"- version: `{self.version or '?'}`",
                f"- base (main at start): `{self.base_sha[:9] or '?'}`",
                f"- candidate commit: `{self.candidate_sha[:9] or '—'}`",
                f"- candidate branch: `{self.branch or '—'}`",
                f"- binary publishes started: {', '.join(self.dispatched) or 'none'}",
                f"- binary entries this attempt published: "
                f"{', '.join(sorted(self.published)) or 'none'}",
                f"- dev integration: {self.integration or '—'}",
                f"- image tag: `{self.image_tag or '—'}`",
                ""]
        if self.notes:
            head += ["Notes:", *[f"- {n}" for n in self.notes], ""]
        if self.owes:
            head += [f"Still owed: {', '.join(self.owes)}.", ""]
        if self.unresolved:
            head += ["This attempt is **unresolved**: a new release run refuses to start while "
                     "it is open. Close it by finishing it (`finish`) or by recovering it "
                     "(`recover`).", ""]
        payload = json.dumps(asdict(self), indent=2, sort_keys=True)
        return "\n".join(head) + f"\n<!--attempt\n{payload}\n-->\n"

    @classmethod
    def from_body(cls, body: str):
        """The record in an issue body, or None when there is none.

        A body carrying a record that will not parse raises `Unreadable`: something wrote a
        record there, and a parse failure is not evidence that nothing happened.
        """
        m = BLOCK.search(body or "")
        if not m:
            return None
        try:
            att = cls(**json.loads(m.group(1)))
        except (ValueError, TypeError) as exc:
            raise Unreadable(f"an attempt record could not be read ({exc})") from None
        att.validate()
        return att


def record_of_labelled_issue(number: int, body: str) -> Attempt:
    """The record an issue carrying the attempt label MUST have.

    The label is itself the assertion that a record was written. An issue that carries it and no
    readable record used to be dropped as "no record here", which defeats the distinction the
    whole design rests on: nothing was written is not the same as something was written and
    cannot be read. Dropped, it blocked nothing and could be addressed by neither repair mode.
    """
    att = Attempt.from_body(body)
    if att is None:
        raise Unreadable(f"issue #{number} carries the {LABEL!r} label but no attempt record")
    return att


def recovery_decision(att: Attempt, main_sha: str, tag_sha: str, released_here: bool) -> str:
    """What a recovery may do, decided from the REMOTE refs rather than from checkpoints.

    A missing `released` note proves nothing: the atomic push may have been accepted and its
    reply lost, or the job cancelled between the push and the write. So the refs are asked
    first, and if THIS attempt's release exists the binaries it needs are never rolled back —
    every box that self-updates to it would then be pointed at an index that cannot satisfy it.

    `released_here` is the caller's ancestry answer: a tag of the same NAME is not this
    attempt's release, and the version may have been taken by somebody else.

      "released"  this attempt's release exists: keep everything, finish what is owed
      "conflict"  a DIFFERENT commit holds the version: touch nothing, report
      "restore"   a publish was started and nothing of ours was released: put the index back
      "clean"     no publish was ever started: only the candidate branch is left to remove
    """
    if main_sha == att.candidate_sha or released_here:
        return "released"
    if tag_sha and tag_sha != att.candidate_sha:
        return "conflict"
    return "restore" if (att.published or att.dispatched) else "clean"


def blocks_new_release(att: Attempt) -> bool:
    """A released controller whose image is still owed BLOCKS the next release: the image
    builder resolves `main`, so releasing again would make that image impossible to cut."""
    return att.unresolved
