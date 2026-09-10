"""No credential may reach anything this bot writes.

The auditor reproduced the whole chain with a dummy token: the clone URL embeds the credential,
git repeats the failing command in its error, and the catch-all handler puts that error into a
public issue. These cases hold each link shut.
"""
from __future__ import annotations

import pytest

from bot.gh import GitHub
from bot.redaction import PLACEHOLDER, scrub

TOKEN = "ghp_notarealtoken0123456789"   # noqa: S105 (a fixture, deliberately token-shaped)


@pytest.fixture
def _token(monkeypatch):
    monkeypatch.setenv("AUTO_RELEASE_TOKEN", TOKEN)


def test_a_token_this_process_holds_never_survives_into_text(_token):
    assert TOKEN not in scrub(f"fatal: could not read Username for {TOKEN}")


def test_a_credential_inside_a_url_goes_even_when_it_is_not_ours():
    """A run may hold a credential this process never read. The URL shape is redacted on sight,
    so a token from anywhere else cannot ride out in a clone error."""
    out = scrub("git clone https://x-access-token:someone-elses@github.com/o/r.git: denied")
    assert "someone-elses" not in out
    assert out.startswith(f"git clone https://{PLACEHOLDER}@github.com/o/r.git")


def test_the_git_error_that_carries_the_clone_url_is_already_scrubbed(
        _token, monkeypatch, tmp_path):
    """The failure the auditor reproduced: a clone that fails names the URL it was given."""
    from bot import cli

    class Failed:
        returncode, stdout, stderr = 1, "", "remote: Invalid username or password"

    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: Failed())
    with pytest.raises(RuntimeError) as caught:
        cli.git("clone", "-q", f"https://x-access-token:{TOKEN}@github.com/o/r.git", str(tmp_path))
    assert TOKEN not in str(caught.value)


def test_an_issue_body_is_scrubbed_however_it_was_assembled(_token):
    """The last link, and the one that matters: a diagnostic assembled anywhere at all still
    cannot publish a credential, because the scrub happens where the text leaves the process."""
    sent = {}

    gh = GitHub(TOKEN)
    gh.request = lambda method, path, payload=None: sent.update(payload or {}) or {}
    gh.create_issue("o/r", f"stopped: {TOKEN}", f"traceback mentioning {TOKEN}", ["auto-release"])
    assert TOKEN not in sent["title"] and TOKEN not in sent["body"]

    sent.clear()
    gh.update_issue("o/r", 1, body=f"still {TOKEN}")
    assert TOKEN not in sent["body"]

    sent.clear()
    gh.comment("o/r", 1, f"note {TOKEN}")
    assert TOKEN not in sent["body"]


def test_scrubbing_leaves_an_ordinary_report_alone(_token):
    ordinary = "5 pin(s) to move, 0 fault(s); see https://github.com/makrohard/lhpc-binaries"
    assert scrub(ordinary) == ordinary


def test_an_empty_or_tiny_variable_is_not_treated_as_a_secret(monkeypatch):
    """Redacting on a one-character value would delete every occurrence of that character and
    destroy the report it was meant to protect."""
    monkeypatch.setenv("AUTO_RELEASE_TOKEN", "")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    assert scrub("nothing secret here") == "nothing secret here"
