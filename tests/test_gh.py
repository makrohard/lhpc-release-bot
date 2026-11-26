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
    (_http(500), 5), (_http(502), 5), (_http(429), 60), (_http(403, x_ratelimit_remaining="0"), 60),
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


NOW = 1_800_000_000.0


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(gh.time, "time", lambda: NOW)


def test_a_primary_rate_limit_waits_until_its_reset_then_tries_again(api, clock, capsys):
    """Run 45733062517 died in prove and in recover on a spent hourly quota: three short waits
    end long before the reset. The reset the reply names is waited for, and the wait is logged."""
    spent = _http(403, x_ratelimit_remaining="0", x_ratelimit_reset=str(int(NOW) + 1800))
    api["script"] = [spent, OK]
    assert GitHub("t").get("/repos/o/r/x") == {"status": "ahead"}
    assert api["calls"] == ["GET", "GET"] and api["slept"] == [1801]
    assert "rate limit" in capsys.readouterr().err


@pytest.mark.parametrize("headers", [
    {"x_ratelimit_remaining": "0", "x_ratelimit_reset": str(int(NOW) - 30)},
    {"x_ratelimit_remaining": "0", "x_ratelimit_reset": str(int(NOW) + 2)},
    {"x_ratelimit_remaining": "4000", "x_ratelimit_reset": str(int(NOW) + 3000)}],
    ids=["reset-past", "reset-soon", "secondary-with-primary-reset"])
def test_a_reset_counts_only_for_a_spent_quota_and_never_below_the_fallback(api, clock, headers):
    """A past or imminent reset is not a reason to send again within seconds (thousands of tries
    in the budget); a secondary limit's headers name the primary quota's reset, not its own."""
    body = b"You have exceeded a secondary rate limit."
    api["script"] = [_http(403, body=body, **headers), OK]
    assert GitHub("t").get("/repos/o/r/x") == {"status": "ahead"}
    assert api["slept"] == [60]


def test_a_retry_after_beyond_the_short_wait_is_waited(api, clock):
    api["script"] = [_http(429, retry_after="120"), OK]
    assert GitHub("t").get("/repos/o/r/x") == {"status": "ahead"}
    assert api["slept"] == [120]


def test_a_403_whose_body_says_rate_limit_is_waited_out(api, clock):
    body = b'{"message": "API rate limit exceeded for installation ID 1."}'
    api["script"] = [_http(403, body=body), OK]
    assert GitHub("t").get("/repos/o/r/x") == {"status": "ahead"}
    assert api["slept"] == [60]


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_a_write_refused_by_a_rate_limit_is_tried_again(api, clock, method):
    """A rate-limited reply is a refusal: nothing was written, so sending it again is safe."""
    api["script"] = [_http(429, retry_after="30"), OK]
    assert GitHub("t").request(method, "/repos/o/r/x", {"a": 1}) == {"status": "ahead"}
    assert api["calls"] == [method, method] and api["slept"] == [30]


def test_rate_limit_waits_stop_at_the_budget_then_raise(api, clock):
    api["script"] = [_http(429, retry_after="600")] * 8
    with pytest.raises(GitHubError) as err:
        GitHub("t").get("/repos/o/r/x")
    assert err.value.rate_limited and api["slept"] == [600] * 6     # 6 x 10 min <= 65 min
    assert len(api["calls"]) == 7


def test_a_reset_beyond_the_budget_raises_without_waiting(api, clock):
    api["script"] = [_http(403, x_ratelimit_remaining="0", x_ratelimit_reset=str(int(NOW) + 7200))]
    with pytest.raises(GitHubError) as err:
        GitHub("t").get("/repos/o/r/x")
    assert err.value.rate_limited and api["calls"] == ["GET"] and api["slept"] == []


@pytest.mark.parametrize("failure,limited", [
    (_http(429, retry_after="99999"), True),
    (_http(403, x_ratelimit_remaining="0", x_ratelimit_reset=str(int(NOW) + 99999)), True),
    (_http(403, body=b"API rate limit exceeded", retry_after="99999"), True),
    (_http(403), False), (_http(500), False)],
    ids=["429", "403-remaining-0", "403-body", "403-permission", "500"])
def test_the_error_says_whether_it_was_a_rate_limit(api, clock, failure, limited):
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


@pytest.mark.parametrize("first,then,want", [
    ({"object": {"type": "commit", "sha": "c" * 40}}, None, "c" * 40),
    ({"object": {"type": "tag", "sha": "a" * 40}}, {"object": {"sha": "c" * 40}}, "c" * 40)],
    ids=["lightweight", "annotated"])
def test_a_tag_resolves_to_its_commit_whether_lightweight_or_annotated(api, first, then, want):
    """The plan's tag checks compare the tag's COMMIT with main; an annotated tag's own object
    sha would never be on main."""
    api["script"] = [json.dumps(first).encode()] + ([json.dumps(then).encode()] if then else [])
    assert GitHub("t").ref("o/r", "tags/v0.14.0") == want


def test_a_missing_tag_is_empty(api):
    api["script"] = [_http(404)]
    assert GitHub("t").ref("o/r", "tags/v0.14.0") == ""
