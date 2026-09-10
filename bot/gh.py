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

    def wait(self, repo: str, run_id: int, timeout_s: float, poll_s: float = 30.0) -> dict:
        """Block until the run is terminal. A timeout returns the run as it stands — the caller
        must then settle the writer, because a run that timed out here is still running there."""
        deadline = time.monotonic() + timeout_s
        while True:
            run = self.run(repo, run_id)
            if run.get("status") in TERMINAL:
                return run
            if time.monotonic() >= deadline:
                run["timed_out"] = True
                return run
            time.sleep(poll_s)

    def artifact(self, repo: str, run_id: int, name: str) -> bytes:
        """One run artifact as a zip; b'' when the run has no artifact of that name.

        The download endpoint answers a redirect to a signed URL and REFUSES an `Accept` it does
        not recognise: asking for `application/zip` is a 415 before any redirect. So it is asked
        with the ordinary API `Accept` and the body is taken as bytes — the artifact is a zip
        because that is what the endpoint serves, not because of what was asked for.
        """
        arts = self.get(f"/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100")
        for art in arts.get("artifacts", []):
            if art["name"] == name:
                return self._signed_download(art["archive_download_url"])
        return b""

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

    def artifact_member(self, repo: str, run_id: int, artifact: str, suffix: str) -> bytes:
        """The first member of a run artifact whose name ends with `suffix`.

        This is how a child build's own evidence is read: its validated fragment, or the JUnit
        the release lane wrote. Reading it from the artifact binds the evidence to the run that
        produced it, which nothing derived from live state can do.
        """
        import io
        import zipfile
        blob = self.artifact(repo, run_id, artifact)
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
