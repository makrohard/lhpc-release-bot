"""The version scalars and the changelog — the three files LHPC pins to each other.

`dev` starts every cycle by bumping the version, so a patch released from `main` ALWAYS collides
with `dev` on exactly these three. That collision is the one this bot resolves; every other
conflict is a judgement call and goes to a pull request.
"""
from __future__ import annotations

import pytest

from bot.changelog import (
    insert_section,
    merge_back,
    next_patch,
    pin_bullets,
    section_of,
    set_pyproject_version,
    set_version_module,
)
from bot.upstream import Finding

CHANGELOG = """# Changelog

## 0.3.5

- something released

## 0.3.4

- older
"""


def test_next_patch():
    assert next_patch("0.3.5") == "0.3.6"
    assert next_patch("1.0.0") == "1.0.1"
    for bad in ("0.3", "v0.3.5", "0.3.5-rc1", ""):
        with pytest.raises(ValueError):
            next_patch(bad)


def test_a_section_goes_above_the_previous_release_not_at_the_end():
    out = insert_section(CHANGELOG, "0.3.6", ["moved a pin"])
    assert out.index("## 0.3.6") < out.index("## 0.3.5")
    assert out.startswith("# Changelog")
    assert "- moved a pin" in out


def test_a_duplicate_section_is_refused():
    with pytest.raises(ValueError, match="already has a section"):
        insert_section(CHANGELOG, "0.3.5", ["x"])


def test_section_of_reads_back_exactly_that_release():
    out = insert_section(CHANGELOG, "0.3.6", ["one", "two"])
    assert section_of(out, "0.3.6") == "- one\n- two"
    assert section_of(out, "0.3.5") == "- something released"
    assert section_of(out, "9.9.9") == ""


def test_version_scalars_move_or_raise():
    assert 'version = "0.3.6"' in set_pyproject_version('version = "0.3.5"\n', "0.3.6")
    assert '__version__ = "0.3.6"' in set_version_module('__version__ = "0.3.5"\n', "0.3.6")
    with pytest.raises(ValueError):
        set_pyproject_version("nothing here\n", "0.3.6")
    with pytest.raises(ValueError):
        set_version_module("nothing here\n", "0.3.6")


DEV = """# Changelog

## 0.4.0

- the next feature, still unreleased

## 0.3.5

- something released
"""


def test_merge_back_keeps_devs_unreleased_section_first():
    out = merge_back(DEV, "- moved a pin", "0.3.6")
    assert out.index("## 0.4.0") < out.index("## 0.3.6") < out.index("## 0.3.5")
    assert "- the next feature, still unreleased" in out
    assert "- moved a pin" in out


def test_merge_back_is_idempotent():
    once = merge_back(DEV, "- moved a pin", "0.3.6")
    assert merge_back(once, "- moved a pin", "0.3.6") == once


def test_bullets_name_the_component_the_range_and_the_consumers():
    f = Finding(key="src/reticulum", track="tag", status="move", current="a" * 40,
                candidate="b" * 40, tag="1.5.3", consumers=("rns", "nomadnet"))
    at_pin = Finding(key="src/other", track="tip", status="at-pin")
    out = pin_bullets([f, at_pin])
    assert out == ["reticulum: aaaaaaaaa -> bbbbbbbbb (1.5.3), used by rns, nomadnet"]


# --------------------------------------------------- R7-3: dev that has NOT opened a new cycle

# The ordinary case, and the one every earlier fixture missed: `dev` has not moved since the last
# release, so its first section is the OLD released one rather than a newer unreleased cycle.
DEV_NOT_MOVED = """# Changelog

## 0.3.14

- openhop-repeater: 47e49e64a -> 4705c99c3

## 0.3.13

- something older
"""


def test_a_patch_lands_above_a_stale_dev_section_not_below_it():
    """R7-3, the live defect. `dev` at 0.3.14, releasing 0.3.15.

    Inserting after the first heading assumed that heading was newer. Here it is older, so the
    file came out `0.3.14, 0.3.15, 0.3.13` — which is what the bot actually opened as PR #4.
    """
    out = merge_back(DEV_NOT_MOVED, "- kiss + bridge", "0.3.15")
    order = [line[3:].strip() for line in out.splitlines() if line.startswith("## ")]
    assert order == ["0.3.15", "0.3.14", "0.3.13"], f"out of order: {order}"
    assert "- openhop-repeater: 47e49e64a -> 4705c99c3" in out, "dev's own section survives"
    assert "- kiss + bridge" in out


def test_a_genuinely_newer_dev_cycle_still_keeps_its_place():
    """The other half: when `dev` really has opened 0.4.0, the patch belongs beneath it. Version
    order says so without the helper needing to know which situation it is in."""
    out = merge_back(DEV, "- moved a pin", "0.3.6")
    order = [line[3:].strip() for line in out.splitlines() if line.startswith("## ")]
    assert order == ["0.4.0", "0.3.6", "0.3.5"], f"out of order: {order}"


def test_a_patch_older_than_everything_goes_last():
    out = merge_back(DEV_NOT_MOVED, "- an old one", "0.3.12")
    order = [line[3:].strip() for line in out.splitlines() if line.startswith("## ")]
    assert order == ["0.3.14", "0.3.13", "0.3.12"], f"out of order: {order}"


def test_merge_back_stays_idempotent_on_the_stale_dev_case():
    once = merge_back(DEV_NOT_MOVED, "- kiss + bridge", "0.3.15")
    assert merge_back(once, "- kiss + bridge", "0.3.15") == once


def test_the_result_always_ends_with_a_newline():
    """The caller reads `dev` through a helper that strips trailing whitespace, so the text
    arriving here has usually already lost its final newline. Preserving that faithfully put
    `\\ No newline at end of file` in every merge-back pull request and left a spurious one-line
    diff for whatever touched the file next. Found by a reviewer reading the live PR."""
    for stripped in (DEV_NOT_MOVED.rstrip(), DEV.rstrip()):
        for version in ("0.3.15", "0.3.6", "0.0.1"):
            out = merge_back(stripped, "- a bullet", version)
            assert out.endswith("\n"), f"{version} on {stripped[:20]!r} lost the final newline"
            assert not out.endswith("\n\n\n"), "and must not gain blank lines instead"


def test_idempotence_survives_a_heading_with_trailing_whitespace():
    """The guard and the insertion must read the file the same way. The guard was a substring
    search for `## <version>\\n` while `HEADING` tolerates trailing spaces, so a heading written
    `## 0.3.15 ` — which the insertion happily counts as 0.3.15 — slipped past it and the section
    was added a second time. Deciding both from the same parse removes the disagreement."""
    once = merge_back(DEV_NOT_MOVED, "- kiss + bridge", "0.3.15")
    padded = once.replace("## 0.3.15\n", "## 0.3.15 \n", 1)
    again = merge_back(padded, "- kiss + bridge", "0.3.15")
    assert again == padded
    assert again.count("kiss + bridge") == 1, "the section must not be inserted a second time"


def test_the_idempotent_path_still_ends_with_a_newline():
    """The trailing-newline guard has to cover the path where NOTHING is inserted too. An early
    return there hands back the caller's text unchanged — and the caller reads `dev` through a
    helper that strips trailing whitespace, so it is exactly the text that has already lost its
    newline. That path writes `CHANGELOG.md` on a pull request this bot opens, where a missing
    final newline is `\\ No newline at end of file` and a `ruff` W292 failure."""
    once = merge_back(DEV_NOT_MOVED, "- kiss + bridge", "0.3.15")
    assert merge_back(once.rstrip(), "- kiss + bridge", "0.3.15").endswith("\n"), \
        "the no-op path must normalise the newline like every other path"


def test_a_v_prefixed_cycle_is_still_a_version():
    """PEP 440 permits a leading `v`, and one character was the whole difference between the case
    the pre-release fix handles and the downgrade it exists to prevent: `v0.4.0` failing to parse
    sends the caller down the "nothing can be inferred" path, which advances and overwrites the
    cycle somebody opened."""
    from bot.changelog import version_order
    assert version_order("v0.4.0") == (0, 4, 0) == version_order("0.4.0")
    assert version_order("V0.4.0") == (0, 4, 0), "PEP 440 is case-insensitive about the prefix"
    assert version_order("v0.4.0rc1") == (0, 4, 0)
    assert version_order("v0.4.0") > version_order("0.3.16")
    # The strings the optional prefix makes newly interesting: it must not turn a bare `v`, or a
    # word beginning with one, into a version.
    for junk in ("unreleased", "", "rc1", "main", "v", "V", "version 0.4.0", "v 0.4.0"):
        try:
            version_order(junk)
        except ValueError:
            continue
        raise AssertionError(f"{junk!r} has no version at its start and must not parse as one")
