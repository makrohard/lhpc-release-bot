"""A blocked attempt is re-recovered by every scheduled run (the plan names it, release.yml's
recover job settles it). Recovery reports — the note in the attempt record and the comment in the
attempt's issue — only when its outcome CHANGED since the last report for that attempt; the same
outcome again leaves the run red and its job summary saying why, nothing more.

Driven through `main`, the path a scheduled run takes: `recover --attempt`, the record read from
and written back to its issue body, the stop reported into the attempt's issue."""
from __future__ import annotations

from bot import cli
from bot.attempt import Attempt
from tests.test_transaction import _RecoverCtx, v3entry


class _Issues:
    """The bot repository's issues, with labels: the attempt record and its failure issue."""

    def __init__(self):
        self.issues, self.notes = {}, {}

    def open_issues(self, repo, label):
        return [{"number": n, "title": i["title"], "body": i["body"]}
                for n, i in self.issues.items() if i["state"] == "open" and label in i["labels"]]

    def create_issue(self, repo, title, body, labels):
        n = len(self.issues) + 1
        self.issues[n] = {"title": title, "state": "open", "body": body, "labels": list(labels)}
        self.notes[n] = []
        return {"number": n}

    def comment(self, repo, number, body):
        self.notes[number].append(body)

    def update_issue(self, repo, number, **fields):
        self.issues[number].update(fields)


class _Run(_RecoverCtx):
    """One scheduled run whose recover job settles attempt 100. Everything but the bot's issues
    comes from `_RecoverCtx`; the record lives in its issue body and is read the real way."""
    open_attempts, find_attempt, save_attempt = (
        cli.Ctx.open_attempts, cli.Ctx.find_attempt, cli.Ctx.save_attempt)
    token, version = "", ""

    def __init__(self, issues, run_id, tmp_path, **world):
        super().__init__(fragment=None, live=[v3entry("8")], snapshot=[v3entry("8")], **world)
        self.bot_gh, self.run_id, self.attempt_id = issues, run_id, "100"
        self.run_url = f"https://example.invalid/run/{run_id}"
        self.work = tmp_path / run_id
        self.work.mkdir()


def _blocked(issues, tmp_path, unsettled=True):
    """Attempt 100 left open by its own stop (issue #2 carries that report). Its publish reply
    was lost: no run id, so no recovery can settle it."""
    att = _Run(issues, "seed", tmp_path).att
    att.branch = "pins/0.3.16-100"         # a `mutated` record names its candidate branch
    att.validate()
    if unsettled:
        del att.runs["binary:meshtastic"]
    issues.create_issue(cli.BOT, "attempt 100 — mutated", att.to_body(), [cli.LABEL])
    issues.create_issue(cli.BOT, "stopped at build", "the first report\n<!--auto-release:100-->\n",
                        ["auto-release"])


def _record(issues) -> Attempt:
    return Attempt.from_body(issues.issues[1]["body"])


def _recover(monkeypatch, issues, tmp_path, run_id, **world):
    run = _Run(issues, run_id, tmp_path, **world)
    monkeypatch.setattr(cli, "Ctx", lambda: run)
    assert cli.main(["recover", "--attempt", "100"]) == 1, "a blocked recovery is a red run"
    return run


def test_three_runs_on_one_blocked_attempt_report_once(monkeypatch, tmp_path):
    issues = _Issues()
    _blocked(issues, tmp_path)
    runs = [_recover(monkeypatch, issues, tmp_path, r) for r in ("201", "202", "203")]
    assert len(issues.notes[2]) == 1 and "/run/201" in issues.notes[2][0]
    assert [n for n in _record(issues).notes if n.startswith("recovery could not settle")] == [
        "recovery could not settle: meshtastic dispatched with no recorded run, so its publisher "
        "cannot be identified or waited for"]
    assert list(issues.issues) == [1, 2], "no new issue"
    # The quiet runs still say why they are red, in their own job summary.
    for run in runs[1:]:
        assert any("has not stopped" in s and "already reported" in s for s in run.summaries)


def test_a_changed_outcome_is_reported_again(monkeypatch, tmp_path):
    """Outcome A, then B (a second publish found without its run), then A again: three
    outcomes, each a change, so three reports and three notes."""
    issues = _Issues()
    _blocked(issues, tmp_path)
    _recover(monkeypatch, issues, tmp_path, "201")
    att = _record(issues)
    att.dispatched.append("meshcore")
    issues.issues[1]["body"] = att.to_body()
    _recover(monkeypatch, issues, tmp_path, "202")
    att = _record(issues)
    att.dispatched.remove("meshcore")
    issues.issues[1]["body"] = att.to_body()
    _recover(monkeypatch, issues, tmp_path, "203")
    assert len(issues.notes[2]) == 3
    assert all(f"/run/{r}" in b for r, b in zip(("201", "202", "203"), issues.notes[2], strict=True))
    notes = [n for n in _record(issues).notes if n.startswith("recovery could not settle")]
    assert len(notes) == 3 and "meshcore" in notes[1] and "meshcore" not in notes[2]


def test_a_record_written_before_the_field_existed_reports_its_first_recovery(monkeypatch,
                                                                             tmp_path):
    issues = _Issues()
    _blocked(issues, tmp_path)
    body = issues.issues[1]["body"]
    assert body.count('  "last_report": "",\n') == 1
    issues.issues[1]["body"] = body.replace('  "last_report": "",\n', "")
    _recover(monkeypatch, issues, tmp_path, "201")
    _recover(monkeypatch, issues, tmp_path, "202")
    assert len(issues.notes[2]) == 1
