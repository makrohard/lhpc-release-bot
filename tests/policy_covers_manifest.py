"""The live manifest and policy.toml must name exactly the same pinned sources.

A run refuses at its first stage when they diverge, which is correct but late: a new pinned
source upstream would be found only on the next release attempt. This says so on every push
here instead. It is the one check that reaches the network, so it lives outside the offline
suite and is run explicitly.

    python -m tests.policy_covers_manifest
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

from bot.manifest import pinned_sources
from bot.upstream import freeze_of, load_policy, policy_gaps

MANIFEST = ("https://raw.githubusercontent.com/makrohard/loraham-pi-control/main"
            "/lhpc/data/manifest.example.toml")


def main() -> int:
    with urllib.request.urlopen(MANIFEST, timeout=60) as r:
        text = r.read().decode()
    policy = load_policy(Path(__file__).resolve().parents[1] / "policy.toml")
    sources = pinned_sources(text)
    gaps = policy_gaps(policy, [s.path for s in sources])
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
