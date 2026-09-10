"""Read LHPC's manifest, and move a pin in it without disturbing anything else.

The edit is line-based on purpose. The manifest is a hand-maintained document whose comments
carry the reasons for its pins; a TOML round-trip would rewrite the whole file and throw those
away. Only the two lines that state a pin are touched, in every stanza that shares the source.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass

SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class Source:
    """One managed source path, as every consumer of it agrees it is."""
    path: str
    pin: str
    tag: str
    remote: str
    branch: str
    consumers: tuple
    # True when the manifest declares this source `artifact = true`. LHPC then resolves EVERY
    # selector to the default branch tip and skips the pin check entirely, so the pin is
    # decorative: a hold on such a source cannot hold. Moving its pin still works.
    artifact: bool = False


def pinned_sources(manifest_text: str) -> list:
    """Every pinned source, in manifest order, with its consumers folded together.

    Consumers of one path must agree on pin, tag, remote and branch — LHPC's own
    `tests/test_pin_consistency.py` and its CI job enforce that, so disagreement here is a
    manifest defect this bot must not paper over.
    """
    doc = tomllib.loads(manifest_text)
    by_path: dict = {}
    for stack in doc.get("stack", []):
        for comp in stack.get("component", []):
            src = comp.get("source") or {}
            path, pin = src.get("path"), src.get("pin_commit")
            if not path or not pin:
                continue
            rec = by_path.setdefault(path, {"pin": set(), "tag": set(), "remote": set(),
                                            "branch": set(), "consumers": [],
                                            "artifact": set()})
            rec["pin"].add(pin)
            rec["artifact"].add(bool(src.get("artifact")))
            rec["tag"].add(src.get("pin_tag", ""))
            rec["remote"].add(src.get("remote", ""))
            rec["branch"].add(src.get("branch", "main"))
            rec["consumers"].append(comp["id"])

    out = []
    for path, rec in by_path.items():
        for field in ("pin", "tag", "remote", "branch", "artifact"):
            if len(rec[field]) != 1:
                raise ValueError(f"{path}: consumers disagree on {field}: {sorted(rec[field])}")
        pin = next(iter(rec["pin"]))
        if not SHA.match(pin):
            raise ValueError(f"{path}: pin is not a full 40-hex sha: {pin!r}")
        out.append(Source(path=path, pin=pin, tag=next(iter(rec["tag"])),
                          remote=next(iter(rec["remote"])), branch=next(iter(rec["branch"])),
                          consumers=tuple(rec["consumers"]),
                          artifact=next(iter(rec["artifact"]))))
    return out


def set_pin(text: str, path: str, commit: str, tag: str) -> str:
    """Rewrite `pin_commit`/`pin_tag` in every source stanza whose `path` is `path`.

    A stanza is `[stack.component.source]` (at any indentation) up to the next table header or
    blank line — the same shape the test lab's overlay walks.
    """
    if not SHA.match(commit):
        raise ValueError(f"refusing a pin that is not a full 40-hex sha: {commit!r}")
    lines = text.splitlines(keepends=True)
    out, i, touched = [], 0, 0
    while i < len(lines):
        line = lines[i]
        if line.strip() != "[stack.component.source]":
            out.append(line)
            i += 1
            continue
        # Collect the whole stanza, then decide.
        j = i + 1
        stanza = []
        while j < len(lines):
            s = lines[j].strip()
            if not s or s.startswith("["):
                break
            stanza.append(lines[j])
            j += 1
        this_path = ""
        for s in stanza:
            m = re.match(r'\s*path\s*=\s*"([^"]+)"', s)
            if m:
                this_path = m.group(1)
                break
        out.append(line)
        if this_path == path:
            for s in stanza:
                if re.match(r'\s*pin_commit\s*=', s):
                    out.append(re.sub(r'"[^"]*"', f'"{commit}"', s, count=1))
                    touched += 1
                elif re.match(r'\s*pin_tag\s*=', s):
                    out.append(re.sub(r'"[^"]*"', f'"{tag}"', s, count=1))
                else:
                    out.append(s)
        else:
            out.extend(stanza)
        i = j
    if not touched:
        raise ValueError(f"no pin_commit line found for {path!r} — refusing a silent no-op")
    return "".join(out)


def graywolf_version(manifest_text: str) -> str:
    """The version the manifest's graywolf build step fetches."""
    m = re.search(r'graywolf-fetch\.sh"[^]]*?"([0-9][0-9.]*)"', manifest_text)
    return m.group(1) if m else ""


def set_graywolf_version(manifest_text: str, old: str, new: str) -> str:
    """Move the graywolf version in the two places the manifest states it: the fetch step (its
    argv and its announcement) and the version-bearing build marker.

    The marker carries the version on purpose — with only `bin`, an already-built box would keep
    reading "built" while running the old graywolf — so it must move with the step or the bump
    does nothing on a deployed box.
    """
    if old == new:
        raise ValueError("graywolf: old and new version are the same")
    lines, out, hits = manifest_text.splitlines(keepends=True), [], 0
    for line in lines:
        if "graywolf-fetch.sh" in line or "build_marker" in line and "graywolf" in line:
            new_line = line.replace(old, new)
            hits += new_line != line
            out.append(new_line)
        else:
            out.append(line)
    if hits < 2:
        raise ValueError(f"graywolf {old} -> {new}: expected the fetch step and the build "
                         f"marker to move, changed {hits} line(s)")
    return "".join(out)


CHECKSUM_ROW = re.compile(r'^\s*(?P<ver>[0-9][0-9.]*)/(?P<arch>[a-z0-9]+)\)\s*echo\s*"(?P<sha>[0-9a-f]{64})"')


def graywolf_checksums(script_text: str) -> dict:
    """{"<version>/<arch>": sha256} as the fetch script's own table records them."""
    out = {}
    for line in script_text.splitlines():
        m = CHECKSUM_ROW.match(line)
        if m:
            out[f"{m.group('ver')}/{m.group('arch')}"] = m.group("sha")
    return out


def add_graywolf_checksums(script_text: str, version: str, sums: dict) -> str:
    """Add one version's rows to the fetch script's table, keeping every existing row.

    Old rows stay: the table is what lets a box verify a version it already has, and rewriting
    history to make a bump look tidy would break exactly that.
    """
    have = graywolf_checksums(script_text)
    missing = [a for a in ("arm64", "armhf", "amd64") if a not in sums]
    if missing:
        raise ValueError(f"graywolf {version}: no checksum for {', '.join(missing)}")
    for arch, sha in sums.items():
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError(f"graywolf {version}/{arch}: not a sha256: {sha!r}")
        key = f"{version}/{arch}"
        if key in have and have[key] != sha:
            raise ValueError(f"graywolf {key} is already recorded with a different digest")
    lines, out, inserted = script_text.splitlines(keepends=True), [], False
    for line in lines:
        if not inserted and CHECKSUM_ROW.match(line):
            indent = line[:len(line) - len(line.lstrip())]
            for arch in ("arm64", "armhf", "amd64"):
                if f"{version}/{arch}" not in have:
                    out.append(f'{indent}{version}/{arch}) echo "{sums[arch]}" ;;\n')
            inserted = True
        out.append(line)
    if not inserted:
        raise ValueError("graywolf: no checksum table found in the fetch script")
    return "".join(out)


def binary_stacks(manifest_text: str) -> dict:
    """{stack id: (component ids the published artifact covers)} for every stack that declares a
    binary channel. A moved pin only needs a rebuilt binary where it is one of these."""
    doc = tomllib.loads(manifest_text)
    return {st["id"]: tuple(st["binary"].get("covers", []))
            for st in doc.get("stack", []) if st.get("binary")}


def components_of(manifest_text: str) -> dict:
    """{component id: stack id} — how a moved source maps to the stack that must be proved."""
    doc = tomllib.loads(manifest_text)
    return {c["id"]: st["id"] for st in doc.get("stack", []) for c in st.get("component", [])}


# The Meshtastic browser UI is LHPC's own pin, not a git source: the manifest names a
# meshtastic/web release and the sha256 of its `build.tar`, and the fetch script verifies that
# digest on every install. The version appears twice on its line — in the argv and in the
# announcement an operator reads — so a bump that moved only one would leave the log lying.
WEB_LINE = re.compile(
    r'(meshtastic-web-assets\.sh",\s*"[^"]+",\s*")(?P<ver>[0-9]+(?:\.[0-9]+)*)'
    r'(",\s*")(?P<sha>[0-9a-f]{64})(")')
CLI_PIN = re.compile(r'"meshtastic==(?P<ver>[0-9]+(?:\.[0-9]+)*)"')


class Unreadable(ValueError):
    """A pin the bot is responsible for moving cannot be read out of the manifest.

    Never an empty string. An empty "current" compares unequal to whatever upstream publishes,
    so the run would classify an unreadable pin as a move and then edit a line it never found —
    the one shape of failure that must stop a release rather than drive one.
    """


def meshtastic_web(manifest_text: str) -> tuple:
    """(version, sha256) of the pinned web client."""
    m = WEB_LINE.search(manifest_text)
    if not m:
        raise Unreadable("the manifest states no meshtastic web-client version and digest")
    return (m.group("ver"), m.group("sha"))


def meshtastic_cli(manifest_text: str) -> str:
    """The pinned Meshtastic CLI version."""
    m = CLI_PIN.search(manifest_text)
    if not m:
        raise Unreadable("the manifest pins no meshtastic CLI version")
    return m.group("ver")


# The same two versions again, in the component's `build_inputs` — what LHPC records inside the
# completion marker so an already-built box notices the bump. LHPC refuses to load a manifest
# whose recorded value is absent from the build step it mirrors, so these move together or the
# candidate does not load at all.
def _build_input(name: str) -> re.Pattern:
    return re.compile(rf'(\{{\s*name\s*=\s*"{re.escape(name)}"\s*,\s*value\s*=\s*")'
                      rf'(?P<val>[^"]+)(")')


def set_build_input(manifest_text: str, name: str, old: str, new: str) -> str:
    """Move one recorded build input, checking it was the value we think we are replacing."""
    pat = _build_input(name)
    m = pat.search(manifest_text)
    if m is None:
        raise Unreadable(f"the manifest records no build_input {name!r}")
    if m.group("val") != old:
        raise ValueError(
            f"build_input {name!r} records {m.group('val')!r}, not the pinned {old!r} — "
            f"the manifest and its recorded inputs have drifted apart")
    return pat.sub(lambda mm: mm.group(1) + new + mm.group(3), manifest_text, count=1)


def set_meshtastic_web(manifest_text: str, old: str, new: str, sha256: str) -> str:
    """Move the web-client pin: the version in the argv, the digest beside it, and the version
    in the announcement.

    The digest is not optional and is not derived here — it is the sha256 of that release's own
    `build.tar`, which the fetch script re-checks on every install. A version moved without its
    digest would fail every install; a digest moved without its version would install the old
    client and claim the new one.
    """
    if old == new:
        raise ValueError("meshtastic web: old and new version are the same")
    # The fetch script demands MAJOR.MINOR.PATCH and exits on anything else. Rejecting it here
    # costs one run; accepting it publishes binaries and fails at prove, which costs a cycle.
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", new or ""):
        raise ValueError(
            f"meshtastic web: {new!r} is not MAJOR.MINOR.PATCH — the fetch script refuses it")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise ValueError(f"meshtastic web {new}: not a sha256: {sha256!r}")
    text, n = WEB_LINE.subn(lambda m: m.group(1) + new + m.group(3) + sha256 + m.group(5),
                            manifest_text, count=1)
    if n != 1:
        raise ValueError("meshtastic web: no fetch step found to move")
    text, a = re.subn(rf"web client v{re.escape(old)}\b", f"web client v{new}", text, count=1)
    if a != 1:
        raise ValueError(f"meshtastic web: the announcement does not name v{old}")
    return set_build_input(text, "meshtastic-web", old, new)


def set_meshtastic_cli(manifest_text: str, old: str, new: str) -> str:
    """Move the CLI pin in its pip step, in the announcement beside it, and in the build input
    LHPC records.

    The CLI venv itself is built on the box and is not in the artifact. The RECORDED value is,
    though: it lives in the completion marker, which the artifact ships. So the meshtastic binary
    has to be republished for this move as well — without it every box on the binary channel
    reads "not built" and the reinstall hands back the same stale marker.
    """
    if old == new:
        raise ValueError("meshtastic cli: old and new version are the same")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", new or ""):
        raise ValueError(f"meshtastic cli: not a version: {new!r}")
    text, n = re.subn(rf'"meshtastic=={re.escape(old)}"', f'"meshtastic=={new}"',
                      manifest_text, count=1)
    if n != 1:
        raise ValueError(f"meshtastic cli: no pip step pinning {old}")
    text, a = re.subn(rf"Meshtastic CLI {re.escape(old)}\b", f"Meshtastic CLI {new}", text,
                      count=1)
    if a != 1:
        raise ValueError(f"meshtastic cli: the announcement does not name {old}")
    return set_build_input(text, "meshtastic-cli", old, new)
