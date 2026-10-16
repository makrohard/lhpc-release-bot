"""LHPC's own Python pins, checked in `prepare` before anything is pushed.

The constraints check (finding 138): a component whose build installs against
`{asset}/<name>-constraints.txt` breaks the whole run at prove when its upstream raises a dependency
floor above what that file pins: pip's ResolutionImpossible there is unattributable. So every moved
checkout such a step installs is resolved against its constraints file HERE, with pip's own
resolver, and a conflict stops `prepare` naming the requirement and the pin. The bot never edits a
constraints file: raising a floor is a reviewed commit on LHPC's `dev`.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

PYTHON = "python3.13"            # the interpreter the image runs (trixie's)
CONSTRAINTS = re.compile(r"^\{asset\}/(?P<file>[A-Za-z0-9._-]+-constraints\.txt)$")
RUNTIME_SRC = re.compile(r"^\{runtime\}/(?P<path>src/[A-Za-z0-9._-]+)$")
NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
CONFLICT_MAX = 4000


class CheckFailed(RuntimeError):
    """A check that could not pass. `cli` turns it into `Stop("prepare", …)`."""

    def __init__(self, observed: str, next_action: str, detail: str = ""):
        super().__init__(observed)
        self.observed, self.next_action, self.detail = observed, next_action, detail


CALL_BOUND = 300         # s, one git or pip call (measured: venv 1.6 s, pip-tools install 1.6 s, compile 2.8 s)
BOUND = 10 * 60          # s, both checks of one run together; the plan job's 35 min ceiling holds it


def run(argv, cwd=None, timeout=CALL_BOUND) -> subprocess.CompletedProcess:
    """THE seam: every process this module starts goes through here, with its real argv. A call
    that outlives its bound is a failed call (124), so it becomes the check's own Stop."""
    try:
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, errors="replace",
                              check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"`{' '.join(map(str, argv[:4]))} …` "
                                                          f"timed out after {timeout:.0f} s")
    except OSError as exc:                          # no such program, not executable, bad cwd
        return subprocess.CompletedProcess(argv, 127, "", f"`{' '.join(map(str, argv[:4]))} …` "
                                                          f"could not be started ({exc})")


class Clock:
    """One bound for both checks of a run: a call gets at most CALL_BOUND, never more than is
    left; with nothing left it is not started (124)."""

    def __init__(self, seconds: float = BOUND):
        self.end = time.monotonic() + seconds

    def call(self, runner, argv, cwd=None):
        left = self.end - time.monotonic()
        if left <= 0:
            return subprocess.CompletedProcess(argv, 124, "", f"`{' '.join(map(str, argv[:4]))} …` "
                                                              "not started: the checks' bound is spent")
        return runner(argv, cwd=cwd, timeout=min(CALL_BOUND, left))


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def fenced(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) > limit:
        text = text[:limit] + "\n… (cut)"
    return f"```\n{text}\n```"


def interpreter(python: str, runner=run, clock=None) -> tuple:
    """(executable, version) of `python`, as that interpreter reports them itself."""
    r = (clock or Clock()).call(runner, [python, "-c",
                                         "import sys; print(sys.executable); print(sys.version)"])
    if r.returncode != 0:
        raise CheckFailed(f"`{python}` cannot be run: {r.stderr.strip()[:300]}",
                          "Give the plan job a Python 3.13 (`actions/setup-python`).")
    exe, _, version = r.stdout.strip().partition("\n")
    if not version.startswith("3.13."):
        raise CheckFailed(f"`{python}` is {exe} (Python {version.split()[0] if version else '?'}),"
                          " not Python 3.13, the interpreter the image runs",
                          "Give the plan job a Python 3.13 (`actions/setup-python`).")
    return exe, version.split()[0]


# ---- B: a moved constraints-pinned checkout still fits its constraints file --------------------

@dataclass(frozen=True)
class Governed:
    """One checkout a constraints file governs."""
    component: str            # the component whose build step carries `-c {asset}/<file>`
    checkout: str             # its source path, e.g. src/meshcore-cli
    subdir: str               # where the declared dependencies live inside it ("" or "backend")
    names: tuple              # a named-list step installs exactly these; () = all declared
    constraints: str          # the file under lhpc/data


def _step_lists(comp: dict):
    for value in comp.values():
        if isinstance(value, list) and value and all(isinstance(s, dict) for s in value):
            for step in value:
                if isinstance(step.get("argv"), list):
                    yield step["argv"]


def _pip_install(argv) -> list:
    """The positional arguments of a `pip install` argv (options and their values dropped)."""
    if not argv or not argv[0].endswith("pip") or "install" not in argv:
        return []
    out, skip = [], False
    for tok in argv[argv.index("install") + 1:]:
        if skip:
            skip = False
        elif tok in ("-c", "-r", "--constraint", "--requirement", "-i", "--index-url"):
            skip = True
        elif not tok.startswith("-"):
            out.append(tok)
    return out


def governed(manifest_text: str) -> list:
    """Every checkout a `-c {asset}/<name>-constraints.txt` build step governs, read from the
    manifest: its component's own source (`./<sub>` names where in it the dependencies are
    declared) plus every `{runtime}/src/<path>` checkout the same component installs (the
    openhop repeater, installed `--no-deps` beside meshcore-node's constraints step). A step that
    installs a named list governs those names only."""
    out = []
    for stack in tomllib.loads(manifest_text).get("stack", []):
        for comp in stack.get("component", []):
            own = (comp.get("source") or {}).get("path", "")
            steps = list(_step_lists(comp))
            runtime = [RUNTIME_SRC.match(a)["path"] for s in steps for a in _pip_install(s)
                       if RUNTIME_SRC.match(a)]
            for argv in steps:
                i = argv.index("-c") + 1 if "-c" in argv else 0
                m = CONSTRAINTS.match(argv[i]) if 0 < i < len(argv) else None
                args = _pip_install(argv)
                if not m or not args:
                    continue
                names = tuple(a for a in args if a != "." and not a.startswith("./")
                              and not RUNTIME_SRC.match(a))
                sub = next((a[2:].rstrip("/") for a in args if a.startswith("./")), "")
                for path in dict.fromkeys([own, *runtime]):
                    if path:
                        out.append(Governed(comp["id"], path, sub if path == own else "", names,
                                            m["file"]))
    return out


# requirements.txt option lines that add no requirement (where packages come from, which builds),
# full spellings only. An option line stops the check unless every option on it is listed
# (pip parses them all: `--pre -r floor.txt` includes floor.txt) (W9 F1).
IGNORED_OPTIONS = frozenset({"-i", "--index-url", "--extra-index-url", "--no-index", "-f",
                             "--find-links", "--trusted-host", "--pre", "--prefer-binary",
                             "--only-binary", "--no-binary"})


def _read(path: Path, what: str) -> str:
    """A fetched or shipped text file; unreadable or not text is the check's own failure."""
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        raise CheckFailed(f"{what}: {path.name} cannot be read ({exc})",
                          "Hold the pin until it reads again. Nothing was pushed.") from None


def declared(base: Path, names: tuple, what: str = "the checkout") -> list:
    """The requirements a checkout declares statically: `[project] dependencies`, else
    `requirements.txt`. A direct-URL requirement (`name @ git+…`) is dropped: such a source has
    its own pin. For a named-list step, only those names (a bare name where none is declared).
    Every way the metadata cannot be read is a CheckFailed naming `what` and the file."""
    reqs = None
    pp = base / "pyproject.toml"
    hold = "Hold the pin until its metadata reads again. Nothing was pushed."
    if pp.is_file():
        try:
            project = tomllib.loads(_read(pp, what)).get("project", {})
        except tomllib.TOMLDecodeError as exc:
            raise CheckFailed(f"{what}: pyproject.toml is not valid TOML ({exc})", hold) from None
        reqs = project.get("dependencies") if isinstance(project, dict) else None
        if reqs is not None and not (isinstance(reqs, list)
                                     and all(isinstance(r, str) for r in reqs)):
            raise CheckFailed(f"{what}: pyproject.toml's `[project] dependencies` is not a list "
                              "of strings", hold)
    if reqs is None and (base / "requirements.txt").is_file():
        reqs = [ln.split("#", 1)[0].strip()
                for ln in _read(base / "requirements.txt", what).splitlines()]
        opts = [r for r in reqs if r.startswith("-")
                and any(t.startswith("-") and t.split("=", 1)[0] not in IGNORED_OPTIONS
                        for t in r.split())]
        if opts:    # an include (also `--requiremen=`, `-rfile`, `--pre -r f`), `-e`, …: unread
            raise CheckFailed(f"{what}: requirements.txt has an option line this check does not "
                              f"read ({opts[0]})",
                              "Name its requirements in the manifest's pip step, or hold the pin.")
        reqs = [r for r in reqs if r and not r.startswith("-")]
    if reqs is None:
        raise CheckFailed(f"{what} declares no dependencies statically (no `[project] "
                          "dependencies`, no requirements.txt)",
                          "Name its requirements in the manifest's pip step, or hold the pin.")
    reqs = [r for r in reqs if "@" not in r.split(";", 1)[0]]        # PEP 508 `name @ url`
    if not names:
        return reqs
    want = {canonical(n) for n in names}
    keep = [r for r in reqs if NAME.match(r) and canonical(NAME.match(r)[1]) in want]
    have = {canonical(NAME.match(r)[1]) for r in keep}
    return keep + [n for n in names if canonical(n) not in have]


def _conflict(output: str):
    """(requirement, through, pin) from pip's "The conflict is caused by:" block, which only a run
    without `--quiet` prints (on stdout, measured). `through` names the package that requires it
    ("" for the checkout's own requirement): the first one on a constrained name that provably
    excludes its pin. None when the block names no such pair."""
    block = output.split("The conflict is caused by:", 1)
    if len(block) < 2:
        return None
    needs, pins = [], {}
    for ln in block[1].splitlines()[1:]:
        if not ln.startswith("    "):
            break
        ln = ln.strip()
        if m := re.fullmatch(r"The user requested \(constraint\) (.+)", ln):
            if NAME.match(m[1]):
                pins[canonical(NAME.match(m[1])[1])] = m[1]
        elif m := re.fullmatch(r"The user requested (.+)", ln):
            needs.append((m[1], ""))
        elif m := re.fullmatch(r"(\S+) (\S+) depends on (.+)", ln):
            needs.append((m[3], f"{m[1]} {m[2]}"))
    for req, through in needs:
        name = canonical(NAME.match(req)[1]) if NAME.match(req) else ""
        if name in pins and _excludes(req, pins[name]):
            return req, through, pins[name]
    return None


RELEASE = re.compile(r"\d+(?:\.\d+)*")
CLAUSE = re.compile(r"\s*(~=|==|!=|<=|>=|<|>)\s*(\S+?)\s*")


def _release(text: str):
    return tuple(int(p) for p in text.split(".")) if RELEASE.fullmatch(text) else None


def _excludes(req: str, pin: str) -> bool:
    """True only when `req` provably excludes the version `pin` (`name==X`) fixes (W9 F2): one
    clause rules it out, comparing plain release numbers (`1.9` = `1.9.0`). A pre-release, a
    wildcard or anything else is not proven, so the caller gives the generic stop."""
    pinned = CLAUSE.fullmatch(pin[NAME.match(pin).end():].split(";", 1)[0])
    v = _release(pinned[2]) if pinned and pinned[1] == "==" else None
    spec = re.sub(r"^\[[^\]]*\]", "", req[NAME.match(req).end():].split(";", 1)[0].strip())
    if v is None or not spec:
        return False
    for clause in spec.split(","):
        m = CLAUSE.fullmatch(clause)
        x = _release(m[2]) if m else None
        if x is None:
            continue
        n = max(len(v), len(x))
        a, b = v + (0,) * (n - len(v)), x + (0,) * (n - len(x))
        if {"~=": a < b, ">=": a < b, ">": a <= b, "<": a >= b, "<=": a > b, "==": a != b,
                "!=": a == b}[m[1]]:
            return True
    return False


def resolve(python: str, reqs: list, constraints: Path, tmp: Path, extra=(), runner=run,
            clock=None, quiet=True):
    """pip's resolver, nothing installed: (returncode, stderr; with quiet=False stdout + stderr,
    where pip prints the conflict's cause)."""
    argv = [python, "-m", "pip", "install", "--dry-run", "--ignore-installed",
            *(["--quiet"] if quiet else []), "--report", str(tmp / "report.json"), *extra, "-c",
            str(constraints), *reqs]
    r = (clock or Clock()).call(runner, argv)
    return r.returncode, r.stderr if quiet else (r.stdout or "") + (r.stderr or "")


def check_constraints(lhpc: Path, manifest_text: str, moved, runner=run, python=PYTHON,
                      clock=None) -> str:
    """B. `moved` = the findings that move (key = source path, candidate, remote). Returns the
    summary line; raises CheckFailed on a conflict or on any failure to judge."""
    by_path = {f.key: f for f in moved}
    todo = [g for g in governed(manifest_text) if g.checkout in by_path]
    if not todo:
        return "Constraints check: no moved pin is installed against a constraints file."
    clock = clock or Clock()
    interpreter(python, runner, clock)
    lines = []
    for g in todo:
        f = by_path[g.checkout]
        with tempfile.TemporaryDirectory(prefix="lhpc-constraints-") as t:
            tmp, co = Path(t), Path(t) / "checkout"
            for argv in (["git", "init", "-q", str(co)],
                         ["git", "-C", str(co), "fetch", "-q", "--depth", "1", f.remote,
                          f.candidate],
                         ["git", "-C", str(co), "checkout", "-q", "FETCH_HEAD"]):
                r = clock.call(runner, argv)
                if r.returncode != 0:
                    raise CheckFailed(f"`{g.checkout}` {f.candidate[:9]} could not be fetched to "
                                      "check it against its constraints",
                                      "Re-run; if it persists, hold the pin.",
                                      fenced(r.stderr, CONFLICT_MAX))
            reqs = declared(co / g.subdir if g.subdir else co, g.names,
                            f"`{g.checkout}` {f.candidate[:9]}")
            venv = tmp / "venv"
            r = clock.call(runner, [python, "-m", "venv", str(venv)])
            if r.returncode != 0:
                raise CheckFailed("a scratch venv could not be created", "Re-run.",
                                  fenced(r.stderr, CONFLICT_MAX))
            cfile = lhpc / "lhpc" / "data" / g.constraints
            code, err = resolve(str(venv / "bin" / "python"), reqs, cfile, tmp, runner=runner,
                                clock=clock)
            cause = None
            if code != 0 and "ResolutionImpossible" in err:   # once more without --quiet, for the
                _, out = resolve(str(venv / "bin" / "python"), reqs, cfile, tmp, runner=runner,
                                 clock=clock, quiet=False)   # cause, while the scratch venv exists
                cause, err = _conflict(out), out or err
        if code == 0:
            lines.append(f"`{g.checkout}` {f.candidate[:9]}: fits {g.constraints}")
            continue
        remedy = (f"On `dev`, regenerate `{g.constraints}` for the new commit (its header "
                  f"procedure) and release it, or hold `{g.checkout}`. Nothing was pushed.")
        if cause:
            req, through, pin = cause
            raise CheckFailed(f"{g.component} {f.candidate[:9]} needs {req}"
                              f"{f' (through {through})' if through else ''} but "
                              f"{g.constraints} pins {pin}", remedy, fenced(err, CONFLICT_MAX))
        raise CheckFailed(f"`{g.checkout}` {f.candidate[:9]} could not be resolved against "
                          f"{g.constraints}", remedy, fenced(err, CONFLICT_MAX))
    return "Constraints check:\n" + "\n".join(f"- {ln}" for ln in lines)
