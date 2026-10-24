"""The live manifest and policy.toml must name exactly the same pinned sources.

A run refuses at its first stage when they diverge, which is correct but late: a new pinned
source upstream would be found only on the next release attempt. This says so on every push
here instead. It is the one check that reaches the network, so it lives outside the offline
suite and is run explicitly.

    python -m tests.policy_covers_manifest                      # the manifest on controller main
    python -m tests.policy_covers_manifest --manifest PATH      # a checked-out manifest

Either way main is fetched too: every source main or the checked manifest pins needs its rule, and
a rule counts as live while main, the controller's `dev` (fetched here) or the checked manifest pins
its source: a new source's rule lands before it reaches dev, while main still lags.

The second form is what the controller's own CI runs on every push, against its checked-out
manifest and this repository's `policy.toml` at main: a new pinned source cannot merge there
without its rule here.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

from bot.manifest import pinned_sources
from bot.upstream import freeze_of, load_policy, policy_gaps

MANIFEST = ("https://raw.githubusercontent.com/makrohard/loraham-pi-control/main"
            "/lhpc/data/manifest.example.toml")
DEV_MANIFEST = MANIFEST.replace("/main/", "/dev/")


def _fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode()


def main() -> int:
    args = sys.argv[1:]
    if args and not (args[:1] == ["--manifest"] and len(args) == 2):
        print("usage: python -m tests.policy_covers_manifest [--manifest PATH]", file=sys.stderr)
        return 2
    main_text = _fetch(MANIFEST)
    text = Path(args[1]).read_text() if args else main_text
    policy = load_policy(Path(__file__).resolve().parents[1] / "policy.toml")
    sources = pinned_sources(text)
    # A candidate never replaces main: main's sources still need their rules (a run checks main),
    # and a rule stays live while main, dev or the candidate pins its source.
    required = sorted({s.path for s in sources} | {s.path for s in pinned_sources(main_text)})
    gaps = policy_gaps(policy, required, [s.path for s in pinned_sources(_fetch(DEV_MANIFEST))])
    for gap in gaps:
        print(f"::error::{gap}")
    # A frozen input is still tracked and still reported every run; it is simply not movable
    # today. Counting it as movable would make this line disagree with what a run actually does.
    held = {f"extra.{n}" if table == "extra" else n
            for table in ("source", "extra")
            for n, rule in (policy.get(table) or {}).items()
            if freeze_of(rule or {}, n)[0]}
    moved = [p for p, rule in policy["source"].items()
             if rule.get("track") != "manual" and p not in held]
    print(f"{len(sources)} pinned source(s) on main; {len(moved)} of them movable by this bot; "
          f"{len(policy.get('extra', {}))} further tracked input(s)"
          + (f"; {len(held)} frozen: {', '.join(sorted(held))}" if held else ""))
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
