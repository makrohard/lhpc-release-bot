"""What has moved upstream, and which of it this bot is allowed to move.

Pure decisions live in this module and are unit-tested; the git and HTTP calls sit behind
`Remote`, which the tests replace. Nothing here writes anything.
"""
from __future__ import annotations

import json
import re
import subprocess
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# A RELEASE tag is a whole name of optional `v` plus dot-separated numbers — the same shape
# LHPC's own `--source stable` accepts. A build-suffixed (`v2.8.0.7239fe8`) or prerelease
# (`1.8.2-pre`) name is a snapshot, not a release.
VERSION_TAG = re.compile(r"^v?\d+(\.\d+)*$")


def version_key(tag: str) -> tuple:
    return tuple(int(p) for p in tag.lstrip("v").split("."))


def newest_version_tag(tags) -> str:
    """The newest release-shaped tag, numerically. '' when none qualifies."""
    ok = [t for t in tags if VERSION_TAG.match(t)]
    return max(ok, key=version_key) if ok else ""


@dataclass
class Finding:
    """One tracked input, and what this run decided about it. Every input gets one, moved or
    not: a summary that lists only the movers implies the rest were checked and were current,
    which is exactly the thing a release must not imply."""
    key: str                       # source path, or extra.<name>
    track: str
    status: str                    # "at-pin" | "move" | "manual" | "fault"
    current: str = ""
    candidate: str = ""
    tag: str = ""
    detail: str = ""
    consumers: tuple = ()
    remote: str = ""
    branch: str = ""

    @property
    def moves(self) -> bool:
        return self.status == "move"


@dataclass
class Remote:
    """Every outward call the watch makes. Replaced wholesale in tests.

    `token` authenticates the GitHub reads. They are all public, but anonymous requests share
    one small hourly quota per source IP, and a hosted runner's IP is shared with everybody
    else's jobs — so unauthenticated release lookups fail on a busy hour and the whole run
    refuses over a rate limit rather than over anything real.
    """
    workdir: Path
    token: str = ""
    _fetched: dict = field(default_factory=dict)

    def _repo(self, remote: str, branch: str) -> Path:
        """A bare-ish mirror of one branch, fetched once per (remote, branch) per run."""
        key = f"{remote}#{branch}"
        if key in self._fetched:
            return self._fetched[key]
        dest = self.workdir / re.sub(r"[^A-Za-z0-9_.-]", "_", key)
        dest.mkdir(parents=True, exist_ok=True)
        self._git(["init", "-q", str(dest)])
        self._git(["-C", str(dest), "remote", "add", "origin", remote], check=False)
        self._git(["-C", str(dest), "fetch", "-q", "--tags", "origin", branch])
        self._fetched[key] = dest
        return dest

    @staticmethod
    def _git(args, check=True) -> str:
        r = subprocess.run(["git", *args], capture_output=True, text=True, check=False,
                           timeout=600)
        if check and r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
        return r.stdout.strip()

    def branch_tip(self, remote: str, branch: str) -> str:
        return self._git(["-C", str(self._repo(remote, branch)), "rev-parse", "FETCH_HEAD"])

    def tags(self, remote: str, branch: str) -> list:
        d = self._repo(remote, branch)
        return [t for t in self._git(["-C", str(d), "tag", "-l"]).splitlines() if t]

    def commit_of_tag(self, remote: str, branch: str, tag: str) -> str:
        d = self._repo(remote, branch)
        return self._git(["-C", str(d), "rev-list", "-n", "1", tag])

    def is_ancestor(self, remote: str, branch: str, a: str, b: str) -> bool:
        d = self._repo(remote, branch)
        r = subprocess.run(["git", "-C", str(d), "merge-base", "--is-ancestor", a, b],
                           capture_output=True, check=False, timeout=120)
        return r.returncode == 0

    def has_commit(self, remote: str, branch: str, sha: str) -> bool:
        d = self._repo(remote, branch)
        r = subprocess.run(["git", "-C", str(d), "cat-file", "-e", f"{sha}^{{commit}}"],
                           capture_output=True, check=False, timeout=120)
        return r.returncode == 0

    def describe(self, remote: str, branch: str, sha: str) -> str:
        d = self._repo(remote, branch)
        out = self._git(["-C", str(d), "describe", "--tags", "--always", sha], check=False)
        return out or sha[:7]

    def log(self, remote: str, branch: str, a: str, b: str, limit: int = 30) -> list:
        d = self._repo(remote, branch)
        out = self._git(["-C", str(d), "log", "--oneline", "--no-decorate",
                         f"-{limit}", f"{a}..{b}"], check=False)
        return out.splitlines()

    def latest_release(self, repo: str) -> dict:
        """The newest release that is neither a draft nor a prerelease, as {tag, published}."""
        url = f"https://api.github.com/repos/{repo}/releases?per_page=30"
        headers = {"Accept": "application/vnd.github+json",
                   "User-Agent": "lhpc-release-bot"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:      # noqa: S310 (fixed host)
                data = json.load(r)
        except (urllib.error.URLError, ValueError, OSError) as exc:
            raise RuntimeError(f"cannot read releases of {repo}: {exc}") from None
        for rel in data:
            if not rel.get("draft") and not rel.get("prerelease"):
                return {"tag": rel.get("tag_name", ""), "published": rel.get("published_at", "")}
        return {}

    @staticmethod
    def latest_pypi(package: str) -> str:
        url = f"https://pypi.org/pypi/{package}/json"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:      # noqa: S310 (fixed host)
                return json.load(r)["info"]["version"]
        except (urllib.error.URLError, ValueError, KeyError, OSError) as exc:
            raise RuntimeError(f"cannot read PyPI {package}: {exc}") from None


def load_policy(path: Path) -> dict:
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def policy_gaps(policy: dict, pinned_paths) -> list:
    """Reasons the policy and the manifest disagree. A new pinned source with no rule is a
    STOP: it must never be moved by a rule nobody wrote, nor silently left behind."""
    declared = set(policy.get("source", {}))
    actual = set(pinned_paths)
    gaps = [f"{p}: pinned in the manifest, absent from policy.toml" for p in sorted(actual - declared)]
    gaps += [f"{p}: in policy.toml, no longer pinned in the manifest"
             for p in sorted(declared - actual)]
    # A malformed hold is as fatal as a missing rule, and for the same reason: it decides whether
    # an input moves, so it must never be guessed at.
    return gaps + freeze_problems(policy)


def freeze_of(rule: dict, key: str) -> tuple:
    """`(reason, problem)` for one policy entry. A nonblank reason is a hold; a problem is fatal.

    A freeze is a REASON, never a flag. `freeze = true` tells a maintainer nothing months later
    about what is being waited for, so only a nonblank string is accepted. Refusing the two
    entries where a hold would be a lie matters as much: a manual input is never moved anyway,
    and a derived input moves with its owner, so a hold written here would hold nothing while
    reading as though it did.
    """
    if "freeze" not in rule:
        return "", ""
    value = rule["freeze"]
    if not isinstance(value, str) or not value.strip():
        return "", f"{key}: freeze must be a nonblank reason string, got {value!r}"
    if rule.get("track") == "manual":
        return "", f"{key}: freeze on a manual input, which is never moved anyway"
    if rule.get("kind") == "owned-by-pin":
        owner = rule.get("owner", "?")
        return "", (f"{key}: freeze its owner {owner} instead — this input moves with that pin, "
                    f"so a hold here would not hold anything")
    return value.strip(), ""


def freeze_problems(policy: dict) -> list:
    out = []
    for table in ("source", "extra"):
        for name, rule in (policy.get(table) or {}).items():
            key = name if table == "source" else f"extra.{name}"
            problem = freeze_of(rule or {}, key)[1]
            if problem:
                out.append(problem)
    return out


def examine(source, rule: dict, remote: Remote) -> Finding:
    """Decide one git source. `source` is the manifest contract for one path."""
    track = rule.get("track", "")
    base = {"key": source.path, "track": track, "current": source.pin,
            "consumers": tuple(source.consumers), "remote": source.remote,
            "branch": source.branch}
    frozen = freeze_of(rule, source.path)[0]
    if track == "manual" or frozen:
        # Held or permanently manual, the report is the same shape: what upstream looks like, and
        # why this input is not following it. A frozen input keeps its declared `track` so the
        # hold can be lifted by deleting one line.
        status = "frozen" if frozen else "manual"
        why = frozen or rule.get("why", "")
        try:
            tip = remote.branch_tip(source.remote, source.branch)
            newest = newest_version_tag(remote.tags(source.remote, source.branch))
            ahead = tip != source.pin
            detail = (f"upstream {'has moved' if ahead else 'is at the pin'}"
                      + (f" (tip {tip[:9]}" + (f", newest tag {newest}" if newest else "") + ")"
                         if ahead else "")
                      + (f" — {why}" if why else ""))
            return Finding(status=status, candidate=tip if ahead else "", detail=detail, **base)
        except RuntimeError as exc:
            # A hold survives an unreadable upstream. Downgrading it to a fault would let a
            # transient lookup failure block every unrelated change in the same run.
            return Finding(status=status,
                           detail=f"upstream not readable ({exc})"
                                  + (f" — held: {why}" if why else ""), **base)

    try:
        tip = remote.branch_tip(source.remote, source.branch)
        if track == "tip":
            candidate, tag = tip, ""
        elif track == "tag":
            tag = newest_version_tag(remote.tags(source.remote, source.branch))
            if not tag:
                return Finding(status="fault", detail="no release-shaped tag upstream", **base)
            candidate = remote.commit_of_tag(source.remote, source.branch, tag)
        elif track == "release":
            rel = remote.latest_release(_repo_of(source.remote))
            if not rel:
                return Finding(status="fault", detail="no published non-prerelease release",
                               **base)
            tag = rel["tag"]
            candidate = remote.commit_of_tag(source.remote, source.branch, tag)
        else:
            return Finding(status="fault", detail=f"unknown track {track!r}", **base)

        if not remote.has_commit(source.remote, source.branch, source.pin):
            return Finding(status="fault", candidate=candidate, tag=tag,
                           detail="the CURRENT pin is not on its branch any more (orphaned by a "
                                  "force-push?) — a release cannot be built on it", **base)
        if candidate == source.pin:
            return Finding(status="at-pin", candidate=candidate, tag=tag, **base)
        if not remote.is_ancestor(source.remote, source.branch, source.pin, candidate):
            return Finding(status="fault", candidate=candidate, tag=tag,
                           detail="the candidate is not a descendant of the current pin — "
                                  "upstream rewrote history or the tag left the branch", **base)
        if not remote.is_ancestor(source.remote, source.branch, candidate, tip):
            return Finding(status="fault", candidate=candidate, tag=tag,
                           detail="the candidate is not on the declared branch", **base)
        described = tag or remote.describe(source.remote, source.branch, candidate)
        return Finding(status="move", candidate=candidate, tag=described, **base)
    except RuntimeError as exc:
        return Finding(status="fault", detail=str(exc), **base)


def _repo_of(remote_url: str) -> str:
    m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", remote_url)
    if not m:
        raise RuntimeError(f"not a GitHub remote: {remote_url}")
    return m.group(1)


def _version_parts(v: str):
    """A release-shaped version as a comparable tuple, or None. Same shape rule as the tags —
    one definition of "a version" for git tags and for the pins that are not git."""
    return version_key(v) if VERSION_TAG.match(v or "") else None


def _is_backwards(current: str, latest: str) -> str:
    """"" when `latest` is a legitimate forward move, else why it is not.

    Unorderable is refused too: a pin the bot cannot compare is a pin it must not move on its
    own, and saying so is cheaper than discovering it in a published release.
    """
    a, b = _version_parts(current), _version_parts(latest)
    if a is None or b is None:
        return "neither is a dotted numeric version" if a is None and b is None else (
            f"{current!r} is not a dotted numeric version" if a is None
            else f"{latest!r} is not a dotted numeric version")
    return "" if b > a else "numerically older"


def examine_extra(name: str, rule: dict, current: str, remote: Remote) -> Finding:
    """A pinned input that is not a git source: a fetched release, a pip version, or one that
    another pin already owns."""
    kind, track = rule.get("kind", ""), rule.get("track", "manual")
    base = {"key": f"extra.{name}", "track": track, "current": current}
    if kind == "owned-by-pin":
        return Finding(status="manual", detail=f"moves with {rule.get('owner', '?')}", **base)
    frozen = freeze_of(rule, f"extra.{name}")[0]
    try:
        if kind == "github-release":
            rel = remote.latest_release(rule["repo"])
            latest = rel.get("tag", "").lstrip("v")
        elif kind == "pypi":
            latest = remote.latest_pypi(rule["package"])
        else:
            return Finding(status="fault", detail=f"unknown extra kind {kind!r}", **base)
    except RuntimeError as exc:
        if frozen:
            return Finding(status="frozen",
                           detail=f"upstream not readable ({exc}) — held: {frozen}", **base)
        return Finding(status="fault", detail=str(exc), **base)

    if not latest:
        return Finding(status="fault", detail="upstream published nothing readable", **base)
    if latest == current:
        return Finding(status="frozen" if frozen else "at-pin", candidate=latest, tag=latest,
                       detail=f"held: {frozen}" if frozen else "", **base)
    if frozen:
        # Never a move, and never a fault either: a newer release is information, not evidence
        # that the problem being waited on is fixed.
        return Finding(status="frozen", candidate=latest, tag=latest,
                       detail=f"upstream is at {latest} — held: {frozen}", **base)
    # FORWARD ONLY, the same rule a git source gets. A git candidate must descend from the pin;
    # here there is no history to walk, so the versions are ordered instead. It matters because
    # GitHub returns releases newest-CREATED first: a hotfix cut on an older line after a newer
    # major is the first non-draft entry, and without this the bot would write that downgrade
    # into the manifest as an ordinary move.
    back = _is_backwards(current, latest)
    if back:
        return Finding(status="fault", candidate=latest, tag=latest,
                       detail=f"upstream's newest is {latest}, behind the pinned {current} "
                              f"({back}) — a downgrade is never an automatic move", **base)
    if track == "manual":
        return Finding(status="manual", candidate=latest, tag=latest,
                       detail=f"{current} -> {latest} available"
                              + (f" — {rule['why']}" if rule.get("why") else ""), **base)
    return Finding(status="move", candidate=latest, tag=latest, **base)
