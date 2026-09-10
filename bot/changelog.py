"""Version scalars and changelog sections — the three files a release commit always touches.

LHPC pins `pyproject.toml`, `lhpc/version.py` and the first `## X.Y.Z` changelog heading to each
other in its own test suite, so these must move together or CI stops the release.
"""
from __future__ import annotations

import re

VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
HEADING = re.compile(r"^## (\d+\.\d+\.\d+)\s*$", re.M)


def next_patch(version: str) -> str:
    m = VERSION.match(version)
    if not m:
        raise ValueError(f"not a release triple: {version!r}")
    major, minor, patch = (int(x) for x in m.groups())
    return f"{major}.{minor}.{patch + 1}"


def set_pyproject_version(text: str, version: str) -> str:
    new, n = re.subn(r'^version = "[^"]*"', f'version = "{version}"', text, count=1, flags=re.M)
    if n != 1:
        raise ValueError("pyproject.toml: no version line to move")
    return new


def set_version_module(text: str, version: str) -> str:
    new, n = re.subn(r'__version__ = "[^"]*"', f'__version__ = "{version}"', text, count=1)
    if n != 1:
        raise ValueError("version.py: no __version__ to move")
    return new


def current_version(pyproject_text: str) -> str:
    m = re.search(r'^version = "([^"]+)"', pyproject_text, re.M)
    if not m:
        raise ValueError("pyproject.toml: no version line")
    return m.group(1)


def insert_section(changelog: str, version: str, bullets) -> str:
    """Put this release's section at the top, under the title, above the previous release."""
    if f"## {version}\n" in changelog:
        raise ValueError(f"the changelog already has a section for {version}")
    body = "".join(f"- {b}\n" for b in bullets)
    section = f"## {version}\n\n{body}\n"
    m = HEADING.search(changelog)
    if m:
        return changelog[:m.start()] + section + changelog[m.start():]
    head, sep, rest = changelog.partition("\n")
    return f"{head}{sep}\n{section}{rest.lstrip(chr(10))}"


def section_of(changelog: str, version: str) -> str:
    """The bullets of one release's section, for the commit body and the release notes."""
    start = changelog.find(f"## {version}\n")
    if start < 0:
        return ""
    rest = changelog[start + len(f"## {version}\n"):]
    m = HEADING.search(rest)
    return rest[:m.start()].strip() if m else rest.strip()


def version_tuple(text: str) -> tuple:
    """`"0.3.15"` -> `(0, 3, 15)`, so versions compare as numbers and not as strings."""
    return tuple(int(part) for part in text.split("."))


NUMERIC_HEAD = re.compile(r"^[vV]?(\d+(?:\.\d+)*)")


def version_order(text: str) -> tuple:
    """`version_tuple`, but tolerant of a suffix: `"0.4.0rc1"` -> `(0, 4, 0)`.

    Changelog HEADINGS stay strict triples and are read with `version_tuple`. A version SCALAR on
    `dev` is written by a person and may carry a pre-release marker, and the only question ever
    asked of it is whether `dev` has opened a later cycle than the release being merged back.
    The numbers in front answer that; treating `0.4.0rc1` as unorderable and advancing past it
    would silently downgrade somebody's declared cycle. The optional leading `v` is there for the
    same reason and not for tidiness: PEP 440 permits `v0.4.0` and is case-insensitive about it, and
    one character was the whole difference between the case this handles and the downgrade it
    exists to prevent — twice over, since the first version of this accepted only the lower-case
    one. An epoch (`1!0.4.0`) is still not handled; LHPC has never used one.
    """
    m = NUMERIC_HEAD.match(text.strip())
    if not m:
        raise ValueError(f"no version number in {text!r}")
    return tuple(int(part) for part in m.group(1).split("."))


def merge_back(dev_changelog: str, patch_section: str, patch_version: str) -> str:
    """Insert the released patch in VERSION ORDER, wherever that puts it.

    This is the ONE conflict resolved automatically, because it is the one that is guaranteed:
    a cycle starts by bumping the version on `dev`, so `dev` and a patch from `main` always
    collide on the changelog heading and on the two version scalars. Everything else is a real
    conflict and belongs in a pull request.

    It used to insert after the FIRST heading, on the assumption that `dev`'s first section is
    always a newer unreleased cycle. That is true when `dev` has started `0.4.0`; it is false in
    the ordinary case where `dev` has simply not moved since the last release, and its first
    section is the OLD released one. Then a `0.3.15` patch landed *under* `0.3.14` and the file
    was out of order — which is what the live PR did, and which no test caught because every
    fixture gave `dev` a newer section to sit beneath.

    Version order says the right thing in both cases without needing to know which one it is: a
    genuinely newer `0.4.0` still sorts above the patch, and a stale `0.3.14` sorts below it.
    """
    section = f"## {patch_version}\n\n{patch_section.strip()}\n\n"
    headings = list(HEADING.finditer(dev_changelog))
    if not headings:
        raise ValueError("dev changelog has no release heading to insert after")
    mine = version_tuple(patch_version)
    # Idempotence is decided by the same parse that does the insertion, not by a substring
    # search for `## <version>\n`: `HEADING` tolerates trailing whitespace, so a heading written
    # `## 0.3.15 ` defeated the search and the section was inserted a second time. Note that this
    # FALLS THROUGH to the newline guard below rather than returning here — an early return would
    # hand back the caller's stripped text and reinstate the missing-newline defect on the one
    # path where nothing else changes, which is the path hardest to notice.
    if any(version_tuple(h.group(1)) == mine for h in headings):
        out = dev_changelog
    else:
        for h in headings:
            if version_tuple(h.group(1)) < mine:
                out = dev_changelog[:h.start()] + section + dev_changelog[h.start():]
                break
        else:
            # Older than everything already there — the end of the file is where it belongs.
            out = dev_changelog.rstrip() + "\n\n" + section.rstrip() + "\n"
    # The caller reads `dev` through a helper that strips trailing whitespace, so the text arriving
    # here has usually lost its final newline. Faithfully preserving that absence put
    # `\ No newline at end of file` in every merge-back pull request, and left the next commit that
    # touches the file carrying a spurious one-line diff.
    return out if out.endswith("\n") else out + "\n"


def pin_bullets(findings) -> list:
    """One short line per moved input — the changelog is the release note."""
    out = []
    for f in findings:
        if not f.moves:
            continue
        name = f.key.split("/")[-1]
        if len(f.current) == 40 and len(f.candidate) == 40:
            what = f"{f.current[:9]} -> {f.candidate[:9]}"
        else:
            what = f"{f.current} -> {f.candidate}"
        line = f"{name}: {what}"
        if f.tag:
            line += f" ({f.tag})"
        if f.consumers:
            line += f", used by {', '.join(f.consumers)}"
        out.append(line)
    return out
