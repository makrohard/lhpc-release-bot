# Changelog

Milestones only.

## Unreleased

- src/reticulum, src/lxmf and src/nomadnet are no longer held: the controller now stops RNS 1.6.1
  (LHPC testlab release-verify 45779297917, 18/18, on cons/c1-rns161-r4).
- A GitHub rate limit no longer ends a stage: the call (any method; a rate-limited reply wrote
  nothing) waits for its `Retry-After`, else (quota spent) its `X-RateLimit-Reset` but at least
  60 s, else 60 s, logs the wait and tries again, up to 65 min of waits per call; a 403 whose
  body says "rate limit" counts too.
- A run the bot has just started is waited for while GitHub does not know it yet: a 404 on its
  id (up to 3 min) no longer ends the stage, and a builder missing from the runs list no longer
  starts a second image build on the same tag. A 404 past that window still fails, naming the run.
- A run blocked by an unresolved attempt recovers the oldest one itself; one that cannot be settled
  provably (e.g. an unrecorded publisher) stays open, so the scheduled run stays red until settled.
- A recovery that stops the same way again (every scheduled run re-recovers a blocked attempt)
  adds no note and no comment: only a changed outcome is reported. The run stays red and its job
  summary says why. Upgrade: attempt records gain `last_report`; a bot older than this cannot
  read a record that has it, so do not roll the bot back past this while an attempt is open.
  A withdrawal or rollback that fails the same way again is the same outcome, although each
  recovery dispatches a new rollback run. Upgrade: an attempt blocked on one is reported once more.
- Recovery never settles a publish whose run id was lost (the attempt stays open); a release is
  recorded only when `main` and the tag both name the candidate, whatever the push answered.
- Recovery withdraws an unproven attempt's own binaries from index-v3.json (installed copies stay);
  a same-file entry of another run, or one without `build_run`, stays and the attempt stays open.
- A re-run of the build stage waits on the build it recorded instead of dispatching a second
  publisher of the same stack.
- A scheduled run pushes one empty "heartbeat" commit when this repository's main has had no
  commit for 28 days, so GitHub never switches the weekly schedule off.
- The attempt record keeps the index-v3 snapshot as one short key per entry, so it stays far
  below GitHub's issue-body cap; records holding whole entries still read.
- The plan stops, nothing pushed, unless main's version is tagged on main and the next tag is
  free; a rate-limited upstream is skipped for the week instead of stopping every move.
- One GitHub blip no longer strands an attempt: a run id is kept from its dispatch reply, and a
  failed read is tried again (4 tries; never a write).
- Binaries go into the index the candidate's manifest names: `index.json`, or the history
  `index-v3.json`. A web-client move republishes only an artifact that still records it; a dry
  run shows which.
- New `web` stage (weekly, or mode `web`): rebuilds the Meshtastic web client's `dev` or `stable`
  build when the one a box would take is not upstream's current commit; problems open an issue.
- A release cut from a `main` that carries LHPC's `## Unreleased` section turns that section into
  the release (the moves first), so its notes hold dev's items too.
- The plan stops before pushing anything when a moved component raised a dependency floor its
  LHPC constraints file does not allow (naming the requirement and the pin where provable),
  or when LHPC's `requirements.lock` is not what its pyproject resolves to on Python 3.13.

## 0.1.0

- First version. Weekly (and on demand) it moves the pins its policy allows, republishes the
  binaries those pins cover, proves the result with the controller's release-verification lane,
  releases a patch and cuts the image — or releases nothing and says why.
- The daemon, RadioLib and the shared chat source are reported, never moved: the lab retargets
  them at fakes, so a moved pin would not be exercised at all.
- The Meshtastic web client and CLI ARE moved. Either move forces the Meshtastic binary to be
  republished: the client ships inside that artifact, and the CLI's recorded version ships in the
  completion marker that artifact carries, even though the venv itself is built on the box.
- A pin can be frozen: one reason string in `policy.toml` holds that input while everything else
  keeps releasing. Refused where it would hold nothing, and never expiring on its own.
- The bot freezes a stack itself when the lane's evidence names it as the one that failed, opens
  an incident and retries once. It acts on an explicit per-stack assertion, never on a job name
  or a case name, and refuses whenever the hold would be a guess.
- A run that published anything records it in an `attempt` issue here, which outlives the run
  and blocks the next release until the attempt is finished or undone.
