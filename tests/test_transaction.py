"""The two decisions that keep a failed run from damaging a good release: which binary entry
this attempt may undo, and whether an image really is this release's.

Each case here is a way the bot could act on something that is not its own — an entry another
publisher wrote, a publish whose outcome it never learned, a green build with no release behind
it, a tag that has stopped meaning what it meant.
"""
from __future__ import annotations

import pytest

from bot.cli import IMAGE_EVIDENCE, image_problems, reconcile

CAND = "c" * 40


def entry(sha="a", lhpc="1"):
    return {"filename": f"meshtastic-{sha * 8}.tar.zst", "sha256": sha * 64,
            "lhpc_commit": lhpc * 40, "components": {"meshtastic": "b" * 40}}


OLD, MINE, FOREIGN = entry("8"), entry("6", "2"), entry("f", "9")


def test_the_entry_this_attempt_published_is_the_one_it_may_restore():
    restore, noop, conflicts = reconcile(
        ["meshtastic"], {"meshtastic": MINE}, {"meshtastic": MINE}, {"meshtastic": OLD})
    assert (restore, noop, conflicts) == (["meshtastic"], [], [])


def test_an_entry_somebody_else_published_is_a_conflict_never_a_restore():
    """The counterexample this exists for: adopting whatever changed in the index would let a
    rollback delete another publisher's work."""
    restore, noop, conflicts = reconcile(
        ["meshtastic"], {"meshtastic": MINE}, {"meshtastic": FOREIGN}, {"meshtastic": OLD})
    assert (restore, noop, conflicts) == ([], [], ["meshtastic"])


def test_a_dispatch_whose_outcome_is_unknown_is_a_conflict_not_a_no_op():
    """A publish was started and we never learned what it did. Concluding 'nothing happened'
    from our own missing note is exactly the inference that loses a release."""
    restore, noop, conflicts = reconcile(
        ["meshtastic"], {}, {"meshtastic": FOREIGN}, {"meshtastic": OLD})
    assert conflicts == ["meshtastic"] and restore == [] and noop == []


def test_a_dispatch_that_never_published_is_a_verified_no_op():
    restore, noop, conflicts = reconcile(
        ["meshtastic"], {}, {"meshtastic": OLD}, {"meshtastic": OLD})
    assert (restore, noop, conflicts) == ([], ["meshtastic"], [])


def test_two_stacks_are_judged_independently():
    restore, noop, conflicts = reconcile(
        ["meshtastic", "meshcom"],
        {"meshtastic": MINE, "meshcom": MINE},
        {"meshtastic": MINE, "meshcom": FOREIGN},
        {"meshtastic": OLD, "meshcom": OLD})
    assert restore == ["meshtastic"] and conflicts == ["meshcom"]


def test_an_entry_that_differs_only_in_provenance_is_not_ours():
    """Same artifact digest, different recipe commit. Comparing a few fields would call this
    ours; the whole entry is compared for exactly this reason."""
    twin = dict(MINE, lhpc_commit="7" * 40)
    _restore, _noop, conflicts = reconcile(
        ["meshtastic"], {"meshtastic": MINE}, {"meshtastic": twin}, {"meshtastic": OLD})
    assert conflicts == ["meshtastic"]


# --------------------------------------------------------------------------------- images


def release(names=IMAGE_EVIDENCE, draft=False):
    return {"draft": draft, "assets": [{"name": n} for n in names]}


GOOD_TAG = f"auto-release: rebuild\nlhpc-commit: {CAND}\n"
OK_RUN = {"conclusion": "success"}


def test_a_complete_published_image_for_this_release_has_no_problems():
    assert image_problems("v0.3.7", CAND, OK_RUN, release(), GOOD_TAG) == []


def test_a_draft_is_not_a_published_image():
    problems = image_problems("v0.3.7", CAND, OK_RUN, release(draft=True), GOOD_TAG)
    assert any("draft" in p for p in problems)


def test_a_green_build_with_no_release_is_not_an_image():
    assert image_problems("v0.3.7", CAND, OK_RUN, {}, GOOD_TAG) == ["v0.3.7 has no release"]


def test_a_release_missing_a_variant_or_its_evidence_is_incomplete():
    without_desktop = [n for n in IMAGE_EVIDENCE if n != "loraham-lhpc-desktop.img.xz"]
    assert any("loraham-lhpc-desktop.img.xz" in p
               for p in image_problems("v0.3.7", CAND, OK_RUN, release(without_desktop),
                                       GOOD_TAG))
    without_provenance = [n for n in IMAGE_EVIDENCE if n != "provenance-lite.json"]
    assert any("provenance-lite.json" in p
               for p in image_problems("v0.3.7", CAND, OK_RUN, release(without_provenance),
                                       GOOD_TAG))


def test_a_tag_that_names_another_controller_commit_is_not_this_release():
    other = f"auto-release: rebuild\nlhpc-commit: {'9' * 40}\n"
    assert any("does not name the controller commit" in p
               for p in image_problems("v0.3.7", CAND, OK_RUN, release(), other))


def test_a_timed_out_or_failed_build_is_reported_even_with_a_release_present():
    assert any("bound" in p for p in
               image_problems("v0.3.7", CAND, {"timed_out": True}, release(), GOOD_TAG))
    assert any("failure" in p for p in
               image_problems("v0.3.7", CAND, {"conclusion": "failure"}, release(), GOOD_TAG))


# ------------------------------------------------ which binaries a candidate makes stale


def finding(key, consumers=()):
    from bot.upstream import Finding
    return Finding(key=key, track="tip", status="move", current="a" * 40,
                   candidate="b" * 40, consumers=tuple(consumers))


COVERS = {"daemon": ("loraham-daemon", "radiolib"), "meshtastic": ("meshtastic",),
          "meshcom": ("meshcom-qemu", "meshcom-bridge", "meshcom-firmware")}
# The build inputs each binary stack's covered components record (the completion marker the
# artifact ships), as the manifest declares them today.
RECORDED = {"daemon": (), "meshcom": (),
            "meshtastic": ("meshtastic-web", "meshtastic-cli", "meshtastic-decoder-crypto")}


def test_a_moved_component_pin_rebuilds_the_artifact_that_covers_it():
    from bot.cli import binary_rebuilds
    moved = [finding("src/meshcom-qemu-raspi", ["meshcom-qemu"])]
    assert binary_rebuilds(COVERS, RECORDED, moved) == ["meshcom"]


def test_a_pin_no_artifact_covers_rebuilds_nothing():
    from bot.cli import binary_rebuilds
    assert binary_rebuilds(COVERS, RECORDED, [finding("src/openhop-core", ["meshcore-node"])]) == []


def test_moving_the_web_client_rebuilds_the_meshtastic_artifact():
    """The client ships INSIDE that artifact but is not a component pin, so no `covers` set
    names it. Without this rule the index would keep serving the old client while the manifest
    claimed the new one, and the pins-must-match gate would not notice: it compares component
    commits, and none moved."""
    from bot.cli import binary_rebuilds
    assert binary_rebuilds(COVERS, RECORDED, [finding("extra.meshtastic-web")]) == ["meshtastic"]


def test_moving_the_cli_also_rebuilds_the_meshtastic_artifact():
    """The venv is built on the box, but the VERSION is recorded in the completion marker and
    the artifact ships that marker. Without a republish every binary box reads "not built" and
    the reinstall hands back the same stale marker — a dead end no operator can leave."""
    from bot.cli import binary_rebuilds
    assert binary_rebuilds(COVERS, RECORDED, [finding("extra.meshtastic-cli")]) == ["meshtastic"]


def test_the_republish_follows_the_stack_that_records_the_input():
    """The rule is the manifest's own record, not a stack name: a renamed stack is still the one
    rebuilt, and the obligation cannot vanish with a name."""
    from bot.cli import binary_rebuilds
    covers = {"mesh": ("meshtastic",), "meshcom": ("meshcom-qemu",)}
    recorded = {"mesh": ("meshtastic-web", "meshtastic-cli"), "meshcom": ()}
    assert binary_rebuilds(covers, recorded, [finding("extra.meshtastic-web")]) == ["mesh"]


def test_a_web_client_that_is_its_own_component_republishes_nothing():
    """Once the client is no longer a build input of the meshtastic artifact (its own component,
    fetched or built on its own), moving it leaves every published binary valid."""
    from bot.cli import binary_rebuilds
    recorded = {**RECORDED, "meshtastic": ("meshtastic-cli", "meshtastic-decoder-crypto")}
    assert binary_rebuilds(COVERS, recorded, [finding("extra.meshtastic-web")]) == []
    assert binary_rebuilds(COVERS, recorded, [finding("extra.meshtastic-cli")]) == ["meshtastic"]


MANIFEST_BIN = """
[[stack]]
id = "meshtastic"
  [stack.binary]
  index_url = "https://github.com/makrohard/lhpc-binaries/releases/download/binaries/{meshtastic}"
  covers = ["meshtastic"]
  [[stack.component]]
  id = "meshtastic"
  build_inputs = [
    {{ name = "meshtastic-web", value = "2.7.2", command = "web.sh", token = "{{value}}" }},
    {{ name = "meshtastic-cli", value = "2.7.8", command = "pip", token = "{{value}}" }},
  ]
  [[stack.component]]
  id = "meshtastic-gps"

[[stack]]
id = "daemon"
  [stack.binary]
  index_url = "https://github.com/makrohard/lhpc-binaries/releases/download/binaries/{daemon}"
  covers = ["loraham-daemon"]
  [[stack.component]]
  id = "loraham-daemon"

[[stack]]
id = "chat"
  [[stack.component]]
  id = "loraham-chat"
  build_inputs = [ {{ name = "x", value = "1", command = "c", token = "{{value}}" }} ]
"""


def test_the_recorded_inputs_are_read_from_the_covered_components():
    from bot.manifest import recorded_inputs
    text = MANIFEST_BIN.format(meshtastic="index.json", daemon="index.json")
    assert recorded_inputs(text) == {"meshtastic": ("meshtastic-web", "meshtastic-cli"),
                                     "daemon": ()}


# ------------------------------------------------ which index the candidate publishes into

@pytest.mark.parametrize("name", ["index.json", "index-v3.json"])
def test_the_index_is_the_one_the_candidate_manifest_names(name):
    from bot.manifest import binary_index
    assert binary_index(MANIFEST_BIN.format(meshtastic=name, daemon=name)) == name


@pytest.mark.parametrize("meshtastic, daemon", [
    ("index.json", "index-v3.json"),            # two stacks, two indexes
    ("index.prev.json", "index.prev.json"),     # not an index a publish writes
    ("SHA256SUMS", "SHA256SUMS")])
def test_an_index_the_bot_cannot_name_stops_the_plan(meshtastic, daemon):
    from bot.manifest import Unreadable, binary_index
    with pytest.raises(Unreadable):
        binary_index(MANIFEST_BIN.format(meshtastic=meshtastic, daemon=daemon))


def test_an_index_in_another_repository_stops_the_plan():
    from bot.manifest import Unreadable, binary_index
    text = MANIFEST_BIN.format(meshtastic="index.json", daemon="index.json").replace(
        "makrohard/lhpc-binaries", "someone/else")
    with pytest.raises(Unreadable):
        binary_index(text)


# ------------------------------------------------ the history index (index-v3.json)

def v3entry(sha="a", pin="b", inputs="f", published="2026-10-16T08:00:00Z"):
    return {**entry(sha), "components": {"meshtastic": pin * 40}, "target": "aarch64-trixie",
            "inputs": {"meshtastic": inputs * 64}, "published_at": published}


def core(e):
    """The entry as the build's fragment states it: the publisher adds the other fields."""
    return {k: v for k, v in e.items() if k not in ("inputs", "published_at", "build_run")}


def test_v3_our_build_must_be_the_newest_of_its_stack():
    from bot.cli import published_first
    mine, older = v3entry("6"), v3entry("8", pin="7")
    assert published_first({"meshtastic": [mine, older]}, "meshtastic", core(mine))
    assert not published_first({"meshtastic": [older, mine]}, "meshtastic", core(mine))
    assert not published_first({"meshtastic": []}, "meshtastic", core(mine))
    assert not published_first({}, "meshtastic", core(mine))


def test_v3_an_entry_that_differs_in_provenance_is_not_ours():
    from bot.cli import published_first
    mine = v3entry("6")
    twin = dict(mine, lhpc_commit="7" * 40)
    assert not published_first({"meshtastic": [twin]}, "meshtastic", core(mine))


def test_v3_the_publishers_run_field_is_not_part_of_what_the_fragment_states():
    """The publisher writes `build_run` (lhpc-binaries S1) beside `inputs` and `published_at`. Our
    own entry carrying it is still ours: the build stage must not read it as somebody else's
    publish, and recovery must not call it a conflict."""
    from bot.cli import published_first, reconcile_v3
    mine, old = dict(v3entry("6", pin="2"), build_run="777.1"), v3entry("8")
    assert published_first({"meshtastic": [mine, old]}, "meshtastic", core(mine))
    assert reconcile_v3(["meshtastic"], {"meshtastic": core(mine)}, {"meshtastic": [mine, old]},
                        {"meshtastic": [old]}) == (["meshtastic"], [])


def test_v3_the_build_stage_takes_its_own_entry_with_build_run_as_published(tmp_path, monkeypatch):
    """The same through the public path: a green v3 build whose live entry carries the
    publisher's `build_run` is this attempt's publish, not somebody else's (second read)."""
    import json

    from bot import cli
    from tests.test_autofreeze import BUILD_POLICY, _BuildCtx
    monkeypatch.setenv("BINARY_STACK", "meshtastic")
    monkeypatch.setattr(cli, "MANIFEST", "m.toml")
    monkeypatch.setattr(cli.up, "load_policy", lambda p: BUILD_POLICY)
    monkeypatch.setattr(cli, "git", lambda *a, **k: "")
    ctx = _BuildCtx(tmp_path, b"")
    ctx.att.binary_index = "index-v3.json"
    entry = cli.entry_from_fragment(_frag(), "meshtastic", CAND)
    live = dict(entry, inputs={"meshtastic": "f" * 64}, published_at="2026-11-14T08:00:00Z",
                build_run="777.1")
    ctx.gh.release_asset = lambda repo, tag, name: json.dumps(
        {"schema": 3, "stacks": {"meshtastic": [live]}}).encode()
    ctx.gh.wait = lambda repo, run_id, bound: {"conclusion": "success", "workflow_id": 9,
                                               "run_attempt": 1, "head_sha": "c" * 40,
                                               "html_url": "https://example.invalid/b/777"}
    ctx.gh.artifact_member = lambda repo, run_id, name, suffix, attempt=1: (
        _frag().encode() if suffix == ".frag.json" else b"")
    assert cli.stage_build(ctx) == 0
    assert ctx.att.published["meshtastic"] == entry


def test_v3_recover_leaves_a_new_composition_where_it_is():
    """Nothing to undo: only a controller with exactly these pins and inputs selects it, and no
    released one has them."""
    from bot.cli import reconcile_v3
    mine, old = v3entry("6", pin="2"), v3entry("8")
    noop, conflicts = reconcile_v3(["meshtastic"], {"meshtastic": core(mine)},
                                   {"meshtastic": [mine, old]}, {"meshtastic": [old]})
    assert (noop, conflicts) == (["meshtastic"], [])


def test_v3_recover_stops_when_our_build_replaced_a_published_composition():
    """The one case history cannot absorb: a rebuild of a composition an older controller already
    selects replaced that controller's proven entry, and B1 has no v3 rollback."""
    from bot.cli import reconcile_v3
    old = v3entry("8")
    mine = v3entry("6", published="2026-10-16T09:00:00Z")          # same pins, same inputs
    noop, conflicts = reconcile_v3(["meshtastic"], {"meshtastic": core(mine)},
                                   {"meshtastic": [mine]}, {"meshtastic": [old]})
    assert (noop, conflicts) == ([], ["meshtastic"])


def test_v3_recover_treats_an_unknown_outcome_as_a_conflict():
    from bot.cli import reconcile_v3
    old, foreign = v3entry("8"), v3entry("f", pin="9")
    noop, conflicts = reconcile_v3(["meshtastic"], {}, {"meshtastic": [foreign, old]},
                                   {"meshtastic": [old]})
    assert (noop, conflicts) == ([], ["meshtastic"])


def test_v3_recover_after_no_publish_is_a_verified_no_op():
    from bot.cli import reconcile_v3
    old = v3entry("8")
    assert reconcile_v3(["meshtastic"], {}, {"meshtastic": [old]},
                        {"meshtastic": [old]}) == (["meshtastic"], [])
    mine = v3entry("6", pin="2")                       # recorded, but never reached the index
    assert reconcile_v3(["meshtastic"], {"meshtastic": core(mine)}, {"meshtastic": [old]},
                        {"meshtastic": [old]}) == (["meshtastic"], [])


def test_several_moves_are_folded_into_one_rebuild_set():
    from bot.cli import binary_rebuilds
    moved = [finding("extra.meshtastic-web"), finding("src/meshtastic-firmware", ["meshtastic"]),
             finding("src/MeshCom-Firmware", ["meshcom-firmware"])]
    assert binary_rebuilds(COVERS, RECORDED, moved) == ["meshcom", "meshtastic"]


# ------------------------------------------------- what a build's own fragment must prove

FRAG = {"filename": f"meshtastic-{'a' * 64}.tar.zst", "sha256": "a" * 64,
        "lhpc_commit": CAND, "components": {"meshtastic": "b" * 40}, "stack": "meshtastic"}


def _frag(**over):
    import json as _json
    return _json.dumps({**FRAG, **over})


def test_a_fragment_that_names_this_stack_and_this_candidate_becomes_the_entry():
    from bot.cli import entry_from_fragment
    entry = entry_from_fragment(_frag(), "meshtastic", CAND)
    assert entry["sha256"] == "a" * 64
    assert entry["url"].endswith(FRAG["filename"])
    assert "stack" not in entry, "the entry is compared with the index, which has no stack key"


def _frag_without(key: str) -> str:
    import json as _json
    return _json.dumps({k: v for k, v in FRAG.items() if k != key})


@pytest.mark.parametrize("body,why", [
    (_frag(stack="meshcom"), "names another stack"),
    (_frag_without("stack"), "does not name a stack at all"),
    (_frag(filename="meshtastic-deadbeef.tar.zst"), "is not content-addressed"),
    (_frag(filename=f"meshcom-{'a' * 64}.tar.zst"), "names another stack in its filename"),
    (_frag(sha256="b" * 64), "disagrees with its own filename"),
    (_frag(lhpc_commit="9" * 40), "was built from another candidate"),
])
def test_a_fragment_this_attempt_cannot_claim_is_refused(body, why):
    """It comes out of the build container and later becomes the expectation a rollback is
    judged against, so well-formed JSON is not enough. A missing `stack` key used to pass as
    whichever stack we hoped for."""
    from bot.cli import entry_from_fragment
    assert entry_from_fragment(body, "meshtastic", CAND) is None, why


def test_neither_junk_nor_a_bare_list_is_a_fragment():
    from bot.cli import entry_from_fragment
    assert entry_from_fragment(b"", "meshtastic", CAND) is None
    assert entry_from_fragment("not json", "meshtastic", CAND) is None
    assert entry_from_fragment("[1, 2]", "meshtastic", CAND) is None


# ------------------------------------------------- a dispatch whose run id was never written

def test_a_dispatch_with_no_recorded_run_is_named():
    """Recovery cancels and waits BY RUN ID, so for these it would cancel nothing and wait for
    nothing, then read an index a publisher may still be writing."""
    from bot.attempt import Attempt
    from bot.cli import unrecorded_dispatches
    att = Attempt(run_id="1", state="mutated", dispatched=["meshtastic", "meshcom"],
                  runs={"binary:meshcom": {"repo": "o/r", "id": 5}})
    assert unrecorded_dispatches(att) == ["meshtastic"]
    att.runs["binary:meshtastic"] = {"repo": "o/r", "id": 6}
    assert unrecorded_dispatches(att) == []


# ------------------------------------------------- an image that is already published

def test_a_complete_release_needs_no_rebuild_even_with_no_run_to_judge():
    """The repair path asks this BEFORE dispatching: a wait that timed out while the build
    actually succeeded would otherwise rebuild both variants from scratch."""
    assert image_problems("v0.3.7", CAND, {}, release(), GOOD_TAG) == []
    assert any("draft" in p for p in
               image_problems("v0.3.7", CAND, {}, release(draft=True), GOOD_TAG))
    assert any("does not name the controller commit" in p for p in
               image_problems("v0.3.7", CAND, {}, release(), "auto-release: x\n"))


def test_the_required_evidence_is_what_the_publisher_actually_writes():
    """Exact by intent. The other cases here BUILD their fixtures from `IMAGE_EVIDENCE`, so they
    are blind to its contents: drop a name from the constant and they all still pass. This is the
    only case that notices, and the names are transcribed from the image publisher's `assemble`
    step rather than from the constant."""
    assert set(IMAGE_EVIDENCE) == {
        "loraham-lhpc-lite.img.xz", "loraham-lhpc-desktop.img.xz",
        "loraham-lhpc-lite.img.xz.sha256", "loraham-lhpc-desktop.img.xz.sha256",
        "provenance-lite.json", "provenance-desktop.json",
        "components-lite.txt", "components-desktop.txt",
        "packages-lite.txt", "packages-desktop.txt",
        "SHA256SUMS", "signature.txt", "AUTO-RELEASE"}


# ------------------------------------- the snapshot kept as keys (the record must stay small)

def test_a_key_stands_for_the_whole_entry_and_its_composition():
    from bot.cli import entry_key
    e = v3entry("6")
    assert entry_key(e) == entry_key(entry_key(e))           # a stored key reads as itself
    assert entry_key(e)[:2] == [e["filename"], e["sha256"]]
    twin = dict(e, lhpc_commit="7" * 40)                     # same file and digest, other provenance
    assert entry_key(twin)[2] != entry_key(e)[2] and entry_key(twin)[3] == entry_key(e)[3]
    rebuilt = v3entry("6", inputs="9")                       # other inputs: another composition
    assert entry_key(rebuilt)[3] != entry_key(e)[3]


@pytest.mark.parametrize("ours,live,before,want", [
    ({"meshtastic": core(v3entry("6", pin="2"))}, [v3entry("6", pin="2"), v3entry("8")],
     [v3entry("8")], (["meshtastic"], [])),
    ({"meshtastic": core(v3entry("6", published="2026-10-16T09:00:00Z"))},
     [v3entry("6", published="2026-10-16T09:00:00Z")], [v3entry("8")], ([], ["meshtastic"])),
    ({}, [v3entry("f", pin="9"), v3entry("8")], [v3entry("8")], ([], ["meshtastic"])),
    ({}, [v3entry("8")], [v3entry("8")], (["meshtastic"], [])),
    ({}, [dict(v3entry("8"), lhpc_commit="7" * 40)], [v3entry("8")], ([], ["meshtastic"]))],
    ids=["new-composition", "replaced-composition", "unknown-outcome", "nothing-published",
         "entry-changed-in-place"])
def test_v3_a_snapshot_of_keys_gives_the_verdicts_of_a_snapshot_of_entries(ours, live, before,
                                                                           want):
    """Records written before keys hold whole entries and must still read; new ones hold keys.
    Both give the same verdict for every case recovery tells apart."""
    from bot.cli import entry_key, reconcile_v3
    full = reconcile_v3(["meshtastic"], ours, {"meshtastic": live}, {"meshtastic": before})
    keys = reconcile_v3(["meshtastic"], ours, {"meshtastic": live},
                        {"meshtastic": [entry_key(e) for e in before]})
    assert full == keys == want


# ------------------------------------------------ recovery: an unproven attempt's OWN v3 entries
# Plan part 2, P2 + P5: an entry is the attempt's own only when its `build_run` is the recorded
# build run's id AND attempt and it agrees with the fragment. An unproven attempt withdraws its
# own entries (rollback-binary withdraw-v3), reads them back gone, and then reconciles with ONLY
# those own entries, so a same-file entry of another publisher is a conflict, never ours.

CAND = "c" * 40
BUILD = {"id": 777, "workflow": 9, "attempt": 1, "sha": "d" * 40}


class _RecoverCtx:
    """`stage_recover` on an index-v3 attempt that published meshtastic. The release (tags,
    main) does not exist yet; every recorded run is finished. `ci` is the CI run's conclusion;
    `withdraw` is what the rollback run does: apply / fail / succeed-without-removing."""

    attempt_id = run_id = "100"
    retry_of = retry_incident = ""
    run_url = "https://example.invalid/run/100"

    def __init__(self, *, fragment, live, snapshot, ci="failure", withdraw="apply", runs=None):
        from bot import cli
        from bot.attempt import Attempt
        self.cli, self.gh, self.bot_gh = cli, self, self
        self.index = {"schema": 3, "stacks": {"meshtastic": list(live)}}
        self.ci, self.withdraw = ci, withdraw
        self.dispatches, self.saved, self.summaries, self.closed = [], [], [], []
        self.att = Attempt(
            run_id="100", state="mutated", version="0.3.16", base_sha="b" * 40,
            candidate_sha=CAND, binary_index="index-v3.json", dispatched=["meshtastic"],
            published={"meshtastic": fragment} if fragment else {},
            index_snapshot={"schema": 3, "stacks": {"meshtastic": [cli.entry_key(e)
                                                                    for e in snapshot]}},
            runs={"ci": {"repo": cli.LHPC, "id": 5, "workflow": 42, "attempt": 1, "sha": CAND},
                  "testlab": {"repo": cli.LHPC, "id": 6, "workflow": 42, "attempt": 1,
                              "sha": CAND},
                  "binary:meshtastic": dict(BUILD, repo=cli.BIN), **(runs or {})})

    # --- Ctx
    def find_attempt(self, wanted=""):
        return 7, self.att

    def save_attempt(self, number, att):
        self.saved.append(att.state)

    def summary(self, text):
        self.summaries.append(text)

    def record_run(self, repo, run_id):
        return {"repo": repo, "id": int(run_id), "workflow": 11, "attempt": 1, "sha": "e" * 40}

    # --- Gh
    def ref(self, repo, ref):
        return "b" * 40 if ref == "heads/main" else ""

    def is_ancestor(self, repo, a, b):
        return False

    def unfinished_runs(self, repo, workflow=""):
        return []

    def cancel(self, repo, run_id):
        pass

    def wait(self, repo, run_id, bound, poll_s=30.0, rerun=True, external=None):
        assert rerun is False, "recovery judges and settles runs; it never re-runs a job"
        conclusion = {5: self.ci, 900: "failure" if self.withdraw == "fail" else "success"}.get(
            int(run_id), "success")
        return {"status": "completed", "conclusion": conclusion, "head_sha": CAND,
                "workflow_id": 42, "run_attempt": 1, "html_url": f"https://example.invalid/{run_id}"}

    def jobs(self, repo, run_id, attempt=1):
        names = self.cli.REQUIRED_CI if int(run_id) == 5 else self.cli.REQUIRED_TESTLAB
        state = self.ci if int(run_id) == 5 else "success"
        return [{"name": n, "conclusion": state, "head_sha": CAND} for n in names]

    def failing_jobs(self, repo, run_id, attempt, lines=20):
        return []

    def artifact_member(self, repo, run_id, name, member, attempt=1):
        return b'<testsuite><testcase name="test_release_kiss"></testcase></testsuite>'

    def file_at(self, repo, path, sha):
        import json
        return json.dumps({"required_cases": ["test_release_kiss"]})

    def release_asset(self, repo, tag, name):
        import json
        assert name == "index-v3.json"
        return json.dumps(self.index).encode()

    def dispatch(self, repo, workflow, ref, inputs=None):
        import json
        self.dispatches.append((workflow, dict(inputs or {})))
        assert workflow == "rollback.yml" and inputs["mode"] == "withdraw-v3"
        if self.withdraw == "apply":
            keys = json.loads(inputs["keys_json"])
            for stack, gone in keys.items():
                self.index["stacks"][stack] = [e for e in self.index["stacks"][stack]
                                               if self.cli.entry_key(e) not in gone]
        return 900

    def update_issue(self, repo, number, **fields):
        self.closed.append(fields.get("state"))
        return {}


def _own(sha="6", run="777.1", **over):
    """This attempt's meshtastic build as the index holds it after S1: a new composition."""
    e = dict(v3entry(sha, pin="2", inputs="3"), **over)
    if run is not None:
        e["build_run"] = run
    return e


def _recover(ctx):
    from bot import cli
    return cli.stage_recover(ctx, "100")


def test_an_unproven_attempt_withdraws_its_own_entry_and_closes():
    """CI red, the lane green: not proven (the prove stage's own verdict). The own entry goes,
    the index reads back as the snapshot, and the attempt is restored and closed."""
    old, mine = v3entry("8"), _own()
    ctx = _RecoverCtx(fragment=core(mine), live=[mine, old], snapshot=[old])
    assert _recover(ctx) == 0
    import json

    from bot.cli import entry_key
    (workflow, inputs), = ctx.dispatches
    assert inputs["stacks"] == "meshtastic"
    assert json.loads(inputs["keys_json"]) == {"meshtastic": [entry_key(mine)]}
    assert ctx.index["stacks"]["meshtastic"] == [old]
    assert ctx.att.runs["rollback"]["id"] == 900 and ctx.att.state == "restored"
    assert ctx.closed == ["closed"]


def test_a_proven_attempt_keeps_its_binary():
    """His Q1 is about UNPROVEN binaries only: a proven attempt in recovery withdraws nothing."""
    old, mine = v3entry("8"), _own()
    ctx = _RecoverCtx(fragment=core(mine), live=[mine, old], snapshot=[old], ci="success")
    assert _recover(ctx) == 0
    assert ctx.dispatches == [] and ctx.index["stacks"]["meshtastic"] == [mine, old]


@pytest.mark.parametrize("run", [
    "888.1",        # another publisher's run with the identical file, sha256, inputs, published_at
    "777.2",        # the same run id, another attempt: a re-run this bot did not ask for
])
def test_the_same_build_published_by_another_run_is_never_ours(run):
    """No own entry, so nothing is withdrawn; the history changed, so the attempt stays open."""
    old, theirs = v3entry("8"), _own(run=run)
    ctx = _RecoverCtx(fragment=core(theirs), live=[theirs, old], snapshot=[old])
    from bot import cli
    with pytest.raises(cli.Stop, match="cannot claim"):
        _recover(ctx)
    assert ctx.dispatches == [] and ctx.index["stacks"]["meshtastic"] == [theirs, old]
    assert ctx.att.state == "mutated" and ctx.closed == []


def test_an_unproven_rebuild_that_replaced_a_proven_entry_is_withdrawn_and_names_the_lost_one():
    """E1 (ours, unproven) replaced E0 (same composition) in the history. E1 goes; E0 cannot come
    back (there is no v3 restore), so the attempt stays open and the Stop names E0 by its
    snapshot key."""
    e0 = v3entry("8", pin="2", inputs="3")
    e1 = _own(published="2026-10-16T09:00:00Z")
    ctx = _RecoverCtx(fragment=core(e1), live=[e1], snapshot=[e0])
    from bot import cli
    with pytest.raises(cli.Stop) as stop:
        _recover(ctx)
    assert ctx.index["stacks"]["meshtastic"] == []
    assert f"{e0['filename']} (sha256 {e0['sha256']})" in stop.value.observed
    assert e1["filename"] not in stop.value.observed
    assert ctx.att.state == "mutated"


def test_a_snapshot_entry_replaced_by_the_same_file_of_another_run_is_named():
    """E0 was replaced in its composition by the SAME file published by another run (its
    `build_run`, so its key, differs). The file is still live, but E0 is not; the Stop names it."""
    from bot import cli
    e0, e1 = _own(run="555.1"), _own(run="888.1")
    ctx = _RecoverCtx(fragment=core(e1), live=[e1], snapshot=[e0], ci="success")
    with pytest.raises(cli.Stop) as stop:
        _recover(ctx)
    assert f"{e0['filename']} (sha256 {e0['sha256']}) is no longer in the index" \
        in stop.value.observed
    assert ctx.dispatches == []


def test_a_recovery_after_an_interrupted_withdrawal_waits_for_it_and_does_not_withdraw_again():
    """The last recover stopped while its withdraw run was going; the run finished and removed
    the entry. This one settles that run first, then finds nothing of ours left."""
    from bot import cli
    old = v3entry("8")
    mine = _own()
    ctx = _RecoverCtx(fragment=core(mine), live=[old], snapshot=[old],
                      runs={"rollback": {"repo": cli.BIN, "id": 900, "workflow": 11,
                                         "attempt": 1}})
    waited = []
    wait = ctx.wait
    ctx.wait = lambda repo, run_id, bound, **kw: waited.append(int(run_id)) or wait(
        repo, run_id, bound, **kw)
    assert _recover(ctx) == 0
    assert 900 in waited and ctx.dispatches == [] and ctx.att.state == "restored"


@pytest.mark.parametrize("withdraw, said", [
    ("fail", "could not be withdrawn"),
    ("noop", "still holds this attempt's entry"),
])
def test_a_withdrawal_that_is_not_confirmed_keeps_the_attempt_open(withdraw, said):
    from bot import cli
    old, mine = v3entry("8"), _own()
    ctx = _RecoverCtx(fragment=core(mine), live=[mine, old], snapshot=[old], withdraw=withdraw)
    with pytest.raises(cli.Stop, match=said):
        _recover(ctx)
    assert len(ctx.dispatches) == 1 and ctx.att.state == "mutated" and ctx.closed == []


def test_an_own_entry_from_before_build_run_stops_without_a_withdrawal():
    """Published before the publisher wrote `build_run`: ours or another run's, nobody can tell."""
    from bot import cli
    old, legacy = v3entry("8"), _own(run=None)
    ctx = _RecoverCtx(fragment=core(legacy), live=[legacy, old], snapshot=[old])
    with pytest.raises(cli.Stop, match="without the run that published it"):
        _recover(ctx)
    assert ctx.dispatches == [] and ctx.att.state == "mutated"
