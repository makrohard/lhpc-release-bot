"""The Meshtastic web client's two channels in lhpc-binaries: which ones need a build.

Pure decisions, no I/O. The rule is the controller's own reader (SCHEMA-index-v3, web entries):
a box on channel `ch` takes the FIRST entry of `stacks["meshtastic-web"]`, in list order, whose
`channel` is `ch` and whose `components["meshtastic"]` is the meshtasticd it runs. So the bot asks
the same question about the same entry: an older entry farther down the history is shadowed —
no box takes it — and does not count as "already built".
"""
from __future__ import annotations

import re

STACK = "meshtastic-web"
CHANNELS = ("dev", "stable")
RELEASE_TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+\Z")


def selected(entries: list, channel: str, pin: str):
    """The entry a box on `channel` with meshtasticd `pin` installs, or None."""
    for e in entries:
        if e.get("channel") == channel and (e.get("components") or {}).get("meshtastic") == pin:
            return e
    return None


def is_current(entries: list, channel: str, pin: str, want: str) -> bool:
    """The selected entry is exactly the wanted composition: this web commit with this daemon."""
    e = selected(entries, channel, pin)
    return e is not None and (e.get("components") or {}) == {STACK: want, "meshtastic": pin}


def has_daemon_entry(entries: list, pin: str) -> bool:
    """index-v3 holds a meshtastic (daemon) entry built from `pin`: the smoke's daemon exists."""
    return any((e.get("components") or {}).get("meshtastic") == pin for e in entries)


def web_dispatches(pin: str, want: dict, entries: list, daemon_entry: bool) -> list:
    """The channels to build, in CHANNELS order. `want` = {channel: web commit} for each channel
    whose upstream commit was read this run; a channel missing from it is not decided. Nothing
    without the daemon entry: a build whose smoke has no meshtasticd to run would only fail."""
    if not daemon_entry:
        return []
    return [ch for ch in CHANNELS if ch in want and not is_current(entries, ch, pin, want[ch])]


def peeled_commit(ls_remote: str, tag: str):
    """The commit a release tag names, from `git ls-remote <repo> refs/tags/<tag>*` output: the
    peeled `^{}` line of an annotated tag, else the tag's own line; None when absent. The same
    rule as the builder's (lhpc-binaries `builders/lib_web.py`)."""
    rows = dict(reversed(line.split("\t", 1)) for line in ls_remote.splitlines() if "\t" in line)
    for ref in (f"refs/tags/{tag}^{{}}", f"refs/tags/{tag}"):
        sha = rows.get(ref, "")
        if re.fullmatch(r"[0-9a-f]{40}", sha):
            return sha
    return None
