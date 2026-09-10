"""Holding a stack an update broke, and — mostly — refusing to.

The cases that matter are the refusals. A hold written on a guess pins the wrong stack for weeks
while the real cause stays live, so every path that cannot name its stack must produce an
ordinary failure and no freeze at all.
"""
from __future__ import annotations

import json
import tomllib

import pytest

from bot import autofreeze as af
from bot.attempt import Attempt

MANIFEST = """
[[stack]]
id = "meshcore"
  [[stack.component]]
  id = "meshcore-node"
  [stack.component.source]
  path = "src/openhop-core"
  pin_commit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  [[stack.component]]
  id = "meshcore-cli"
  [stack.component.source]
  path = "src/meshcore-cli"
  pin_commit = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
[[stack]]
id = "chat"
  [[stack.component]]
  id = "loraham-chat"
  [stack.component.source]
  path = "src/LoRaHAM_Daemon"
  pin_commit = "cccccccccccccccccccccccccccccccccccccccc"
[[stack]]
id = "kiss"
  [[stack.component]]
  id = "kiss-tnc"
  [stack.component.source]
  path = "src/shared"
  pin_commit = "dddddddddddddddddddddddddddddddddddddddd"
[[stack]]
id = "voice"
  [[stack.component]]
  id = "voice-cli"
  [stack.component.source]
  path = "src/shared"
  pin_commit = "dddddddddddddddddddddddddddddddddddddddd"
"""

POLICY = {"source": {"src/openhop-core": {"track": "tip"},
                     "src/meshcore-cli": {"track": "tag"},
                     "src/LoRaHAM_Daemon": {"track": "manual"},
                     "src/shared": {"track": "tip"}},
          "extra": {"meshtastic-web": {"kind": "github-release", "track": "release"},
                    "qemu-esp": {"kind": "owned-by-pin", "owner": "src/x"}}}


# ------------------------------------------------------------------ who the evidence blames

def test_a_marked_assertion_names_its_stack():
    got = af.attributed_stacks("E  AssertionError: STACK-REGRESSION stack=meshcore "
                               "phase=readiness — companion never opened 5000")
    assert got == ["meshcore"]


def test_an_ordinary_failure_names_nobody():
    """An infrastructure failure, a cancelled runner, an unreadable log. No hold may follow."""
    for text in ("", "Error: The operation was canceled.", "ConnectionResetError",
                 "FAILED tests/release/test_release_verify.py::test_release_chat"):
        assert af.attributed_stacks(text) == []


def test_a_case_name_alone_is_not_attribution():
    """`test_release_chat` can fail while stopping the stack before it, or while the fake daemon
    is prepared. Freezing chat for that would hold the wrong thing indefinitely."""
    assert af.attributed_stacks("FAILED ...::test_release_chat - AssertionError: band busy") == []


def test_the_grammar_is_read_exactly_as_the_lane_publishes_it():
    """A cross-repository contract, so it is asserted exactly. `lhpc_testlab.release.
    stack_regression` documents this shape and raises rather than emit anything else."""
    assert af.attributed_stacks("STACK-REGRESSION stack=meshcore-x phase=build") == ["meshcore-x"]
    assert af.attributed_stacks("STACK-REGRESSION stack=with_underscore phase=start") == \
        ["with_underscore"]
    for wrong in ("STACK-REGRESSION stack=kiss phase=installx",     # no boundary after the phase
                  "STACK-REGRESSION stack=kiss phase=compile",      # not one of the four phases
                  "STACK-REGRESSION stack=KISS phase=install",      # a stack id is lower case
                  "STACK-REGRESSION  stack=kiss phase=install",     # one space between fields
                  "STACK-REGRESSION stack= kiss phase=install"):    # no space around =
        assert af.attributed_stacks(wrong) == [], wrong


def test_two_named_stacks_are_both_reported():
    got = af.attributed_stacks("STACK-REGRESSION stack=kiss phase=build\n"
                               "STACK-REGRESSION stack=meshcore phase=start")
    assert got == ["kiss", "meshcore"]


# ------------------------------------------------------------------ what a hold covers

def test_a_hold_covers_the_whole_stack_not_only_what_moved():
    """Several updates can land in one run and picking the guilty one is the guess this avoids.
    Holding the stack as a unit is conservative and reviewable."""
    keys = af.stack_inputs(MANIFEST, ["meshcore"], POLICY)
    assert set(keys) == {"src/openhop-core", "src/meshcore-cli"}


def test_a_shared_source_names_the_other_stacks_it_holds():
    keys = af.stack_inputs(MANIFEST, ["kiss"], POLICY)
    assert "shared with voice" in keys["src/shared"]


def test_a_manual_input_is_never_held():
    """It does not move anyway, so a hold on it would be decoration."""
    assert af.stack_inputs(MANIFEST, ["chat"], POLICY) == {}


def test_a_tracked_extra_that_no_stack_owns_is_loud():
    """Dropping it would leave the retry re-resolving that input while the incident claims the
    whole composition is held."""
    policy = {"source": {}, "extra": {"newthing": {"kind": "github-release", "track": "release"}}}
    with pytest.raises(ValueError, match="no stack owns it"):
        af.stack_inputs(MANIFEST, ["meshcore"], policy)


def test_every_tracked_extra_in_the_real_policy_has_an_owner():
    """The live check: this file and `policy.toml` must not drift apart."""
    import pathlib
    import tomllib

    live = tomllib.loads(
        (pathlib.Path(__file__).resolve().parents[1] / "policy.toml").read_text())
    for name, rule in (live.get("extra") or {}).items():
        if rule.get("track", "manual") == "manual" or rule.get("kind") == "owned-by-pin":
            continue
        assert name in af._EXTRA_STACK, f"extra.{name} is tracked but no stack owns it"


def test_an_owned_input_is_not_held_on_its_own():
    keys = af.stack_inputs(MANIFEST, ["meshtastic"], POLICY)
    assert "extra.qemu-esp" not in keys


# ------------------------------------------------------------------ when it refuses

def test_no_attribution_means_no_hold():
    keys, why = af.decide([], ["src/openhop-core"], MANIFEST, POLICY)
    assert keys == {} and "named a stack" in why


def test_a_stack_that_moved_nothing_is_not_held():
    """It failed, but not because of anything this run did. Holding its pins would freeze the
    innocent while whatever really broke it stays live."""
    keys, why = af.decide(["meshcore"], ["src/shared"], MANIFEST, POLICY)
    assert keys == {} and "moved nothing this run" in why


def test_a_stack_with_nothing_holdable_is_refused_rather_than_held_emptily():
    keys, why = af.decide(["chat"], ["src/LoRaHAM_Daemon"], MANIFEST, POLICY)
    assert keys == {} and "no input this bot may hold" in why


def test_an_artifact_source_cannot_be_held_and_says_so():
    """LHPC resolves an `artifact` source to the branch tip and never checks its pin, so the
    retry would install upstream anyway while the incident claimed the pin was held. Refusing is
    the only honest answer until the source becomes an ordinary pinned one."""
    manifest = MANIFEST.replace(
        '  path = "src/openhop-core"\n',
        '  path = "src/openhop-core"\n  artifact = true\n')
    keys, why = af.decide(["meshcore"], ["src/openhop-core"], manifest, POLICY)
    assert keys == {} and "would not hold" in why


def test_a_named_stack_that_moved_is_held():
    keys, why = af.decide(["meshcore"], ["src/openhop-core"], MANIFEST, POLICY)
    assert why == "" and set(keys) == {"src/openhop-core", "src/meshcore-cli"}


# ------------------------------------------------------------------ the edit itself

POLICY_TEXT = '''[source."src/openhop-core"]
track = "tip"
why = "the active line"

[source."src/other"]
track = "tip"

[extra.meshtastic-web]
kind = "github-release"
track = "release"
'''


def test_the_edit_holds_only_the_named_entries_and_still_parses():
    out = af.freeze_edit(POLICY_TEXT, {"src/openhop-core": "holds meshcore"}, "because")
    doc = tomllib.loads(out)
    assert doc["source"]["src/openhop-core"]["freeze"] == "because — holds meshcore"
    assert doc["source"]["src/openhop-core"]["track"] == "tip", "the tracking rule is kept"
    assert "freeze" not in doc["source"]["src/other"]


def test_an_existing_hold_is_never_overwritten():
    """Somebody else's hold has somebody else's reason. This run does not own it."""
    held = POLICY_TEXT.replace('[source."src/other"]\ntrack = "tip"\n',
                               '[source."src/other"]\ntrack = "tip"\nfreeze = "mine"\n')
    out = af.freeze_edit(held, {"src/other": "holds x"}, "automatic")
    assert tomllib.loads(out)["source"]["src/other"]["freeze"] == "mine"


def test_holding_an_entry_that_is_not_there_is_an_error_not_a_silent_no_op():
    with pytest.raises(ValueError, match="no entry"):
        af.freeze_edit(POLICY_TEXT, {"src/absent": "holds y"}, "automatic")


def test_an_extra_input_is_held_the_same_way():
    out = af.freeze_edit(POLICY_TEXT, {"extra.meshtastic-web": "holds meshtastic"}, "automatic")
    assert tomllib.loads(out)["extra"]["meshtastic-web"]["freeze"].startswith("automatic")


# ------------------------------------------------------------------ one incident, one retry

def test_an_incident_for_the_same_group_is_reused_not_reopened():
    """A stack that fails again next week updates one incident instead of opening another every
    Monday."""
    issues = [{"number": 4, "title": "auto-freeze: meshcore"},
              {"number": 9, "title": "auto-freeze: kiss, meshcore"}]
    assert af.already_open(issues, ["meshcore"]) == 4
    assert af.already_open(issues, ["meshcore", "kiss"]) == 9
    assert af.already_open(issues, ["voice"]) == 0


# ------------------------------------------------------------------ the orchestration itself
# The decisions above are pure; these cover the ORDER the stage does them in, which is where a
# lost job leaves state behind. A fake context records every outward call.


class FakeGh:
    def __init__(self):
        self.issues, self.dispatched, self.bodies = {}, [], []
        self.comment_log = []
        self.next_number = 41

    def comments(self, repo, number):
        return [{"body": b} for b in self.comment_log]

    def open_issues(self, repo, label):
        return [{"number": n, "title": t} for n, t in self.issues.items()]

    def create_issue(self, repo, title, body, labels):
        self.next_number += 1
        self.issues[self.next_number] = title
        self.bodies.append(body)
        return {"number": self.next_number}

    def update_issue(self, repo, number, **fields):
        self.bodies.append(fields.get("body", ""))
        return {}

    def comment(self, repo, number, body):
        self.bodies.append(body)
        self.comment_log.append(body)
        return {}

    def dispatch(self, repo, workflow, ref, inputs=None):
        self.dispatched.append(inputs or {})
        return 777

    def ref(self, repo, ref):
        return "b" * 40

    def file_at(self, repo, path, sha):
        return MANIFEST


class FakeCtx:
    run_url = "https://example.invalid/run/1"

    def __init__(self, tmp_path):
        self.gh = self.bot_gh = FakeGh()
        self.bot_token = self.token = "t" * 20
        self.saved, self.summaries, self._tmp = [], [], tmp_path

    def clone(self, repo, ref="", token=""):
        d = self._tmp / repo.split("/")[-1]
        if not d.exists():
            d.mkdir(parents=True)
            (d / "policy.toml").write_text(STAGE_POLICY_TEXT)
        return d

    def summary(self, text):
        self.summaries.append(text)

    def save_attempt(self, number, att):
        self.saved.append((number, att.frozen[:], att.incident, list(att.notes)))
        return number


def _att(**over):
    from bot.attempt import Attempt
    base = {"run_id": "100", "state": "restored", "base_sha": "b" * 40,
            "candidate_sha": "c" * 40, "regression": ["meshcore"],
            "moved_keys": ["src/openhop-core"], "evidence": "the lane"}
    return Attempt(**{**base, **over})


@pytest.fixture
def freeze_ctx(tmp_path, monkeypatch):
    from bot import cli
    monkeypatch.setattr(cli, "MANIFEST", "m.toml")
    monkeypatch.setattr(cli, "git", lambda *a, **k: "")
    monkeypatch.setattr(cli.up, "load_policy", lambda p: POLICY_FOR_STAGE)
    return FakeCtx(tmp_path)


POLICY_FOR_STAGE = {"source": {"src/openhop-core": {"track": "tip"},
                               "src/meshcore-cli": {"track": "tag"}}, "extra": {}}
STAGE_POLICY_TEXT = ('[source."src/openhop-core"]\ntrack = "tip"\n\n'
               '[source."src/meshcore-cli"]\ntrack = "tag"\n')


def test_the_hold_is_recorded_before_the_retry_is_dispatched(freeze_ctx):
    """A job lost between the push and the dispatch must leave a record saying the hold stands
    and a retry is owed. The incident asserting a retry nobody started is the failure here."""
    from bot import cli
    cli._auto_freeze(freeze_ctx, 5, _att())
    saves_before_dispatch = [s for s in freeze_ctx.saved if s[1]]
    assert saves_before_dispatch, "the hold was never written to the attempt"
    assert saves_before_dispatch[0][1] == ["src/meshcore-cli", "src/openhop-core"]
    sent = freeze_ctx.gh.dispatched
    assert len(sent) == 1 and sent[0]["retry_of"] == "100" and sent[0]["retry_incident"]


def test_the_retry_carries_the_parent_so_it_cannot_retry_again(freeze_ctx):
    from bot import cli
    cli._auto_freeze(freeze_ctx, 5, _att())
    assert freeze_ctx.gh.dispatched[0]["retry_of"] == "100"


def test_a_run_that_is_itself_the_retry_dispatches_nothing(freeze_ctx):
    """A chain would peel stacks off one at a time until something passed."""
    from bot import cli
    freeze_ctx.bot_gh.issues[9] = "auto-freeze: meshcore"
    cli._auto_freeze(freeze_ctx, 5, _att(retry_of="100"))
    assert freeze_ctx.gh.dispatched == []
    assert any("retry failed too" in b for b in freeze_ctx.bot_gh.bodies), \
        "the open incident was never told the retry failed"


def test_a_controller_that_moved_underneath_stops_the_hold(freeze_ctx, monkeypatch):
    """The composition captured by the attempt is no longer what `main` describes, so the group
    would be computed from a structure the attempt never saw."""
    from bot import cli
    monkeypatch.setattr(freeze_ctx.gh, "ref", lambda repo, ref: "9" * 40)
    cli._auto_freeze(freeze_ctx, 5, _att())
    assert freeze_ctx.gh.dispatched == [] and not freeze_ctx.bot_gh.issues


def test_a_refused_attribution_neither_opens_an_incident_nor_retries(freeze_ctx):
    from bot import cli
    cli._auto_freeze(freeze_ctx, 5, _att(moved_keys=["src/unrelated"]))
    assert freeze_ctx.gh.dispatched == [] and not freeze_ctx.bot_gh.issues


# ------------------------------------------------------------------ the cascade the lane warns of

def test_an_unexplained_failure_beside_a_marked_one_refuses():
    """The shape the lane's own docstring warns about: a teardown leaves a band held, the NEXT
    stack's marked readiness assertion fails, and its marker is the only one in the file. Holding
    on that would freeze whichever stack happened to run next."""
    keys, why = af.decide(["meshcore"], ["src/openhop-core"], MANIFEST, POLICY,
                          unattributed=["test_release_voice"])
    assert keys == {} and "named no stack" in why


def test_a_clean_lane_failure_still_holds():
    keys, why = af.decide(["meshcore"], ["src/openhop-core"], MANIFEST, POLICY, unattributed=[])
    assert why == "" and keys


def test_only_failing_cases_are_read_for_attribution():
    """A marker in a passing case, a skip reason or captured output is not a failure."""
    from bot.cli import _failure_text
    junit = (
        b'<testsuites><testsuite>'
        b'<testcase name="test_release_kiss">'
        b'<system-out>STACK-REGRESSION stack=kiss phase=start</system-out></testcase>'
        b'<testcase name="test_release_voice">'
        b'<skipped message="STACK-REGRESSION stack=voice phase=build"/></testcase>'
        b'<testcase name="test_release_meshcore">'
        b'<failure message="STACK-REGRESSION stack=meshcore phase=readiness">boom</failure>'
        b'</testcase></testsuite></testsuites>')
    text = _failure_text(junit)
    assert af.attributed_stacks(text) == ["meshcore"]


def test_a_failing_case_with_no_marker_is_named_as_unattributed():
    from bot.cli import _failure_text
    junit = (b'<testsuites><testsuite><testcase name="test_release_voice">'
             b'<failure message="stop failed">rc 1</failure></testcase></testsuite></testsuites>')
    assert af.unattributed_failures(_failure_text(junit)) == ["test_release_voice"]


# ------------------------------------------------------------------ resume, and the one child

def test_a_hold_already_in_the_policy_resumes_instead_of_failing(freeze_ctx, monkeypatch):
    """The defect: a run that pushed the hold and then died left `freeze_edit` with nothing to
    change, so `git commit` failed "nothing to commit" and the incident was told the hold was NOT
    written — the opposite of the truth, and the reason a resume could never finish."""
    from bot import cli

    bot_dir = freeze_ctx.clone("o/lhpc-release-bot")
    calls = []

    def fake_git(*a, **k):
        calls.append(a[0])
        if a[0] == "status":
            return ""                      # clean tree: the hold is already committed
        if a[0] == "commit":
            raise RuntimeError("nothing to commit, working tree clean")
        return ""

    monkeypatch.setattr(cli, "git", fake_git)
    (bot_dir / "policy.toml").write_text(STAGE_POLICY_TEXT)
    cli._auto_freeze(freeze_ctx, 5, _att())
    assert "commit" not in calls, "it tried to commit an unchanged policy"
    assert freeze_ctx.gh.dispatched, "the resume did not go on to dispatch the retry"
    assert not any("NOT written" in b for b in freeze_ctx.gh.bodies)


def test_a_retry_already_claimed_is_not_dispatched_again(freeze_ctx):
    """The parent asks the INCIDENT, not its own note: it cannot tell a dispatch it never sent
    from one whose reply it lost, and a sentinel written before the POST made every resume
    believe a child existed — leaving a real hold, no child, and nothing owed by anybody."""
    from bot import cli
    freeze_ctx.gh.comment_log.append(f"{af.CLAIM}9001 — retrying with the hold in place.")
    cli._auto_freeze(freeze_ctx, 5, _att())
    assert freeze_ctx.gh.dispatched == []


def test_an_unclaimed_hold_is_dispatched(freeze_ctx):
    from bot import cli
    cli._auto_freeze(freeze_ctx, 5, _att())
    assert freeze_ctx.gh.dispatched and freeze_ctx.gh.dispatched[0]["retry_of"] == "100"
    assert freeze_ctx.gh.dispatched[0]["retry_incident"]


def test_a_hold_written_without_a_retry_leaves_the_attempt_unresolved():
    """The interruption the audit reproduced: policy holds, incident says a retry is owed, and
    the record called itself settled."""
    from bot.attempt import Attempt
    att = Attempt(run_id="1", state="restored", frozen=["src/x"])
    assert att.unresolved, "a hold with no retry is an obligation, not a finished attempt"
    att.retry_run = "42"
    assert not att.unresolved


def test_only_one_child_may_claim(monkeypatch):
    """A duplicate dispatch, or a resume that raced, must stop before it mutates anything."""
    import pytest as _pytest

    from bot import cli

    class Gh:
        def __init__(self, existing):
            self.existing, self.posted = existing, []

        def comments(self, repo, number):
            return [{"body": b} for b in self.existing]

        def comment(self, repo, number, body):
            self.posted.append(body)

    class C:
        run_id, run_url, retry_of, retry_incident = "555", "u", "100", 7

    ctx = C()
    ctx.bot_gh = Gh([f"{af.CLAIM}9001 — first"])
    with _pytest.raises(cli.Stop, match="already claimed"):
        cli._claim_the_retry(ctx)

    ctx.bot_gh = Gh([])
    cli._claim_the_retry(ctx)
    assert af.CLAIM + "555" in ctx.bot_gh.posted[0]


# ------------------------------------------------------------------ a red builder is not a fault

class _BuildGh:
    def __init__(self, member=b""):
        self.member = member
        self.asked = []

    def artifact_member(self, repo, run_id, name, suffix):
        self.asked.append((name, suffix))
        return self.member


def _bctx(member=b""):
    class C:
        summaries = []

        def summary(self, text):
            pass
    c = C()
    c.gh = _BuildGh(member)
    return c


CANDIDATE = "c" * 40


def _batt(attempt=1, candidate=CANDIDATE):
    from bot.attempt import Attempt
    att = Attempt(run_id="1", candidate_sha=candidate)
    att.runs["binary:meshtastic"] = {"repo": BIN_REPO, "id": 7, "workflow": 9,
                                     "attempt": attempt, "sha": candidate}
    return att


BIN_REPO = "makrohard/lhpc-binaries"


def _evidence(stack="meshtastic", run="7", attempt="1", commit=CANDIDATE):
    """The bytes `build_stack` actually writes, in the builder, on an owned failure."""
    return (f"STACK-REGRESSION stack={stack} phase=build\n"
            f"builder-run: {run}\n"
            f"builder-attempt: {attempt}\n"
            f"lhpc-commit: {commit}\n").encode()


MARKED = _evidence()


# The execution GitHub returns for the run this attempt dispatched.
DISPATCHED_RUN = {"conclusion": "failure", "workflow_id": 9, "run_attempt": 1,
                  "head_sha": CANDIDATE}


def test_a_builder_that_blamed_the_recipe_attributes():
    from bot.cli import _builder_regression
    got = _builder_regression(_bctx(MARKED), "meshtastic", 7, DISPATCHED_RUN, _batt())
    assert got == ["meshtastic"]


@pytest.mark.parametrize("field,value,why", [
    ("run_attempt", 2, "a re-run keeps the run id while the execution changes"),
    ("workflow_id", 99, "a different workflow answers a different question"),
    ("head_sha", "d" * 40, "a builder built from something else"),
])
def test_evidence_from_a_different_execution_of_that_run_attributes_nothing(field, value, why):
    """Unchanged, valid marker bytes — only the execution GitHub reports differs. Evidence an
    EARLIER execution wrote must not establish what a later red one proved."""
    from bot.cli import _builder_regression
    run = dict(DISPATCHED_RUN, **{field: value})
    assert _builder_regression(_bctx(MARKED), "meshtastic", 7, run, _batt()) == [], why


def test_a_red_builder_with_no_marker_attributes_nothing():
    """A runner that died, a registry that was unreachable, a disk that filled. None of these is
    an upstream fault, and none of them writes the marker."""
    from bot.cli import _builder_regression
    assert _builder_regression(_bctx(b""), "meshtastic", 7,
                               {"conclusion": "failure"}, _batt()) == []


def test_a_cancelled_or_timed_out_builder_attributes_nothing():
    from bot.cli import _builder_regression
    for run in ({"conclusion": "cancelled"}, {"conclusion": None, "timed_out": True}):
        assert _builder_regression(_bctx(MARKED), "meshtastic", 7, run, _batt()) == []


def test_a_builder_that_blamed_another_stack_attributes_nothing():
    """It may only blame what it was dispatched to build; anything else is a builder that has
    lost track of what it was doing."""
    from bot.cli import _builder_regression
    assert _builder_regression(_bctx(_evidence(stack="meshcom")), "meshtastic", 7,
                               {"conclusion": "failure"}, _batt()) == []


def test_the_consumer_asks_for_the_visible_filename_the_builder_writes():
    """`upload-artifact` drops dotfiles by default, so evidence named `.regression` would be
    written, uploaded into nothing, and never read again."""
    from bot.cli import _builder_regression
    ctx = _bctx(MARKED)
    _builder_regression(ctx, "meshtastic", 7, {"conclusion": "failure"}, _batt())
    assert ctx.gh.asked == [("out-meshtastic-7", "meshtastic.regression")]


@pytest.mark.parametrize("evidence,why", [
    (_evidence(run="999"), "evidence from a different builder run"),
    (_evidence(attempt="3"), "evidence from a different attempt of this run"),
    (_evidence(commit="d" * 40), "evidence for a different controller candidate"),
    (b"STACK-REGRESSION stack=meshtastic phase=build\n", "a bare marker binding nothing"),
])
def test_evidence_that_does_not_answer_for_this_execution_attributes_nothing(evidence, why):
    """A marker alone only says "some meshtastic build broke once". Holding an upstream pin on
    that is exactly the unbound-evidence mistake the prove stage exists to prevent."""
    from bot.cli import _builder_regression
    assert _builder_regression(_bctx(evidence), "meshtastic", 7,
                               {"conclusion": "failure"}, _batt()) == [], why


# ------------------------------------------- from the builder's own failure to the hold

BUILD_MANIFEST = """
[[stack]]
id = "meshtastic"
  [[stack.component]]
  id = "meshtastic"
  [stack.component.source]
  path = "src/meshtastic-firmware"
  pin_commit = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
"""
BUILD_POLICY = {"source": {"src/meshtastic-firmware": {"track": "release"}}, "extra": {}}
BUILD_POLICY_TEXT = '[source."src/meshtastic-firmware"]\ntrack = "release"\n'


class _RedBuilderGh(FakeGh):
    """A binary builder that fails and blames the recipe, plus the reads `stage_build` makes."""

    def __init__(self, marker):
        super().__init__()
        self.marker = marker

    def release_asset(self, repo, tag, name):
        return b'{"schema": 2, "stacks": {}}'

    def run(self, repo, run_id):
        return {"workflow_id": 9, "run_attempt": 1, "head_sha": "c" * 40}

    def wait(self, repo, run_id, bound):
        # The execution this attempt dispatched: the same workflow, attempt and builder head
        # that `record_run` filed for it.
        return {"conclusion": "failure", "workflow_id": 9, "run_attempt": 1,
                "head_sha": "c" * 40, "html_url": "https://example.invalid/build/777"}

    def artifact_member(self, repo, run_id, name, suffix):
        # The VISIBLE name the builder writes; a dotfile would never have survived the upload.
        return self.marker if suffix.endswith(".regression") else b""

    def file_at(self, repo, path, sha):
        return BUILD_MANIFEST


class _BuildCtx(FakeCtx):
    run_id = "500"
    attempt_id = ""
    retry_of = ""
    retry_incident = ""

    def __init__(self, tmp_path, marker, att=None):
        super().__init__(tmp_path)
        self.gh = self.bot_gh = _RedBuilderGh(marker)
        self.att = att or _att(state="mutated", regression=[], evidence="",
                               moved_keys=["src/meshtastic-firmware"])

    def find_attempt(self, wanted=""):
        return 5, self.att

    def record_run(self, repo, run_id):
        return {"repo": repo, "id": int(run_id), "workflow": 9, "attempt": 1, "sha": "c" * 40}

    def clone(self, repo, ref="", token=""):
        d = self._tmp / repo.split("/")[-1]
        if not d.exists():
            d.mkdir(parents=True)
            (d / "policy.toml").write_text(BUILD_POLICY_TEXT)
        return d


def _build_then_recover(tmp_path, monkeypatch, marker):
    """Run the real `stage_build` against a red builder, then hand the record it left to the
    recovery path — the two stages are separate JOBS, so the attempt record is the only thing
    that carries the builder's verdict between them."""
    import pytest as _pytest

    from bot import cli
    monkeypatch.setenv("BINARY_STACK", "meshtastic")
    monkeypatch.setattr(cli, "MANIFEST", "m.toml")
    monkeypatch.setattr(cli.up, "load_policy", lambda p: BUILD_POLICY)
    calls = []

    def fake_git(*a, **k):
        calls.append(a)
        return " M policy.toml" if a and a[0] == "status" else ""

    monkeypatch.setattr(cli, "git", fake_git)
    ctx = _BuildCtx(tmp_path, marker)
    with _pytest.raises(cli.Stop):
        cli.stage_build(ctx)
    cli._auto_freeze(ctx, 5, ctx.att)
    return ctx, calls


def test_a_builder_that_blamed_the_recipe_becomes_a_hold_in_recovery(tmp_path, monkeypatch):
    """F1's crossing: the marker the builder wrote survives the stage boundary in the attempt
    record and becomes a real hold when recovery runs. Parsing the marker is not the contract —
    freezing the stack the builder named is."""
    # Bound to the run stage_build actually dispatches in this harness, and to the candidate on
    # the attempt record — evidence that answers for some other execution is refused, which is
    # its own case above.
    ctx, calls = _build_then_recover(tmp_path, monkeypatch, _evidence(run="777"))
    assert ctx.att.regression == ["meshtastic"]
    assert "meshtastic" in ctx.att.evidence and "777" in ctx.att.evidence
    assert ctx.att.frozen == ["src/meshtastic-firmware"]
    assert ctx.att.incident
    assert (tmp_path / "lhpc-release-bot" / "policy.toml").read_text().count("freeze") == 1
    assert any(a[0] == "commit" for a in calls) and any(a[0] == "push" for a in calls)


def test_a_red_builder_without_the_marker_holds_nothing_in_recovery(tmp_path, monkeypatch):
    """The same crossing with the same red builder and no marker: an unclassified failure gets an
    ordinary report, never a hold — a runner that died must not freeze an upstream pin."""
    ctx, calls = _build_then_recover(tmp_path, monkeypatch, b"")
    assert ctx.att.regression == []
    assert ctx.att.frozen == [] and not ctx.att.incident
    # Recovery never even reached the policy: no clone, no edit, no commit.
    assert not (tmp_path / "lhpc-release-bot").exists()
    assert not any(a[0] == "commit" for a in calls)


# ------------------------------------------------------ the rehearsal's scoped base ref

def test_an_attempt_is_based_on_main_unless_the_rehearsal_says_otherwise(monkeypatch):
    """`LHPC_REF` exists for the auto-freeze rehearsal alone. Unset — which is every real
    release — the base is `main`, and no run can quietly acquire a different one."""
    from bot.cli import base_ref
    monkeypatch.delenv("LHPC_REF", raising=False)
    assert base_ref() == "main"
    monkeypatch.setenv("LHPC_REF", "   ")
    assert base_ref() == "main"
    monkeypatch.setenv("LHPC_REF", "rehearsal/auto-freeze")
    assert base_ref() == "rehearsal/auto-freeze"


@pytest.mark.parametrize("env", ["", "main", "rehearsal/somewhere-else"])
def test_the_retry_inherits_the_ref_from_the_record_not_the_environment(freeze_ctx, monkeypatch,
                                                                       env):
    """A parent's recovery may be dispatched by anybody, with any inputs — an ordinary `recover`
    supplies no `lhpc_ref` at all. Reading the environment here turned a recorded rehearsal into
    an ordinary child whose publication predicate then allowed it to publish."""
    from bot import cli
    monkeypatch.setenv("LHPC_REF", env)
    cli._auto_freeze(freeze_ctx, 5, _att(base_ref="rehearsal/auto-freeze"))
    sent = freeze_ctx.gh.dispatched
    assert sent and sent[-1]["lhpc_ref"] == "rehearsal/auto-freeze", \
        "the child must answer for the composition its PARENT held"
    assert sent[-1]["mode"] == "full" and sent[-1]["retry_of"] == "100"


def test_an_ordinary_parent_dispatches_an_ordinary_child(freeze_ctx, monkeypatch):
    """And recovery still works with no special inputs, whatever is left in the environment."""
    from bot import cli
    monkeypatch.setenv("LHPC_REF", "rehearsal/leftover-from-something-else")
    cli._auto_freeze(freeze_ctx, 5, _att())
    assert freeze_ctx.gh.dispatched[-1]["lhpc_ref"] == "", "main is the empty input"


# ------------------------------------------------ a rehearsal publishes nothing, ever

def test_a_rehearsal_is_what_the_record_says_not_what_two_refs_compare_to():
    """A rehearsal branch may point at exactly the same commit as `main`. Defining it by
    comparing SHAs would call that an ordinary release and let it publish."""
    from bot.attempt import Attempt
    same = "e" * 40
    assert Attempt(base_sha=same, candidate_sha=same, base_ref="rehearsal/x").rehearsal
    assert not Attempt(base_sha=same, candidate_sha=same).rehearsal, "main is the default"


def test_a_rehearsal_that_would_republish_a_binary_stops_before_dispatching(tmp_path, monkeypatch):
    """Publishing a binary built from a rehearsal composition puts it in the rolling index every
    real box installs from, and a rollback afterwards cannot make that exposure not have
    happened. So it is refused at the PLAN, before any publishing dispatch."""
    from bot import cli
    monkeypatch.setenv("LHPC_REF", "rehearsal/auto-freeze")
    monkeypatch.setenv("BINARY_STACK", "meshtastic")
    att = _att(base_ref="rehearsal/auto-freeze")
    assert att.rehearsal
    with pytest.raises(cli.Stop) as stop:
        cli.stage_build(_BuildCtx(tmp_path, MARKED, att=att))
    assert "planned from" in str(stop.value.observed)


def test_the_release_stage_refuses_a_rehearsal_on_the_record(tmp_path, monkeypatch):
    """Not on a main-moved comparison — that check passes when the rehearsal ref IS main."""
    from bot import cli
    att = _att(base_ref="rehearsal/auto-freeze", state="mutated")
    ctx = _BuildCtx(tmp_path, b"", att=att)
    with pytest.raises(cli.Stop) as stop:
        cli.stage_release(ctx)
    assert "publishes nothing" in str(stop.value.next_action)


@pytest.mark.parametrize("ref,need,refused", [
    ("rehearsal/auto-freeze", ["meshtastic"], True),
    ("rehearsal/auto-freeze", [], False),          # a rehearsal that moves no covered pin is fine
    ("main", ["meshtastic"], False),               # an ordinary release publishes, that is its job
])
def test_only_a_rehearsal_that_would_publish_is_refused_at_the_plan(ref, need, refused):
    from bot.cli import rehearsal_publish_refusal
    reason = rehearsal_publish_refusal(_att(base_ref=ref), need)
    assert bool(reason) is refused
    if refused:
        assert "meshtastic" in reason and ref in reason


# ------------------------------- the obligation, across its whole lifetime

class _IssueStore:
    """Issue STATE, because that is what the lookup actually reads. A record whose issue was
    closed is invisible to `open_attempts`, however unresolved its body says it is."""

    def __init__(self):
        self.issues = {}          # number -> {"state", "body", "labels", "title"}
        self.by_issue = {}        # number -> [comment body]
        self.next = 40
        self.dispatched = []

    # -- the GitHub surface the bot uses --------------------------------------------------
    def create_issue(self, repo, title, body, labels):
        self.next += 1
        self.issues[self.next] = {"state": "open", "body": body, "labels": list(labels),
                                  "title": title}
        return {"number": self.next}

    def update_issue(self, repo, number, **fields):
        self.issues[number].update(fields)
        return {}

    def open_issues(self, repo, label):
        return [{"number": n, "title": i["title"], "body": i["body"]}
                for n, i in self.issues.items()
                if i["state"] == "open" and label in i["labels"]]

    def comment(self, repo, number, body):
        self.by_issue.setdefault(number, []).append(body)
        return {}

    def comments(self, repo, number):
        return [{"body": b} for b in self.by_issue.get(number, [])]

    def dispatch(self, repo, workflow, ref, inputs=None):
        self.dispatched.append(inputs or {})
        return 777


def test_a_hold_that_owes_a_retry_keeps_the_attempt_findable():
    """`open_attempts` reads OPEN issues. Live attempt #7 was closed while its body still said
    unresolved, so recovering it answered 'no attempt to recover' while the policy carried the
    hold — the obligation was simply gone."""
    from bot.attempt import Attempt
    owed = Attempt(run_id="100", state="restored", frozen=["src/LoRaHAM_Daemon"], incident=99)
    assert owed.unresolved, "a written hold with no claimed retry still owes one"
    owed.retry_run = "200"
    assert not owed.unresolved, "once a child has taken it, the parent owes nothing"


def test_an_incident_without_a_written_hold_still_owes():
    """The incident is opened BEFORE the policy is pushed. A run lost in between left an issue
    asserting a retry was owed while `frozen` was empty, and keying only on `frozen` called that
    settled."""
    from bot.attempt import Attempt
    assert Attempt(run_id="1", state="restored", incident=99).unresolved


def test_only_the_designated_retry_passes_its_parents_block():
    """The real predicate `stage_plan` uses. Leaving the parent open is not enough on its own:
    the child's own plan rejects unresolved attempts before it ever reaches its claim."""
    from bot.attempt import Attempt
    from bot.cli import blocking_attempts
    parent = Attempt(run_id="100", state="restored", frozen=["src/x"], incident=99)
    other = Attempt(run_id="555", state="mutated")

    assert blocking_attempts([(1, parent)], "100") == [], "its own retry may pass"
    assert blocking_attempts([(1, parent)], "") != [], "anything else still stops"
    assert blocking_attempts([(1, parent), (2, other)], "100") == [(2, other)], \
        "passing your parent does not let you past an unrelated unresolved attempt"


def test_the_issue_state_lookup_is_what_loses_an_obligation(tmp_path, monkeypatch):
    """Driven through the REAL `Ctx.open_attempts`, because issue STATE is what it reads.

    Live attempt #7 carried a written hold and an unclaimed retry, and was closed anyway. Its
    body still said unresolved; the lookup could not see it.
    """
    from bot import cli
    from bot.attempt import Attempt

    att = Attempt(run_id="100", state="restored", base_sha="b" * 40, candidate_sha="c" * 40,
                  regression=["chat"], moved_keys=["src/LoRaHAM_Daemon"],
                  frozen=["src/LoRaHAM_Daemon"], incident=99)
    store = _IssueStore()
    number = store.create_issue(cli.BOT, f"attempt {att.run_id}", att.to_body(),
                                [cli.LABEL])["number"]

    ctx = _BuildCtx(tmp_path, b"")
    ctx.bot_gh = store

    found = cli.Ctx.open_attempts(ctx)
    assert [a.run_id for _n, a in found] == ["100"]
    assert found[0][1].unresolved
    assert cli.blocking_attempts(found, "") != [], "an owed retry blocks an unrelated release"

    store.update_issue(cli.BOT, number, state="closed")
    assert cli.Ctx.open_attempts(ctx) == [], "closed is invisible — which is why recovery must " \
                                             "not close an attempt that still owes a retry"


def test_recovery_leaves_an_attempt_open_while_it_still_owes_a_retry(tmp_path, monkeypatch):
    """The crossing the audit asked for: real `stage_recover`, real issue state.

    Live attempt #7 went through exactly this path and was closed with an unclaimed retry still
    owed, which put the obligation out of reach of every later lookup.
    """
    from bot import cli
    from bot.attempt import Attempt

    store = _IssueStore()
    att = Attempt(run_id="100", state="mutated", version="0.3.13", base_sha="b" * 40,
                  candidate_sha="c" * 40, branch="pins/0.3.13-100", regression=["chat"],
                  moved_keys=["src/LoRaHAM_Daemon"], evidence="the lane")
    number = store.create_issue(cli.BOT, "attempt 100", att.to_body(), [cli.LABEL])["number"]

    class _Gh(_RedBuilderGh):
        def ref(self, repo, ref):
            # `main` is exactly where this attempt started (so the hold is still about the
            # composition it captured); the tag does not exist, so nothing was released.
            return "b" * 40 if ref == "heads/main" else ""
        def is_ancestor(self, repo, a, b):
            return False
        def unfinished_runs(self, repo, workflow=""):
            return []
        def file_at(self, repo, path, sha):
            return BUILD_MANIFEST_CHAT

    class _Ctx(_BuildCtx):
        run_id = "100"
        def __init__(self, tmp_path):
            super().__init__(tmp_path, b"", att=att)
            self.gh = _Gh(b"")
            self.bot_gh = store
        def find_attempt(self, wanted=""):
            return number, self.att

    monkeypatch.setattr(cli, "MANIFEST", "m.toml")
    monkeypatch.setattr(cli, "git", lambda *a, **k: " M policy.toml" if a and a[0] == "status" else "")
    monkeypatch.setattr(cli.up, "load_policy",
                        lambda p: {"source": {"src/LoRaHAM_Daemon": {"track": "tip"}}, "extra": {}})
    ctx = _Ctx(tmp_path)
    (tmp_path / "lhpc-release-bot").mkdir(parents=True, exist_ok=True)
    (tmp_path / "lhpc-release-bot" / "policy.toml").write_text(
        '[source."src/LoRaHAM_Daemon"]\ntrack = "tip"\n')

    assert cli.stage_recover(ctx, "100") == 0
    assert att.frozen == ["src/LoRaHAM_Daemon"], "the hold was written"
    assert att.incident, "an incident was opened"
    assert not att.retry_run, "and no child has claimed it in this test"
    assert store.issues[number]["state"] == "open", \
        "an attempt that still owes its retry must stay findable"


BUILD_MANIFEST_CHAT = """
[[stack]]
id = "chat"
  [[stack.component]]
  id = "loraham-chat"
  [stack.component.source]
  path = "src/LoRaHAM_Daemon"
  pin_commit = "cccccccccccccccccccccccccccccccccccccccc"
"""


def test_the_plan_claims_its_retry_before_either_branch():
    """A structural guard, because the defect was an ORDER.

    The no-move path used to return through baseline verification without ever claiming, so a
    child that found nothing eligible still did real work — it dispatched proof — while the
    incident said the retry was unclaimed and a second child could take it. `_claim_the_retry`
    must therefore come before the `if not moved:` branch, not inside the other one.
    """
    import inspect

    from bot import cli
    src = inspect.getsource(cli.stage_plan)
    claim, branch = src.index("_claim_the_retry(ctx)"), src.index("if not moved:")
    check = src.index("_check_parent(ctx,")
    assert claim < branch, "the no-move branch can return without claiming its retry"
    assert check < branch, \
        "a child must validate its parent's baseline and holds before either branch"
    assert check < claim, \
        "a child that must refuse would consume the one claim the hold is owed"

    # And the frozen-only branch settles its parent BEFORE it raises on a failed proof — a retry
    # that proved the held composition still fails has discharged its obligation just as much as
    # one that proved it good.
    settle = src.index("_settle_parent(ctx, Attempt(")
    assert settle < src.index('raise Stop("plan", "the held baseline did not pass'), \
        "a failed baseline proof would leave the parent owing a retry that already ran"


# ------------------------------------------- the interruption permutations of an owed retry

@pytest.mark.parametrize("stopped_at,frozen,incident,retry_run,still_owed", [
    ("before the incident exists",        [],                 0,  "",    False),
    ("after the incident, before the push", [],               99, "",    True),
    ("after the hold was pushed",         ["src/LoRaHAM_Daemon"], 99, "", True),
    ("after a child claimed it",          ["src/LoRaHAM_Daemon"], 99, "200", False),
])
def test_where_an_interruption_leaves_the_obligation(stopped_at, frozen, incident, retry_run,
                                                     still_owed):
    """Every point a freeze can be cut in half, and whether the obligation survives it.

    The two that matter are the middle rows. The incident is opened BEFORE the policy is pushed,
    so a run lost in between has already told a reader that a retry is owed — and a record that
    called that settled left a real hold with nobody answering for it. The last row is the only
    way an attempt stops owing: a child took the work.
    """
    from bot.attempt import Attempt
    att = Attempt(run_id="100", state="restored", frozen=list(frozen), incident=incident,
                  retry_run=retry_run)
    assert att.unresolved is still_owed, stopped_at


def test_a_lost_dispatch_reply_does_not_invent_a_child(tmp_path, monkeypatch):
    """The parent cannot tell a POST it never sent from one whose reply it lost, so it does not
    decide — it reads the incident. With no claim there, the attempt still owes its retry, and
    the next recovery may send one."""
    from bot import cli
    ctx = _BuildCtx(tmp_path, b"")
    # The freeze_ctx fixture's manifest and policy: meshcore, whose inputs this bot may hold.
    ctx.gh.file_at = lambda repo, path, sha: MANIFEST
    ctx.clone = lambda repo, ref="", token="": _policy_dir(tmp_path)
    att = _att()
    monkeypatch.setattr(cli, "MANIFEST", "m.toml")
    monkeypatch.setattr(cli, "git", lambda *a, **k: " M policy.toml" if a and a[0] == "status" else "")
    monkeypatch.setattr(cli.up, "load_policy", lambda p: POLICY_FOR_STAGE)
    ctx.gh.dispatched = []
    cli._auto_freeze(ctx, 5, att)
    assert att.incident, "the incident exists"
    assert not att.retry_run, "no claim was posted, so no child is asserted"
    assert att.unresolved, "and the attempt still owes one"


def _policy_dir(tmp_path):
    d = tmp_path / "lhpc-release-bot"
    d.mkdir(parents=True, exist_ok=True)
    (d / "policy.toml").write_text(STAGE_POLICY_TEXT)
    return d


# ------------------------------------- the whole retry lifecycle, over real issue state

def _held_parent_store():
    """A parent that wrote a hold, dispatched its retry, and is waiting — as recovery leaves it."""
    from bot import cli
    from bot.attempt import Attempt
    store = _IssueStore()
    parent = Attempt(run_id="100", state="restored", base_sha="b" * 40, candidate_sha="c" * 40,
                     regression=["meshcore"], moved_keys=["src/openhop-core"],
                     frozen=["src/meshcore-cli", "src/openhop-core"], incident=99,
                     evidence="the lane")
    number = store.create_issue(cli.BOT, "attempt 100", parent.to_body(), [cli.LABEL])["number"]
    store.create_issue(cli.BOT, "auto-freeze: meshcore", "held", [af.LABEL])
    return store, number, parent


class _ChildCtx(_BuildCtx):
    """A child run, with the parent's issue state as its only source of truth about the parent."""

    def __init__(self, tmp_path, store, *, run_id="200", retry_of="100"):
        super().__init__(tmp_path, b"")
        self.bot_gh = store
        self.run_id = run_id
        self.retry_of = retry_of
        self.retry_incident = "99"

    def open_attempts(self):
        from bot import cli
        return cli.Ctx.open_attempts(self)          # the REAL lookup, over real issue state

    def find_attempt(self, wanted=""):
        return next(((n, a) for n, a in self.open_attempts()
                     if not wanted or a.run_id == wanted), (0, None))

    def save_attempt(self, number, att):
        from bot import cli
        return cli.Ctx.save_attempt(self, number, att)   # the REAL write, into the store


def test_a_successful_retry_settles_its_parent_and_unblocks_the_next_run(tmp_path):
    """The lifecycle, asserted from PERSISTED state.

    A claim only says a child took the work. Until its terminal result is written the parent
    still owes a retry — and it used to owe it for ever: `retry_run` stayed empty, the body kept
    saying unresolved, and the next ordinary run refused a hold whose retry had already passed.
    """
    from bot import cli
    store, number, _ = _held_parent_store()
    ctx = _ChildCtx(tmp_path, store)

    # Before: the parent owes its retry, and an unrelated run is blocked by it.
    before = cli.Ctx.open_attempts(ctx)
    assert [a.run_id for _n, a in before] == ["100"] and before[0][1].unresolved
    assert cli.blocking_attempts(before, "") != [], "an owed retry blocks an unrelated release"
    assert cli.blocking_attempts(before, "100") == [], "but not the child it is owed from"

    # The child claims, then finishes its proof.
    cli._claim_the_retry(ctx)
    proof = {"repo": "makrohard/loraham-pi-control", "id": 555, "workflow": 3,
             "attempt": 1, "sha": "b" * 40}
    cli._settle_parent(ctx, Attempt(run_id="200", retry_of="100"),
                       "held baseline passed", proof=proof)

    # After: read back from the issue store, not from the object we mutated.
    assert store.issues[number]["state"] == "closed"
    settled = cli.record_of_labelled_issue(number, store.issues[number]["body"])
    assert settled.retry_run == "200", "the parent must name the child that discharged it"
    assert settled.runs.get("baseline", {}).get("id") == 555, \
        "the proof execution must be durable, not a local variable in the run that made it"
    assert not settled.unresolved
    assert cli.Ctx.open_attempts(ctx) == [], "and the next ordinary run is no longer blocked"
    # The claim is on the incident, addressed exactly as the code addresses it.
    assert any(af.CLAIM in c["body"] for c in store.comments(cli.BOT, ctx.retry_incident))


def test_a_failed_proof_also_discharges_the_obligation(tmp_path):
    """A retry that proved the held composition still fails has done its job. What differs is
    what a maintainer does next, not who owes the work — and a settled hold must not keep
    blocking unrelated releases."""
    from bot import cli
    store, number, _ = _held_parent_store()
    ctx = _ChildCtx(tmp_path, store)
    cli._settle_parent(ctx, Attempt(run_id="200", retry_of="100"), "held baseline FAILED")

    settled = cli.record_of_labelled_issue(number, store.issues[number]["body"])
    assert settled.retry_run == "200" and not settled.unresolved
    assert any("FAILED" in n for n in settled.notes), "the outcome must be readable afterwards"
    assert store.issues[number]["state"] == "closed"


def test_a_child_cancelled_after_claiming_leaves_the_obligation_with_the_parent(tmp_path):
    """The reason settlement is not done at claim time. A run that claims and then dies must not
    take the obligation with it."""
    from bot import cli
    store, number, _ = _held_parent_store()
    ctx = _ChildCtx(tmp_path, store)
    cli._claim_the_retry(ctx)                     # ... and then nothing else happens

    still = cli.record_of_labelled_issue(number, store.issues[number]["body"])
    assert still.unresolved, "a claim alone must not settle anything"
    assert store.issues[number]["state"] == "open"
    assert cli.blocking_attempts(cli.Ctx.open_attempts(ctx), "") != []


def test_a_second_child_cannot_take_a_claimed_retry(tmp_path):
    """One hold, one retry. A duplicate dispatch or a resume that raced finds the claim."""
    from bot import cli
    store, _number, _ = _held_parent_store()
    cli._claim_the_retry(_ChildCtx(tmp_path, store, run_id="200"))
    with pytest.raises(cli.Stop) as stop:
        cli._claim_the_retry(_ChildCtx(tmp_path, store, run_id="201"))
    assert "already claimed" in str(stop.value.observed)


def test_settling_a_parent_that_is_gone_is_harmless(tmp_path):
    """Settled by hand, or thawed and closed while the child ran."""
    from bot import cli
    store, number, _ = _held_parent_store()
    store.update_issue(cli.BOT, number, state="closed")
    cli._settle_parent(_ChildCtx(tmp_path, store), Attempt(run_id="200", retry_of="100"),
                       "held baseline passed")   # must not raise


def test_the_proof_answers_for_the_parents_ref_not_this_runs_environment(tmp_path, monkeypatch):
    """A retry dispatched by hand, or re-dispatched with different inputs, must still prove the
    composition its PARENT held. Reading the ref from this run's environment is the same class of
    mistake as reading a child's publication mode from it."""
    from bot import cli
    store, _number, _ = _held_parent_store()
    ctx = _ChildCtx(tmp_path, store)
    monkeypatch.setenv("LHPC_REF", "some/other-branch")

    # The parent in the fixture was planned from `main`.
    assert cli._parent_ref(ctx) == "main"

    # And when the parent was a rehearsal, the child answers for THAT.
    from bot.attempt import Attempt
    reh = Attempt(run_id="300", state="restored", frozen=["src/x"], incident=98,
                  base_ref="rehearsal/somewhere")
    store.create_issue(cli.BOT, "attempt 300", reh.to_body(), [cli.LABEL])
    assert cli._parent_ref(_ChildCtx(tmp_path, store, run_id="301", retry_of="300")) \
        == "rehearsal/somewhere"

    # And the frozen-only branch must actually ASK it. Structural, because the defect is a
    # substitution: `base_ref()` reads this run's environment and is otherwise interchangeable.
    import inspect
    src = inspect.getsource(cli.stage_plan)
    call = src[src.index("_verify_baseline("):]
    call = call[:call.index("\n", call.index(")"))]
    assert "_parent_ref(ctx)" in call, f"the proof must answer for the parent's ref: {call}"


def test_an_unrecorded_execution_field_refuses_rather_than_passes():
    """Absence is not agreement. A record this bot cannot check is a record it must not hold an
    upstream pin on — `if want and got != want` treated a missing field as a match."""
    from bot.attempt import Attempt
    from bot.cli import _builder_regression
    att = Attempt(run_id="1", candidate_sha=CANDIDATE)
    # The record binds the attempt (so the marker checks all pass) but never recorded the
    # workflow or the builder head. GitHub returns a run missing exactly those fields, so both
    # sides are absent and compare EQUAL — without the explicit refusal this evidence is accepted
    # on a record that ties it to nothing.
    att.runs["binary:meshtastic"] = {"repo": BIN_REPO, "id": 7, "attempt": 1}
    blind = {"conclusion": "failure", "run_attempt": 1}
    assert _builder_regression(_bctx(MARKED), "meshtastic", 7, blind, att) == []


def test_the_frozen_only_branch_is_actually_driven(tmp_path, monkeypatch):
    """The call path nothing covered.

    Two defects hid here in a row: `_verify_baseline` dispatched a commit SHA, which
    `workflow_dispatch` refuses, and later its caller passed the wrong number of arguments
    entirely — 231 tests stayed green through both, because no test ever entered this branch.
    So this one calls it, with the GitHub surface faked at the seam and nothing else.
    """
    from bot import cli

    seen = {}

    class _Gh(_RedBuilderGh):
        def ref(self, repo, ref):
            seen["ref_read"] = ref
            return "b" * 40

        def dispatch(self, repo, workflow, ref, inputs=None):
            seen["dispatched_at"] = ref          # a REF, never a commit
            return 4242

        def wait(self, repo, run_id, bound):
            return {"conclusion": "success", "workflow_id": 9, "run_attempt": 1,
                    "head_sha": "b" * 40, "html_url": "u"}

        def jobs(self, repo, run_id, attempt):
            return [{"name": n, "conclusion": "success"} for n in cli.REQUIRED_TESTLAB]

        def artifact_member(self, repo, run_id, name, suffix):
            cases = "".join(f'<testcase name="{c}"/>' for c in
                            json.loads(CASE_JSON)["required_cases"])
            return f"<testsuite>{cases}</testsuite>".encode()

        def file_at(self, repo, path, sha):
            return CASE_JSON

    ctx = _BuildCtx(tmp_path, b"")
    ctx.gh = _Gh(b"")
    ctx.run_id = "200"
    verdict, proof = cli._verify_baseline(ctx, [], "main")

    assert verdict == "passed", "every required case was present and green"
    assert seen["dispatched_at"] == "main", \
        f"dispatched at {seen['dispatched_at']!r} — a commit SHA is refused by workflow_dispatch"
    assert proof and proof["id"] == 4242, "the execution must come back for the parent's record"


CASE_JSON = json.dumps({"required_cases": ["test_release_kiss", "test_release_chat"]})


def test_a_baseline_that_could_not_be_read_is_unproven_not_failed(tmp_path):
    """"Could not check" and "checked and bad" are different answers. Reporting the first as the
    second tells a maintainer the held composition is broken when nothing was measured — and it
    would discharge a retry obligation that nothing has actually discharged."""
    from bot import cli

    class _NoRef(_RedBuilderGh):
        def ref(self, repo, ref):
            return ""                       # the ref cannot be read at all

    ctx = _BuildCtx(tmp_path, b"")
    ctx.gh = _NoRef(b"")
    verdict, proof = cli._verify_baseline(ctx, [], "main")
    assert verdict == "unproven" and proof == {}


def test_an_unproven_baseline_leaves_the_obligation_where_it_was():
    """Structural: the frozen-only branch must settle on a MEASURED verdict only."""
    import inspect

    from bot import cli
    src = inspect.getsource(cli.stage_plan)
    settle = src.index("_settle_parent(ctx, Attempt(")
    guard = src.rindex("if verdict != \"unproven\":", 0, settle)
    assert guard < settle, "an unmeasured baseline must not discharge the retry"


def _baseline_gh(*, junit=None, cases=CASE_JSON, refs=("b" * 40,), red=()):
    """A GitHub surface where the held baseline's proof is green, with one thing broken.

    `refs` is read in order, so a second value models a ref that moved while the proof was in
    flight. `red` names required cases the lane reported as failures.
    """
    from bot import cli

    class _Gh(_RedBuilderGh):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._refs = list(refs)

        def ref(self, repo, ref):
            return self._refs.pop(0) if len(self._refs) > 1 else self._refs[0]

        def dispatch(self, repo, workflow, ref, inputs=None):
            return 4242

        def wait(self, repo, run_id, bound):
            return {"conclusion": "success", "workflow_id": 9, "run_attempt": 1,
                    "head_sha": "b" * 40, "html_url": "u"}

        def jobs(self, repo, run_id, attempt):
            return [{"name": n, "conclusion": "success"} for n in cli.REQUIRED_TESTLAB]

        def artifact_member(self, repo, run_id, name, suffix):
            if junit is not None:
                return junit
            body = "".join(
                f'<testcase name="{c}">{"<failure/>" if c in red else ""}</testcase>'
                for c in json.loads(CASE_JSON)["required_cases"])
            return f"<testsuite>{body}</testsuite>".encode()

        def file_at(self, repo, path, sha):
            return cases

    return _Gh(b"")


@pytest.mark.parametrize(("what", "kwargs"), [
    ("the lane's artifact was not there at all", {"junit": b""}),
    ("the lane's JUnit could not be parsed", {"junit": b"<not xml"}),
    ("the commit states no required cases", {"cases": ""}),
    ("the ref moved while the proof was in flight", {"refs": ("b" * 40, "c" * 40)}),
])
def test_evidence_this_bot_could_not_read_is_unproven_not_failed(tmp_path, what, kwargs):
    """The lane was GREEN in every one of these; what failed was the reading of its evidence.

    Calling that "failed" tells a maintainer the held composition is broken when nothing about
    the composition was measured, and — because only a measured verdict settles — it would also
    discharge a retry obligation that nothing has discharged. Infrastructure faults must not be
    able to write a verdict about upstream code.
    """
    from bot import cli
    ctx = _BuildCtx(tmp_path, b"")
    ctx.gh = _baseline_gh(**kwargs)
    verdict, _proof = cli._verify_baseline(ctx, [], "main")
    assert verdict == "unproven", f"{what}: nothing was measured, so nothing may be blamed"


def test_a_required_case_the_lane_reported_red_is_a_measured_failure(tmp_path):
    """The other half, and the reason the distinction is not simply "be cautious everywhere":
    readable evidence naming a red case IS grounds to say the held composition does not pass."""
    from bot import cli
    ctx = _BuildCtx(tmp_path, b"")
    ctx.gh = _baseline_gh(red=("test_release_chat",))
    verdict, proof = cli._verify_baseline(ctx, [], "main")
    assert verdict == "failed" and proof, "a red case is measured, and settles the retry"


# ------------------------------------------------- R7-1: the repair path, not the happy path


def _released_child(store, *, run_id="200", retry_of="100"):
    """A child that RELEASED and owes nothing — the state `finish` is pointed at."""
    from bot import cli
    child = Attempt(run_id=run_id, retry_of=retry_of, state="image-published",
                    version="0.3.15", base_sha="b" * 40, candidate_sha="d" * 40,
                    integration="pr", image_tag="v0.3.15")
    number = store.create_issue(cli.BOT, f"attempt {run_id}", child.to_body(), [cli.LABEL])
    return number["number"], child


class _FinishCtx(_BuildCtx):
    """A HAND-RUN `finish`: an attempt id and nothing else.

    This is the context that exposed R7-1. The automatic dispatch carries `retry_of` and
    `retry_incident`; an operator repairing an interrupted release does not, and cannot be
    expected to reconstruct them.
    """

    def __init__(self, tmp_path, store, attempt_id):
        super().__init__(tmp_path, b"")
        self.bot_gh = store
        self.run_id = "900"                 # the FINISH run, not the retry
        self.retry_of = ""                  # no retry inputs at all
        self.retry_incident = 0
        self.attempt_id = attempt_id

    # The real lookup, against the fake issue store — the stub in _BuildCtx always returns one
    # attempt, which would hide exactly the identity confusion these tests are about.
    def find_attempt(self, wanted=""):
        from bot import cli
        return cli.Ctx.find_attempt(self, wanted)

    def open_attempts(self):
        from bot import cli
        return cli.Ctx.open_attempts(self)

    def save_attempt(self, number, att):
        from bot import cli
        return cli.Ctx.save_attempt(self, number, att)


def test_a_hand_run_finish_still_settles_the_parent(tmp_path):
    """R7-1. `finish` on the released child, with no retry inputs, must settle the parent.

    Settlement used to read `ctx.retry_of` and record `ctx.run_id`, so this path closed the child
    and returned immediately. The parent kept an empty `retry_run`, stayed unresolved and blocked
    every later release — and `recover` on it refuses, because by then the version it names is
    held by the child's commit. The identity has to come from the child's record.
    """
    from bot import cli
    store, parent_number, _ = _held_parent_store()
    child_number, child = _released_child(store)
    ctx = _FinishCtx(tmp_path, store, "200")

    assert cli.blocking_attempts(cli.Ctx.open_attempts(ctx), "") != [], "parent blocks first"

    cli.stage_finalize(ctx)

    parent = cli.record_of_labelled_issue(parent_number, store.issues[parent_number]["body"])
    assert parent.retry_run == "200", \
        f"the parent must name the CHILD that discharged it, not the finish run: {parent.retry_run!r}"
    assert not parent.unresolved
    assert store.issues[parent_number]["state"] == "closed", "and the parent must be closed"
    assert store.issues[child_number]["state"] == "closed", "the child too"
    assert cli.blocking_attempts(cli.Ctx.open_attempts(ctx), "") == [], \
        "the next ordinary release must no longer be blocked"


def test_an_interruption_between_the_two_terminal_writes_leaves_the_child_findable(tmp_path):
    """R7-1, second boundary: the ORDER of the two terminal writes.

    Attempt lookup searches OPEN issues. Closing the child first meant a failure before the
    parent was settled left the parent owing a retry and the child unreachable — the repeat run
    answered "no attempt to finalize" while the parent went on blocking every release.

    The failure is injected at the SETTLEMENT, which is the only place that distinguishes the two
    orders: settle-then-close leaves the child open for the repeat run, close-then-settle has
    already thrown it away. Injecting at the child's close instead would pass under either order
    and prove nothing — which is what a first version of this test did.
    """
    from bot import cli
    store, parent_number, _ = _held_parent_store()
    child_number, _ = _released_child(store)
    ctx = _FinishCtx(tmp_path, store, "200")

    real_update = store.update_issue
    def fail_when_settling_the_parent(repo, number, **kw):
        if number == parent_number:
            raise RuntimeError("connection reset")
        return real_update(repo, number, **kw)
    store.update_issue = fail_when_settling_the_parent

    with pytest.raises(RuntimeError):
        cli.stage_finalize(ctx)

    assert store.issues[child_number]["state"] == "open", \
        "the child must still be findable: settlement has to be attempted BEFORE it is closed"
    store.update_issue = real_update

    repeat = _FinishCtx(tmp_path, store, "200")
    cli.stage_finalize(repeat)                                   # the repair run
    assert store.issues[child_number]["state"] == "closed"
    assert store.issues[parent_number]["state"] == "closed"
    assert cli.blocking_attempts(cli.Ctx.open_attempts(repeat), "") == []


@pytest.mark.parametrize("stage", ["integrate", "image"])
def test_finish_refuses_an_attempt_that_released_nothing(tmp_path, stage):
    """R7-1, third boundary: a typo in the operator path must not authorise finishing a rejected
    candidate.

    `finish` repairs a release that STANDS. Pointed at a restored attempt — one digit away from
    the right id — integrate would have pushed a candidate nothing released towards `dev`, and
    image would have cut an image for a tag that does not exist. Recovery owns those attempts.
    """
    from bot import cli
    store, _parent_number, _ = _held_parent_store()          # attempt 100 is `restored`
    ctx = _FinishCtx(tmp_path, store, "100")

    with pytest.raises(cli.Stop) as caught:
        (cli.stage_integrate if stage == "integrate" else cli.stage_image)(ctx)
    assert "never reached the commit point" in caught.value.observed
    assert "recover" in caught.value.next_action.lower()


# ---------------------------------------- R7-2: precedence, not a majority vote, in the verdict


def _baseline_gh_invalid(*, head_sha=None, conclusion="failure", junit=None, refs=("b" * 40,),
                         red=("test_release_chat",), also_red=()):
    """A baseline proof whose evidence is RED and, in some way, not to be trusted."""
    from bot import cli

    class _Gh(_RedBuilderGh):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._refs = list(refs)

        def ref(self, repo, ref):
            return self._refs.pop(0) if len(self._refs) > 1 else self._refs[0]

        def dispatch(self, repo, workflow, ref, inputs=None):
            return 4242

        def wait(self, repo, run_id, bound):
            return {"conclusion": conclusion, "workflow_id": 9, "run_attempt": 1,
                    "head_sha": head_sha or "b" * 40, "html_url": "u"}

        def jobs(self, repo, run_id, attempt):
            # The lane job mirrors the run: a green run has a green lane, a red one a red lane.
            lane = "success" if conclusion == "success" else "failure"
            return [{"name": n,
                     "conclusion": lane if n == cli.LANE_JOB else
                     "failure" if n in also_red else "success"}
                    for n in cli.REQUIRED_TESTLAB]

        def artifact_member(self, repo, run_id, name, suffix):
            if junit is not None:
                return junit
            body = "".join(
                f'<testcase name="{c}">{"<failure/>" if c in red else ""}</testcase>'
                for c in json.loads(CASE_JSON)["required_cases"])
            return f"<testsuite>{body}</testsuite>".encode()

        def file_at(self, repo, path, sha):
            return CASE_JSON

    return _Gh(b"")


@pytest.mark.parametrize(("what", "kwargs"), [
    ("the run answers for a different controller commit", {"head_sha": "f" * 40}),
    ("the run was cancelled, leaving partial failing JUnit", {"conclusion": "cancelled"}),
    ("the run failed and its JUnit artifact is missing", {"junit": b""}),
    ("the baseline ref moved while the proof was in flight", {"refs": ("b" * 40, "c" * 40)}),
])
def test_red_evidence_from_an_untrustworthy_run_is_unproven_not_failed(tmp_path, what, kwargs):
    """R7-2. Precedence, not a majority vote.

    Each of these carries genuinely RED evidence — a failed lane job, a red required case — AND a
    reason the evidence cannot answer for the held composition. Reading the verdict as
    `outcome or red` alone let the red half win, so the bot reported a held composition as broken
    on the strength of a run that never answered for it, and discharged a retry that had measured
    nothing. Each half had a test; the combination did not.
    """
    from bot import cli
    ctx = _BuildCtx(tmp_path, b"")
    ctx.gh = _baseline_gh_invalid(**kwargs)
    verdict, _proof = cli._verify_baseline(ctx, [], "main")
    assert verdict == "unproven", f"{what}: nothing trustworthy was measured, so nothing may be blamed"


def test_the_controls_still_settle(tmp_path):
    """The other half of precedence: a VALID run whose required case is red is still `failed`,
    and a valid green one is still `passed`. Precedence must not swallow real measurements."""
    from bot import cli
    ctx = _BuildCtx(tmp_path, b"")
    ctx.gh = _baseline_gh_invalid()                       # valid identity, red case
    assert cli._verify_baseline(ctx, [], "main")[0] == "failed"

    ctx2 = _BuildCtx(tmp_path, b"")
    ctx2.gh = _baseline_gh_invalid(conclusion="success", red=())
    assert cli._verify_baseline(ctx2, [], "main")[0] == "passed"


def test_a_doubly_red_baseline_is_failed_not_unproven(tmp_path):
    """R8-1, and the shape this repo has actually witnessed.

    When the kiss regression was broken on purpose, the release lane went red AND the ordinary
    `testlab` job went red with it — the same source breaks both. Splitting `identity` off from
    `outcome` was right, but a red job that is not the lane was left in `identity`, and a later
    change made everything in `identity` mean "could not measure". The two together turned the
    ordinary shape of a broken held baseline into `unproven`: the parent would then never settle,
    and every later release would be blocked behind an obligation nothing could ever discharge.

    A required job that ran on this commit and concluded failure IS a measurement. It names no
    stack — which is why it still bars an attribution in `stage_prove` — but the question here is
    only whether the held composition still passes, and it answers that.
    """
    from bot import cli
    ctx = _BuildCtx(tmp_path, b"")
    ctx.gh = _baseline_gh_invalid(also_red=("testlab",))
    verdict, _proof = cli._verify_baseline(ctx, [], "main")
    assert verdict == "failed", "lane red AND an ordinary required job red is a measured failure"


def test_an_ordinary_job_red_on_its_own_is_still_failed(tmp_path):
    """The lane green, an ordinary job red: nothing to attribute, but something was measured."""
    from bot import cli
    ctx = _BuildCtx(tmp_path, b"")
    ctx.gh = _baseline_gh_invalid(conclusion="success", red=(), also_red=("testlab",))
    assert cli._verify_baseline(ctx, [], "main")[0] == "failed"


def test_a_hand_run_finish_still_tells_the_incident_what_happened(tmp_path):
    """The reporting half of R7-1. A hand-run `finish` carries no incident number either.

    Without the parent's record to fall back on, the terminal outcome went nowhere: the incident
    kept a claim and never learned the retry had released, so a reader saw a retry owed for ever.
    """
    from bot import cli
    store, _parent_number, parent = _held_parent_store()
    _child_number, _child = _released_child(store)
    ctx = _FinishCtx(tmp_path, store, "200")

    cli.stage_finalize(ctx)

    said = [c["body"] for c in store.comments(cli.BOT, parent.incident)]
    assert any("Retry 200:" in b and "released" in b for b in said), \
        f"the incident must be told, with the CHILD's id, not the finish run's: {said}"
    assert not any("Retry 900:" in b for b in said), "never the finish run's own id"
