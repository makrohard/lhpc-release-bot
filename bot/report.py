"""What a run says about itself: the summary it always writes, and the issue it opens when it
stops.

The rule for both: the parts that cost nothing are never omitted, and the parts that need
another API call are best-effort. A failure with no diagnostics still has to produce a usable
report — the original problem this bot exists to fix was a red run nobody was told about.
"""
from __future__ import annotations

COMPARE = "https://github.com/{repo}/compare/{a}...{b}"


def _repo_of(remote: str) -> str:
    import re
    m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", remote or "")
    return m.group(1) if m else ""


def findings_table(findings) -> str:
    """Every tracked input with its status — moved, at the pin, reported only, or faulty."""
    icon = {"move": "→", "at-pin": "=", "manual": "·", "fault": "!", "frozen": "❄"}
    rows = ["| | input | tracks | now | upstream | note |", "|---|---|---|---|---|---|"]
    for f in findings:
        repo = _repo_of(f.remote)
        cur = f.current[:9] if len(f.current) == 40 else (f.current or "—")
        if f.candidate and f.candidate != f.current:
            cand = f.candidate[:9] if len(f.candidate) == 40 else f.candidate
            if repo and len(f.current) == 40 and len(f.candidate) == 40:
                cand = f"[{cand}]({COMPARE.format(repo=repo, a=f.current, b=f.candidate)})"
            if f.tag:
                cand += f" `{f.tag}`"
        else:
            cand = "—"
        rows.append(f"| {icon.get(f.status, '?')} | `{f.key}` | {f.track} | `{cur}` | {cand} "
                    f"| {f.detail or ''} |")
    return "\n".join(rows)


def scope_note() -> str:
    return ("This run moves git pins, the Graywolf release and the Meshtastic web-client and "
            "CLI pins — the last two also force a meshtastic binary republish, because the "
            "artifact carries the client's bytes and a record of both versions. The daemon and "
            "RadioLib stay manual, and so does the shared Chat source: the lab substitutes the "
            "daemon Chat talks to, so their proof is the box test matrix.")


def summary(findings, decision: str, extra: str = "") -> str:
    moved = [f for f in findings if f.moves]
    faults = [f for f in findings if f.status == "fault"]
    # Frozen inputs are counted apart from the movable ones and stay in the tracked total: a
    # deliberate hold must be visible every week without being mistaken for something to do.
    frozen = [f for f in findings if f.status == "frozen"]
    head = [f"## {decision}", "", scope_note(), "",
            f"**{len(moved)} input(s) to move**, {len(faults)} fault(s), "
            + (f"{len(frozen)} frozen, " if frozen else "")
            + f"{len(findings)} tracked in total.", ""]
    if frozen:
        head += ["Held on purpose, and not moved by this run:", ""]
        head += [f"- `{f.key}` — {f.detail or 'held'}" for f in frozen] + [""]
    if extra:
        head += [extra, ""]
    return "\n".join(head) + findings_table(findings) + "\n"


def upstream_log(remote, findings, limit: int = 30) -> str:
    """`git log old..new` per moved source — the fastest answer to "what actually changed"."""
    blocks = []
    for f in findings:
        if not f.moves or len(f.current) != 40:
            continue
        try:
            lines = remote.log(f.remote, f.branch, f.current, f.candidate, limit)
        except Exception as exc:                                   # noqa: BLE001
            blocks.append(f"### {f.key}\n\n_log unavailable ({exc})_\n")
            continue
        body = "\n".join(lines) or "(no commits listed)"
        blocks.append(f"### {f.key}\n\n```\n{body}\n```\n")
    return "\n".join(blocks)


def error_extract(log_text: str, tail: int = 80) -> str:
    """The `::error::` lines a workflow annotated, then the tail of its log. Both, because the
    annotations name the cause and the tail shows what surrounded it."""
    if not log_text:
        return "_no job log was available._"
    errors = [ln.split("::error::", 1)[1].strip()
              for ln in log_text.splitlines() if "::error::" in ln][:20]
    lines = log_text.splitlines()[-tail:]
    out = ""
    if errors:
        out += "**Annotated errors**\n\n```\n" + "\n".join(errors) + "\n```\n\n"
    return out + "**Last lines of the failing job**\n\n```\n" + "\n".join(lines) + "\n```\n"


def failure_issue(*, stage: str, run_url: str, attempt, findings, observed: str,
                  next_action: str, diagnostics: str = "", token_expiry: str = "") -> tuple:
    """(title, body). Everything cheap is unconditional; `diagnostics` is what could be
    fetched."""
    title = f"auto-release: stopped at {stage}"
    body = [f"The scheduled release run stopped at **{stage}**.", "",
            f"- run: {run_url}",
            f"- controller `main` at start: `{attempt.base_sha[:9] or '?'}`",
            f"- version it would have released: `{attempt.version or '?'}`",
            f"- attempt state: `{attempt.state}`",
            "", "### Observed state", "", observed, "",
            "### What happens next", "", next_action, ""]
    if token_expiry:
        body += [f"_The release token expires {token_expiry}._", ""]
    body += ["### Inputs", "", scope_note(), "", findings_table(findings), ""]
    if diagnostics:
        body += ["### Diagnostics", "", diagnostics, ""]
    body += ["### Retry", "",
             "Run the workflow again from the Actions tab. Upstream may have moved on, so the "
             "retry re-reads it rather than replaying this attempt's candidates. A run that "
             "left something behind is listed as an open `attempt` issue and must be resolved "
             "first.", ""]
    return title, "\n".join(body)


def incident(att, keys: dict, run_url: str) -> str:
    """The body of an automatic-freeze incident: what is held, why, and how to lift it.

    It has to answer one question weeks later — is this still needed? — so it names the rejected
    candidate as well as the retained one, and says plainly that nothing here expires. A newer
    upstream release is not evidence that the problem is fixed.
    """
    rows = ["| held input | why |", "|---|---|"]
    rows += [f"| `{k}` | {v} |" for k, v in sorted(keys.items())]
    return "\n".join([
        f"**{', '.join(att.regression)}** failed on candidate `{att.candidate_sha[:9]}` and is "
        f"held at the composition released as {att.base_sha[:9]}.",
        "",
        f"- attribution: {att.evidence or 'the release lane'}",
        f"- the run that stopped: {run_url}",
        f"- attempt: {att.run_id}, recovered — the binary index was restored and nothing was "
        f"released",
        f"- rejected candidate: `{att.candidate_sha}`",
        "",
        *rows,
        "",
        "Other stacks keep releasing. One retry is owed with these holds in place, and it must "
        "prove every stack — including the held one — before anything is published. Whether it "
        "was actually dispatched is appended below; nothing above this line asserts it.",
        "",
        "**This does not expire.** Neither a newer upstream release nor closing this issue lifts "
        "it. When the upstream fix is verified, delete the `freeze` lines named above from "
        "`policy.toml` and let the next run prove the result.",
    ])
