"""Moving a pin in LHPC's manifest, and moving the Graywolf version.

The manifest is a hand-maintained document: its comments carry the reasons for its pins, and one
source is often pinned by several components that must stay identical. So the edit is checked
for what it must do (move every consumer) and for what it must NOT do (touch anything else).
"""
from __future__ import annotations

import pytest

from bot.manifest import (
    add_graywolf_checksums,
    binary_stacks,
    graywolf_checksums,
    graywolf_version,
    pinned_sources,
    set_graywolf_version,
    set_pin,
)

OLD, NEW = "a" * 40, "b" * 40

MANIFEST = f'''# a comment that must survive
[[stack]]
id = "one"

  [stack.binary]
  covers = ["alpha"]

  [[stack.component]]
  id = "alpha"
    # why this pin is what it is
    [stack.component.source]
    path = "src/shared"
    pin_commit = "{OLD}"
    pin_tag = "old-tag"
    remote = "https://github.com/o/shared.git"
    branch = "main"

  [[stack.component]]
  id = "beta"
    [stack.component.source]
    path = "src/shared"
    pin_commit = "{OLD}"
    pin_tag = "old-tag"
    remote = "https://github.com/o/shared.git"
    branch = "main"

[[stack]]
id = "two"

  [[stack.component]]
  id = "gamma"
  build_steps = [
    {{ argv = ["bash", "scripts/graywolf-fetch.sh", "dest", "0.14.13"], announce = "graywolf 0.14.13" }},
  ]
  build_marker = "build/tools/graywolf/.lhpc-built-0.14.13"
    [stack.component.source]
    path = "src/other"
    pin_commit = "{"c" * 40}"
    pin_tag = "other"
    remote = "https://github.com/o/other.git"
    branch = "dev"
'''


def test_every_consumer_of_a_shared_source_moves_together():
    out = set_pin(MANIFEST, "src/shared", NEW, "new-tag")
    shared = next(s for s in pinned_sources(out) if s.path == "src/shared")
    assert shared.pin == NEW and shared.tag == "new-tag"
    assert set(shared.consumers) == {"alpha", "beta"}
    assert out.count(NEW) == 2


def test_nothing_else_is_touched():
    out = set_pin(MANIFEST, "src/shared", NEW, "new-tag")
    other = next(s for s in pinned_sources(out) if s.path == "src/other")
    assert other.pin == "c" * 40 and other.branch == "dev"
    assert "# a comment that must survive" in out
    assert "# why this pin is what it is" in out
    changed = [(a, b) for a, b in zip(MANIFEST.splitlines(), out.splitlines(), strict=True) if a != b]
    assert len(changed) == 4          # two pin_commit + two pin_tag lines, nothing more


def test_a_short_or_symbolic_pin_is_refused():
    for bad in ("HEAD", "abc123", "", "B" * 40):
        with pytest.raises(ValueError):
            set_pin(MANIFEST, "src/shared", bad, "t")


def test_an_unknown_path_is_refused_rather_than_silently_doing_nothing():
    with pytest.raises(ValueError, match="no pin_commit"):
        set_pin(MANIFEST, "src/nope", NEW, "t")


def test_consumers_that_disagree_are_a_manifest_defect():
    broken = MANIFEST.replace(f'pin_commit = "{OLD}"\n    pin_tag = "old-tag"\n'
                              '    remote = "https://github.com/o/shared.git"\n'
                              '    branch = "main"\n\n  [[stack.component]]\n  id = "beta"',
                              f'pin_commit = "{OLD}"\n    pin_tag = "old-tag"\n'
                              '    remote = "https://github.com/o/shared.git"\n'
                              '    branch = "main"\n\n  [[stack.component]]\n  id = "beta"')
    split = broken.replace(f'pin_commit = "{OLD}"', f'pin_commit = "{"e" * 40}"', 1)
    with pytest.raises(ValueError, match="disagree"):
        pinned_sources(split)


def test_binary_stacks_are_read_from_their_own_declaration():
    assert binary_stacks(MANIFEST) == {"one": ("alpha",)}


def test_graywolf_moves_in_the_step_and_in_the_marker():
    assert graywolf_version(MANIFEST) == "0.14.13"
    out = set_graywolf_version(MANIFEST, "0.14.13", "0.15.0")
    assert graywolf_version(out) == "0.15.0"
    assert ".lhpc-built-0.15.0" in out and "0.14.13" not in out


def test_a_graywolf_bump_that_would_move_only_one_place_is_refused():
    """The marker carries the version so a bump reads as 'not built' on a deployed box. A bump
    that moved the fetch step alone would leave every box running the old binary while
    reporting built."""
    only_step = MANIFEST.replace('build_marker = "build/tools/graywolf/.lhpc-built-0.14.13"',
                                 'build_marker = "build/tools/graywolf/.lhpc-built"')
    with pytest.raises(ValueError, match="build marker"):
        set_graywolf_version(only_step, "0.14.13", "0.15.0")


SCRIPT = '''sums() {
    case "$1" in
        0.14.13/arm64) echo "''' + "1" * 64 + '''" ;;
        0.14.13/armhf) echo "''' + "2" * 64 + '''" ;;
        0.14.13/amd64) echo "''' + "3" * 64 + '''" ;;
        0.14.12/arm64) echo "''' + "4" * 64 + '''" ;;
        *) return 1 ;;
    esac
}
'''


def test_new_checksums_are_added_and_old_ones_kept():
    """Old rows are what let a box verify a version it already has — a bump adds, never
    replaces."""
    sums = {"arm64": "a" * 64, "armhf": "b" * 64, "amd64": "c" * 64}
    out = add_graywolf_checksums(SCRIPT, "0.15.0", sums)
    have = graywolf_checksums(out)
    assert have["0.15.0/arm64"] == "a" * 64
    assert have["0.14.13/arm64"] == "1" * 64      # kept
    assert have["0.14.12/arm64"] == "4" * 64      # kept
    assert len(have) == 7


def test_an_incomplete_or_malformed_checksum_set_is_refused():
    with pytest.raises(ValueError, match="no checksum for"):
        add_graywolf_checksums(SCRIPT, "0.15.0", {"arm64": "a" * 64})
    with pytest.raises(ValueError, match="not a sha256"):
        add_graywolf_checksums(SCRIPT, "0.15.0",
                               {"arm64": "nope", "armhf": "b" * 64, "amd64": "c" * 64})


def test_a_digest_that_contradicts_a_recorded_one_is_refused():
    with pytest.raises(ValueError, match="different digest"):
        add_graywolf_checksums(SCRIPT, "0.14.13",
                               {"arm64": "9" * 64, "armhf": "2" * 64, "amd64": "3" * 64})


# ------------------------------------------------- the two pins that are not git sources

MESHTASTIC = '''  build_steps = [
    { argv = ["bash", "{asset}/scripts/meshtastic-web-assets.sh", "{runtime}/build/tools/meshtasticd/web", "2.7.2", "''' + "6" * 64 + '''"], announce = "[fetch] Meshtastic web client v2.7.2 (LHPC pin, sha256-verified) into {runtime}/build/tools/meshtasticd/web" },
    { argv = [".venv/bin/pip", "install", "meshtastic==2.7.11"], announce = "[install] Meshtastic CLI 2.7.11 into the venv" },
  ]
  build_marker = ".lhpc-build-complete"
  build_inputs = [
    { name = "meshtastic-web", value = "2.7.2", command = "meshtastic-web-assets.sh", token = "{value}" },
    { name = "meshtastic-cli", value = "2.7.11", command = "pip", token = "meshtastic=={value}" },
  ]
'''


def test_the_web_pin_is_read_as_its_version_and_its_digest():
    from bot.manifest import meshtastic_cli, meshtastic_web
    assert meshtastic_web(MESHTASTIC) == ("2.7.2", "6" * 64)
    assert meshtastic_cli(MESHTASTIC) == "2.7.11"


def test_moving_the_web_pin_moves_the_version_the_digest_and_the_announcement():
    """The version is stated twice on that line. A bump that moved only the argv would leave the
    log an operator reads announcing a version that is not being installed."""
    from bot.manifest import meshtastic_web, set_meshtastic_web
    out = set_meshtastic_web(MESHTASTIC, "2.7.2", "2.8.0", "a" * 64)
    assert meshtastic_web(out) == ("2.8.0", "a" * 64)
    assert "web client v2.8.0" in out and "2.7.2" not in out


def test_a_web_bump_without_a_real_digest_is_refused():
    """A version moved without its digest fails every install; a digest that is not one is not a
    digest."""
    from bot.manifest import set_meshtastic_web
    for bad in ("", "not-a-digest", "a" * 63):
        with pytest.raises(ValueError, match="sha256"):
            set_meshtastic_web(MESHTASTIC, "2.7.2", "2.8.0", bad)


def test_a_web_bump_whose_announcement_does_not_match_is_refused():
    from bot.manifest import set_meshtastic_web
    with pytest.raises(ValueError, match="announcement"):
        set_meshtastic_web(MESHTASTIC.replace("web client v2.7.2", "web client v9.9.9"),
                           "2.7.2", "2.8.0", "a" * 64)


def test_moving_the_cli_pin_moves_the_pip_step_and_the_announcement():
    from bot.manifest import meshtastic_cli, set_meshtastic_cli
    out = set_meshtastic_cli(MESHTASTIC, "2.7.11", "2.8.0")
    assert meshtastic_cli(out) == "2.8.0"
    assert "Meshtastic CLI 2.8.0" in out and "2.7.11" not in out


def test_a_cli_bump_that_names_the_wrong_current_version_is_refused():
    from bot.manifest import set_meshtastic_cli
    with pytest.raises(ValueError, match="no pip step"):
        set_meshtastic_cli(MESHTASTIC, "9.9.9", "2.8.0")


def test_moving_a_pin_moves_the_value_lhpc_records_with_it():
    """The version lives twice in the manifest: in the build step, and in the `build_inputs`
    entry LHPC writes into the completion marker. LHPC refuses to load a manifest where the two
    disagree, so a move that touched only one would produce a candidate that cannot even load.
    """
    from bot.manifest import set_meshtastic_cli, set_meshtastic_web
    out = set_meshtastic_web(MESHTASTIC, "2.7.2", "2.8.0", "a" * 64)
    assert '{ name = "meshtastic-web", value = "2.8.0"' in out
    out = set_meshtastic_cli(out, "2.7.11", "2.8.1")
    assert '{ name = "meshtastic-cli", value = "2.8.1"' in out


def test_a_web_version_the_fetch_script_would_refuse_is_rejected_before_publishing():
    """`meshtastic-web-assets.sh` demands MAJOR.MINOR.PATCH. Catching it here costs one run;
    catching it at prove costs a publishing cycle."""
    import pytest

    from bot.manifest import set_meshtastic_web
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        set_meshtastic_web(MESHTASTIC, "2.7.2", "2.8", "a" * 64)


def test_a_recorded_input_that_drifted_from_its_pin_stops_the_move():
    """If the two copies already disagree, the bot is not looking at what it thinks it is."""
    import pytest

    from bot.manifest import set_meshtastic_cli
    drifted = MESHTASTIC.replace('name = "meshtastic-cli", value = "2.7.11"',
                                 'name = "meshtastic-cli", value = "2.6.0"')
    with pytest.raises(ValueError, match="drifted apart"):
        set_meshtastic_cli(drifted, "2.7.11", "2.8.0")


def test_an_unreadable_pin_is_a_fault_not_an_empty_string():
    """An empty "current" compares unequal to whatever upstream publishes, so the run would
    call an unreadable pin a move and then edit a line it never found."""
    import pytest

    from bot.manifest import Unreadable, meshtastic_cli, meshtastic_web
    with pytest.raises(Unreadable):
        meshtastic_web("build_steps = []\n")
    with pytest.raises(Unreadable):
        meshtastic_cli("build_steps = []\n")


def test_a_recorded_input_keeps_the_token_that_binds_it():
    """The controller binds each recorded value to the exact build-step token that consumes it,
    so the entry carries the consuming `command` and the `token` it fills beside the value. Moving
    the value must leave that binding alone — an edit that dropped either half would produce a
    manifest the controller refuses to load, and the run would fail after the binaries were
    already published."""
    from bot.manifest import set_meshtastic_cli, set_meshtastic_web
    out = set_meshtastic_web(MESHTASTIC, "2.7.2", "2.8.0", "a" * 64)
    assert ('{ name = "meshtastic-web", value = "2.8.0", '
            'command = "meshtastic-web-assets.sh", token = "{value}" }') in out
    out = set_meshtastic_cli(out, "2.7.11", "2.8.1")
    assert ('{ name = "meshtastic-cli", value = "2.8.1", '
            'command = "pip", token = "meshtastic=={value}" }') in out
