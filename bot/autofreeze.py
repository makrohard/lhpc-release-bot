"""Holding a stack that an upstream update broke, so the rest keep releasing.

This module decides three things and touches nothing: WHICH stack regressed, WHAT that stack's
composition is, and WHAT the policy edit holding it looks like. The stages do the recovering,
the issue and the push.

The rule that shapes all of it: a freeze is only ever written for a failure that names its own
stack. An infrastructure failure, an unreadable one, or one that could belong to a neighbour
gets an ordinary failure report and no hold at all. Guessing which upstream change broke a run
is exactly the thing that would quietly pin the wrong stack for weeks.
"""
from __future__ import annotations

import json
import re
import tomllib

# What the release lane writes at a genuine per-stack assertion. The lane owns the grammar; this
# is the only place that reads it, and an annotation that does not match is not attribution.
# The grammar `lhpc_testlab.release.stack_regression` publishes, copied deliberately: the lane
# owns it and documents it, and this is the only program that reads it. Searched, never anchored
# — pytest prefixes explanation lines with "E   " and the message with "AssertionError: ". The
# trailing boundary matters: without it `phase=installx` would read as `install`.
REGRESSION = re.compile(r"STACK-REGRESSION stack=(?P<stack>[a-z0-9][a-z0-9_-]*) "
                        r"phase=(?P<phase>install|build|start|readiness)(?=\s|$)")

# The label an incident wears. Deliberately NOT the `attempt` label: an attempt blocks the next
# release until it is settled, and a hold that has already been recovered and written must not.
LABEL = "auto-freeze"


# The child claims its work by commenting this on the incident, BEFORE it mutates anything.
# A parent cannot tell a dispatch that was never sent from one whose reply was lost, so it does
# not try: it asks the incident whether a child has claimed the retry, and only one can.
CLAIM = "auto-freeze-claim: run "


def claimed_by(comments) -> str:
    """The run id that claimed this incident's retry, or ""."""
    for c in comments:
        body = (c.get("body") or "")
        if CLAIM in body:
            return body.split(CLAIM, 1)[1].split()[0].strip()
    return ""


class Unholdable(RuntimeError):
    """A stack cannot be held, for a reason that is about the source rather than the failure."""


def attributed_stacks(evidence: str) -> list:
    """Every stack the evidence explicitly blames, newest-first order not implied.

    Reading a failing CASE NAME instead would be wrong: `test_release_chat` can fail while
    stopping the stack before it, or while the fake daemon is being prepared, and freezing chat
    for that would hold the wrong thing indefinitely.
    """
    return sorted({m["stack"] for m in REGRESSION.finditer(evidence or "")})


def stack_inputs(manifest_text: str, stacks, policy: dict) -> dict:
    """{policy key: why} — every tracked input to hold so `stacks` keep their composition.

    The whole composition, not only the input that moved. Several upstream changes can land in
    one run, and picking the one to blame is the guess this feature exists to avoid: holding the
    stack as a unit is conservative and reviewable, and the other stacks are unaffected.

    A source shared with another stack is named as such, because holding it holds them too.
    Manual inputs are never included — they do not move anyway — and an `owned-by-pin` input is
    held through its owner, which is where a hold on it would have to live.
    """
    from . import manifest as mf

    wanted = set(stacks)
    where = mf.components_of(manifest_text)
    rules = policy.get("source") or {}
    out: dict = {}
    for src in mf.pinned_sources(manifest_text):
        consumers = {where.get(c, "") for c in src.consumers}
        if not consumers & wanted:
            continue
        rule = rules.get(src.path) or {}
        if rule.get("track", "manual") == "manual":
            continue
        if src.artifact:
            # LHPC resolves every selector on an artifact source to the branch tip and never
            # checks the pin, so writing a hold here would be a lie: the retry would install
            # upstream anyway while the incident said the pin was held. Moving its pin is fine;
            # holding it is not, until the source becomes an ordinary pinned one.
            raise Unholdable(
                f"{src.path} is an artifact source: LHPC resolves it to the branch tip and "
                f"never verifies its pin, so a hold on it would not hold")
        others = sorted(consumers - wanted - {""})
        out[src.path] = ("holds " + ", ".join(sorted(consumers & wanted))
                         + (f"; shared with {', '.join(others)}" if others else ""))
    for name, rule in (policy.get("extra") or {}).items():
        if rule.get("track", "manual") == "manual" or rule.get("kind") == "owned-by-pin":
            continue
        if name not in _EXTRA_STACK:
            # Loud, not silent. Dropping it would leave the retry re-resolving this input while
            # the incident claims the whole composition is held.
            raise ValueError(f"extra.{name} is tracked but no stack owns it in _EXTRA_STACK — "
                             f"a hold could not cover it")
        if _EXTRA_STACK[name] in wanted:
            out[f"extra.{name}"] = f"holds {_EXTRA_STACK[name]}"
    return out


# The non-source inputs, and the stack each belongs to. Small and explicit on purpose: these are
# the only inputs whose stack cannot be read out of the manifest's own component graph.
_EXTRA_STACK = {"graywolf": "graywolf",
                "meshtastic-web": "meshtastic", "meshtastic-cli": "meshtastic"}


UNATTRIBUTED = re.compile(r"UNATTRIBUTED-FAILURE (?P<case>\S+)")


def unattributed_failures(evidence: str) -> list:
    """Failing cases that carried no marker at all."""
    return sorted({m["case"] for m in UNATTRIBUTED.finditer(evidence or "")})


def decide(attributed, moved_keys, manifest_text: str, policy: dict, unattributed=()) -> tuple:
    """`(keys_to_hold, refusal)` — what to freeze for these stacks, or why nothing may be.

    Five ways this refuses, and every one is a case where a hold would be a guess or a lie:

      * nothing named a stack — infrastructure, a cancellation, an unreadable log.
      * a failure named nobody while others were named. It may be what broke them.
      * the source cannot be held at all: LHPC resolves an `artifact` source to the branch tip
        and never checks its pin, so a hold there would not hold.
      * the stack has no input this bot may move (chat's source is manual): an empty edit.
      * the stack moved nothing this run, so this run did not break it.
    """
    if not attributed:
        return {}, "nothing in the evidence named a stack"
    if unattributed:
        return {}, (f"{len(unattributed)} failure(s) named no stack "
                    f"({', '.join(unattributed[:3])}) — a hold beside an unexplained failure "
                    f"would be a guess")
    try:
        keys = stack_inputs(manifest_text, attributed, policy)
        # PER STACK, not over the union: one stack's failure can leave a band held and make a
        # neighbour's marked assertion fail too, and holding the neighbour is the wrong-stack
        # freeze this design exists to avoid.
        moved = set(moved_keys)
        unmoved = [s for s in attributed
                   if not moved & set(stack_inputs(manifest_text, [s], policy))]
    except Unholdable as exc:
        return {}, str(exc)
    if not keys:
        return {}, (f"{', '.join(attributed)} has no input this bot may hold — its sources are "
                    f"manual, so the hold would be empty")
    if unmoved:
        return {}, (f"{', '.join(unmoved)} failed but moved nothing this run — a stack that "
                    f"broke with no changed input of its own needs investigation, not a hold")
    return keys, ""


def freeze_edit(policy_text: str, keys: dict, reason: str) -> str:
    """`policy.toml` with a `freeze` added under each key that has none.

    Written under the key's own `track` line, so the entry still reads as what it tracks with a
    hold on top. An entry that is already frozen is left exactly as it is: a hold somebody else
    wrote, for their own reason, is not this run's to overwrite.

    The result is PARSED and compared before it is returned, because this edits TOML as text and
    a textual edit can land somewhere convincing and wrong — a header that also appears inside a
    comment wins the search, and the freeze then sits at the top level where it holds nothing
    while every later read still finds the entry unfrozen. An incident that says a pin is held
    while it moves is the worst outcome this feature has, so the edit proves itself.
    """
    text = policy_text
    for key in sorted(keys):
        header = (f'[source."{key}"]' if not key.startswith("extra.")
                  else f"[{key}]")
        # Anchored: a header is a line of its own, never a substring of a comment or a value.
        found = re.search(rf"^{re.escape(header)}[ \t]*$", text, re.M)
        if not found:
            raise ValueError(f"policy.toml has no entry {header}")
        start = found.start()
        end = re.compile(r"^\[", re.M).search(text, found.end())
        end = len(text) if end is None else end.start()
        block = text[start:end]
        if re.search(r"^freeze\s*=", block, re.M):
            continue
        # json.dumps produces a TOML-compatible basic string, so a quote or a backslash in the
        # reason cannot end the value early and leave a file that does not parse.
        line = f"freeze = {json.dumps(f'{reason} — {keys[key]}')}\n"
        track = re.search(r"^track\s*=.*\n", block, re.M)
        at = start + (track.end() if track else len(found.group()) + 1)
        text = text[:at] + line + text[at:]
    _verify_edit(policy_text, text, keys)
    return text


def _verify_edit(before_text: str, after_text: str, keys: dict) -> None:
    """The edit did what it said: each key holds a freeze INSIDE its own entry, its tracking rule
    survived, and nothing else appeared."""
    before, after = tomllib.loads(before_text), tomllib.loads(after_text)
    if set(after) != set(before):
        raise ValueError(f"the edit changed the policy's top-level keys: "
                         f"{sorted(set(after) ^ set(before))}")
    for key in keys:
        table, name = (("extra", key.split(".", 1)[1]) if key.startswith("extra.")
                       else ("source", key))
        was, now = before[table][name], after[table][name]
        if not str(now.get("freeze", "")).strip():
            raise ValueError(f"the edit did not hold {key} inside its own entry")
        if now.get("track") != was.get("track"):
            raise ValueError(f"the edit changed what {key} tracks")


def incident_title(stacks) -> str:
    return "auto-freeze: " + ", ".join(sorted(stacks))


def already_open(issues, stacks) -> int:
    """The number of the open incident for exactly these stacks, or 0.

    Deduplicated by the held group, so a stack that fails again next week updates one incident
    instead of opening another every Monday.
    """
    want = incident_title(stacks)
    for issue in issues:
        if issue.get("title", "").strip() == want:
            return int(issue.get("number", 0))
    return 0
