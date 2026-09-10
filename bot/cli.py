"""The stages, one subcommand each. `release.yml` runs them in order, one job per stage.

Every stage is written so that the world it leaves behind is described by the attempt issue.
Nothing is inferred from "the job failed, so it cannot have happened": a job can be cancelled
after its write, and a reply can be lost after the server accepted it. Where that matters the
stage reads the remote state back and believes THAT.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import autofreeze as af
from . import changelog as cl
from . import manifest as mf
from . import report as rp
from . import upstream as up
from .attempt import (
    LABEL,
    OPEN_STATES,
    Attempt,
    Unreadable,
    record_of_labelled_issue,
    recovery_decision,
)
from .gh import GitHub, GitHubError
from .redaction import scrub

LHPC = "makrohard/loraham-pi-control"
BIN = "makrohard/lhpc-binaries"
IMG = "makrohard/loraham-images"
BOT = os.environ.get("GITHUB_REPOSITORY", "makrohard/lhpc-release-bot")

CI_WORKFLOW = "ci.yml"
TESTLAB_WORKFLOW = "testlab.yml"
BUILD_WORKFLOW = "build.yml"
IMAGE_WORKFLOW = "build-images.yml"
# The one required job whose red is the EXPECTED shape of a stack regression.
LANE_JOB = "release-verify"


def base_ref() -> str:
    """Which controller ref an attempt is based on. `main` for every real release.

    `LHPC_REF` exists for ONE purpose: the auto-freeze rehearsal, which needs a composition the
    bot can move and break without touching `main` or an upstream default branch. It moves only
    the BASE — the release stage still pushes to `main` and still refuses when `main` is not the
    commit it captured, so a run based on anything else can prove a freeze and can never publish.
    """
    return os.environ.get("LHPC_REF", "").strip() or "main"

RELEASE_WORKFLOW = "release.yml"
MANIFEST = "lhpc/data/manifest.example.toml"
BOT_URL = "https://github.com/" + BOT

# Required jobs on the candidate commit. A skipped, neutral or missing one is NOT proof: the
# release is authorised by an admin-bypass push, so nothing downstream re-checks these.
REQUIRED_CI = ("test (3.11)", "test (3.12)", "test (3.13)", "pin-validation", "meshcore-host")
REQUIRED_TESTLAB = ("testlab", "release-verify")

BOUNDS = {"ci": 40 * 60, "binary": 190 * 60, "testlab": 240 * 60, "image": 330 * 60,
          "settle": 60 * 60}
# The release lane's own case count. A lane that reports fewer has lost cases, whatever its
# colour; the exact names are the lane's contract and are checked individually.
# Where the controller states which lane cases a release requires. Read from the CANDIDATE,
# so the list a release is judged against is the one that commit ships.
RELEASE_CASES_PATH = "testlab/lhpc_testlab/data/required-release-cases.json"


# ---------------------------------------------------------------------------- infrastructure


class Stop(RuntimeError):
    """A refusal with a reason fit to put in an issue."""

    def __init__(self, stage: str, observed: str, next_action: str, detail: str = "",
                 findings=()):
        super().__init__(f"{stage}: {observed}")
        self.stage, self.observed, self.next_action, self.detail = (
            stage, observed, next_action, detail)
        self.findings = list(findings)


def git(*args, cwd=None, check=True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
                       timeout=1800)
    if check and r.returncode != 0:
        # Scrubbed HERE, not at the reporter: the clone URL carries the token, and this message
        # is what the catch-all handler puts into a public issue.
        raise RuntimeError(scrub(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[:500]}"))
    return r.stdout.strip()


class Ctx:
    def __init__(self):
        self.token = os.environ.get("AUTO_RELEASE_TOKEN", "")
        self.bot_token = os.environ.get("GITHUB_TOKEN", "")
        self.gh = GitHub(self.token)
        self.bot_gh = GitHub(self.bot_token or self.token)
        self.mode = os.environ.get("MODE", "full")
        # Set only on the ONE child an automatic freeze dispatches. Its presence is what stops a
        # retry from retrying: a chain that could freeze again would peel stacks off one at a
        # time until something passed, which is not a release anybody asked for.
        self.retry_of = os.environ.get("RETRY_OF", "")
        # The incident this run must claim and report back to. Passed by the parent that
        # dispatched it, so a child never has to guess which hold it is answering for.
        self.retry_incident = int(os.environ.get("RETRY_INCIDENT") or 0)
        self.run_id = os.environ.get("GITHUB_RUN_ID", "local")
        self.run_url = (f"https://github.com/{BOT}/actions/runs/{self.run_id}"
                        if self.run_id != "local" else "(local run)")
        # A repair or a recovery works on ANOTHER run's attempt, named on the dispatch.
        self.attempt_id = os.environ.get("ATTEMPT_RUN_ID", "").strip() or self.run_id
        self.work = Path(tempfile.mkdtemp(prefix="release-bot-"))

    # -- the attempt issue is the durable record ------------------------------------------

    def open_attempts(self) -> list:
        """EVERY open attempt record, as (issue number, record).

        An issue that carries a record which cannot be read raises: something wrote it, and
        being unable to say what happened is not the same as nothing having happened. The list
        is complete — a page limit here would let an older unresolved attempt hide behind a
        newer completed one.
        """
        out = []
        for issue in self.bot_gh.open_issues(BOT, LABEL):
            try:
                att = record_of_labelled_issue(issue["number"], issue.get("body", ""))
            except Unreadable as exc:
                raise Unreadable(str(exc)) from None    # the message already names the issue
            out.append((issue["number"], att))
        return out

    def find_attempt(self, run_id: str = "") -> tuple:
        """This run's own attempt (or the one named on the dispatch)."""
        for number, att in self.open_attempts():
            if not run_id or att.run_id == run_id:
                return number, att
        return 0, None

    def save_attempt(self, number: int, att: Attempt) -> int:
        title = f"attempt {att.run_id} — {att.state}"
        if number:
            self.bot_gh.update_issue(BOT, number, title=title, body=att.to_body())
            return number
        return self.bot_gh.create_issue(BOT, title, att.to_body(), [LABEL])["number"]

    def clone(self, repo: str, ref: str = "", token: str = "") -> Path:
        """A checkout of `repo`. `token` names WHICH credential: the release PAT reaches the
        three product repositories and deliberately not this one, so a write to the bot's own
        policy uses the workflow's own `GITHUB_TOKEN` instead."""
        dest = self.work / repo.split("/")[-1]
        if dest.exists():
            return dest
        url = f"https://x-access-token:{token or self.token}@github.com/{repo}.git"
        git("clone", "-q", url, str(dest))
        git("-c", "advice.detachedHead=false", "checkout", "-q", ref or "main", cwd=dest)
        git("config", "user.name", "lhpc-release-bot", cwd=dest)
        git("config", "user.email", "lhpc-release-bot@users.noreply.github.com", cwd=dest)
        return dest

    def record_run(self, repo: str, run_id: int) -> dict:
        """Everything needed later to prove WHICH execution produced a result: a run id alone
        is not enough, because a re-run keeps the id and the jobs endpoint answers for the
        latest attempt."""
        run = self.gh.run(repo, run_id)
        return {"repo": repo, "id": int(run_id), "workflow": run.get("workflow_id"),
                "attempt": run.get("run_attempt", 1), "sha": run.get("head_sha", "")}

    def out(self, **kv) -> None:
        path = os.environ.get("GITHUB_OUTPUT")
        if path:
            with open(path, "a", encoding="utf-8") as fh:
                for k, v in kv.items():
                    fh.write(f"{k}={v}\n")
        for k, v in kv.items():
            print(f"[output] {k}={v}")

    def summary(self, text: str) -> None:
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        text = scrub(text)
        if path:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        print(text)


# ---------------------------------------------------------------------------- stage: plan


def _findings(ctx: Ctx, manifest_text: str, policy: dict) -> tuple:
    sources = mf.pinned_sources(manifest_text)
    gaps = up.policy_gaps(policy, [s.path for s in sources])
    if gaps:
        raise Stop("watch", "policy.toml and the manifest disagree:\n\n"
                   + "\n".join(f"- {g}" for g in gaps),
                   "Add the missing rule (or drop the stale one) in policy.toml, then re-run. "
                   "A pin with no rule is never moved by a rule nobody wrote.")
    remote = up.Remote(ctx.work / "upstream", token=ctx.token)
    found = [up.examine(s, policy["source"][s.path], remote) for s in sources]
    current = {"graywolf": mf.graywolf_version(manifest_text),
               "meshtastic-web": mf.meshtastic_web(manifest_text)[0],
               "meshtastic-cli": mf.meshtastic_cli(manifest_text)}
    for name, rule in policy.get("extra", {}).items():
        found.append(up.examine_extra(name, rule, current.get(name, ""), remote))
    return found, remote


def blocking_attempts(open_attempts, retry_of: str) -> list:
    """Which open attempts stop a new release from starting.

    The ONE retry a hold is owed may pass its OWN parent — that is the work the parent is waiting
    for, and the parent has to stay open to keep the obligation findable. It may not pass any
    other unresolved attempt, and nothing else may pass at all.
    """
    return [(n, a) for n, a in open_attempts
            if a.unresolved and not (retry_of and a.run_id == retry_of)]


def stage_plan(ctx: Ctx) -> int:
    """Check access, refuse an unresolved attempt, read upstream, and (in `full`) push the
    candidate. Everything before the first push happens here, so a run that is going to stop
    stops cheaply."""
    if not ctx.token:
        raise Stop("observe", "AUTO_RELEASE_TOKEN is not set.",
                   "Add the release token as a repository secret of this repo.")
    try:
        who = ctx.gh.whoami().get("login", "?")
    except GitHubError as exc:
        raise Stop("observe", f"the release token cannot authenticate: {exc}",
                   "Rotate AUTO_RELEASE_TOKEN and re-run.") from None
    expiry = ctx.gh.token_expiry()
    budget = _credential_problem(expiry, ctx.mode)
    if budget:
        raise Stop("observe", budget,
                   "Rotate AUTO_RELEASE_TOKEN. Read-only modes (`watch-only`, `dry-run`) run "
                   "regardless — only a run that may publish is refused for want of time to "
                   "finish and, if needed, undo itself.")
    for repo in (LHPC, BIN, IMG):                       # probe, do not assume
        try:
            ctx.gh.get(f"/repos/{repo}/actions/workflows")
        except GitHubError as exc:
            raise Stop("observe", f"the release token cannot reach {repo}: {exc}",
                       "Check the token's repository access and Actions permission.") from None
    print(f"authenticated as {who}; token expiry: {expiry or 'none'}")

    if ctx.mode == "full":
        blocking = blocking_attempts(ctx.open_attempts(), ctx.retry_of)
        if blocking:
            lines = [f"- issue #{n}: attempt {a.run_id}, state `{a.state}`"
                     + (f", still owes {', '.join(a.owes)}" if a.owes else "")
                     for n, a in blocking]
            raise Stop("observe",
                       "an earlier attempt is unresolved:\n\n" + "\n".join(lines),
                       "Finish it (`finish`) or undo it (`recover`) before starting another "
                       "release. Starting one now could make that attempt's image impossible to "
                       "cut, because the image builder resolves `main`.")

    lhpc = ctx.clone(LHPC, base_ref())
    base_sha = git("rev-parse", "HEAD", cwd=lhpc)
    dev_sha = ctx.gh.ref(LHPC, "heads/dev")
    manifest_p = lhpc / MANIFEST
    script_p = lhpc / "lhpc" / "data" / "scripts" / "graywolf-fetch.sh"
    policy = up.load_policy(Path(__file__).resolve().parents[1] / "policy.toml")
    found, remote = _findings(ctx, manifest_p.read_text(), policy)

    faults = [f for f in found if f.status == "fault"]
    moved = [f for f in found if f.moves]
    if faults:
        raise Stop("watch", "an upstream input could not be judged:\n\n"
                   + "\n".join(f"- `{f.key}`: {f.detail}" for f in faults),
                   "Fix the upstream situation (an orphaned pin, a rewritten branch, an "
                   "unreachable remote) or adjust policy.toml, then re-run.",
                   findings=found)

    ctx.summary(rp.summary(found, "No pin has moved" if not moved else
                           f"{len(moved)} pin(s) to move"))
    if ctx.mode == "watch-only":
        ctx.out(proceed="false")
        print("watch-only: reported, nothing else.")
        return 0
    # BEFORE either branch. The no-move path used to return without claiming, so a child that
    # found nothing eligible did real work — it dispatched proof — while the incident still said
    # the retry was unclaimed and a second child could take it.
    # Validate BEFORE claiming. A child that must refuse — the base moved, or the hold it was
    # sent to prove has been thawed — would otherwise consume the one claim the hold is owed and
    # leave the incident with a claim that led nowhere. The claim itself still settles races: it
    # re-reads the incident and stands down if another run got there first.
    _check_parent(ctx, [f for f in found if f.status == "frozen"])
    _claim_the_retry(ctx)

    if not moved:
        # A retry exists BECAUSE a stack was held. With nothing else eligible there is no
        # candidate to build, but the held baseline has still never been proved as a whole — so
        # prove it once, here, and publish nothing: no branch, no binary, no release, no image.
        # Without this the retry returned "nothing to do" and the hold went unverified.
        if ctx.retry_of:
            report_retry_outcome(ctx, "nothing eligible moved; proving the held baseline only")
            verdict, proof = _verify_baseline(ctx, [f for f in found if f.status == "frozen"],
                                              _parent_ref(ctx))
            # Settled on either MEASURED outcome. A retry that proved the held composition still
            # fails has discharged its obligation just as much as one that proved it good — what
            # differs is what a maintainer does next, not who owes the work. `unproven` is
            # neither: nothing was measured, so the obligation stays where it was.
            if verdict != "unproven":
                # No attempt record exists on this path — nothing moved, so none was created —
                # and the dispatch inputs are therefore the only statement of who this retry is.
                # Everywhere a record DOES exist, the record decides; see `_settle_parent`.
                _settle_parent(ctx, Attempt(run_id=ctx.run_id, retry_of=ctx.retry_of),
                               f"held baseline {verdict}", proof=proof)
            if verdict == "failed":
                raise Stop("plan", "the held baseline did not pass.",
                           "Nothing was released. The hold stands; the composition it retains "
                           "is itself failing, so investigate before thawing.")
            if verdict == "unproven":
                raise Stop("plan", "the held baseline could not be proved at all.",
                           "Nothing was released and nothing was measured, so the retry is "
                           "still owed. Settle the parent by hand or re-run it.")
        ctx.out(proceed="false")
        return 0

    version = cl.next_patch(cl.current_version((lhpc / "pyproject.toml").read_text()))
    branch = f"pins/{version}-{ctx.run_id}"

    # ---- the edit -------------------------------------------------------------------------
    text = manifest_p.read_text()
    for f in moved:
        if f.key.startswith("extra."):
            continue
        text = mf.set_pin(text, f.key, f.candidate, f.tag)
    gw = next((f for f in moved if f.key == "extra.graywolf"), None)
    if gw:
        sums = _graywolf_sums(gw.candidate)
        script_p.write_text(mf.add_graywolf_checksums(script_p.read_text(), gw.candidate, sums))
        text = mf.set_graywolf_version(text, gw.current, gw.candidate)
    web = next((f for f in moved if f.key == "extra.meshtastic-web"), None)
    cli = next((f for f in moved if f.key == "extra.meshtastic-cli"), None)
    try:
        if web:
            # The digest is the release's own build.tar, which the fetch script re-checks on
            # every install. Computed here from the artifact itself, never carried over.
            text = mf.set_meshtastic_web(text, web.current, web.candidate,
                                         _meshtastic_web_sha(web.candidate))
        if cli:
            text = mf.set_meshtastic_cli(text, cli.current, cli.candidate)
    except mf.Unreadable as exc:
        # Both moves also write the value LHPC records in the completion marker. A controller
        # that predates `build_inputs` has no such line, and editing only half of the pair would
        # produce a candidate whose manifest LHPC refuses to load.
        raise Stop("plan", f"this manifest cannot carry the move: {exc}",
                   "The controller on `main` predates the recorded build inputs. Release the "
                   "controller change that adds them first; the pin move is then ordinary.")            from None
    manifest_p.write_text(text)

    bullets = cl.pin_bullets(moved)
    (lhpc / "CHANGELOG.md").write_text(
        cl.insert_section((lhpc / "CHANGELOG.md").read_text(), version, bullets))
    (lhpc / "pyproject.toml").write_text(
        cl.set_pyproject_version((lhpc / "pyproject.toml").read_text(), version))
    (lhpc / "lhpc" / "version.py").write_text(
        cl.set_version_module((lhpc / "lhpc" / "version.py").read_text(), version))

    # LHPC's own contract for a pin: the file must still parse and every consumer must agree.
    mf.pinned_sources(manifest_p.read_text())
    check = subprocess.run([sys.executable, "tools/manifest_pin.py", "--list"], cwd=lhpc,
                           capture_output=True, text=True, check=False)
    if check.returncode != 0:
        raise Stop("prepare", f"the edited manifest fails LHPC's own pin contract:\n\n```\n"
                   f"{check.stderr.strip()[:1000]}\n```",
                   "Nothing was pushed. Fix the edit rule in `bot/manifest.py`.")

    if ctx.mode == "dry-run":
        ctx.summary("### Dry run — the diff that would be pushed\n\n```diff\n"
                    + git("diff", cwd=lhpc)[:8000] + "\n```")
        ctx.out(proceed="false")
        return 0

    git("checkout", "-q", "-b", branch, cwd=lhpc)
    git("add", "-A", cwd=lhpc)
    git("commit", "-q", "-m", version, "-m", "\n".join(f"- {b}" for b in bullets), cwd=lhpc)
    candidate = git("rev-parse", "HEAD", cwd=lhpc)

    att = Attempt(run_id=ctx.run_id, state="prepared", version=version, base_sha=base_sha,
                  candidate_sha=candidate, branch=branch, dev_sha=dev_sha,
                  moved_keys=[f.key for f in moved], retry_of=ctx.retry_of,
                  base_ref=base_ref(),
                  notes=[f"moves: {', '.join(f.key for f in moved)}"])
    # The record exists BEFORE the branch is pushed. A push whose reply is lost still happened,
    # and a branch no attempt names is a mutation nothing would ever clean up.
    number = ctx.save_attempt(0, att)
    git("push", "-q", "origin", f"HEAD:refs/heads/{branch}", cwd=lhpc)
    att.runs["ci"] = ctx.record_run(LHPC, ctx.gh.dispatch(LHPC, CI_WORKFLOW, branch))
    ctx.save_attempt(number, att)

    need = binary_rebuilds(mf.binary_stacks(manifest_p.read_text()), moved)
    refusal = rehearsal_publish_refusal(att, need)
    if refusal:
        raise Stop("plan", refusal,
                   "A rehearsal may not publish binaries to the rolling index. Move only pins "
                   "no artifact covers, or run it as an ordinary release from `main`.")
    ctx.out(proceed="true", version=version, candidate=candidate, branch=branch,
            attempt_issue=number, binary_stacks=",".join(need),
            binary_stacks_json=json.dumps(need or ["none"]))
    ctx.summary(f"\nCandidate `{candidate[:9]}` on `{branch}`; binaries to rebuild: "
                f"{', '.join(need) or 'none'}; attempt issue #{number}.")
    return 0


# The wall-clock a publishing run may need, including settling and undoing itself. Derived from
# the release workflow's own job ceilings rather than estimated, because a token that expires
# mid-image leaves a released controller with no image and no credential to repair it — the one
# state this check exists to prevent:
#
#   plan 30 + build 210 x 2 stacks (max-parallel: 1) + prove 300 + release 20 + integrate 20
#   + image 350 + finalize 20 + recover 150  =  1310 min  =  21.8 h
#
# Two stacks, not three: the daemon's sources are all `manual` in policy, so the bot can only
# ever dispatch meshtastic and meshcom. `tests/test_proof.py` re-derives this from the workflow
# and fails if a ceiling is raised without raising this.
MUTATION_BUDGET_H = 22
# One weekly cycle plus a day, so a token that will die before the next scheduled run says so
# while somebody is still watching this one.
NEXT_RUN_DAYS = 8


def _credential_problem(expiry: str, mode: str) -> str:
    """"" when this run may proceed. A publishing run needs enough credential left to finish AND
    to recover; a read-only run needs none of that and is never refused for it."""
    if mode in ("watch-only", "dry-run"):
        return ""
    if not expiry:
        # Absent is not "never expires": it is "not stated". Say so rather than assume.
        print("the release token reports no expiry — treated as unknown, not as unlimited")
        return ""
    import datetime as _dt
    try:
        when = _dt.datetime.strptime(expiry.strip()[:19], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=_dt.UTC)
    except ValueError:
        print(f"the release token's expiry {expiry!r} could not be read — treated as unknown")
        return ""
    left = when - _dt.datetime.now(_dt.UTC)
    if left <= _dt.timedelta(hours=MUTATION_BUDGET_H):
        return (f"the release token expires {expiry} — less than the {MUTATION_BUDGET_H} h a "
                f"publishing run may need to finish and, if it must, undo itself.")
    if left <= _dt.timedelta(days=NEXT_RUN_DAYS):
        print(f"WARNING: the release token expires {expiry}, before the next weekly run")
    return ""


def _meshtastic_web_sha(version: str) -> str:
    """sha256 of that release's own `build.tar` — the exact artifact the box will fetch."""
    import hashlib
    import urllib.request
    url = f"https://github.com/meshtastic/web/releases/download/v{version}/build.tar"
    with urllib.request.urlopen(url, timeout=180) as r:            # noqa: S310 (fixed host)
        digest = hashlib.sha256()
        while chunk := r.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _graywolf_sums(version: str) -> dict:
    """The release's own checksums.txt, which is where every recorded digest comes from."""
    import urllib.request
    url = (f"https://github.com/chrissnell/graywolf/releases/download/v{version}/checksums.txt")
    with urllib.request.urlopen(url, timeout=60) as r:             # noqa: S310 (fixed host)
        text = r.read().decode()
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].endswith(".deb"):
            for arch in ("arm64", "armhf", "amd64"):
                if parts[1] == f"graywolf_{version}_{arch}.deb":
                    out[arch] = parts[0]
    return out


# ---------------------------------------------------------------------------- stage: build


def _verify_baseline(ctx: Ctx, frozen, ref: str) -> tuple:
    """Prove the held baseline once, on ONE named commit, and report. Mutates nothing.

    This is the whole of what a frozen-only retry can honestly do: there is no candidate, so
    there is nothing to release — but "we held a stack and never checked the result" is not an
    outcome anybody should accept either.

    The ref is passed IN, from the parent's own record — not resolved from this run's
    environment. A retry dispatched by hand with some other ref would otherwise prove a
    composition its parent never held, which is the same class of mistake as reading a child's
    publication mode from the environment.

    Bound to a commit, not to a branch name. A branch is mutable: a queued lane could run against
    a different commit and be reported as proof of the composition being held, which is the same
    unbound-evidence mistake the prove stage exists to prevent. The commit is captured first, the
    required-case contract is read AT it, and the run is checked against it by the same identity
    rules — right SHA, right workflow, right attempt, required jobs green.
    """
    held = ", ".join(f.key for f in frozen) or "nothing"
    baseline = ctx.gh.ref(LHPC, f"heads/{ref}")
    if not baseline:
        # UNPROVEN, not failed. "Could not check" and "checked and bad" are different answers,
        # and reporting this one as a failure would tell a maintainer the held composition is
        # broken when nothing was measured at all.
        ctx.summary(f"\nThe held baseline could not be proved: `{ref}` could not be read.")
        return "unproven", {}
    # Dispatched at the REF, bound to the SHA. `workflow_dispatch` resolves a branch or a tag
    # and refuses a bare commit ("No ref found for: …"), which is how this path failed the first
    # time it ever ran: the frozen-only proof could not start at all. Binding is unchanged and
    # still does the real work — the run's own head is compared with the baseline captured
    # above, and the check below refuses a ref that moved while the proof was in flight.
    run_id = ctx.gh.dispatch(LHPC, TESTLAB_WORKFLOW, ref, {"release_verify": "true"})
    rec = ctx.record_run(LHPC, run_id)
    run = ctx.gh.wait(LHPC, run_id, BOUNDS["testlab"])
    at = Attempt(run_id=ctx.run_id, candidate_sha=baseline)   # identity is asked of the commit
    identity, offlane, outcome = _run_problems(ctx, at, "testlab", rec, run, REQUIRED_TESTLAB)
    junit = ctx.gh.artifact_member(LHPC, run_id, "testlab-logs-release-verify",
                                   "junit-release.xml")
    unreadable, red = _release_case_problems(
        junit, required_release_cases(ctx.gh.file_at(LHPC, RELEASE_CASES_PATH, baseline)))
    moved = []
    if ctx.gh.ref(LHPC, f"heads/{ref}") != baseline:
        moved.append(f"`{ref}` moved while the baseline was being proved — the result "
                     f"answers for a commit that is no longer released")
    problems = identity + offlane + outcome + unreadable + red + moved

    # `failed` is reserved for a MEASURED negative, and that takes PRECEDENCE, not a majority
    # vote. Anything saying this evidence cannot be trusted to describe the held composition —
    # a run that is not the one dispatched, a cancelled or timed-out run, a missing or unparsable
    # artifact, no case list, a ref that moved under the proof — makes the answer "could not
    # check", however red the rest of it looks.
    #
    # Reading it as `outcome or red` alone was wrong in exactly the combination that matters: red
    # evidence from an INVALID execution was reported as a measured failure, which says a held
    # composition is broken on the strength of a run that never answered for it, and discharges a
    # retry that measured nothing. Each half had a test; their combination did not.
    uncheckable = identity + unreadable + moved
    measured = bool(outcome or red or offlane) and not uncheckable
    # `unreadable` is in that list ON PURPOSE, and it has a cost worth knowing. A lane that
    # concluded failure but died before uploading its JUnit is red in a way a human would call
    # measured; here it is `unproven`, so the parent stays owing and a person has to settle it.
    # The trade is deliberate: what the lane concluded is not the same as which stack it blamed,
    # and holding an upstream pin is a claim about the second. Paying an occasional manual
    # settlement is cheaper than freezing the wrong project on evidence nobody could read.
    #
    # `offlane` counts as measured HERE and not in `stage_prove`, and the difference is the
    # question being asked. There it is "may this bot name a stack and freeze its pin?", and an
    # ordinary job's red names nobody. Here it is only "does the held composition still pass?",
    # and a required job that ran on this commit and concluded failure answers that: no. This is
    # the live kiss-regression shape — release lane red AND the ordinary `testlab` job red — and
    # calling it `unproven` would leave the parent owing forever on evidence that exists.
    ctx.summary(f"\nNothing eligible moved, so nothing was released. The held baseline "
                f"({held}) was proved at `{baseline[:9]}`: "
                + ("every required case passed." if not problems else
                   ("**it did not pass** — " if measured else
                    "**it could not be measured** — ") + "; ".join(problems[:5]))
                + f"\n\nLane run: {run.get('html_url', run_id)}")
    if not problems:
        return "passed", rec
    return ("failed" if measured else "unproven"), rec


def _check_parent(ctx: Ctx, frozen) -> None:
    """A retry answers for ITS parent's composition, or it answers for nothing.

    Execution identity is checked elsewhere; this is identity RELATIVE to the parent. The child
    reads the parent's own record and refuses if the ground it was sent to prove has moved: a
    different base, or holds that are no longer in the policy it just read. Reporting a green run
    against a composition nobody held would be the worst possible outcome — it reads as proof
    that the held revision is fine.
    """
    if not ctx.retry_of:
        return
    parent = next((a for _n, a in ctx.open_attempts() if a.run_id == ctx.retry_of), None)
    if parent is None:
        # Settled by hand, or closed after its hold was thawed. The hold it was owed no longer
        # exists to prove, and inventing an obligation here would block a legitimate release.
        ctx.summary(f"\nParent attempt {ctx.retry_of} is no longer open; continuing as an "
                    f"ordinary run.")
        return
    if parent.base_sha and parent.base_sha != ctx.gh.ref(LHPC, f"heads/{base_ref()}"):
        raise Stop("plan", f"the controller moved since attempt {ctx.retry_of} was held "
                   f"({parent.base_sha[:9]} -> now something else).",
                   "This retry would prove a composition its parent never held. Settle the "
                   "parent and let the next scheduled run start from the new base.")
    missing = [k for k in parent.frozen if k not in {f.key for f in frozen}]
    if missing:
        raise Stop("plan", "the hold this retry was sent to prove is not in the policy any "
                   f"more: {', '.join(missing)}.",
                   "Somebody thawed it. A run proving a composition nobody holds is not "
                   "evidence; re-run the ordinary release instead.")


def _parent_ref(ctx: Ctx) -> str:
    """The controller ref THIS RETRY'S PARENT was planned from.

    Not this run's environment: a retry dispatched by hand, or re-dispatched with different
    inputs, must still answer for the composition its parent held. Falls back to this run's own
    base when there is no parent to ask — an ordinary run answers for itself.
    """
    if ctx.retry_of:
        parent = next((a for _n, a in ctx.open_attempts() if a.run_id == ctx.retry_of), None)
        if parent is not None:
            return parent.base_ref
    return base_ref()


def _settle_parent(ctx: Ctx, att: Attempt, outcome: str, proof: dict | None = None) -> None:
    """Hand the retry obligation back with its TERMINAL result, and close the parent.

    The claim only says a child took the work. Until this is written the parent still owes a
    retry — deliberately, because a child cancelled straight after claiming must leave the
    obligation with somebody. So this runs when the child's own outcome is known and never at
    claim time, which is the difference between transferring responsibility and dropping it.

    **Identity comes from the child's RECORD, never from this dispatch.** `att.retry_of` names the
    parent and `att.run_id` names the retry, both written when the child was planned. Reading them
    from `ctx` instead made settlement depend on inputs only the automatic dispatch carries: an
    operator running `finish` on that child by hand supplies an attempt id and nothing else, so
    the child closed, this returned at once, and the parent stayed unresolved and blocked every
    later release — with no way to reach it, because `recover` on a parent whose child already
    released refuses on the version it now sees held by a different commit.

    The hold and its incident are untouched: they are lifted by hand, and a settled hold must not
    keep blocking unrelated releases.
    """
    if not att.retry_of:
        return
    number, parent = next(((n, a) for n, a in ctx.open_attempts()
                           if a.run_id == att.retry_of), (0, None))
    if parent is None:
        return                                  # already settled, or settled by hand
    parent.retry_run = att.run_id
    if proof:
        parent.runs["baseline"] = proof
    parent.notes.append(f"retry {att.run_id}: {outcome}")
    ctx.save_attempt(number, parent)
    if parent.unresolved:
        ctx.summary(f"\nParent attempt {att.retry_of} recorded this retry but still owes "
                    f"something; leaving it open.")
        return
    ctx.bot_gh.update_issue(BOT, number, state="closed")
    ctx.summary(f"\nParent attempt {att.retry_of} settled ({outcome}); its hold stands until "
                f"somebody thaws it, and it no longer blocks a release.")


def _claim_the_retry(ctx: Ctx) -> None:
    """A retry claims its incident before it changes anything, and only one may.

    The parent cannot tell a dispatch it never sent from one whose reply it lost, so it does not
    decide: it asks the incident. This is the answer. A second child — a duplicate dispatch, or a
    resume that raced — finds the claim already there and stops before it can put a second
    candidate through the same holds.
    """
    if not (ctx.retry_of and ctx.retry_incident):
        return
    held = ctx.bot_gh.comments(BOT, ctx.retry_incident)
    claim = af.claimed_by(held)
    if claim and claim != ctx.run_id:
        raise Stop("plan", f"run {claim} already claimed this retry.",
                   "Nothing was changed. One hold gets one retry; let that run finish.")
    if not claim:
        ctx.bot_gh.comment(BOT, ctx.retry_incident,
                           f"{af.CLAIM}{ctx.run_id} — retrying with the hold in place "
                           f"({ctx.run_url}).")


def report_retry_outcome(ctx: Ctx, outcome: str, att: Attempt | None = None) -> None:
    """Tell the incident what became of its retry. Every outcome, not only failure: an incident
    that says a retry is owed for ever is as misleading as one that claims a hold it never
    wrote."""
    retry_of = att.retry_of if att else ctx.retry_of
    if not retry_of:
        return
    run_id = att.run_id if att else ctx.run_id
    # EVERYTHING here is suppressed, the lookup included. This runs from the `Stop` and
    # `BaseException` handlers in `main`, so anything raised inside it escapes before the run's
    # own failure is reported — and `open_attempts()` is a live API call that raises by design on
    # a corrupt attempt record. A report that cannot be delivered must stay silent, not replace
    # the diagnosis with its own traceback.
    with contextlib.suppress(Exception):        # never turn a report into the run's own failure
        incident = ctx.retry_incident
        if not incident:
            # A hand-run `finish` carries no retry inputs. The parent's own record names the
            # incident it opened, so the report still reaches the right issue.
            parent = next((a for _n, a in ctx.open_attempts() if a.run_id == retry_of), None)
            incident = parent.incident if parent else 0
        if incident:
            ctx.bot_gh.comment(BOT, incident, f"Retry {run_id}: {outcome}")


def rehearsal_publish_refusal(att: Attempt, need) -> str:
    """Why this attempt may not republish binaries, or `""`.

    A rehearsal proves the FREEZE. Publishing a binary built from a rehearsal composition puts it
    in the rolling index every real box installs from, and a rollback afterwards cannot make that
    exposure not have happened. Said at the plan, before anything is dispatched; the build stage
    refuses on the record as well, because a recovery brings its own inputs.
    """
    if att.rehearsal and need:
        return (f"this attempt is planned from `{att.base_ref}`, and its moves would republish "
                f"{', '.join(need)}.")
    return ""


def stage_build(ctx: Ctx) -> int:
    """Publish ONE candidate binary — the first change to the world outside this bot.

    One stack per job: each has its own time bound, and a failure names exactly one entry. The
    entry this attempt owns is taken from the child's OWN validated fragment, never from
    whatever happens to differ in the live index — another publisher's work must never become
    this attempt's rollback expectation.
    """
    stack = os.environ.get("BINARY_STACK", "").strip()
    if not stack or stack == "none":
        print("no binary-covered pin moved — nothing to publish")
        return 0
    number, att = ctx.find_attempt(ctx.attempt_id)
    if not att:
        raise Stop("build", "this run has no attempt record.", "Re-run from the start.")
    if att.rehearsal:
        # The plan refuses this case before dispatching anything; this is the second lock, on the
        # RECORD rather than on the environment, because a recover or a re-run brings its own
        # inputs and must not be able to reinterpret a rehearsal as an ordinary release.
        raise Stop("build", f"attempt {att.run_id} was planned from `{att.base_ref}`, not `main`.",
                   "A rehearsal never publishes a binary. Nothing was dispatched.")

    if not att.index_snapshot:
        att.index_snapshot = _live_index(ctx)
    # Recorded BEFORE the dispatch: a dispatch whose reply is lost has still started a writer,
    # and recovery must know a publish may exist for this stack.
    if stack not in att.dispatched:
        att.dispatched.append(stack)
    att.state = "mutated"
    ctx.save_attempt(number, att)

    run_id = ctx.gh.dispatch(BIN, BUILD_WORKFLOW, "main",
                             {"stack": stack, "source_commit": "",
                              "lhpc_ref": att.candidate_sha, "smoke_test": "true"})
    att.runs[f"binary:{stack}"] = ctx.record_run(BIN, run_id)
    ctx.save_attempt(number, att)
    run = ctx.gh.wait(BIN, run_id, BOUNDS["binary"])

    entry = _candidate_entry(ctx, run_id, stack, att.candidate_sha)
    if entry:
        att.published[stack] = entry
        ctx.save_attempt(number, att)

    if run.get("timed_out"):
        raise Stop("build", f"the {stack} binary build did not finish within its bound.",
                   "Recovery settles the run before deciding anything; the attempt stays open "
                   "until it can.", detail=run.get("html_url", ""))
    if run.get("conclusion") != "success":
        # A red builder is not by itself an upstream fault: it is just as likely to be the
        # runner, the network, or a cancellation. It attributes only when the build ITSELF says
        # the recipe broke — the same marker the release lane emits, written by the builder at
        # its own compile step and read here, bound to this stack, this run and this candidate.
        att.regression = _builder_regression(ctx, stack, run_id, run, att)
        if att.regression:
            att.evidence = (f"binary build run {run_id} for {stack} on "
                            f"{att.candidate_sha[:9]}")
            ctx.save_attempt(number, att)
        raise Stop("build", f"the {stack} binary build did not succeed "
                   f"({run.get('conclusion')}).",
                   "Recovery restores the index for whatever this attempt published; nothing "
                   "was released.", detail=run.get("html_url", ""))
    if not entry:
        raise Stop("build", f"the {stack} build reported success but published no fragment this "
                   f"attempt can claim.",
                   "Nothing was released. Inspect the publish job before re-running.",
                   detail=run.get("html_url", ""))
    live = _live_index(ctx).get("stacks", {}).get(stack)
    if _canon(live) != _canon(entry):
        raise Stop("build", f"the {stack} entry this build produced is not the live one — "
                   f"somebody published in between.",
                   "Nothing was released. Recovery will report the conflict rather than "
                   "overwrite another publisher's entry.", detail=run.get("html_url", ""))
    ctx.summary(f"published {stack}: {entry.get('sha256', '?')[:12]}")
    return 0


# The two pins that are not commits and ARE recorded in the Meshtastic completion marker, which
# ships inside the published artifact. Moving either one obliges a republish.
_MESHTASTIC = "meshtastic"
_MARKER_RECORDED = ("extra.meshtastic-web", "extra.meshtastic-cli")


def binary_rebuilds(binary_stacks: dict, moved) -> list:
    """Which published binaries this candidate makes stale.

    A moved component pin makes stale every artifact that COVERS it — that is the pins-must-match
    gate's own rule. The Meshtastic web client is the exception that rule cannot see: it is not a
    component pin, so no `covers` set names it, yet it is unpacked into
    `build/tools/meshtasticd/web`, which is a publish root. Left out, the index would go on
    serving an artifact carrying the OLD client while the manifest claimed the new one, and
    nothing would notice — the gate compares component commits, and none of them moved.

    The CLI venv is likewise built on the box and is not in the artifact — but the VALUE is.
    LHPC records both versions in the completion marker, and the artifact ships that marker, so
    an un-republished binary reads "not built" on every box and the reinstall hands back the same
    stale marker. Both moves therefore force the republish.
    """
    moved_components = {c for f in moved for c in f.consumers}
    need = {s for s, covers in binary_stacks.items() if moved_components.intersection(covers)}
    if any(f.key in _MARKER_RECORDED for f in moved):
        # Named, not hard-coded: a renamed stack must fail loudly here rather than quietly stop
        # forcing the republish that keeps every binary box installable.
        if _MESHTASTIC not in binary_stacks:
            raise Stop("plan", f"the manifest has no {_MESHTASTIC!r} binary stack, but a pin "
                               f"recorded in its build marker moved.",
                       "The stack was renamed or dropped. Update the rebuild rule in the bot "
                       "before releasing, or the published artifact goes stale silently.")
        need.add(_MESHTASTIC)
    return sorted(need)


def _canon(entry) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":")) if entry else ""


def unrecorded_dispatches(att) -> list:
    """Stacks a publish was STARTED for whose run id was never written down.

    The record is saved before the dispatch precisely so a lost reply leaves a trace, but the
    trace is only the stack name. Recovery cancels and waits by run id, so for these it would
    cancel nothing, wait for nothing, and then read an index a publisher may still be writing.
    """
    return sorted(s for s in att.dispatched if f"binary:{s}" not in att.runs)


def reconcile(dispatched, ours: dict, live: dict, snapshot: dict) -> tuple:
    """Per stack a publish was started for: (restore, no-op, conflict).

    The whole entry is compared, never a few fields: an entry with the same artifact digest but
    different provenance is a different entry, and treating it as ours would let this attempt
    overwrite somebody else's publication.

      restore   the live entry IS the one this attempt produced
      no-op     the live entry is already the snapshot; there is nothing to undo
      conflict  anything else, INCLUDING a dispatch whose own outcome is unknown — an
                unrecorded publish is not evidence that no publish happened
    """
    restore, noop, conflicts = [], [], []
    for stack in dispatched:
        mine, current = ours.get(stack), live.get(stack)
        if mine and _canon(current) == _canon(mine):
            restore.append(stack)
        elif _canon(current) == _canon(snapshot.get(stack)):
            noop.append(stack)
        else:
            conflicts.append(stack)
    return restore, noop, conflicts


ARTIFACT_NAME = re.compile(r"(?P<stack>[a-z0-9-]+)-(?P<sha>[0-9a-f]{64})\.tar\.zst\Z")


def entry_from_fragment(raw, stack: str, candidate_sha: str):
    """The index entry a build claims to have published, or `None`.

    The fragment comes out of the build container, which is the least trusted thing this bot
    reads: it later becomes the expectation a rollback is judged against, so a fragment that is
    merely well-formed JSON is not enough. It must name THIS stack (present, never defaulted —
    a missing key used to pass as the stack we hoped for), carry a content-addressed filename
    that agrees with its own digest, and say it was built from THIS candidate. Anything else is
    a build whose output this attempt cannot claim.
    """
    try:
        frag = json.loads(raw) if raw else None
    except ValueError:
        return None
    if not isinstance(frag, dict):
        return None
    if frag.pop("stack", None) != stack:
        return None
    name = ARTIFACT_NAME.fullmatch(str(frag.get("filename", "")))
    if not name or name["stack"] != stack or name["sha"] != frag.get("sha256"):
        return None
    if frag.get("lhpc_commit") != candidate_sha:
        return None
    frag["url"] = ("https://github.com/" + BIN + "/releases/download/binaries/"
                   + frag["filename"])
    return frag


def _builder_regression(ctx: Ctx, stack: str, run_id: int, run: dict, att: Attempt) -> list:
    """`[stack]` when THIS builder execution blamed the recipe for THIS candidate, else `[]`.

    Deliberately narrow, and bound at every step. `conclusion == "failure"` only — a cancelled or
    timed-out builder says nothing about upstream. The builder must have written the evidence
    file at its own compile step, naming exactly the stack it was dispatched for. And the
    evidence must answer for THIS execution: a marker alone only says "some meshtastic build
    broke once", which is not grounds to hold an upstream pin. So the run id, the run attempt and
    the controller candidate are compared against what this attempt actually dispatched.

    Anything else is an unclassified failure and gets an ordinary report — the right outcome for
    a runner that died, a registry that was unreachable, or evidence from some other run.
    """
    if run.get("conclusion") != "failure":
        return []
    raw = ctx.gh.artifact_member(BIN, run_id, f"out-{stack}-{run_id}", f"{stack}.regression")
    text = raw.decode("utf-8", "replace") if raw else ""
    if af.attributed_stacks(text) != [stack]:
        # It may only blame the stack it was dispatched for; anything else is a builder that has
        # lost track of what it was building.
        return []
    rec = att.runs.get(f"binary:{stack}") or {}
    # The run GitHub returned must be the execution this attempt started. A re-run keeps the run
    # id while the attempt number changes, so evidence written by an earlier execution would
    # otherwise be read as what a later red one proved. The builder SHA is compared against the
    # BUILDER record — it is the builder repo's head, not the controller candidate.
    for what, got, want in (("workflow", run.get("workflow_id"), rec.get("workflow")),
                            ("run attempt", run.get("run_attempt", 1), rec.get("attempt", 1)),
                            ("builder commit", run.get("head_sha"), rec.get("sha"))):
        if not want:
            # Nothing recorded to compare against. Absence is not agreement: a record this bot
            # cannot check is a record it must not hold an upstream pin on.
            ctx.summary(f"\nignoring {stack} build evidence: this attempt recorded no {what} "
                        f"for the run it dispatched, so the evidence cannot be tied to it")
            return []
        if got != want:
            ctx.summary(f"\nignoring {stack} build evidence: the run GitHub returned has "
                        f"{what} {got}, not the {what} {want} this attempt dispatched")
            return []
    for field, expected in (("builder-run", str(run_id)),
                            ("builder-attempt", str(rec.get("attempt", ""))),
                            ("lhpc-commit", att.candidate_sha)):
        got = _evidence_field(text, field)
        if not expected or got != expected:
            ctx.summary(f"\nignoring {stack} build evidence: {field} is {got or 'absent'}, not "
                        f"{expected or 'anything this attempt can check'} — it does not answer "
                        f"for this execution")
            return []
    return [stack]


def _evidence_field(text: str, field: str) -> str:
    """One `field: value` line of the builder's evidence file, or `""`."""
    for line in text.splitlines():
        head, sep, rest = line.partition(":")
        if sep and head.strip() == field:
            return rest.strip()
    return ""


def _candidate_entry(ctx: Ctx, run_id: int, stack: str, candidate_sha: str):
    """`entry_from_fragment` on the build job's own artifact — the fetch, nothing more."""
    return entry_from_fragment(
        ctx.gh.artifact_member(BIN, run_id, f"out-{stack}-{run_id}", ".frag.json"),
        stack, candidate_sha)


def _live_index(ctx: Ctx) -> dict:
    """The published index, read through the AUTHENTICATED API.

    Not the public download URL: that is served by a CDN which can return the previous bytes
    for a while after a pointer switch, and a rollback decided on stale bytes is a decision
    about the past.
    """
    return json.loads(ctx.gh.release_asset(BIN, "binaries", "index.json"))


# ---------------------------------------------------------------------------- stage: prove


def stage_prove(ctx: Ctx) -> int:
    """Every required job succeeded ON THIS CANDIDATE, and the release lane actually ran its
    cases.

    A job name and a green tick are not proof: the branch is mutable, a run can be re-run, and
    a lane can report success having skipped everything. So each result is bound to the run
    this attempt started, to that run's attempt number, and to the candidate commit — and the
    lane's own JUnit is read for the cases it must have run.
    """
    number, att = ctx.find_attempt(ctx.attempt_id)
    if not att:
        raise Stop("prove", "this run has no attempt record.", "Re-run from the start.")
    testlab = ctx.gh.dispatch(LHPC, TESTLAB_WORKFLOW, att.branch, {"release_verify": "true"})
    att.runs["testlab"] = ctx.record_run(LHPC, testlab)
    ctx.save_attempt(number, att)

    identity, outcome = [], []
    for name, required, bound in (("ci", REQUIRED_CI, BOUNDS["ci"]),
                                  ("testlab", REQUIRED_TESTLAB, BOUNDS["testlab"])):
        rec = att.runs.get(name)
        if not rec:
            identity.append(f"{name}: this attempt never recorded a run")
            continue
        run = ctx.gh.wait(LHPC, int(rec["id"]), bound)
        got_identity, got_offlane, got_outcome = _run_problems(ctx, att, name, rec, run,
                                                                required)
        # A measured red OUTSIDE the release lane disqualifies an attribution exactly as a broken
        # identity does, so it joins the same list here: the lane did not name it, and holding an
        # upstream pin for it would freeze the wrong project.
        identity += got_identity + got_offlane
        # Only the LANE's own outcome may accompany an attribution. A red CI run is a different
        # run answering a different question.
        (outcome if name == "testlab" else identity).extend(got_outcome)
    problems = identity + outcome

    junit = ctx.gh.artifact_member(LHPC, int(att.runs["testlab"]["id"]),
                                   "testlab-logs-release-verify", "junit-release.xml")
    unreadable, red = _release_case_problems(
        junit, required_release_cases(
            ctx.gh.file_at(LHPC, RELEASE_CASES_PATH, att.candidate_sha)))
    # A stack may be named when the lane's cases failed and NOTHING questions the run's identity.
    # The lane's own red conclusion is expected here and does not disqualify it. Evidence this bot
    # could not read never blames an upstream project either, and needs no separate guard: the
    # helper reports EITHER what it could not read OR what it read as red, never both, so `red`
    # is non-empty only when the evidence was readable.
    lane_only = bool(red) and not identity
    problems += unreadable + red

    if problems:
        # Record WHO the lane blamed, before stopping. Acting on it here would be wrong: the
        # index still holds this attempt's binaries, and a hold written before the rollback
        # would describe a composition that does not exist yet. Recovery acts on this.
        att.regression = af.attributed_stacks(_failure_text(junit)) if lane_only else []
        if att.regression:
            unmarked = af.unattributed_failures(_failure_text(junit))
            att.evidence = (f"release lane run {att.runs['testlab']['id']} attempt "
                            f"{att.runs['testlab']['attempt']} on {att.candidate_sha[:9]}"
                            + ("; " + " ".join(f"UNATTRIBUTED-FAILURE {c}" for c in unmarked)
                               if unmarked else ""))
            ctx.save_attempt(number, att)
        raise Stop("prove", "the candidate is not proven:\n\n"
                   + "\n".join(f"- {p}" for p in problems),
                   "Recovery restores whatever this attempt published and deletes the candidate "
                   "branch; nothing was released.",
                   detail="\n".join(str(r.get("id")) for r in att.runs.values()))
    ctx.summary(f"every required job succeeded on `{att.candidate_sha[:9]}`, and the release "
                f"lane ran its cases.")
    return 0


def _run_problems(ctx: Ctx, att: Attempt, name: str, rec: dict, run: dict,
                  required) -> tuple:
    """`(identity, offlane, outcome)` — why this run is not evidence, split by KIND.

    * `identity` says "this run does not answer for this candidate at all": a different commit,
      a different workflow, a different attempt, a timeout, a cancellation, a required job that
      is missing or skipped. Nothing here was measured.
    * `offlane` is a MEASURED negative that the release lane did not produce — an ordinary
      required job going red. Something really is broken; the release lane just did not say so,
      and it names no stack.
    * `outcome` is the one thing an attributed regression is expected to produce: this run, or
      the lane job itself, concluded failure because its cases failed.

    All three were once one list, and conflating them disabled the automatic freeze completely:
    a red lane always put a problem in the list, so no failure could ever name the stack that
    caused it. `offlane` is separate from `identity` for the mirror-image reason: it must block
    ATTRIBUTION (freezing an upstream pin for someone else's breakage blames the innocent) while
    still counting as a measured negative when the question is merely "does this still pass?".
    Folding it into `identity` made a doubly-red run — lane red AND ordinary job red, the
    ordinary shape of a broken held baseline — report `unproven` instead of `failed`.
    """
    identity, offlane, outcome = [], [], []
    if run.get("timed_out"):
        return ([f"{name}: did not finish within its bound"], [], [])
    if run.get("head_sha") != att.candidate_sha:
        identity.append(f"{name}: ran on {str(run.get('head_sha'))[:9]}, not on the candidate "
                        f"{att.candidate_sha[:9]}")
    if rec.get("workflow") and run.get("workflow_id") != rec["workflow"]:
        identity.append(f"{name}: is not the workflow this attempt dispatched")
    attempt_no = run.get("run_attempt", 1)
    if attempt_no != rec.get("attempt", 1):
        identity.append(f"{name}: attempt {attempt_no} is not the attempt this run started "
                        f"({rec.get('attempt')})")
    if run.get("conclusion") != "success":
        # ONLY `failure`. A lane whose cases failed concludes failure, and that is the signal.
        # `cancelled` is not: pytest still writes its JUnit on interrupt, so a run somebody
        # cancelled mid-lane publishes a partial file with one marked failure in it — and
        # treating that as the expected shape would freeze a stack on a cancelled run.
        (outcome if run.get("conclusion") == "failure" else identity).append(
            f"{name}: {run.get('conclusion')}")
    jobs = {j["name"]: j for j in ctx.gh.jobs(LHPC, int(rec["id"]), attempt_no)}
    for job_name in required:
        job = jobs.get(job_name)
        if job is None:
            identity.append(f"{job_name}: did not run")
        elif job.get("head_sha") and job["head_sha"] != att.candidate_sha:
            # WHICH COMMIT FIRST, before the conclusion is read at all. As a later branch of the
            # same chain this was unreachable for a red job, so a job that failed on somebody
            # ELSE's commit was classified by its conclusion and counted as a measurement of
            # this one. Nothing that ran elsewhere measured anything here, red or green.
            identity.append(f"{job_name}: ran on another commit")
        elif job.get("conclusion") != "success":
            # The LANE's own red is the expected shape of a regression. Any OTHER required job
            # going red is a different problem: it was measured, but freezing upstream pins for
            # it would blame the innocent while the real cause stays live.
            (outcome if job_name == LANE_JOB and job.get("conclusion") == "failure"
             else offlane if job.get("conclusion") == "failure"
             else identity).append(f"{job_name}: {job.get('conclusion')}")
    return identity, offlane, outcome


def _failure_text(junit: bytes) -> str:
    """The text of FAILING cases only, and the names of any that failed unmarked.

    Two reasons not to search the whole document. A marker in `system-out`, in a skip reason or
    in a passing case is not a failure. And a failure with no marker beside marked ones means
    something happened that nobody attributed — a teardown that left a band held, say — so the
    caller must see it and refuse rather than believe the marker it can read.
    """
    if not junit:
        return ""
    import xml.etree.ElementTree as ET  # noqa: S405
    try:
        root = ET.fromstring(junit)     # noqa: S314
    except ET.ParseError:
        return ""
    out = []
    for case in root.iter("testcase"):
        bad = [e for e in case if e.tag in ("failure", "error")]
        if not bad:
            continue
        text = " ".join((e.get("message") or "") + " " + (e.text or "") for e in bad)
        if af.REGRESSION.search(text):
            out.append(text)
        else:
            # Named so it cannot be read as an attribution, and so `decide` sees a stack it
            # cannot group and refuses.
            out.append(f"UNATTRIBUTED-FAILURE {case.get('name', '?')}")
    return "\n".join(out)


def _release_case_problems(junit: bytes, required) -> tuple:
    """`(unreadable, red)` — what stopped the measurement, and what the measurement found.

    The release lane must have PASSED every case the candidate requires, by name. Counting was
    not enough: fourteen cases named anything at all satisfied a count, so a renamed or replaced
    case stopped proving its stack without stopping the release. The names come from the
    candidate itself, so a release is judged against the list that commit ships.

    Both lists block a release — every caller concatenates them — but they are not the same
    statement. `unreadable` means this bot could not look; `red` means it looked and the lane
    was not green. Only the second is grounds to tell a maintainer a composition is broken, or
    to blame an upstream project for it.

    At most one of the two is ever non-empty: reading has to succeed before there is anything to
    judge. Callers rely on that — a non-empty `red` is by itself proof that the evidence was
    readable.
    """
    if not junit:
        return ["the release lane produced no JUnit — its cases cannot be confirmed"], []
    if not required:
        return [f"the candidate does not state its required cases ({RELEASE_CASES_PATH})"], []
    # The JUnit comes from our own workflow's artifact, not from a third party, and it is
    # parsed only for element names and attributes.
    import xml.etree.ElementTree as ET  # noqa: S405
    try:
        root = ET.fromstring(junit)     # noqa: S314
    except ET.ParseError as exc:
        return [f"the release lane's JUnit could not be read ({exc})"], []
    cases = {c.get("name", ""): c for c in root.iter("testcase")}
    red = []
    for name in sorted(required):
        case = cases.get(name)
        if case is None:
            # Readable evidence that does not contain the case the candidate requires. The lane
            # ran and did not prove it, which is a finding about the lane, not about this bot.
            red.append(f"{name}: the lane did not report it")
        elif case.find("skipped") is not None:
            red.append(f"{name}: skipped — a skip is not proof")
        elif case.find("failure") is not None or case.find("error") is not None:
            red.append(f"{name}: failed")
    return [], red


def required_release_cases(text: str) -> list:
    """The case names the candidate's own list declares. [] if it cannot be read."""
    try:
        got = json.loads(text)["required_cases"]
    except (ValueError, KeyError, TypeError):
        return []
    return [str(n) for n in got] if isinstance(got, list) else []


# ---------------------------------------------------------------------------- stage: release


def stage_release(ctx: Ctx) -> int:
    """The commit point: `main` and its tag move together, or neither moves."""
    number, att = ctx.find_attempt(ctx.attempt_id)
    if not att:
        raise Stop("release", "this run has no attempt record.", "Re-run from the start.")
    tag = f"v{att.version}"
    if att.rehearsal:
        # NOT the same thing as "main moved": a rehearsal branch may point at exactly the same
        # commit as main, and that is still a rehearsal. The record says what this attempt is.
        raise Stop("release", f"attempt {att.run_id} was planned from `{att.base_ref}`, not "
                   f"`main`.",
                   "A rehearsal proves the freeze and publishes nothing. Recovery will undo it.")
    now = ctx.gh.ref(LHPC, "heads/main")
    if now != att.base_sha:
        raise Stop("release", f"`main` moved from {att.base_sha[:9]} to {now[:9]} during this "
                   f"run.", "Someone released meanwhile. The index is rolled back and the "
                   "candidate branch deleted; re-run to rebase on the new main.")
    if ctx.gh.ref(LHPC, f"tags/{tag}"):
        raise Stop("release", f"the tag {tag} already exists.",
                   "Recover this attempt by hand: the version was taken by someone else.")

    lhpc = ctx.clone(LHPC, att.branch)
    git("fetch", "-q", "origin", att.candidate_sha, cwd=lhpc)
    git("tag", "-a", tag, "-m", f"{att.version}\n\n"
        + cl.section_of((lhpc / "CHANGELOG.md").read_text(), att.version), att.candidate_sha,
        cwd=lhpc)
    # ONE ref update: a tagless main would let boxes self-update to an unreleased commit.
    git("push", "--atomic", "origin", f"{att.candidate_sha}:refs/heads/main",
        f"refs/tags/{tag}", cwd=lhpc)

    # Believe the remote, not the exit status: a push can be accepted and its reply lost.
    if ctx.gh.ref(LHPC, "heads/main") != att.candidate_sha or not ctx.gh.ref(LHPC, f"tags/{tag}"):
        raise Stop("release", "the atomic push did not take effect.",
                   "Nothing is released. Recover the attempt.")
    att.state = "released"
    att.notes.append(f"released {tag} at {att.candidate_sha[:9]}")
    ctx.save_attempt(number, att)
    # `main` now carries the commit, so the candidate branch is litter. Removed here rather
    # than at the end: every later stage reads the commit, none reads the branch.
    git("push", "-q", "origin", "--delete", att.branch, cwd=lhpc, check=False)
    ctx.out(version=att.version, tag=tag, candidate=att.candidate_sha)
    ctx.summary(f"released **{tag}** — `main` is now {att.candidate_sha[:9]}.")
    return 0


# ---------------------------------------------------------------------------- stage: dev


def stage_integrate(ctx: Ctx) -> int:
    """`dev` gets the patch as a fast-forward, or as a pull request — never as a rewrite."""
    number, att = ctx.find_attempt(ctx.attempt_id)
    if not att:
        raise Stop("integrate", "this run has no attempt record.", "Re-run from the start.")
    if not att.past_commit_point:
        # A `finish` repair completes a release that STANDS. Pointed at a rejected or restored
        # attempt — an operator typo away — this would otherwise integrate a candidate nothing
        # released and cut an image for a tag that does not exist. Recovery owns those.
        raise Stop("integrate", f"attempt {att.run_id} never reached the commit point "
                   f"(state `{att.state}`).",
                   "`finish` repairs a release that stands. This attempt released nothing, so "
                   "there is nothing to integrate or cut an image for; `recover` owns it.")
    if att.integration:
        # Idempotent so a repair can re-run it: an attempt that owes integration is closed by
        # running this stage again, and one that does not must not push `dev` a second time.
        print(f"integration already done: {att.integration}")
        return 0
    lhpc = ctx.clone(LHPC, "main")
    git("fetch", "-q", "origin", "dev", cwd=lhpc)
    dev_now = ctx.gh.ref(LHPC, "heads/dev")
    if dev_now != att.base_sha and ctx.gh.is_ancestor(LHPC, att.candidate_sha, dev_now):
        # It already happened and the record did not survive to say so. Believing our own note
        # over the remote is what made this stage impossible to repair: the cherry-pick applies
        # nothing, the commit fails with "nothing to commit", and the attempt can never close.
        att.state = "integrated" if att.state == "released" else att.state
        att.integration = "fast-forward"
        att.notes.append("dev already contains the release")
        ctx.save_attempt(number, att)
        ctx.summary("`dev` already contains the release.")
        return 0
    if dev_now == att.base_sha:
        # `dev` never moved: the release IS its next commit.
        git("push", "-q", "--force-with-lease=refs/heads/dev:" + att.base_sha, "origin",
            f"{att.candidate_sha}:refs/heads/dev", cwd=lhpc)
        att.state = "integrated" if att.state == "released" else att.state
        att.integration = "fast-forward"
        att.notes.append("dev fast-forwarded")
        ctx.save_attempt(number, att)
        ctx.summary("`dev` fast-forwarded to the release.")
        return 0

    branch = f"integrate/{att.version}"
    git("checkout", "-q", "-B", branch, "origin/dev", cwd=lhpc)
    pick = subprocess.run(["git", "cherry-pick", "-n", att.candidate_sha], cwd=lhpc,
                          capture_output=True, text=True, check=False)
    resolved = _resolve_version_conflicts(lhpc, att.version, att.candidate_sha)
    att.integration = ""
    conflicts = [ln[3:] for ln in git("status", "--porcelain", cwd=lhpc).splitlines()
                 if ln.startswith(("UU ", "AA ", "DU ", "UD "))]
    if pick.returncode != 0 and conflicts:
        # A real conflict is a judgement call. Give the reviewer the release patch itself, with
        # the conflict visible on GitHub — never a resolved-looking branch, never conflict
        # markers, never an empty PR.
        git("cherry-pick", "--abort", cwd=lhpc, check=False)
        git("checkout", "-q", "-B", branch, att.candidate_sha, cwd=lhpc)
        git("push", "-q", "-f", "origin", f"HEAD:refs/heads/{branch}", cwd=lhpc)
        pr = ctx.gh.pull_request(
            LHPC, branch, "dev", f"Bring {att.version} back to dev",
            f"`{att.version}` was released from `main`. `dev` has moved on, and these paths "
            f"conflict:\n\n" + "\n".join(f"- `{c}`" for c in conflicts)
            + "\n\nThe branch is the release commit itself, so the conflict is visible here "
              "rather than resolved by a bot. Version scalars and changelog placement are the "
              "only things this bot resolves automatically.")
        att.state = "integrated" if att.state == "released" else att.state
        att.integration = f"pr:{pr['number']}"
        att.notes.append(f"dev diverged; PR #{pr['number']} opened with the conflict visible")
        ctx.save_attempt(number, att)
        ctx.summary(f"`dev` diverged — pull request #{pr['number']} opened.")
        return 0

    git("add", "-A", cwd=lhpc)
    git("commit", "-q", "-m", f"{att.version} (released from main)", cwd=lhpc)
    git("push", "-q", "-f", "origin", f"HEAD:refs/heads/{branch}", cwd=lhpc)
    pr = ctx.gh.pull_request(
        LHPC, branch, "dev", f"Bring {att.version} back to dev",
        f"`{att.version}` was released from `main`. Version scalars and changelog placement "
        f"were resolved automatically ({', '.join(resolved) or 'nothing to resolve'}); "
        f"everything else is the release commit unchanged. Merge when the checks are green.")
    att.state = "integrated" if att.state == "released" else att.state
    att.integration = f"pr:{pr['number']}"
    att.notes.append(f"dev diverged; PR #{pr['number']} opened")
    ctx.save_attempt(number, att)
    ctx.summary(f"`dev` diverged — pull request #{pr['number']} opened.")
    return 0


def _merge_but_for_the_scalar(repo: Path, path: str, candidate: str, set_version, version: str):
    """A real three-way merge of one version-bearing file, with the version taken out of the
    argument. Returns the merged text, or `None` if the rest of the file genuinely conflicts.

    The version line is the ONE thing the two sides are always expected to disagree about, and it
    has a known answer — decided by the caller, and passed in as `version`. So the scalar is set
    to that answer on all three sides before merging, which makes it identical everywhere and
    removes it from the merge; git then decides the rest, which is the part neither side may lose.

    The answer is NOT "dev keeps its own", as this said while that was the rule. It is whichever
    version is genuinely newer, which is only `dev`'s when `dev` has opened a later cycle.

    Rewriting the file from one side, as this used to do, is not a merge in either direction: it
    dropped whatever the OTHER side had changed there while producing a branch that looked
    cleanly resolved.
    """
    try:
        sides = [set_version(git("show", f"{ref}:{path}", cwd=repo), version)
                 for ref in ("origin/dev", f"{candidate}^", candidate)]
    except (RuntimeError, ValueError):
        return None                      # absent on a side, or no scalar to set: not ours to do
    with tempfile.TemporaryDirectory() as d:          # OUTSIDE the work tree: `git add -A` runs
        files = []                                    # over it later and would commit strays
        for name, text in zip(("ours", "base", "theirs"), sides, strict=True):
            f = Path(d) / name
            f.write_text(text)
            files.append(str(f))
        r = subprocess.run(["git", "merge-file", "-p", *files],
                           capture_output=True, text=True, check=False, timeout=120)
    if r.returncode != 0:
        return None
    # `git show` is read through a stripping helper, so the merge output loses the final newline
    # and `ruff` fails the very pull request this opens (W292).
    return r.stdout if r.stdout.endswith("\n") else r.stdout + "\n"


def _resolve_version_conflicts(repo: Path, version: str, candidate: str) -> list:
    """The ONE resolution this bot makes: the two version scalars and the changelog placement.

    The scalars go to whichever version is genuinely newer — `dev`'s own if it has opened a later
    cycle, the released one otherwise — and the released section is inserted in version order.
    Both halves move together, because the controller gates that the newest changelog section
    equals the version scalar, and fixing either alone fails that gate.

    Everything else in those files is MERGED, not chosen. A file whose remainder really does
    conflict is left conflicted and unstaged, so it reaches the pull request for a person —
    which is the whole point of opening one.
    """
    resolved = []
    dev_version = cl.current_version(git("show", "origin/dev:pyproject.toml", cwd=repo))

    # Which scalar `dev` should end up with is decided by comparing it with the version being
    # RELEASED, not with the base.
    #
    #   dev NEWER than the release -> somebody deliberately opened a cycle of their own (0.4.0).
    #                                 That is a real decision and this bot does not overwrite it.
    #   otherwise                  -> `dev`'s scalar is simply an older one. Keeping it leaves
    #                                 `dev` claiming a version older than the release it just
    #                                 absorbed, and the controller's own gate — the newest
    #                                 changelog section must equal the version scalar — then
    #                                 rejects the correctly ordered changelog.
    #
    # Comparing against the BASE instead looked equivalent and is not: `dev` differs from the base
    # whenever the PREVIOUS merge-back PR is still unmerged, which is the ordinary state, since
    # this bot opens a PR for a person to merge. `dev` 0.3.14 with base 0.3.15 releasing 0.3.16
    # would then have been read as "dev opened its own cycle" and left at 0.3.14 under a 0.3.16
    # section — the very inconsistency this resolution exists to prevent.
    # `version_order`, not `version_tuple`: a scalar on `dev` is written by a person and may carry
    # a pre-release marker. `0.4.0rc1` IS a newer cycle and must be kept; ordering it by the
    # numbers in front says so, where a strict triple parse would raise. And that raise mattered:
    # this runs AFTER the commit point, so an exception here leaves a release standing with no
    # integration branch and an attempt owing one.
    try:
        keep = cl.version_order(dev_version) > cl.version_order(version)
    except ValueError:
        # A scalar that does not BEGIN with a version number. Nothing can be inferred from it,
        # so take the released patch — the value the controller's own consistency gate expects —
        # and let the resolution note below name what it replaced, on a branch a person merges.
        keep = False
    target = dev_version if keep else version

    for path, setter in (("pyproject.toml", cl.set_pyproject_version),
                         ("lhpc/version.py", cl.set_version_module)):
        merged = _merge_but_for_the_scalar(repo, path, candidate, setter, target)
        if merged is None:
            continue                     # stays conflicted -> the PR shows a person the reason
        (repo / path).write_text(merged)
        git("add", path, cwd=repo, check=False)
        why = ("dev's own newer cycle kept" if keep else
               f"advanced to the released patch from {dev_version}")
        resolved.append(f"{path}: merged, version -> {target} ({why})")

    ours = git("show", f"{candidate}:CHANGELOG.md", cwd=repo)
    dev_log = git("show", "origin/dev:CHANGELOG.md", cwd=repo)
    section = cl.section_of(ours, version)
    if section:
        # Not a merge: where a released section belongs relative to dev's unreleased one is a
        # decided ordering, and `merge_back` owns it.
        merged = cl.merge_back(dev_log, section, version)
        (repo / "CHANGELOG.md").write_text(merged)
        git("add", "CHANGELOG.md", cwd=repo, check=False)
        # Say what HAPPENED, not what was attempted. `merge_back` is idempotent: if `dev` already
        # carries a section for this version it keeps its own and inserts nothing. Reporting an
        # insertion anyway told a pull request's reviewer that the released notes had been placed
        # when dev's — possibly different — text was kept and the cherry-picked one discarded.
        # Compared on the STRIPPED text: `merge_back` normalises the trailing newline, and the
        # caller's `dev_log` has usually already lost it, so a raw `!=` would call every no-op an
        # insertion — the same trap in miniature.
        resolved.append(f"CHANGELOG.md: {version} inserted in version order"
                        if merged.strip() != dev_log.strip() else
                        f"CHANGELOG.md: unchanged — `dev` already has a {version} section, and "
                        f"the released one was NOT merged into it")
    return resolved


# ---------------------------------------------------------------------------- stage: image


def stage_image(ctx: Ctx) -> int:
    number, att = ctx.find_attempt(ctx.attempt_id)
    if not att:
        raise Stop("image", "this run has no attempt record.", "Re-run from the start.")
    if not att.past_commit_point:
        # A `finish` repair completes a release that STANDS. Pointed at a rejected or restored
        # attempt — an operator typo away — this would otherwise integrate a candidate nothing
        # released and cut an image for a tag that does not exist. Recovery owns those.
        raise Stop("image", f"attempt {att.run_id} never reached the commit point "
                   f"(state `{att.state}`).",
                   "`finish` repairs a release that stands. This attempt released nothing, so "
                   "there is nothing to integrate or cut an image for; `recover` owns it.")
    tag = f"v{att.version}"
    att.image_tag = tag
    ctx.save_attempt(number, att)

    if not ctx.gh.ref(IMG, f"tags/{tag}"):
        img = ctx.clone(IMG, "main")
        changelog = img / "CHANGELOG.md"
        changelog.write_text(_image_changelog(changelog.read_text(), att))
        git("add", "-A", cwd=img)
        git("commit", "-q", "-m", f"{tag}: rebuild on loraham-pi-control {tag} "
            f"({att.candidate_sha[:7]})", cwd=img)
        git("tag", "-a", tag, "-m",
            f"auto-release: rebuild on loraham-pi-control {tag} ({att.candidate_sha[:7]})\n"
            f"lhpc-commit: {att.candidate_sha}\n", cwd=img)
        git("push", "--atomic", "origin", "HEAD:refs/heads/main", f"refs/tags/{tag}", cwd=img)
        run_id = _find_image_run(ctx, tag)
    else:
        # Resuming. Ask FIRST whether the image is already there: a wait that timed out while the
        # build actually succeeded would otherwise rebuild both variants from scratch.
        done = image_problems(tag, att.candidate_sha, {}, ctx.gh.release_by_tag(IMG, tag),
                              ctx.gh.tag_message(IMG, tag))
        if not done:
            att.state = "image-published"
            att.notes.append(f"image {tag} was already published; nothing rebuilt")
            ctx.save_attempt(number, att)
            ctx.summary(f"\nImage `{tag}` was already published.")
            return 0
        busy = ctx.gh.unfinished_runs(IMG, IMAGE_WORKFLOW)
        if busy:
            raise Stop("image", f"an image build is still running while {tag} is incomplete.",
                       "Wait for it and re-run `finish`. A second builder on the same tag would "
                       "upload over the first one's assets.",
                       detail="\n".join(str(r.get("html_url", "")) for r in busy))
        # The tag stands and the controller identity stands; only the run is new. `builder_ref`
        # is explicit: without it the images workflow resolves the builder from the TAG, which is
        # the very revision that failed. `main` is the only builder revision that has been
        # through that repository's own CI, and the run records which one it really used.
        run_id = ctx.gh.dispatch(IMG, IMAGE_WORKFLOW, "main",
                                 {"publish_to_tag": tag,
                                  "expected_lhpc_sha": att.candidate_sha,
                                  "builder_ref": "main"})
    att.runs["image"] = ctx.record_run(IMG, run_id)
    ctx.save_attempt(number, att)

    run = ctx.gh.wait(IMG, run_id, BOUNDS["image"])
    reasons = image_problems(tag, att.candidate_sha, run,
                             ctx.gh.release_by_tag(IMG, tag), ctx.gh.tag_message(IMG, tag))
    if reasons:
        att.notes.append(f"image {tag} not published: {reasons[0]}")
        ctx.save_attempt(number, att)
        raise Stop("image", "the image is not published:\n\n"
                   + "\n".join(f"- {r}" for r in reasons),
                   f"The controller release {tag} STANDS — boxes self-update to it. Only the "
                   f"image is missing, and the previous image is still the latest. Re-run this "
                   f"workflow with mode `finish` once the cause is fixed.",
                   detail=run.get("html_url", ""))
    att.state = "image-published"
    att.notes.append(f"image {tag} published")
    ctx.save_attempt(number, att)
    ctx.summary(f"image **{tag}** published. Integration: {att.integration or 'still owed'}.")
    return 0


# The evidence a published image must carry beside its two variants.
# Everything the image publisher writes for a bot-made release — its `assemble` step is the
# source of truth, and it refuses to publish without any of these. The list was a hand-kept
# subset, so a build whose signature or package report never landed read as a published image.
IMAGE_EVIDENCE = ("loraham-lhpc-lite.img.xz", "loraham-lhpc-desktop.img.xz",
                  "loraham-lhpc-lite.img.xz.sha256", "loraham-lhpc-desktop.img.xz.sha256",
                  "provenance-lite.json", "provenance-desktop.json",
                  "components-lite.txt", "components-desktop.txt",
                  "packages-lite.txt", "packages-desktop.txt",
                  "SHA256SUMS", "signature.txt", "AUTO-RELEASE")


def image_problems(tag: str, candidate: str, run: dict, release: dict,
                   tag_message: str) -> list:
    """Why this is not a published image for THIS release. [] when it is.

    A green build is not a published image, and a published image is not THIS release's: the
    release must be out of draft, carry both variants with their evidence, and its tag must
    still name the controller commit this attempt released.
    """
    out = []
    # A falsy `run` means "not asking about a build" — used to judge whether a release is already
    # complete BEFORE deciding to start one.
    if run and run.get("timed_out"):
        out.append("the build did not finish within its bound")
    elif run and run.get("conclusion") != "success":
        out.append(f"the build concluded {run.get('conclusion')}")
    if not release:
        out.append(f"{tag} has no release")
        return out
    if release.get("draft"):
        out.append("the release is still a draft — its assets were not all verified")
    names = {a["name"] for a in release.get("assets", [])}
    missing = [n for n in IMAGE_EVIDENCE if n not in names]
    if missing:
        out.append("the release is missing " + ", ".join(missing))
    if f"lhpc-commit: {candidate}" not in (tag_message or ""):
        out.append(f"{tag} does not name the controller commit this attempt released")
    return out


def _image_changelog(text: str, att: Attempt) -> str:
    tag = f"v{att.version}"
    line = (f"- Rebuild on `loraham-pi-control` **{tag}** (`{att.candidate_sha[:7]}`); see that "
            f"repo's changelog.\n")
    if "## Unreleased\n" in text:
        head, _, rest = text.partition("## Unreleased\n")
        return f"{head}## {tag}\n{line}{rest}"
    marker = "\n## "
    at = text.find(marker)
    section = f"## {tag}\n\n{line}\n"
    return text[:at + 1] + section + text[at + 1:] if at > 0 else text + "\n" + section


def _find_image_run(ctx: Ctx, tag: str) -> int:
    """The run a TAG PUSH started — the one case with no dispatch reply to read the id from."""
    import time
    for _ in range(30):
        runs = ctx.gh.get(f"/repos/{IMG}/actions/runs?per_page=20")["workflow_runs"]
        for run in runs:
            if run.get("head_branch") == tag:
                return int(run["id"])
        time.sleep(10)
    raise Stop("image", f"no image build appeared for {tag} within five minutes.",
               "The tag is pushed. Re-run with mode `finish` once Actions is healthy.")


# ---------------------------------------------------------------------------- stage: finalize


def stage_finalize(ctx: Ctx) -> int:
    """The ONE place an attempt is closed, and only when nothing is owed.

    Integration and the image are separate stages that can each fail on their own. Neither may
    decide the attempt is finished: an image that succeeded would otherwise close over a failed
    integration, and the repair path could never find it again.
    """
    number, att = ctx.find_attempt(ctx.attempt_id)
    if not att:
        print("no attempt to finalize")
        return 0
    if not att.past_commit_point:
        print(f"attempt {att.run_id} never reached the commit point — recovery owns it")
        return 0
    if att.owes:
        att.notes.append(f"left open: still owes {', '.join(att.owes)}")
        ctx.save_attempt(number, att)
        ctx.summary(f"attempt {att.run_id} stays open — still owes {', '.join(att.owes)}.")
        return 0
    att.state = "complete"
    ctx.save_attempt(number, att)
    report_retry_outcome(ctx, f"released {att.version} with the hold in place — the held stack "
                              f"and every other required case passed", att)
    # A retry that RELEASED has discharged its obligation too. Same settlement as the
    # frozen-only path, in the other place a child can terminate.
    #
    # BEFORE the child's issue is closed, deliberately. Attempt lookup searches OPEN issues, so a
    # crash between the two writes used to leave the parent unresolved and the child unreachable —
    # re-running this stage answered "no attempt to finalize" while the parent blocked every later
    # release. In this order an interruption leaves the child open, which is exactly what a repeat
    # run needs to find; settling twice is harmless, because the second call finds no open parent.
    _settle_parent(ctx, att, f"released {att.version} with the hold in place")
    ctx.bot_gh.update_issue(BOT, number, state="closed")
    ctx.summary(f"attempt {att.run_id} complete: released {att.version}, "
                f"integration {att.integration}, image {att.image_tag}.")
    return 0


# ---------------------------------------------------------------------------- stage: recover


def stage_recover(ctx: Ctx, run_id: str = "") -> int:
    """Undo what this attempt changed — but only what is provably still this attempt's, and
    only after every writer it started has stopped.

    The order matters. Settling first means a rollback can never race the publisher that is
    still running; reconciling from the child's own recorded entry means another publisher's
    work is reported as a conflict rather than overwritten; and reading the refs before any of
    it means a release whose reply was lost is never undone.
    """
    number, att = ctx.find_attempt(run_id or ctx.attempt_id)
    if not att:
        print("no attempt to recover")
        return 0

    tag = f"v{att.version}"
    main_now = ctx.gh.ref(LHPC, "heads/main")
    tag_sha = ctx.gh.ref(LHPC, f"tags/{tag}")
    released_here = bool(att.candidate_sha) and (
        tag_sha == att.candidate_sha
        or ctx.gh.is_ancestor(LHPC, att.candidate_sha, main_now or att.candidate_sha)
        and main_now == att.candidate_sha)
    decision = recovery_decision(att, main_now, tag_sha, released_here)

    if decision == "released":
        # The REMOTE has just said this attempt's release exists, so the record is behind the
        # world and it is the record that must move. Normalising only from `mutated` left the one
        # shape that needs it most stuck: a candidate needing NO binary publish stays `prepared`
        # through its whole proof, so an accepted atomic push whose journal write was lost kept a
        # `prepared` record. `past_commit_point` was then false, `owes` empty, and recovery said
        # "nothing owed" about a release that had really happened — while the attempt stayed open
        # and blocked every later one, and the finish guards (rightly) refused it. Repeating
        # recover or finish could not resolve it.
        #
        # `OPEN_STATES` matters as much as the negation: it promotes a live pre-commit record and
        # never a terminal one. A `restored` attempt is not past the commit point either, and
        # nothing may promote it to released on a ref coincidence.
        if att.state in OPEN_STATES and not att.past_commit_point:
            att.state = "released"
        att.notes.append("recovery found this attempt's controller release already published — "
                         "its binaries stay; only what it still owes is outstanding")
        ctx.save_attempt(number, att)
        ctx.summary(f"{tag} is released. Nothing rolled back; still owed: "
                    f"{', '.join(att.owes) or 'nothing'}.")
        return 0
    if decision == "conflict":
        att.notes.append(f"recovery stopped: {tag} exists at {tag_sha[:9]}, not at this "
                         f"attempt's candidate {att.candidate_sha[:9]}")
        ctx.save_attempt(number, att)
        raise Stop("recover", f"the version {att.version} is held by a different commit.",
                   "This attempt stays open. Somebody else released that version; decide by "
                   "hand what should happen to this attempt's candidate.")

    # ---- settle every writer this attempt started, BEFORE touching anything -------------
    unsettled = []
    # A publish was started for these and the reply was lost, so there is no run id to cancel or
    # wait for. Silence about them is not evidence: the only safe reading is that a publisher may
    # still be writing, so nothing may be concluded until no build is running at all.
    forgotten = unrecorded_dispatches(att)
    if forgotten:
        running = ctx.gh.unfinished_runs(BIN, BUILD_WORKFLOW)   # one answer, not one per stack
        if running:
            unsettled.append(f"{', '.join(forgotten)} dispatched with no recorded run, and "
                             f"{len(running)} build(s) have not finished")
    for _name, rec in att.runs.items():
        repo = rec.get("repo", BIN) if isinstance(rec, dict) else BIN
        rid = int(rec["id"]) if isinstance(rec, dict) else int(rec)
        ctx.gh.cancel(repo, rid)
    for name, rec in att.runs.items():
        if not (name.startswith("binary:") or name == "rollback"):
            continue
        rid = int(rec["id"]) if isinstance(rec, dict) else int(rec)
        run = ctx.gh.wait(BIN, rid, BOUNDS["settle"], poll_s=15)
        if run.get("timed_out") or run.get("status") != "completed":
            unsettled.append(f"{name} (run {rid}) is still running")
    if unsettled:
        att.notes.append("recovery could not settle: " + "; ".join(unsettled))
        ctx.save_attempt(number, att)
        raise Stop("recover", "a publisher this attempt started has not stopped:\n\n"
                   + "\n".join(f"- {u}" for u in unsettled),
                   "The attempt stays open and keeps blocking new releases. Rolling the index "
                   "back while that job can still write would undo the rollback. Re-run "
                   "`recover` once it is terminal.")

    # ---- reconcile every stack a publish was STARTED for --------------------------------
    live = _live_index(ctx).get("stacks", {})
    snapshot = (att.index_snapshot or {}).get("stacks", {})
    for stack in att.dispatched:
        if stack not in att.published:
            # A dispatch whose outcome was never recorded: ask its artifact once more before
            # concluding anything about it. What comes back is WRITTEN DOWN — the rollback is
            # judged against `published`, so an entry known only to this loop would reach the
            # child as no expectation at all, and the child would overwrite whatever it found.
            rec = att.runs.get(f"binary:{stack}")
            entry = (_candidate_entry(ctx, int(rec["id"]), stack, att.candidate_sha)
                     if rec else None)
            if entry:
                att.published[stack] = entry
                ctx.save_attempt(number, att)
    ours = dict(att.published)
    restore, noop, conflicts = reconcile(att.dispatched, ours, live, snapshot)

    if conflicts:
        att.notes.append("recovery stopped: the live entry for "
                         + ", ".join(conflicts) + " is neither this attempt's nor the snapshot")
        ctx.save_attempt(number, att)
        raise Stop("recover", "the binary index holds an entry this attempt cannot claim:\n\n"
                   + "\n".join(f"- {c}" for c in conflicts),
                   "Nothing was changed. Somebody published in between, or the outcome of this "
                   "attempt's own build is unknown. The attempt stays open for inspection.")

    if restore:
        stacks = ",".join(sorted(restore))
        rb = ctx.gh.dispatch(BIN, "rollback.yml", "main", {
            "stacks": stacks,
            "snapshot_json": json.dumps(att.index_snapshot),
            # No `if s in published` filter: a stack chosen for restore whose entry is missing
            # is a bug here, and must fail here, not silently disable the child's ownership
            # check and let it overwrite a foreign entry.
            "expect_json": json.dumps({s: ours[s] for s in restore})})
        # Recorded BEFORE the wait, like every other dispatch: a cancellation in between would
        # otherwise leave no trace of a writer that is mid-write on the index, and the next
        # `recover` would start a second rollback on top of it.
        att.runs["rollback"] = ctx.record_run(BIN, rb)
        ctx.save_attempt(number, att)
        run = ctx.gh.wait(BIN, rb, BOUNDS["settle"], poll_s=15)
        if run.get("conclusion") != "success":
            att.notes.append(f"ROLLBACK NOT CONFIRMED: {run.get('html_url')}")
            ctx.save_attempt(number, att)
            raise Stop("recover", "the binary index could not be restored.",
                       "This attempt stays open and blocks new releases. Inspect the rollback "
                       "run, then re-run `recover`.", detail=run.get("html_url", ""))
        back = _live_index(ctx).get("stacks", {})
        wrong = [s for s in restore if _canon(back.get(s)) != _canon(snapshot.get(s))]
        if wrong:
            att.notes.append("rollback reported success but the index still differs for "
                             + ", ".join(wrong))
            ctx.save_attempt(number, att)
            raise Stop("recover", "the index read back is not the snapshot for "
                       + ", ".join(wrong) + ".",
                       "This attempt stays open. Inspect the rolling release by hand.")
        att.notes.append(f"index restored for {stacks}")
    if noop:
        att.notes.append(f"already at the snapshot: {', '.join(sorted(noop))}")

    if att.branch:
        lhpc = ctx.clone(LHPC, "main")
        git("push", "-q", "origin", "--delete", att.branch, cwd=lhpc, check=False)
    att.state = "restored"
    ctx.save_attempt(number, att)
    ctx.summary("attempt restored: index back, candidate branch deleted, nothing released.")
    # ONLY here: the index is provably back, so a hold now describes a composition that exists.
    # The attempt issue is still OPEN while this runs — it is the durable record of a hold that
    # was written and a retry that is owed, and a job lost midway must leave that readable.
    _auto_freeze(ctx, number, att)      # mutates `att`: the hold, the incident, the claim
    if att.unresolved:
        # A hold was written and its retry has not been claimed. Closing here lost the obligation
        # outright: `open_attempts` reads OPEN issues, so recovering it afterwards answered "no
        # attempt to recover" while the policy still carried the hold. It stays open until a
        # child claims it or somebody settles it by hand.
        ctx.summary("\nThis attempt stays OPEN: a hold was written and its retry is still owed.")
        return 0
    ctx.bot_gh.update_issue(BOT, number, state="closed")
    return 0


def _auto_freeze(ctx: Ctx, number: int, att: Attempt) -> None:
    """Hold the stack this run's evidence blamed, say so in an incident, and retry once.

    Everything about this is deliberately conservative. It runs after a CONFIRMED restore, never
    on a released attempt, never for a failure that did not name a stack, never for a stack that
    moved nothing, and never twice: a run that is itself the retry hands off to nobody. A hold
    that cannot be written stops the chain rather than dispatching a child that would rediscover
    the same break.
    """
    if att.retry_of and att.regression:
        # The one retry failed too. Say so on the incident rather than only on stdout: it is
        # still open and still claiming a retry is in flight.
        print("this run is already the one retry; not freezing again")
        open_incident = af.already_open(ctx.bot_gh.open_issues(BOT, af.LABEL), att.regression)
        if open_incident:
            ctx.bot_gh.comment(BOT, open_incident,
                               f"The retry failed too ({ctx.run_url}). The hold stands and this "
                               f"chain stops here — peeling off more stacks to get a green run "
                               f"is not a release. Investigate before thawing.")
        return
    if not att.regression or att.retry_of:
        return
    # The manifest at the attempt's OWN base, not at whatever `main` is now. A controller change
    # landing in between would otherwise be used to group a composition captured before it, and
    # the hold would cover the wrong set — or be refused for the wrong reason.
    def _no_hold(why: str) -> None:
        """Say it where somebody will read it. An incident opened by an earlier pass says a
        retry is owed; if these guards now fire, no re-run can ever satisfy it, so the incident
        must be told rather than left asserting it for ever."""
        print(f"no automatic hold: {why}")
        if att.incident:
            ctx.bot_gh.comment(BOT, att.incident,
                               f"No retry will follow: {why}. The hold, if one was written, "
                               f"stands. Settle this attempt by hand.")

    if ctx.gh.ref(LHPC, f"heads/{att.base_ref}") != att.base_sha:
        _no_hold("the controller moved since this attempt started")
        return
    manifest = ctx.gh.file_at(LHPC, MANIFEST, att.base_sha)
    if not manifest:
        _no_hold("the manifest at the attempt's base could not be read")
        return
    bot = ctx.clone(BOT, "main", token=ctx.bot_token or ctx.token)
    policy_p = bot / "policy.toml"
    keys, refusal = af.decide(att.regression, att.moved_keys, manifest,
                              up.load_policy(policy_p),
                              unattributed=af.unattributed_failures(att.evidence))
    if refusal:
        print(f"no automatic hold: {refusal}")
        return

    incident = af.already_open(ctx.bot_gh.open_issues(BOT, af.LABEL), att.regression)
    body = rp.incident(att, keys, ctx.run_url)
    if incident:
        ctx.bot_gh.update_issue(BOT, incident, body=body)
    else:
        incident = ctx.bot_gh.create_issue(
            BOT, af.incident_title(att.regression), body, [af.LABEL])["number"]

    # Written down BEFORE the policy is touched. From here on this attempt owes a retry, and a
    # job lost between the issue and the push must leave that readable — the issue already
    # asserts it.
    att.incident = incident
    ctx.save_attempt(number, att)

    reason = (f"Automatic hold after {att.evidence or 'a failed release'}; "
              f"see {BOT_URL}/issues/{incident}")
    try:
        policy_p.write_text(af.freeze_edit(policy_p.read_text(), keys, reason))
        if git("status", "--porcelain", "policy.toml", cwd=bot).strip():
            git("add", "policy.toml", cwd=bot)
            git("commit", "-q", "-m",
                f"auto-freeze: hold {', '.join(att.regression)} (#{incident})", cwd=bot)
            # No force. A policy somebody edited meanwhile is a reason to stop and reconcile,
            # never to overwrite: the other edit may be a hold of their own.
            git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=bot)
        else:
            # The hold is ALREADY there — `freeze_edit` changed nothing because a previous run of
            # this same recovery wrote it and then died. Committing would fail with "nothing to
            # commit" and be reported as "the hold was NOT written", which is the opposite of the
            # truth and the reason a resume could never finish.
            print(f"the hold on {', '.join(sorted(keys))} is already in policy.toml; resuming")
    except (RuntimeError, ValueError) as exc:
        ctx.bot_gh.update_issue(BOT, incident, body=body + "\n\n**The hold was NOT written**: "
                                f"{exc}. Nothing was retried. Apply the freeze by hand.")
        raise Stop("recover", f"the automatic hold could not be written: {exc}",
                   "The attempt is recovered and nothing was released. Apply the freeze by "
                   "hand, or re-run once the policy is settled.") from None

    # Written down BEFORE the dispatch. A job lost between here and the dispatch must leave a
    # record that says the hold stands and a retry is owed — the alternative is an incident
    # asserting a retry that nobody ever started.
    att.frozen, att.incident = sorted(keys), incident
    ctx.save_attempt(number, att)
    ctx.bot_gh.update_issue(BOT, incident, body=body + "\n\nThe hold is written. A retry is "
                            "owed; re-run `recover` for this attempt if none is linked below.")
    ctx.summary(f"\nHeld {', '.join(att.regression)} and recorded incident #{incident}.")

    # A parent cannot tell a dispatch that was never sent from one whose reply was lost, and a
    # sentinel written before the POST made every resume believe a child existed — leaving a real
    # hold, no child, and nothing owed by anybody. So the CHILD claims the work on the incident
    # before it mutates anything, and the parent asks the incident rather than its own note.
    claim = af.claimed_by(ctx.bot_gh.comments(BOT, incident))
    if claim:
        att.retry_run = claim
        ctx.save_attempt(number, att)
        ctx.summary(f"\nRetry run {claim} has already claimed this hold; not sending another.")
        return
    child = ctx.bot_gh.dispatch(BOT, RELEASE_WORKFLOW, "main",
                                {"mode": "full", "retry_of": att.run_id,
                                 "retry_incident": str(incident),
                                 # From the RECORD, not the environment. An ordinary `recover`
                                 # dispatch supplies no `lhpc_ref`, so reading the environment
                                 # here turned a recorded rehearsal into an ordinary child that
                                 # was allowed to publish — the record-based locks stopped at
                                 # this boundary. A rehearsal's child is a rehearsal.
                                 "lhpc_ref": "" if att.base_ref == "main" else att.base_ref})
    att.notes.append(f"retry dispatched: run {child}, awaiting its claim")
    ctx.save_attempt(number, att)
    ctx.bot_gh.update_issue(BOT, incident, body=body
                            + f"\n\nThe hold is written. Retry: {BOT_URL}/actions/runs/{child}")
    ctx.summary(f"Retry dispatched as run {child}; this run ends here rather than waiting for "
                f"a child that shares its concurrency group.")


# ---------------------------------------------------------------------------- entry point


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bot")
    ap.add_argument("stage", choices=("plan", "build", "prove", "release", "integrate",
                                      "image", "finalize", "recover"))
    ap.add_argument("--attempt", default="")
    args = ap.parse_args(argv)
    ctx = Ctx()
    try:
        if args.stage == "recover":
            return stage_recover(ctx, args.attempt)
        return {"plan": stage_plan, "build": stage_build, "prove": stage_prove,
                "release": stage_release, "integrate": stage_integrate,
                "image": stage_image, "finalize": stage_finalize}[args.stage](ctx)
    except Stop as stop:
        report_retry_outcome(ctx, f"stopped at {stop.stage} — {stop.observed}")
        _report_stop(ctx, stop)
        return 1
    except Unreadable as exc:
        # An issue wearing the `attempt` label with no record in it. Fail closed, but say the
        # remedy: this reaches EVERY stage, including the two that repair an attempt, and the
        # generic advice ("run recover") cannot work until the label is gone.
        _report_stop(ctx, Stop(
            args.stage, str(exc),
            "If that issue is not an attempt, remove its `attempt` label and re-run. If it is, "
            "its record was lost and the attempt must be settled by hand."))
        return 1
    except BaseException as exc:                                   # noqa: BLE001
        report_retry_outcome(ctx, f"ended unexpectedly ({type(exc).__name__})")
        # Anything at all — an API error, a git failure, a bug here, a cancellation. A run that
        # may already have changed something must never end without saying so, and the reason
        # this bot exists is a red run nobody was told about.
        _report_stop(ctx, Stop(
            args.stage, f"an unexpected {type(exc).__name__} ended this stage: {exc}",
            "The attempt (if any) is left open and keeps blocking new releases. Run `recover` "
            "with its run id to settle and undo it, or `finish` if the release already "
            "stands.", detail=_traceback_tail()))
        raise
    finally:
        shutil.rmtree(ctx.work, ignore_errors=True)


def _traceback_tail(limit: int = 2000) -> str:
    import traceback
    return "```\n" + traceback.format_exc()[-limit:] + "\n```"


def _report_stop(ctx: Ctx, stop: Stop) -> None:
    """Always produce a report. Everything that could fail on the way is optional."""
    att, number = Attempt(run_id=ctx.attempt_id), 0
    try:
        found_number, found = ctx.find_attempt(ctx.attempt_id)
        if found:
            att, number = found, found_number
    except Exception as exc:                                       # noqa: BLE001
        stop.detail = (stop.detail + f"\n\n_the attempt record could not be read: {exc}_")
    expiry = ""
    try:
        expiry = ctx.gh.token_expiry() if ctx.token else ""
    except Exception:                                              # noqa: BLE001
        expiry = ""
    observed = stop.observed
    if number:
        observed += (f"\n\nThe attempt is issue #{number}, state `{att.state}`"
                     + (f", still owes {', '.join(att.owes)}" if att.owes else "") + ".")
    title, body = rp.failure_issue(
        stage=stop.stage, run_url=ctx.run_url, attempt=att, findings=stop.findings,
        observed=observed, next_action=stop.next_action, diagnostics=stop.detail,
        token_expiry=expiry)
    ctx.summary(f"## Stopped at {stop.stage}\n\n{observed}\n\n{stop.next_action}")
    try:
        marker = f"<!--auto-release:{att.run_id or ctx.run_id}-->"
        existing = [i for i in ctx.bot_gh.open_issues(BOT, "auto-release")
                    if marker in (i.get("body") or "")]
        if existing:
            ctx.bot_gh.comment(BOT, existing[0]["number"], body + f"\n{marker}\n")
        else:
            ctx.bot_gh.create_issue(BOT, title, body + f"\n{marker}\n", ["auto-release"])
    except Exception as exc:                                       # noqa: BLE001
        print(f"could not open the failure issue: {exc}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
