"""Every test runs as a job of the release workflow unless it says otherwise: `_report_stop`
files nothing anywhere else (tests/test_one_reporter.py tests both sides)."""
import pytest

from bot import cli


@pytest.fixture(autouse=True)
def _in_the_release_workflow(monkeypatch):
    monkeypatch.setenv("GITHUB_WORKFLOW_REF",
                       f"{cli.BOT}/.github/workflows/{cli.RELEASE_WORKFLOW}@refs/heads/main")
