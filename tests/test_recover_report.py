"""A blocked attempt is re-recovered by every scheduled run (the plan names it, release.yml's
recover job settles it). Recovery reports — the note in the attempt record and the comment in the
attempt's issue — only when its outcome CHANGED since the last report for that attempt; the same
outcome again leaves the run red and its job summary saying why, nothing more.

Driven through `main`, the path a scheduled run takes: `recover --attempt`, the record read from
and written back to its issue body, the stop reported into the attempt's issue."""
from __future__ import annotations

import pytest

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


class _Legacy(_RecoverCtx):
    """An attempt that published into index.json (the pointer index): recovery restores the
    snapshot entry through rollback.yml and reads the index back. `withdraw` is what that run
    does: "fail" (the run fails) or "noop" (it succeeds and changes nothing)."""

    def __init__(self, withdraw):
        mine, old = v3entry("6"), v3entry("8")
        super().__init__(fragment=mine, live=[], snapshot=[], withdraw=withdraw)
        self.att.binary_index, self.att.published = "index.json", {"meshtastic": mine}
        self.att.index_snapshot = {"stacks": {"meshtastic": old}}
        self.legacy = {"stacks": {"meshtastic": mine}}

    def release_asset(self, repo, tag, name):
        import json
        assert name == "index.json"
        return json.dumps(self.legacy).encode()

    def dispatch(self, repo, workflow, ref, inputs=None):
        self.dispatches.append((workflow, dict(inputs or {})))
        return 900


class _TagTaken(_RecoverCtx):
    def ref(self, repo, ref):
        return "f" * 40 if ref.startswith("tags/") else super().ref(repo, ref)


def _own_v3(run="777.1"):
    from tests.test_transaction import _own
    return _own(run=run)


def _site(name):
    from tests.test_transaction import core
    old, mine = v3entry("8"), _own_v3()
    if name == "tag-taken":
        return _TagTaken(fragment=core(mine), live=[mine, old], snapshot=[old])
    if name == "unsettled":
        ctx = _RecoverCtx(fragment=None, live=[old], snapshot=[old])
        del ctx.att.runs["binary:meshtastic"]
        return ctx
    if name == "cannot-claim":
        theirs = _own_v3(run="888.1")
        return _RecoverCtx(fragment=core(theirs), live=[theirs, old], snapshot=[old])
    if name == "no-build-run":
        legacy = _own_v3(run=None)
        return _RecoverCtx(fragment=core(legacy), live=[legacy, old], snapshot=[old])
    if name in ("withdraw-fail", "withdraw-noop"):
        return _RecoverCtx(fragment=core(mine), live=[mine, old], snapshot=[old],
                           withdraw=name.split("-")[1])
    return _Legacy(withdraw={"rollback-fail": "fail", "rollback-differs": "noop"}[name])


SITES = {   # every place a recovery stops with a note, and the words of its stop
    "tag-taken": "held by a different commit",
    "unsettled": "has not stopped",
    "cannot-claim": "cannot claim",
    "no-build-run": "without the run that published it",
    "withdraw-fail": "could not be withdrawn",
    "withdraw-noop": "still holds this attempt's entry",
    "rollback-fail": "could not be restored",
    "rollback-differs": "not the snapshot",
}


@pytest.mark.parametrize("site", sorted(SITES))
def test_every_recovery_stop_notes_and_reports_an_unchanged_outcome_once(monkeypatch, tmp_path,
                                                                         site):
    ctx = _site(site)
    ctx.work, ctx.summaries = tmp_path, []
    reported = []
    monkeypatch.setattr(cli, "Ctx", lambda: ctx)
    monkeypatch.setattr(cli, "_report_stop", lambda c, stop: reported.append(stop) or True)
    for _ in range(2):
        tmp_path.mkdir(exist_ok=True)
        assert cli.main(["recover", "--attempt", "100"]) == 1
    assert len(reported) == 1 and SITES[site] in reported[0].observed
    assert len(ctx.att.notes) == len(set(ctx.att.notes)), ctx.att.notes
    assert ctx.att.last_report == ctx.att.notes[-1]


class _FailingComments(_Issues):
    """The bot's issues, whose next `fail` comments raise (an API error, a cut connection)."""

    def __init__(self, fail=1):
        super().__init__()
        self.fail = fail

    def comment(self, repo, number, body):
        if self.fail:
            self.fail -= 1
            raise RuntimeError("HTTP 502")
        super().comment(repo, number, body)


def test_a_report_that_failed_leaves_the_record_as_it_was_and_the_next_run_reports(monkeypatch,
                                                                                  tmp_path):
    issues = _FailingComments(fail=1)
    _blocked(issues, tmp_path)
    record = issues.issues[1]["body"]
    _recover(monkeypatch, issues, tmp_path, "201")
    assert issues.notes[2] == [] and issues.issues[1]["body"] == record
    _recover(monkeypatch, issues, tmp_path, "202")
    assert len(issues.notes[2]) == 1 and "/run/202" in issues.notes[2][0]
    assert _record(issues).last_report.startswith("recovery could not settle")
    _recover(monkeypatch, issues, tmp_path, "203")
    assert len(issues.notes[2]) == 1


def test_a_run_that_dies_after_its_report_reports_again(monkeypatch, tmp_path):
    """Filed, then the record could not be saved (or the job was killed): the outcome is not
    remembered, so the next run reports it once more. Twice is the price; never is not."""
    issues = _Issues()
    _blocked(issues, tmp_path)
    saves, real = [], _Run.save_attempt

    def lost(self, number, att):
        saves.append(att.last_report)
        if len(saves) == 1:
            raise RuntimeError("HTTP 502")
        return real(self, number, att)
    monkeypatch.setattr(_Run, "save_attempt", lost)
    _recover(monkeypatch, issues, tmp_path, "201")
    _recover(monkeypatch, issues, tmp_path, "202")
    _recover(monkeypatch, issues, tmp_path, "203")
    assert saves and saves[-1].startswith("recovery could not settle")
    assert [b.split("/run/")[1][:3] for b in issues.notes[2]] == ["201", "202"]


def test_a_report_refused_outside_release_yml_is_not_remembered(monkeypatch, tmp_path):
    issues = _Issues()
    _blocked(issues, tmp_path)
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", f"{cli.BOT}/.github/workflows/ci.yml@refs/heads/x")
    _recover(monkeypatch, issues, tmp_path, "201")
    assert issues.notes[2] == [] and _record(issues).last_report == ""
