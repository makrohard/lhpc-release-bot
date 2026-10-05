"""Every GitHub call this bot makes, in one place, behind one class the tests replace.

Two credentials, deliberately kept apart:

  * the **release token** (`AUTO_RELEASE_TOKEN`) touches the three product repositories;
  * the bot repository's own `GITHUB_TOKEN` writes the attempt and failure issues, so a run
    whose release token is dead can still say so.

Nothing here decides anything. Every refusal lives in the caller.
"""
from __future__ import annotations

import contextlib
import json
import time
import urllib.error
import urllib.request

from .redaction import scrub

API = "https://api.github.com"
# The version whose workflow-dispatch response carries the run id, so a caller never has to
# guess which run it started.
API_VERSION = "2026-03-10"
TERMINAL = ("completed",)
# GitHub's own words for a job whose runner went away. Nothing else counts as runner loss.
RUNNER_LOST = ("The runner has received a shutdown signal", "lost communication with the server",
               "was not acquired by Runner")


class GitHubError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Turns a redirect into an `HTTPError` instead of following it, so the caller decides what
    to send to the new host. Used for artifact downloads, where following would replay this
    bot's credential at a storage host that neither needs nor accepts it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, token: str, api: str = API):
        self._token, self._api = token, api

    # ---- transport -------------------------------------------------------------------------

    def request(self, method: str, path: str, body=None, accept="application/vnd.github+json"):
        url = path if path.startswith("http") else f"{self._api}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._token}", "Accept": accept,
            "X-GitHub-Api-Version": API_VERSION, "User-Agent": "lhpc-release-bot",
            **({"Content-Type": "application/json"} if data else {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw and accept.endswith("json") else raw
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise GitHubError(f"{method} {url} -> {exc.code}: {detail}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise GitHubError(f"{method} {url} -> {exc}") from None

    def get(self, path):
        return self.request("GET", path)

    # ---- identity and access ---------------------------------------------------------------

    def whoami(self) -> dict:
        return self.get("/user")

    def token_expiry(self) -> str:
        """'' when the token does not expire or the header is absent."""
        req = urllib.request.Request(f"{self._api}/user", headers={
            "Authorization": f"Bearer {self._token}", "User-Agent": "lhpc-release-bot"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.headers.get("github-authentication-token-expiration", "") or ""
        except (urllib.error.URLError, OSError):
            return ""

    # ---- refs ------------------------------------------------------------------------------

    def ref(self, repo: str, ref: str) -> str:
        """The commit a ref points at; '' when it does not exist."""
        try:
            obj = self.get(f"/repos/{repo}/git/ref/{ref}")["object"]
        except GitHubError as exc:
            if "-> 404" in str(exc):
                return ""
            raise
        if obj["type"] == "tag":
            return self.get(f"/repos/{repo}/git/tags/{obj['sha']}")["object"]["sha"]
        return obj["sha"]

    def file_at(self, repo: str, path: str, ref: str) -> str:
        """One file's text at one commit. "" when it is not there — the caller decides whether
        an absent file is a problem, because for a candidate that predates it, it is."""
        try:
            got = self.get(f"/repos/{repo}/contents/{path}?ref={ref}")
        except GitHubError as exc:
            if "-> 404" not in str(exc):
                raise           # a rate limit is not "the candidate does not ship this file"
            return ""
        if got.get("encoding") != "base64":
            return ""
        import base64
        return base64.b64decode(got.get("content", "")).decode("utf-8", "replace")

    def tag_message(self, repo: str, tag: str) -> str:
        obj = self.get(f"/repos/{repo}/git/ref/tags/{tag}")["object"]
        if obj["type"] != "tag":
            return ""
        return self.get(f"/repos/{repo}/git/tags/{obj['sha']}").get("message", "")

    # ---- workflows -------------------------------------------------------------------------

    def dispatch(self, repo: str, workflow: str, ref: str, inputs: dict | None = None) -> int:
        """Start a workflow and return ITS run id — not a guess from a title or a timestamp."""
        body = {"ref": ref}
        if inputs:
            body["inputs"] = inputs
        got = self.request("POST", f"/repos/{repo}/actions/workflows/{workflow}/dispatches",
                           body)
        if not isinstance(got, dict) or "workflow_run_id" not in got:
            raise GitHubError(f"dispatch of {workflow} did not return a run id: {got!r}")
        return int(got["workflow_run_id"])

    def run(self, repo: str, run_id: int) -> dict:
        return self.get(f"/repos/{repo}/actions/runs/{run_id}")

    def jobs(self, repo: str, run_id: int, attempt: int = 0) -> list:
        """The jobs of ONE attempt. Without the attempt the endpoint returns the latest, so a
        re-run of the same run would answer for a different execution than the one recorded."""
        path = (f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs"
                if attempt else f"/repos/{repo}/actions/runs/{run_id}/jobs")
        return self.get(f"{path}?per_page=100")["jobs"]

    def cancel(self, repo: str, run_id: int) -> None:
        # Already finished, or already cancelling: both are the state we wanted.
        with contextlib.suppress(GitHubError):
            self.request("POST", f"/repos/{repo}/actions/runs/{run_id}/cancel")

    def wait(self, repo: str, run_id: int, timeout_s: float, poll_s: float = 30.0,
             rerun: bool = True) -> dict:
        """Block until the run is terminal. A timeout returns the run as it stands — the caller
        must then settle the writer, because a run that timed out here is still running there.

        A first attempt that only lost a runner (`runner_lost`) has its failed jobs re-run ONCE
        and is waited on again under the same id; the returned run then carries `rerun`
        (the attempt that was re-run and its lost jobs). Any other red comes back as it is.
        ONE bound covers both attempts — the caller's job has its own timeout around it — so a
        re-run is asked for only while the time left is at least the time already spent.
        `rerun=False` for runs that are being settled, not judged."""
        start = time.monotonic()
        deadline, reran = start + timeout_s, None
        while True:
            run = self.run(repo, run_id)
            if reran:
                run["rerun"] = reran
            # After the re-run request the run still reads as the old, finished attempt until
            # GitHub has started the new one; that old answer is not the result.
            done = (run.get("status") in TERMINAL
                    and not (reran and run.get("run_attempt", 1) <= reran["attempt"]))
            if done:
                lost = [] if (reran or not rerun) else self.runner_lost(repo, run)
                # Measured AFTER the classification: its HTTP calls spend the same bound.
                now = time.monotonic()
                if not lost or deadline - now < now - start:
                    return run
                try:
                    self.request("POST", f"/repos/{repo}/actions/runs/{run_id}/rerun-failed-jobs")
                except GitHubError as exc:
                    run["rerun_error"] = str(exc)
                    return run
                reran = {"attempt": run.get("run_attempt", 1), "jobs": lost}
            elif time.monotonic() >= deadline:
                run["timed_out"] = True
                return run
            time.sleep(poll_s)

    def runner_lost(self, repo: str, run: dict) -> list:
        """The names of the jobs that lost their runner when re-running this finished first
        attempt's failed jobs is warranted, else [].

        Warranted when at least one failed job lost its runner — GitHub's own check-run
        annotation in `RUNNER_LOST`, never the log, where a real failure can print the same
        words — and every other failed job is COLLATERAL: it `needs` a lost job, directly or
        through other jobs, per the run's own workflow file at the run's commit, and it started
        only after that lost job had ended. A file that cannot be read or understood re-runs
        nothing. A second attempt never qualifies: once per run.

        Why a collateral job may run again. GitHub skips a job whose `needs` failed, so the
        only one that can fail beside a lost job is an `if: always()` job that ran knowing its
        input was missing — the images workflow's publish-tag, which refuses to publish one
        variant without the other. Whether such a job wrote anything before failing is not
        something the API can tell; what it can tell is that the job ran AFTER the loss, so it
        failed on the loss and not on its own. Not publishing half is the workflow's own
        contract, and the re-run is that same job once more with its input present."""
        if (run.get("conclusion") not in ("failure", "cancelled")
                or run.get("run_attempt", 1) != 1):
            return []
        run_id = int(run["id"])
        failed = [j for j in self.jobs(repo, run_id, 1)
                  if j.get("conclusion") not in ("success", "skipped", "neutral")]
        lost = [j for j in failed if self._said_runner_lost(repo, j["id"])]
        if not lost:
            return []
        # Read and understood BEFORE anything is re-run, even when every failed job was lost:
        # a workflow this cannot read is one whose re-run it cannot reason about.
        try:
            graph = workflow_needs(self.file_at(repo, run.get("path", "").split("@")[0],
                                                run.get("head_sha", "")))
        except (GitHubError, ValueError):
            return []
        if len(lost) < len(failed):
            for job in failed:
                if job in lost:
                    continue
                key = job_key(graph, job.get("name", ""))
                needs = needed_by(graph, key) if key else set()
                after = [j for j in lost if job_key(graph, j.get("name", "")) in needs
                         and j.get("completed_at") and job.get("started_at")
                         and job["started_at"] >= j["completed_at"]]
                if not after:
                    return []
        return [j.get("name", str(j["id"])) for j in lost]

    def _said_runner_lost(self, repo: str, job_id: int) -> bool:
        try:
            said = " ".join(a.get("message", "") for a in self.get(
                f"/repos/{repo}/check-runs/{job_id}/annotations?per_page=100"))
        except GitHubError:
            said = ""
        return any(m in said for m in RUNNER_LOST)

    def artifact(self, repo: str, run_id: int, name: str, attempt: int) -> bytes:
        """One run artifact as a zip; b'' when the run has no artifact of that name.

        The download endpoint answers a redirect to a signed URL and REFUSES an `Accept` it does
        not recognise: asking for `application/zip` is a 415 before any redirect. So it is asked
        with the ordinary API `Accept` and the body is taken as bytes — the artifact is a zip
        because that is what the endpoint serves, not because of what was asked for.
        """
        arts = self.get(f"/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100")
        named = [a for a in arts.get("artifacts", []) if a["name"] == name]
        art = self._judged_artifact(repo, run_id, named, attempt) if named else None
        return self._signed_download(art["archive_download_url"]) if art else b""

    def _judged_artifact(self, repo: str, run_id: int, named: list, attempt: int) -> dict | None:
        """Which of a run's same-named artifacts belongs to `attempt`, the attempt the caller
        recorded and judges — never whichever attempt GitHub reports now, which somebody else
        may have started since.

        The run's artifact list spans every attempt. An upload made between this attempt's
        start and the next attempt's start is this attempt's own; the newest of those is taken.
        A job a re-run carried over is NOT run again, and its upload keeps its old date — the
        build whose output the re-run tests and publishes. Such an artifact is accepted only
        when it predates every job of the previous attempt that failed: a job the lost ones
        waited for. A lost job's own last-moment upload comes after that job started, and is
        refused. So is an artifact a parallel successful job uploaded after a failed job
        started; it reads as absent, the evidence is unproven, as it is today without a
        re-run."""
        start = self._attempt_started(repo, run_id, attempt)
        end = self._attempt_started(repo, run_id, attempt + 1) or "\uffff"
        if not start:
            return None
        named = sorted(named, key=lambda a: a.get("created_at", ""), reverse=True)
        own = [a for a in named if start <= a.get("created_at", "") < end]
        if own:
            return own[0]
        carried = [a for a in named if a.get("created_at", "") < start]
        if attempt == 1 or not carried:
            return None
        failed = [j.get("started_at") or "" for j in self.jobs(repo, run_id, attempt - 1)
                  if j.get("conclusion") not in ("success", "skipped", "neutral")]
        if not failed or not all(failed):
            return None
        return carried[0] if carried[0].get("created_at", "") < min(failed) else None

    def _attempt_started(self, repo: str, run_id: int, attempt: int) -> str:
        """When one attempt of a run started; '' when there is no such attempt."""
        try:
            got = self.get(f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}")
        except GitHubError as exc:
            if "-> 404" in str(exc):
                return ""
            raise
        return got.get("run_started_at", "")

    def _signed_download(self, url: str) -> bytes:
        """The artifact endpoint's redirect, followed BY HAND.

        Two things about it break the ordinary path. It refuses an `Accept` it does not know, so
        asking for `application/zip` is a 415 before any redirect; and it answers 302 to a
        storage URL that is ALREADY signed, which urllib would follow while re-sending our
        `Authorization: Bearer ...` — the storage host rejects that with 401
        `InvalidAuthenticationInfo`, and replaying one host's credential at another is not
        something to do by accident in the first place.

        So: ask with the ordinary API `Accept`, do not follow, and fetch the signed URL with no
        credential at all. The URL is never quoted in an error — it IS the credential.
        """
        req = urllib.request.Request(url, method="GET", headers={
            "Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION, "User-Agent": "lhpc-release-bot"})
        try:
            with urllib.request.build_opener(_NoRedirect).open(req, timeout=60) as r:
                return r.read()                      # no redirect: the bytes came straight back
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                detail = exc.read().decode("utf-8", "replace")[:400]
                raise GitHubError(f"GET {url} -> {exc.code}: {detail}") from None
            location = exc.headers.get("Location")
        except (urllib.error.URLError, OSError) as exc:
            raise GitHubError(f"GET {url} -> {exc}") from None
        if not location:
            raise GitHubError(f"GET {url} -> redirect with no Location")
        try:
            signed = urllib.request.Request(location, headers={"User-Agent": "lhpc-release-bot"})
            with urllib.request.urlopen(signed, timeout=120) as r:
                return r.read()
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
            code = getattr(exc, "code", exc)
            raise GitHubError(f"the signed artifact download failed -> {code}") from None

    def artifact_member(self, repo: str, run_id: int, artifact: str, suffix: str,
                        attempt: int) -> bytes:
        """The first member of a run artifact whose name ends with `suffix`.

        This is how a child build's own evidence is read: its validated fragment, or the JUnit
        the release lane wrote. Reading it from the artifact binds the evidence to the run that
        produced it, which nothing derived from live state can do.
        """
        import io
        import zipfile
        blob = self.artifact(repo, run_id, artifact, attempt)
        if not blob:
            return b""
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for name in zf.namelist():
                if name.endswith(suffix):
                    return zf.read(name)
        return b""

    def release_asset(self, repo: str, tag: str, name: str) -> bytes:
        """A release asset read through the AUTHENTICATED API.

        Never the public download URL: that is served by a CDN which can hand back the previous
        bytes for a while after a pointer switch, and a rollback decision taken on stale bytes
        would be a decision about the past.
        """
        rel = self.release_by_tag(repo, tag)
        for asset in rel.get("assets", []):
            if asset["name"] == name:
                return self.request("GET", f"/repos/{repo}/releases/assets/{asset['id']}",
                                    accept="application/octet-stream")
        raise GitHubError(f"{repo} release {tag} has no asset {name!r}")

    def job_log(self, repo: str, job_id: int) -> str:
        try:
            raw = self.request("GET", f"/repos/{repo}/actions/jobs/{job_id}/logs",
                               accept="text/plain")
        except GitHubError:
            return ""
        return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)

    # ---- issues ----------------------------------------------------------------------------

    def open_issues(self, repo: str, label: str) -> list:
        """EVERY open issue with the label, paginated. A page limit here would let an older
        unresolved attempt hide behind newer ones."""
        out, page = [], 1
        while True:
            batch = self.get(f"/repos/{repo}/issues?state=open&labels={label}"
                             f"&per_page=100&page={page}")
            if not batch:
                return out
            out.extend(batch)
            if len(batch) < 100:
                return out
            page += 1

    # Every issue this bot writes is a public page, and its bodies quote diagnostics that were
    # produced somewhere else — a git error, a traceback, an API message. Scrubbing at THIS
    # boundary means a new caller cannot forget to do it.
    def unfinished_runs(self, repo: str, workflow: str) -> list:
        """Runs of one workflow that have not finished. Answers the only question that can settle
        a dispatch whose run id was never recorded: is anything still writing?

        Every non-terminal status, not just `in_progress`. A queued run is the COMMON case here —
        the build matrix is `max-parallel: 1`, so a second stack waits its turn — and calling a
        publisher that has not started yet "settled" is exactly the conclusion that loses a
        release.
        """
        out = []
        for status in ("queued", "in_progress", "waiting", "requested", "pending"):
            got = self.get(f"/repos/{repo}/actions/workflows/{workflow}/runs"
                           f"?status={status}&per_page=100")
            out.extend(got.get("workflow_runs") or [])
        return out

    def create_issue(self, repo: str, title: str, body: str, labels) -> dict:
        return self.request("POST", f"/repos/{repo}/issues",
                            {"title": scrub(title), "body": scrub(body),
                             "labels": list(labels)})

    def update_issue(self, repo: str, number: int, **fields) -> dict:
        fields = {k: scrub(v) if k in ("title", "body") else v for k, v in fields.items()}
        return self.request("PATCH", f"/repos/{repo}/issues/{number}", fields)

    def comments(self, repo: str, number: int) -> list:
        """Every comment on one issue. Used to ask whether a retry has been claimed — the
        incident is the shared record, and the only place a parent and its child can both see."""
        return list(self.get(f"/repos/{repo}/issues/{number}/comments?per_page=100") or [])

    def comment(self, repo: str, number: int, body: str) -> dict:
        return self.request("POST", f"/repos/{repo}/issues/{number}/comments",
                            {"body": scrub(body)})

    # ---- releases --------------------------------------------------------------------------

    def release_by_tag(self, repo: str, tag: str) -> dict:
        try:
            return self.get(f"/repos/{repo}/releases/tags/{tag}")
        except GitHubError as exc:
            if "-> 404" in str(exc):
                return {}
            raise

    def is_ancestor(self, repo: str, ancestor: str, descendant: str) -> bool:
        """Does `descendant` contain `ancestor`? Asked of GitHub so no clone is needed."""
        if ancestor == descendant:
            return True
        try:
            got = self.get(f"/repos/{repo}/compare/{ancestor}...{descendant}")
        except GitHubError:
            return False
        return got.get("status") in ("identical", "ahead")

    def pull_request(self, repo: str, head: str, base: str, title: str, body: str) -> dict:
        """Open the pull request, or return the one that is already open for this head.

        A stage that opened a PR and then failed to write its record must be able to run again:
        GitHub answers 422 for a duplicate head, and treating that as an error made the repair
        impossible forever. The existing PR is the outcome this wanted.
        """
        try:
            return self.request("POST", f"/repos/{repo}/pulls",
                                {"head": head, "base": base,
                                 "title": scrub(title), "body": scrub(body)})
        except GitHubError as exc:
            if "-> 422" not in str(exc):
                raise
            owner = repo.split("/")[0]
            existing = self.get(f"/repos/{repo}/pulls?head={owner}:{head}&state=open")
            if existing:
                return existing[0]
            raise


# ---- a workflow's job graph ------------------------------------------------------------------
# Only what a re-run needs: each job's key, display name and `needs`. Read line by line from the
# `jobs:` block, because the bot has no YAML parser and must not grow a dependency for three
# keys. Anything this does not recognise raises ValueError, and the caller re-runs nothing.

def _scalar(text: str) -> str:
    text = text.split(" #")[0].strip()
    if text[:1] in "'\"" and text[-1:] == text[:1] and len(text) > 1:
        text = text[1:-1]
    if not text or any(c in text for c in "{}[]&*|>") or "${{" in text:
        raise ValueError(f"not a plain scalar: {text!r}")
    return text


def workflow_needs(text: str) -> dict:
    """{job key: (display name, set of needed job keys)} of a workflow file's `jobs:` block."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    try:
        start = lines.index("jobs:") + 1
    except ValueError:
        raise ValueError("no top-level jobs: block") from None
    jobs, key, attr_indent, job_indent, open_list = {}, None, None, None, None
    for ln in lines[start:]:
        bare = ln.lstrip()
        if not bare or bare.startswith("#"):
            continue
        indent = len(ln) - len(bare)
        if indent == 0:
            break                                       # the next top-level key
        if job_indent is None:
            job_indent = indent
        if indent == job_indent:
            if not bare.endswith(":"):
                raise ValueError(f"unexpected job line: {bare!r}")
            key = _scalar(bare[:-1])
            jobs[key] = [key, set()]
            attr_indent, open_list = None, None
            continue
        if indent < job_indent or key is None:
            raise ValueError(f"unexpected line: {bare!r}")
        if attr_indent is None:
            attr_indent = indent
        if indent > attr_indent:
            if open_list is not None and bare.startswith("- "):
                open_list.add(_scalar(bare[2:]))
            continue                                    # inside some other attribute
        open_list = None
        name, _, value = bare.partition(":")
        value = value.split(" #")[0].strip()
        if name == "name":
            jobs[key][0] = _scalar(value)
        elif name == "needs":
            if not value:
                open_list = jobs[key][1]
            elif value.startswith("[") and value.endswith("]"):
                jobs[key][1].update(_scalar(v) for v in value[1:-1].split(",") if v.strip())
            else:
                jobs[key][1].add(_scalar(value))
    if not jobs:
        raise ValueError("no jobs")
    for _key, (_name, needs) in jobs.items():
        if needs - jobs.keys():
            raise ValueError(f"needs an unknown job: {sorted(needs - jobs.keys())}")
    return {k: (n, frozenset(d)) for k, (n, d) in jobs.items()}


def job_key(graph: dict, api_name: str) -> str:
    """The workflow key of a job as the API names it — the display name, with a matrix job's
    values appended in parentheses. '' when no job, or more than one, matches."""
    hits = [k for k, (name, _) in graph.items()
            if api_name == name or api_name.startswith(f"{name} (")]
    return hits[0] if len(hits) == 1 else ""


def needed_by(graph: dict, key: str) -> set:
    """Every job `key` waits for, directly or through other jobs."""
    seen, todo = set(), list(graph[key][1])
    while todo:
        k = todo.pop()
        if k not in seen:
            seen.add(k)
            todo.extend(graph[k][1])
    return seen
