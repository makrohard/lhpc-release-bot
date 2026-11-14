"""One API call that fails: which failures are tried again, and which are not.

Every stage waits on GitHub. One 500, one rate limit or one cut reply used to end the stage; in a
four-hour proof wait that rolled a green candidate back. A read is tried again; a write never is,
because a lost reply may hide a write that happened.
"""
from __future__ import annotations

import email.message
import http.client
import io
import json
import urllib.error

import pytest

from bot import gh
from bot.gh import GitHub, GitHubError


def _http(code, body=b"detail", **headers):
    msg = email.message.Message()
    for k, v in headers.items():
        msg[k.replace("_", "-")] = v
    return urllib.error.HTTPError("https://api.invalid/x", code, "said", msg, io.BytesIO(body))


class _Reply:
    def __init__(self, raw):
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        if isinstance(self._raw, Exception):
            raise self._raw
        return self._raw


@pytest.fixture
def api(monkeypatch):
    """`script` is what each call answers, in order: an exception to raise, or reply bytes."""
    state = {"script": [], "calls": [], "slept": []}

    def urlopen(req, timeout):
        state["calls"].append(req.get_method())
        step = state["script"].pop(0)
        if isinstance(step, urllib.error.HTTPError | urllib.error.URLError):
            raise step
        return _Reply(step)

    monkeypatch.setattr(gh.urllib.request, "urlopen", urlopen)    # the fake: no network
    monkeypatch.setattr(gh.time, "sleep", state["slept"].append)
    return state


OK = json.dumps({"status": "ahead"}).encode()


@pytest.mark.parametrize("failure,slept", [
    (_http(500), 5), (_http(502), 5), (_http(429), 5), (_http(403, x_ratelimit_remaining="0"), 5),
    (_http(403, retry_after="30"), 30), (urllib.error.URLError("timed out"), 5),
    (http.client.IncompleteRead(b"{"), 5), (b"<html>not json</html>", 5)],
    ids=["500", "502", "429", "403-remaining-0", "403-retry-after", "network",
         "incomplete-read", "bad-json"])
def test_a_get_that_failed_on_something_passing_is_tried_again(api, failure, slept):
    api["script"] = [failure, OK]       # an IncompleteRead is raised by read(), as in urllib
    assert GitHub("t").get("/repos/o/r/x") == {"status": "ahead"}
    assert api["calls"] == ["GET", "GET"] and api["slept"] == [slept]


class _CutBody(io.BytesIO):
    def read(self, *a):
        raise http.client.IncompleteRead(b"<ht")


def test_an_error_whose_body_is_cut_short_is_still_a_retried_github_error(api):
    """The status line arrived, the body did not: the status alone decides."""
    cut = urllib.error.HTTPError("https://api.invalid/x", 500, "said", email.message.Message(),
                                 _CutBody())
    api["script"] = [cut, OK]
    assert GitHub("t").get("/repos/o/r/x") == {"status": "ahead"}
    assert api["calls"] == ["GET", "GET"] and api["slept"] == [5]


def test_a_get_that_keeps_failing_is_tried_four_times_then_raises(api):
    api["script"] = [_http(503)] * 4
    with pytest.raises(GitHubError, match="-> 503"):
        GitHub("t").get("/repos/o/r/x")
    assert api["calls"] == ["GET"] * 4 and api["slept"] == [5, 15, 45]


@pytest.mark.parametrize("failure", [_http(403), _http(404), _http(422)],
                         ids=["403-permission", "404", "422"])
def test_a_get_refused_for_good_raises_at_once(api, failure):
    api["script"] = [failure]
    with pytest.raises(GitHubError):
        GitHub("t").get("/repos/o/r/x")
    assert api["calls"] == ["GET"] and api["slept"] == []


def test_a_retry_after_beyond_the_cap_raises_without_waiting(api):
    api["script"] = [_http(429, retry_after="120")]
    with pytest.raises(GitHubError):
        GitHub("t").get("/repos/o/r/x")
    assert api["calls"] == ["GET"] and api["slept"] == []


@pytest.mark.parametrize("failure,limited", [
    (_http(429, retry_after="120"), True), (_http(403, x_ratelimit_remaining="0"), True),
    (_http(403), False), (_http(500), False)],
    ids=["429", "403-remaining-0", "403-permission", "500"])
def test_the_error_says_whether_it_was_a_rate_limit(api, failure, limited):
    """The upstream reader skips a rate-limited source for the week; any other refusal stays a
    fault. It reads that from the error, decided once, here."""
    api["script"] = [failure] * 4
    with pytest.raises(GitHubError) as err:
        GitHub("t").get("/repos/o/r/x")
    assert err.value.rate_limited is limited


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_a_write_is_never_tried_again(api, method):
    api["script"] = [_http(502)]
    with pytest.raises(GitHubError, match="-> 502"):
        GitHub("t").request(method, "/repos/o/r/x", {"a": 1})
    assert api["calls"] == [method] and api["slept"] == []


def test_a_reply_that_is_not_json_is_a_github_error_not_a_crash(api):
    api["script"] = [b"<html>"] * 4
    with pytest.raises(GitHubError):
        GitHub("t").get("/repos/o/r/x")


def test_ancestry_is_false_only_when_github_does_not_know_the_commits(api):
    api["script"] = [_http(404)]
    assert GitHub("t").is_ancestor("o/r", "a" * 40, "b" * 40) is False
    api["script"] = [_http(500)] * 4
    with pytest.raises(GitHubError, match="-> 500"):
        GitHub("t").is_ancestor("o/r", "a" * 40, "b" * 40)


ARTIFACTS = json.dumps({"artifacts": [{"name": "out", "archive_download_url": "https://x.invalid",
                                       "created_at": "2026-01-01T00:05:00Z"}]}).encode()


@pytest.mark.parametrize("call,before", [
    (lambda g: g.ref("o/r", "tags/v0.14.0"), []),
    (lambda g: g.file_at("o/r", "pyproject.toml", "c" * 40), []),
    (lambda g: g.release_by_tag("o/r", "v0.14.0"), []),
    (lambda g: g.is_ancestor("o/r", "a" * 40, "b" * 40), []),
    (lambda g: g.artifact("o/r", 6, "out", 1), [ARTIFACTS])],      # the attempt's start time
    ids=["ref", "file_at", "release_by_tag", "is_ancestor", "attempt-started"])
def test_a_server_error_that_mentions_a_404_is_not_a_404(api, call, before):
    """Each of these reads a 404 as "absent". The error text carries the response body, so a
    500 whose body says "-> 404" read as absent too: a tag, a file, a release, an ancestry or an
    attempt that is there would have been reported missing."""
    api["script"] = before + [_http(500, body=b"upstream comparison -> 404") for _ in range(4)]
    with pytest.raises(GitHubError) as err:
        call(GitHub("t"))
    assert err.value.status == 500

