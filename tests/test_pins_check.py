"""LHPC's own Python pins, checked in `prepare` (bot/pins_check.py, PLAN-bot-lockregen-NOTE v7).

B (finding 138): a moved checkout installed against `{asset}/<name>-constraints.txt` is resolved
against that file with pip's own resolver before anything is pushed. The resolver itself is real
here: pip with `--no-index --find-links` over wheels built in the test, so no network.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot import pins_check as pc

SHA = "c" * 40

MANIFEST = '''
[[stack]]
id = "meshcore"

  [[stack.component]]
  id = "cli"
    build_steps = [
      {{ argv = [".venv/bin/pip", "install", "--prefer-binary", "-c", "{{asset}}/cli-constraints.txt", "."] }},
    ]
    [stack.component.source]
    path = "src/cli"
    pin_commit = "{a}"
    remote = "https://example.invalid/cli.git"

  [[stack.component]]
  id = "webui"
    build_steps = [
      {{ argv = ["backend/.venv/bin/pip", "install", "-c", "{{asset}}/webui-constraints.txt", "./backend"] }},
    ]
    [stack.component.source]
    path = "src/webui"
    pin_commit = "{a}"
    remote = "https://example.invalid/webui.git"

  [[stack.component]]
  id = "node"
    build_steps = [
      {{ argv = [".venv/bin/pip", "install", "."] }},
      {{ argv = [".venv/bin/pip", "install", "-c", "{{asset}}/repeater-constraints.txt", "pyyaml", "psutil"] }},
      {{ argv = [".venv/bin/pip", "install", "--no-deps", "--no-build-isolation", "{{runtime}}/src/repeater"] }},
    ]
    [stack.component.source]
    path = "src/core"
    pin_commit = "{a}"
    remote = "https://example.invalid/core.git"

  [[stack.component]]
  id = "repeater-src"
    [stack.component.source]
    path = "src/repeater"
    pin_commit = "{a}"
    remote = "https://example.invalid/repeater.git"

  [[stack.component]]
  id = "plain"
  build_steps = [ {{ argv = [".venv/bin/pip", "install", "."] }} ]
    [stack.component.source]
    path = "src/plain"
    pin_commit = "{a}"
    remote = "https://example.invalid/plain.git"
'''.format(a="a" * 40)


def _moved(*paths):
    return [SimpleNamespace(key=p, candidate=SHA, remote=f"https://example.invalid/{p}.git")
            for p in paths]


# ---- which checkouts a constraints file governs (read from the manifest) -----------------------

def test_the_governed_checkouts_are_read_from_the_manifest():
    got = {(g.component, g.checkout, g.subdir, g.names, g.constraints)
           for g in pc.governed(MANIFEST)}
    assert got == {
        ("cli", "src/cli", "", (), "cli-constraints.txt"),
        ("webui", "src/webui", "backend", (), "webui-constraints.txt"),
        # a named list governs its component's own source AND the checkout the component
        # installs from {runtime}/src (the repeater, `--no-deps` beside it)
        ("node", "src/core", "", ("pyyaml", "psutil"), "repeater-constraints.txt"),
        ("node", "src/repeater", "", ("pyyaml", "psutil"), "repeater-constraints.txt"),
    }


# ---- what a checkout declares (statically) --------------------------------------------------

def test_pep621_dependencies_minus_direct_urls(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["meshcore >= 2.3.15", '
        '"core @ git+https://example.invalid/core.git@dev ; sys_platform == \'linux\'", '
        '"pyyaml>=6 ; python_version >= \'3.11\'"]\n')
    (tmp_path / "requirements.txt").write_text("ignored==1\n")
    assert pc.declared(tmp_path, ()) == ["meshcore >= 2.3.15",
                                         "pyyaml>=6 ; python_version >= '3.11'"]


def test_requirements_txt_when_there_is_no_project_table_and_a_named_list_restricts(tmp_path):
    (tmp_path / "setup.py").write_text("from cx_Freeze import setup\n")   # no deps declared here
    (tmp_path / "requirements.txt").write_text(
        "# the app\naiohttp>=3.13.3\ncx_freeze>=7.0.0\nPeewee>=3.18.1,<4.0.0\n")
    assert pc.declared(tmp_path, ("aiohttp", "peewee", "rns")) == [
        "aiohttp>=3.13.3", "Peewee>=3.18.1,<4.0.0", "rns"]


@pytest.mark.parametrize("bad", [
    ("pyproject.toml", b'[project\nname = "x"\n'),                                # not TOML
    ("pyproject.toml", b'[project]\ndependencies = "meshcore>=2"\n'),             # not a list
    ("pyproject.toml", b"\xff\xfe not text"),                                     # not UTF-8
    ("requirements.txt", b"\xff\xfe not text"),
], ids=["toml", "not-a-list", "pyproject-bytes", "requirements-bytes"])
def test_unreadable_metadata_is_the_checks_own_failure(tmp_path, bad):
    (tmp_path / bad[0]).write_bytes(bad[1])
    with pytest.raises(pc.CheckFailed, match="`src/x` cccc"):
        pc.declared(tmp_path, (), "`src/x` cccc")


@pytest.mark.parametrize("line", ["-r floor.txt", "-rfloor.txt", "--requirement=floor.txt", "-c pins.txt",
                                  "-cpins.txt", "--requiremen=floor.txt", "--req floor.txt",
                                  "--constr=pins.txt", "-e .", "--index-ur=https://x.invalid"])
def test_an_unread_option_line_is_the_checks_own_failure_not_dropped(tmp_path, line):
    # W8/W9 F1: an include's floors would be skipped, so the check could pass unread; pip also
    # takes an unambiguous prefix of a long option, so only listed full spellings are ignored
    (tmp_path / "requirements.txt").write_text(f"aiohttp>=3.13.3\n{line}\n")
    (tmp_path / "floor.txt").write_text("fixture-core>=2.0\n")
    with pytest.raises(pc.CheckFailed, match=r"has an option line this check does not read \("
                                             + re.escape(line) + r"\)"):
        pc.declared(tmp_path, ())


def test_listed_index_options_are_not_requirements(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "--index-url https://x.invalid/simple\n--extra-index-url=https://y.invalid\n--pre\n"
        "aiohttp>=3.13.3\n")
    assert pc.declared(tmp_path, ()) == ["aiohttp>=3.13.3"]


@pytest.mark.parametrize("req,pin,excludes", [
    ("fixture-core>=2.0", "fixture-core==1.9", True),
    ("fixture-core>=1.0", "fixture-core==1.9", False),
    ("fixture-core>=1.9.0", "fixture-core==1.9", False),
    ("fixture-core[x]>1.0,<1.9", "fixture-core==1.9", True),
    ("fixture-core~=2.0 ; python_version >= '3'", "fixture-core==1.9", True),
    ("fixture-core!=1.9", "fixture-core==1.9", True),
    ("fixture-core==1.*", "fixture-core==1.9", False),            # not proven: generic stop
    ("fixture-core>=2.0rc1", "fixture-core==1.9", False),
    ("fixture-core>=2.0", "fixture-core==1.9rc1", False),
    ("fixture-core", "fixture-core==1.9", False),
])
def test_a_conflict_is_named_only_when_the_requirement_excludes_the_pin(req, pin, excludes):
    assert pc._excludes(req, pin) is excludes


def test_a_checkout_that_declares_nothing_statically_fails_closed(tmp_path):
    (tmp_path / "setup.py").write_text("setup(install_requires=['x'])\n")
    with pytest.raises(pc.CheckFailed, match="declares no dependencies"):
        pc.declared(tmp_path, ())


# ---- the resolver, for real: pip over local wheels --------------------------------------------

def _wheel(dest: Path, name: str, version: str, requires=()):
    dist = f"{name.replace('-', '_')}-{version}"
    meta = (f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {r}\n" for r in requires))
    path = dest / f"{dist}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{dist}.dist-info/METADATA", meta)
        z.writestr(f"{dist}.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: t\n"
                   "Root-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(f"{dist}.dist-info/RECORD", "")
    return path


class _Box:
    """The seam: git fetches the fixture checkout, the interpreter reports 3.13, the scratch venv
    is a real one, and pip runs for real with `--no-index --find-links` added."""

    def __init__(self, tmp: Path, checkout: Path, version="3.13.5 (main)", fetch_ok=True):
        self.wheels, self.checkout, self.version, self.fetch_ok = tmp / "wheels", checkout, \
            version, fetch_ok
        self.wheels.mkdir(exist_ok=True)
        self.calls = []

    def __call__(self, argv, cwd=None, timeout=900):
        self.calls.append(list(argv))
        ok = subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:2] == [pc.PYTHON, "-c"]:
            return subprocess.CompletedProcess(argv, 0, f"/usr/bin/python3.13\n{self.version}\n", "")
        if argv[0] == "git":
            if "fetch" in argv and not self.fetch_ok:
                return subprocess.CompletedProcess(argv, 128, "", "fatal: unable to access")
            if "checkout" in argv:
                co = Path(argv[2])
                co.mkdir(parents=True, exist_ok=True)
                for f in self.checkout.iterdir():
                    (co / f.name).write_bytes(f.read_bytes())
            return ok
        if argv[:3] == [pc.PYTHON, "-m", "venv"]:
            return pc.run([sys.executable, "-m", "venv", "--without-pip", argv[3]])
        if "--dry-run" in argv:            # real pip, offline, from the test's interpreter
            # the scratch venv's python must still be on disk when the check calls it (lab r5:
            # the verbose re-run ran after its TemporaryDirectory was gone)
            assert Path(argv[0]).exists(), f"the scratch venv is gone: {argv[0]}"
            i = argv.index("-c")
            return pc.run([sys.executable, *argv[1:i], "--no-index", "--find-links",
                           str(self.wheels), "--disable-pip-version-check", *argv[i:]])
        raise AssertionError(f"unexpected argv {argv}")


def _lhpc(tmp: Path, pin: str) -> Path:
    data = tmp / "lhpc" / "lhpc" / "data"
    data.mkdir(parents=True)
    (data / "cli-constraints.txt").write_text(f"# pinned\nfixture-core=={pin}\n")
    return tmp / "lhpc"


def _checkout(tmp: Path) -> Path:
    co = tmp / "fixture-checkout"
    co.mkdir()
    (co / "pyproject.toml").write_text(
        '[project]\nname = "fixture-cli"\ndependencies = ["fixture-core>=2.0"]\n')
    return co


@pytest.mark.parametrize("pin,stops", [("1.9", True), ("2.0", False)])
def test_a_raised_floor_stops_naming_the_requirement_and_the_pin(tmp_path, pin, stops):
    box = _Box(tmp_path, _checkout(tmp_path))
    for v in ("1.9", "2.0"):
        _wheel(box.wheels, "fixture-core", v)
    lhpc = _lhpc(tmp_path, pin)
    if stops:
        with pytest.raises(pc.CheckFailed) as exc:
            pc.check_constraints(lhpc, MANIFEST, _moved("src/cli"), runner=box)
        assert exc.value.observed == (f"cli {SHA[:9]} needs fixture-core>=2.0 but "
                                      "cli-constraints.txt pins fixture-core==1.9")
        assert "ResolutionImpossible" in exc.value.detail
        assert "hold `src/cli`" in exc.value.next_action
    else:
        line = pc.check_constraints(lhpc, MANIFEST, _moved("src/cli"), runner=box)
        assert f"`src/cli` {SHA[:9]}: fits cli-constraints.txt" in line
    assert (lhpc / "lhpc" / "data" / "cli-constraints.txt").read_text() == \
        f"# pinned\nfixture-core=={pin}\n"                      # never written


def test_a_transitive_conflict_names_the_real_requirement_and_its_pin(tmp_path):
    # W8 F2: with --quiet pip names only its target ("Cannot install fixture-mid==1.0"); the cause
    # is read from one more run without --quiet
    co = tmp_path / "fixture-checkout"
    co.mkdir()
    (co / "pyproject.toml").write_text(
        '[project]\nname = "fixture-cli"\ndependencies = ["fixture-mid>=1.0"]\n')
    box = _Box(tmp_path, co)
    for v in ("1.9", "2.0"):
        _wheel(box.wheels, "fixture-core", v)
    _wheel(box.wheels, "fixture-mid", "1.0", ["fixture-core>=2.0"])
    with pytest.raises(pc.CheckFailed) as exc:
        pc.check_constraints(_lhpc(tmp_path, "1.9"), MANIFEST, _moved("src/cli"), runner=box)
    assert exc.value.observed == (f"cli {SHA[:9]} needs fixture-core>=2.0 (through fixture-mid "
                                  "1.0) but cli-constraints.txt pins fixture-core==1.9")
    runs = [a for a in box.calls if "--dry-run" in a]
    assert len(runs) == 2 and "--quiet" in runs[0] and "--quiet" not in runs[1]


def test_a_compatible_requirement_listed_first_is_not_named_as_the_conflict(tmp_path):
    # W9 F2: pip lists the direct fixture-core>=1.0 before the transitive >=2.0; only the one that
    # excludes the pin is named
    co = tmp_path / "fixture-checkout"
    co.mkdir()
    (co / "pyproject.toml").write_text('[project]\nname = "fixture-cli"\n'
                                       'dependencies = ["fixture-core>=1.0", "fixture-mid>=1.0"]\n')
    box = _Box(tmp_path, co)
    for v in ("1.9", "2.0"):
        _wheel(box.wheels, "fixture-core", v)
    _wheel(box.wheels, "fixture-mid", "1.0", ["fixture-core>=2.0"])
    with pytest.raises(pc.CheckFailed) as exc:
        pc.check_constraints(_lhpc(tmp_path, "1.9"), MANIFEST, _moved("src/cli"), runner=box)
    assert "The user requested fixture-core>=1.0" in exc.value.detail
    assert exc.value.observed == (f"cli {SHA[:9]} needs fixture-core>=2.0 (through fixture-mid "
                                  "1.0) but cli-constraints.txt pins fixture-core==1.9")


def test_no_provable_pair_gives_the_generic_stop():
    out = ("ERROR: ResolutionImpossible\nThe conflict is caused by:\n"
           "    The user requested fixture-core>=1.0\n"
           "    fixture-mid 1.0 depends on fixture-core==2.*\n"
           "    The user requested (constraint) fixture-core==1.9\n\n")
    assert pc._conflict(out) is None


def test_an_abbreviated_include_with_a_conflicting_floor_stops_before_pip(tmp_path):
    # W9 F1, the auditor's case: pip reads `--requiremen=floor.txt` and fails on fixture-core>=2.0
    co = tmp_path / "fixture-checkout"
    co.mkdir()
    (co / "requirements.txt").write_text("fixture-core>=1.0\n--requiremen=floor.txt\n")
    (co / "floor.txt").write_text("fixture-core>=2.0\n")
    box = _Box(tmp_path, co)
    for v in ("1.9", "2.0"):
        _wheel(box.wheels, "fixture-core", v)
    with pytest.raises(pc.CheckFailed, match=r"option line this check does not read "
                                             r"\(--requiremen=floor.txt\)"):
        pc.check_constraints(_lhpc(tmp_path, "1.9"), MANIFEST, _moved("src/cli"), runner=box)
    assert not [c for c in box.calls if "--dry-run" in c]


def test_the_resolve_argv_and_what_is_not_resolved(tmp_path):
    box = _Box(tmp_path, _checkout(tmp_path))
    _wheel(box.wheels, "fixture-core", "2.0")
    lhpc = _lhpc(tmp_path, "2.0")
    pc.check_constraints(lhpc, MANIFEST, _moved("src/cli", "src/plain", "extra.graywolf"),
                         runner=box)
    pips = [c for c in box.calls if "--dry-run" in c]
    assert len(pips) == 1                       # src/plain has no constraints step; extra.* none
    venv_python = pips[0][0]
    assert venv_python.endswith("/venv/bin/python") and not venv_python.startswith(str(lhpc))
    report = pips[0][pips[0].index("--report") + 1]
    assert pips[0][1:] == ["-m", "pip", "install", "--dry-run", "--ignore-installed", "--quiet",
                           "--report", report, "-c",
                           str(lhpc / "lhpc" / "data" / "cli-constraints.txt"),
                           "fixture-core>=2.0"]
    assert not report.startswith(str(lhpc))     # nothing is written into the checkout
    fetch = next(c for c in box.calls if "fetch" in c)
    assert fetch[-2:] == ["https://example.invalid/src/cli.git", SHA]
    assert next(c for c in box.calls if "venv" in c)[:3] == [pc.PYTHON, "-m", "venv"]


def test_nothing_moved_under_a_constraints_file_runs_nothing(tmp_path):
    box = _Box(tmp_path, _checkout(tmp_path))
    line = pc.check_constraints(_lhpc(tmp_path, "2.0"), MANIFEST, _moved("src/plain"), runner=box)
    assert box.calls == [] and "no moved pin" in line


@pytest.mark.parametrize("what", ["fetch", "interpreter", "no-declared-deps"])
def test_a_check_that_cannot_judge_fails_closed(tmp_path, what):
    co = _checkout(tmp_path)
    if what == "no-declared-deps":
        (co / "pyproject.toml").write_text('[project]\nname = "x"\ndynamic = ["dependencies"]\n')
    box = _Box(tmp_path, co, fetch_ok=what != "fetch",
               version="3.11.9 (main)" if what == "interpreter" else "3.13.5 (main)")
    with pytest.raises(pc.CheckFailed):
        pc.check_constraints(_lhpc(tmp_path, "2.0"), MANIFEST, _moved("src/cli"), runner=box)
    assert not [c for c in box.calls if "--dry-run" in c]


# ---- in the plan: a failed check stops `prepare` before anything is pushed ----------------

class _PlanCtx:
    """What `stage_plan` reaches for up to `prepare`, in `full` mode."""
    token, mode, retry_of, run_id = "t" * 20, "full", "", "5000"

    def __init__(self, lhpc: Path):
        self.lhpc, self.summaries, self.saved, self.outs = lhpc, [], [], []
        self.gh = self.bot_gh = self

    def whoami(self):
        return {"login": "bot"}

    def token_expiry(self):
        return ""

    def get(self, path):
        return {}

    def ref(self, repo, ref):
        return "d" * 40

    def open_attempts(self):
        return []

    def open_issues(self, repo, label):
        return []

    def clone(self, repo, ref=""):
        return self.lhpc

    def summary(self, text):
        self.summaries.append(text)

    def out(self, **kv):
        self.outs.append(kv)

    def save_attempt(self, number, att):
        self.saved.append(att)
        return 1


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _plan_ctx(tmp: Path, monkeypatch):
    """An LHPC checkout and a full-mode ctx that reach `prepare` with `src/cli` moved."""
    from bot import cli
    from bot import upstream as up
    lhpc = tmp / "lhpc"
    (lhpc / "lhpc" / "data").mkdir(parents=True)
    (lhpc / "tools").mkdir()
    (lhpc / cli.MANIFEST).write_text(MANIFEST)
    (lhpc / "tools" / "manifest_pin.py").write_text("")
    (lhpc / "pyproject.toml").write_text('[project]\nname = "lhpc"\nversion = "0.12.10"\n')
    (lhpc / "lhpc" / "version.py").write_text('__version__ = "0.12.10"\n')
    (lhpc / "CHANGELOG.md").write_text("# Changelog\n\n## 0.12.10\n\n- x\n")
    _git("init", "-q", cwd=lhpc)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base",
         cwd=lhpc)
    moved = up.Finding(key="src/cli", track="branch", status="move", current="a" * 40,
                       candidate=SHA, remote="https://example.invalid/cli.git")
    monkeypatch.setattr(cli, "_findings", lambda ctx, text, policy: ([moved], {}))
    monkeypatch.setattr(cli, "_check_parent", lambda ctx, frozen: None)
    monkeypatch.setattr(cli, "_claim_the_retry", lambda ctx: None)
    return lhpc, _PlanCtx(lhpc)


@pytest.mark.parametrize("which", ["check_lock", "check_constraints"])
def test_a_failed_check_stops_prepare_with_nothing_pushed_or_saved(tmp_path, monkeypatch, which):
    from bot import cli
    lhpc, ctx = _plan_ctx(tmp_path, monkeypatch)
    seen = []

    def failing(lhpc_, *args, **kw):
        seen.append(args)
        raise pc.CheckFailed("cli c… needs x>=2 but cli-constraints.txt pins x==1", "hold it",
                             "```\nERROR: ResolutionImpossible\n```")
    monkeypatch.setattr(pc, which, failing)
    with pytest.raises(cli.Stop) as stop:
        cli.stage_plan(ctx)
    assert stop.value.stage == "prepare" and "pins x==1" in stop.value.observed
    assert "ResolutionImpossible" in stop.value.detail
    assert any("ResolutionImpossible" in s for s in ctx.summaries)
    if which == "check_constraints":
        assert [f.key for f in seen[0][1]] == ["src/cli"]    # the EDITED manifest's moves
    assert len(seen) == 1
    assert ctx.saved == []                                    # no attempt
    branches = subprocess.run(["git", "branch", "--list", "pins/*"], cwd=lhpc,
                              capture_output=True, text=True, check=True).stdout
    assert branches == ""                                     # no candidate branch


# ---- bounded: a hung call is the check's own Stop, never an escape -------------------------

def _hanging(tmp: Path):
    """A process that blocks until something writes to its FIFO (nothing does)."""
    fifo = tmp / "never"
    os.mkfifo(fifo)
    return [sys.executable, "-c", f"open({str(fifo)!r}).read()"]


def test_a_call_past_its_bound_is_a_failed_call_not_an_exception(tmp_path):
    r = pc.run(_hanging(tmp_path), timeout=0.5)
    assert r.returncode == 124 and "timed out after 0 s" in r.stderr  # 0.5 printed as "0"


def test_a_program_that_cannot_start_or_prints_bytes_is_a_failed_call_not_an_exception(tmp_path):
    # W8 F3: only TimeoutExpired was caught; FileNotFoundError and UnicodeDecodeError escaped
    r = pc.run([str(tmp_path / "no-such-python3.13"), "-c", "pass"])
    assert r.returncode == 127 and "could not be started" in r.stderr
    r = pc.run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([0xff, 0xfe]))"])
    assert r.returncode == 0 and isinstance(r.stdout, str)
    with pytest.raises(pc.CheckFailed):
        pc.check_constraints(_lhpc(tmp_path, "2.0"), MANIFEST, _moved("src/cli"),
                             python=str(tmp_path / "no-such-python3.13"))


def test_a_spent_bound_starts_nothing():
    calls = []
    r = pc.Clock(seconds=0).call(lambda *a, **k: calls.append(a), ["git", "fetch"])
    assert r.returncode == 124 and "bound is spent" in r.stderr and calls == []


def test_a_hung_resolve_stops_the_check(tmp_path):
    box = _Box(tmp_path, _checkout(tmp_path))
    hang = _hanging(tmp_path)

    def runner(argv, cwd=None, timeout=900):
        if "--dry-run" in argv:
            return pc.run(hang, timeout=min(timeout, 0.5))
        return box(argv, cwd=cwd, timeout=timeout)
    with pytest.raises(pc.CheckFailed) as exc:
        pc.check_constraints(_lhpc(tmp_path, "2.0"), MANIFEST, _moved("src/cli"), runner=runner)
    assert "could not be resolved" in exc.value.observed and "timed out" in exc.value.detail



def test_malformed_fetched_metadata_stops_prepare_not_the_catch_all(tmp_path, monkeypatch):
    # Every failure of a check is its own Stop at `prepare`, never main()'s "attempt left open".
    from bot import cli
    co = _checkout(tmp_path)
    (co / "pyproject.toml").write_text('[project\ndependencies = ["fixture-core>=2.0"]\n')
    box = _Box(tmp_path, co)
    real = pc.check_constraints
    monkeypatch.setattr(pc, "check_constraints",
                        lambda lhpc_, text, moved_, **kw: real(lhpc_, text, moved_, runner=box))
    lhpc, ctx = _plan_ctx(tmp_path / "plan", monkeypatch)
    (lhpc / "lhpc" / "data" / "cli-constraints.txt").write_text("fixture-core==2.0\n")
    with pytest.raises(cli.Stop) as stop:
        cli.stage_plan(ctx)
    assert stop.value.stage == "prepare" and "pyproject.toml is not valid TOML" in stop.value.observed
    assert ctx.saved == []

# ---- A: requirements.lock compared by content ------------------------------------------------

H1, H2, H3 = ("sha256:" + c * 64 for c in "123")
LOCK = f"""# LHPC's runtime dependencies (a header the bot never writes)
flask==3.1.3 \\
    --hash={H1} \\
    --hash={H2}
setuptools==84.0.0 \\
    --hash={H3}
tomli==2.2.1 ; python_version < "3.11" \\
    --hash={H1}
"""
# what pip-tools writes for the same content: no header, the build backend in its own section
COMPILED = f"""flask==3.1.3 \\
    --hash={H2} \\
    --hash={H1}
tomli==2.2.1 ; python_version < '3.11' \\
    --hash={H1}

# The following packages are considered to be unsafe in a requirements file:
setuptools==84.0.0 \\
    --hash={H3}
"""


class _Compile:
    """The seam for A: the interpreter reports itself, and `piptools compile` writes `produce`
    into its `--output-file` (an empty `produce` = the compile fails)."""

    def __init__(self, produce: str, version="3.13.5 (main)"):
        self.produce, self.version, self.calls = produce, version, []

    def __call__(self, argv, cwd=None, timeout=900):
        self.calls.append(list(argv))
        if argv[:2] == [pc.PYTHON, "-c"]:
            return subprocess.CompletedProcess(argv, 0, f"/usr/bin/python3.13\n{self.version}\n", "")
        if "compile" in argv:
            if not self.produce:
                return subprocess.CompletedProcess(argv, 1, "", "pip._internal… no matching dist")
            Path(argv[argv.index("--output-file") + 1]).write_text(self.produce)
        return subprocess.CompletedProcess(argv, 0, "", "")


def _with_lock(tmp: Path, text: str) -> Path:
    lhpc = tmp / "lhpc"
    lhpc.mkdir()
    (lhpc / "requirements.lock").write_text(text)
    (lhpc / "pyproject.toml").write_text('[project]\nname = "lhpc"\n')
    return lhpc


def test_header_order_and_quote_style_are_layout_not_content(tmp_path):
    box = _Compile(COMPILED)
    line = pc.check_lock(_with_lock(tmp_path, LOCK), runner=box)
    assert line == "requirements.lock is current (compiled with /usr/bin/python3.13, Python 3.13.5)."


@pytest.mark.parametrize("change", [
    ("tomli==2.2.1 ; python_version < '3.11'", "tomli==2.2.1 ; python_version < '3.12'"),  # marker
    ("flask==3.1.3", "flask==3.1.4"),                                                      # version
    (f"--hash={H2}", f"--hash={H3}"),                                                       # hash
], ids=["marker-only", "version", "hash"])
def test_a_content_change_stops_with_the_normalized_diff(tmp_path, change):
    lhpc = _with_lock(tmp_path, LOCK)
    with pytest.raises(pc.CheckFailed) as exc:
        pc.check_lock(lhpc, runner=_Compile(COMPILED.replace(*change)))
    assert exc.value.observed == "requirements.lock on main is not what its pyproject resolves to"
    assert "--- requirements.lock (main)" in exc.value.detail
    assert "+++ requirements.lock (regenerated)" in exc.value.detail
    assert (lhpc / "requirements.lock").read_text() == LOCK      # never written


def test_the_compile_argv_runs_outside_the_checkout_on_3_13(tmp_path):
    lhpc = _with_lock(tmp_path, LOCK)
    box = _Compile(COMPILED)
    pc.check_lock(lhpc, runner=box)
    venv, install, compile_ = box.calls[1:]
    assert venv[:3] == [pc.PYTHON, "-m", "venv"] and not venv[3].startswith(str(lhpc))
    vpy = str(Path(venv[3]) / "bin" / "python")
    assert install == [vpy, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                       "pip==24.2", "pip-tools==7.4.1"]
    out = compile_[compile_.index("--output-file") + 1]
    assert compile_ == [vpy, "-m", "piptools", "compile", "--generate-hashes",
                        "--no-reuse-hashes", "--allow-unsafe",
                        "--strip-extras", "--no-header", "--no-annotate", "--no-emit-index-url",
                        "--build-deps-for", "editable", "--output-file", out,
                        str(lhpc / "pyproject.toml")]
    assert not out.startswith(str(lhpc))


@pytest.mark.parametrize("what", ["interpreter-3.11", "compile-fails"])
def test_a_lock_check_that_cannot_judge_stops(tmp_path, what):
    box = _Compile("" if what == "compile-fails" else COMPILED,
                   version="3.11.9 (main)" if what == "interpreter-3.11" else "3.13.5 (main)")
    with pytest.raises(pc.CheckFailed):
        pc.check_lock(_with_lock(tmp_path, LOCK), runner=box)
    if what == "interpreter-3.11":
        assert len(box.calls) == 1                 # nothing compiled on the wrong interpreter


def test_a_lock_that_is_not_text_is_the_checks_own_failure(tmp_path):
    lhpc = _with_lock(tmp_path, "")
    (lhpc / "requirements.lock").write_bytes(b"\xff\xfe")
    box = _Compile(COMPILED)
    with pytest.raises(pc.CheckFailed, match="requirements.lock cannot be read"):
        pc.check_lock(lhpc, runner=box)
    assert not [c for c in box.calls if "compile" in c]


def test_no_lock_on_main_yet_is_a_skip_with_a_line(tmp_path):
    box = _Compile(COMPILED)
    assert "skipped" in pc.check_lock(tmp_path, runner=box) and box.calls == []
