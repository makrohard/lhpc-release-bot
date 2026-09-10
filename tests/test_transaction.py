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


def test_a_moved_component_pin_rebuilds_the_artifact_that_covers_it():
    from bot.cli import binary_rebuilds
    assert binary_rebuilds(COVERS, [finding("src/meshcom-qemu-raspi", ["meshcom-qemu"])]) \
        == ["meshcom"]


def test_a_pin_no_artifact_covers_rebuilds_nothing():
    from bot.cli import binary_rebuilds
    assert binary_rebuilds(COVERS, [finding("src/openhop-core", ["meshcore-node"])]) == []


def test_moving_the_web_client_rebuilds_the_meshtastic_artifact():
    """The client ships INSIDE that artifact but is not a component pin, so no `covers` set
    names it. Without this rule the index would keep serving the old client while the manifest
    claimed the new one, and the pins-must-match gate would not notice: it compares component
    commits, and none moved."""
    from bot.cli import binary_rebuilds
    assert binary_rebuilds(COVERS, [finding("extra.meshtastic-web")]) == ["meshtastic"]


def test_moving_the_cli_also_rebuilds_the_meshtastic_artifact():
    """The venv is built on the box, but the VERSION is recorded in the completion marker and
    the artifact ships that marker. Without a republish every binary box reads "not built" and
    the reinstall hands back the same stale marker — a dead end no operator can leave."""
    from bot.cli import binary_rebuilds
    assert binary_rebuilds(COVERS, [finding("extra.meshtastic-cli")]) == ["meshtastic"]


def test_a_renamed_meshtastic_stack_stops_the_run_instead_of_silently_not_rebuilding():
    """The rule names a stack. If that name stops existing, failing here is the only way the
    republish obligation does not vanish quietly."""
    import pytest

    from bot.cli import Stop, binary_rebuilds
    with pytest.raises(Stop):
        binary_rebuilds({"meshcom": ("meshcom-qemu",)}, [finding("extra.meshtastic-web")])


def test_several_moves_are_folded_into_one_rebuild_set():
    from bot.cli import binary_rebuilds
    moved = [finding("extra.meshtastic-web"), finding("src/meshtastic-firmware", ["meshtastic"]),
             finding("src/MeshCom-Firmware", ["meshcom-firmware"])]
    assert binary_rebuilds(COVERS, moved) == ["meshcom", "meshtastic"]


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
