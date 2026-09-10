# lhpc-release-bot

The scheduled pin release for [`loraham-pi-control`](https://github.com/makrohard/loraham-pi-control).

Once a week it asks what has moved upstream, and if anything has: moves the pins, rebuilds the
binaries those pins cover, proves the result in the test lab, releases a patch, and cuts the
image. It opens an issue saying what it found and what state it left behind whenever it stops.

There is one moment that cannot be undone. Before it, a failure restores everything the run
changed and releases nothing. After it — `main` and its tag pushed together — the release
stands, and what is left is finished or repaired rather than reversed.

It exists because the pins are what a NEW box gets. Existing boxes update themselves; a fresh
image carries whatever the manifest pinned on the day it was built, and keeping that current by
hand across three repositories is a procedure nobody runs weekly.

## Contents

- [What it moves](#what-it-moves)
- [What it does](#what-it-does)
- [What you see](#what-you-see)
- [Freeze a pin](#freeze-a-pin)
- [Running it, pausing it, retrying it](#running-it-pausing-it-retrying-it)
- [When something is left behind](#when-something-is-left-behind)
- [The token](#the-token)
- [Working on the bot](#working-on-the-bot)

## What it moves

`policy.toml` is the whole answer, and every pinned source in the manifest must appear in it —
a source with no rule stops the run rather than being moved by a rule nobody wrote.

| tracks | meaning |
|---|---|
| `tip` | the declared branch's tip |
| `tag` | the newest version-shaped tag on that branch (`v1.2.3`, `1.5.2`, `v112`) |
| `release` | the newest GitHub release that is neither a draft nor a prerelease |
| `manual` | reported every run, never moved |

A move is only ever forward and only ever on the branch the manifest declares: the candidate
must be a descendant of the current pin and an ancestor of the tip. A rewritten history, an
orphaned pin or a tag that left the branch is a fault, and a fault stops the run.

**It does not move the daemon, RadioLib or the shared chat source.** Not because they are
risky, but because the lab SUBSTITUTES them: its manifest overlay retargets those two sources at
local fakes, so a moved pin would not be exercised by one instruction. Those pins move by hand,
with the box
[test matrix](https://github.com/makrohard/loraham-pi-control/blob/main/docs/test-matrix.md).

Chat is not faked. Its source is the daemon's repository, so the lab builds and runs the real
Chat program; what is substituted is the DAEMON it talks to. What that costs is worth stating per
stack, because the lab has more than one backend:

| stack | what it runs against in the lane |
|---|---|
| daemon, chat, kiss, voice, graywolf | the FAKE daemon's implementation of the v112 wire protocol |
| reticulum | its own SPI driver compiled against the FAKE RadioLib |
| meshtastic | the real `meshtasticd`, on upstream's own `Module: sim` radio |
| meshcom | the real firmware, in QEMU |
| meshcore | the real openHop node |

So a green lane is real evidence for the last three and evidence against a fake for the rest.

**Two pins that are not git sources are moved.** The Meshtastic browser client is named in the
manifest by release version and by the sha256 of that release's `build.tar`; the bot fetches the
archive, hashes it, moves both, and — because the client ships INSIDE the Meshtastic artifact —
forces that binary to be republished. The Meshtastic CLI is a pip version in a build step, and its
venv is built on the box, so the box installs the new CLI itself. What the artifact carries is
the web client's BYTES and, beside the built binary, a record of both versions — and that record
is why moving either one forces the republish. Both also move the matching
`build_inputs` entry, which is what makes an already-built box notice the bump at all. Graywolf is
the third: its release version plus the three checksum rows the fetch script verifies.

A non-git pin moves forward only, like a git one. There is no history to walk, so the versions
are ordered instead: GitHub lists releases newest-CREATED first, and a hotfix on an older line
would otherwise be written into the manifest as a downgrade.

Every run reports every tracked input with a status, so a green run never implies more than it
proved.

## What it does

| stage | what it changes | what stops it |
|---|---|---|
| plan | pushes a candidate branch | no access, an unresolved earlier attempt, a policy gap, an upstream fault, nothing moved |
| build | publishes the candidate binaries | a build, its smoke test or its clean-runtime test |
| prove | nothing | any required job on the candidate that is not `success`, or any release-lane case the candidate requires by name that did not pass — missing and skipped included |
| release | `main` and its tag, in ONE atomic push; the candidate branch is removed | `main` moved meanwhile, or the tag exists |
| integrate | fast-forwards `dev`, or opens a pull request | nothing: its failure never unmakes the release |
| image | tags `loraham-images`, waits for both variants | a red build, a draft release, missing evidence, or a tag that no longer names this release's controller |
| finalize | closes the attempt | anything still owed: it stays open instead |

When a stage before the commit point fails, recovery restores the index and deletes the candidate branch. If the failure named the stack that broke, it also holds that stack and retries once — see [Freeze a pin](#freeze-a-pin).

The order is forced by the proof: the aarch64 test lab installs MeshCom and Meshtastic from the
published index, so the candidate binaries have to be live before the lane can run. Between that
publish and the proof, a fresh install of a moved stack on the released `main` is refused with
the channel's typed message and offered the source build. Installed boxes are untouched.

## What you see

- **Nothing moved:** a green run, a summary table, no branch, no release.
- **Everything green:** a tag and a one-commit release on `loraham-pi-control`, a new image
  release, older patch images of the current minor line pruned to the newest three, and either a
  fast-forwarded `dev` or a pull request against it. The attempt issue closes itself only once
  both the integration and the image are done.

  **When it opens that pull request, MERGE it — do not squash it.** The PR exists because `dev`
  diverged, and its whole job is to put the release commit back into `dev`'s ancestry. A squash
  copies the content and not the commit, so the release commit never becomes an ancestor, `dev`
  can no longer fast-forward into `main`, and the next release opens the same PR again. It is not
  a style preference: it is the difference between the PR doing its job and only appearing to.
  **This needs `allow_merge_commit` enabled on `loraham-pi-control`** — with merge commits off,
  squash is the only method GitHub offers and the gap cannot be closed at all (rebase-merge does
  not help either: it replays with new SHAs). Measured on 2026-09-10: PR #4 was squash-merged
  because it was the only option, `main` stopped being an ancestor of `dev`, and it took a manual
  rebase of `dev` to repair.
- **Something failed:** one issue **in this repository**, labelled `auto-release`, naming the
  stage, the run, the observed state, the next action, the pin table with compare links, and
  whatever diagnostics could be fetched. It lives here rather than in the controller so that a
  run whose release credential is the thing that failed can still report; this repository's own
  `GITHUB_TOKEN` writes it. Diagnostics are best-effort; the rest is never omitted.

## Freeze a pin

When upstream breaks something, hold that one input and let the rest keep releasing. Add a reason
to its entry in `policy.toml`:

```toml
[source."src/openhop-core"]
track = "tip"
freeze = "Upstream startup regression; hold the tested revision until the fix is verified."
```

The held value is whatever the controller manifest already pins — it is never copied into policy,
so there is one source of truth. Every run still reports the input, its hold and what upstream has
done since, and never counts it as something to move. Delete the line to thaw. There is no expiry:
time passing is not evidence that the problem is fixed.

- **Set or lift a hold while the bot is idle.** Policy is read from the revision a run checked
  out, so a change cannot reach an attempt that has already prepared a candidate. Settle any open
  attempt first.
- **To hold a DIFFERENT revision than the one pinned** — including going back to an older tested
  one — freeze first, then move the pin by the ordinary manual patch: pin, rebuild affected
  binaries, run the lane, release, image. A freeze by itself releases nothing.
- **A hold on a `manual` or an `owned-by-pin` entry is refused.** Neither would hold anything; the
  refusal names the owner to freeze instead.
- A run in which only frozen inputs moved upstream releases nothing at all.

### When the bot freezes one itself

If the release lane fails and its evidence NAMES the stack that failed, the bot holds that
stack's composition itself, opens an incident and retries once with everything else still
advancing. It never guesses: it acts only on an assertion the lane marked as that stack's own
install, build, start or readiness, so an infrastructure failure, a cancelled run, or a case that
failed while stopping its predecessor produces an ordinary failure report and no hold.

It refuses in three more places, each because a hold would be a lie: when the named stack moved
nothing this run, so this run did not break it; when the stack has no input this bot may hold, as
chat does not; and when the policy moved underneath it, which stops the chain rather than
overwriting somebody's edit.

**The regression has to be confined to the release lane.** Any required job other than the lane
going red is treated as a different problem and suppresses the hold — deliberately, because a
lane that blames one stack while something else is also broken is not evidence about that stack.
The practical consequence is worth knowing before you rely on this, stated as what was actually
tested rather than as a general promise. **A failure that also turns the ordinary `testlab` job
red cannot produce a lane attribution.** That was measured on 2026-09-10: a kiss readiness
regression on `main` made the lane emit `STACK-REGRESSION stack=kiss phase=start`, which the
attribution rule read correctly, while six tests in the ordinary job errored at setup with
`Run FAILED for 'kiss'` — so the bot reported an ordinary failure and held nothing.

What that does **not** say is that a stack appearing in the ordinary suite can never be held. It
depends on the failure, not on the stack: a different fault in the same stack need not touch the
ordinary cases at all, and owned binary-build attribution runs earlier and is unaffected by this
rule entirely. For orientation, the same day's count of ordinary-suite files naming each stack was
voice and chat none, kiss and graywolf two each, meshcore and meshcom three — a guide to which
regressions are likely to spill, not a list of what may ever be frozen.

That is the intended trade, not an oversight: the alternative is a rule that can freeze an
upstream pin while the real cause is somewhere else entirely. For a widely-depended-on stack the
bot stops and reports, and a person decides whether to freeze.

The rule is about ATTRIBUTION only. When a hold is already in place and the bot is merely proving
the held baseline, the question is not "which stack may be blamed?" but "does this still pass?" —
and a required job that ran on that commit and concluded failure answers it. So the same
doubly-red shape reads `failed` there while it names nobody here, and the retry that measured it
settles its parent instead of leaving the obligation open for ever.

What it does, in order: recover the attempt and confirm the binary index is back, open or update
one incident labelled `auto-freeze`, write the holds into `policy.toml` on `main`, then dispatch
exactly one retry. The retry cannot retry — a chain would peel stacks off one at a time until
something passed. The incident carries the rejected candidate, the retained one and the retry
link, and it does not block later releases, because by then the attempt is settled.

Lifting it is the same explicit thaw as any other hold. Nothing expires, and a newer upstream
release is not evidence that the problem is fixed.

**Close the incident when you thaw, not later.** A hold and its incident are two pieces of state,
and deleting the `freeze` lines without closing the issue leaves a trap that fires on the NEXT
freeze rather than on the edit that caused it: an automatic freeze updates the open `auto-freeze`
incident instead of opening a fresh one, and that issue still carries the claim comment from the
retry the previous hold already spent. The new retry then reads a claim that is not its own and
stands down — *"run … already claimed this retry"* — dying at `plan` for a reason that has nothing
to do with the stack it was sent to prove. Observed on 2026-09-10, and caught only because the
stale incident was noticed minutes before the next hold was written.

## Running it, pausing it, retrying it

Actions → **release** → Run workflow:

| mode | does |
|---|---|
| `full` | the whole thing (this is what the schedule runs) |
| `watch-only` | reports what has moved and stops — the check to run before a minor release |
| `dry-run` | makes the edit locally, prints the diff, pushes nothing |
| `finish` | finishes whatever an attempt whose controller release already happened still owes — its `dev` integration, its image, or both |
| `recover` | undoes an attempt that stopped before the commit point |

`finish` and `recover` take the attempt's run id, which the attempt issue names.

There is one further input, `lhpc_ref`, and it is **not** for ordinary use. It names the
controller ref an attempt is planned from; empty — which is every real release — means `main`. It
exists so the automatic freeze can be rehearsed against a composition that may be moved and
broken without touching `main` or an upstream default branch. The one retry inherits it.

Such an attempt publishes **nothing**, and that is enforced in three places rather than argued:
the plan refuses a rehearsal whose moves would republish any binary, before dispatching anything;
the build stage refuses outright; and the release stage refuses as well. All three read the
`base_ref` recorded ON THE ATTEMPT, not the environment they happen to run with and not a
comparison of two SHAs — a rehearsal branch may point at exactly the same commit as `main`, and a
recovery brings its own dispatch inputs.

**Before a release is tagged, the release-verification lane must have run on the candidate.** Not
on the `main` push afterwards: proof that arrives after the thing it was meant to gate is not a
gate. For a hand-made patch that means dispatching it on the release branch first:

```sh
gh workflow run testlab.yml --ref <release-branch> -f release_verify=true
```

**The schedule is gated in this file, not in a setting.** A cron in the source proves nothing
about whether scheduled publishing is on — the workflow is enabled server-side and the event
fires regardless. So a scheduled run stops immediately unless the repository variable
`SCHEDULE_ENABLED` is `true`. To turn weekly publishing on: Settings → Secrets and variables →
Actions → Variables → `SCHEDULE_ENABLED` = `true`; to turn it off, remove it. Manual dispatch
works either way.

To pause everything including manual runs: Actions → release → **Disable workflow**. GitHub also
disables an idle schedule after about 60 days.

## When something is left behind

A run that publishes binaries or pushes a release records what it did in an **issue in this
repository**, labelled `attempt`. The issue, not a run artifact: artifacts expire, and the
record has to outlive the run that made it.

While such an issue is open, a new `full` run refuses to start. That is deliberate: the image
builder resolves `main`, so releasing again while an image is owed would make that image
impossible to cut.

An issue that carries the `attempt` label but no record stops every mode, on purpose: the label
is the claim that something was written, and being unable to read it is not the same as nothing
having happened. If it is not an attempt at all, remove the label.

Two ways out, both from the same issue:

- the controller release exists and something after it is missing → `finish`, which re-runs
  the integration and the image in that order and closes the attempt if nothing is left. Both
  stages are idempotent, so one that already completed is a no-op;
- nothing was released → `recover`, which cancels the children, WAITS for them to stop, puts the
  binary index back and deletes the candidate branch.

**If you cannot tell which of those it is, run `recover` on that attempt first.** The two writes
at the commit point go to two different systems — the atomic push to GitHub, then the state to
this issue — so a run that died between them leaves an issue saying less than the world does. The
issue may read `prepared` or `mutated` under a release that really happened, and `finish` will
refuse it, correctly, for not being past the commit point. `recover` reads `main` and the tag
before it decides anything: if **either** holds this attempt's candidate — `main` at it, or the
tag on it — the release happened, so it rolls nothing back, writes the state the refs prove, and
lists what is still owed. Then `finish` that same attempt. Never
edit the record by hand to get past this — `recover` is what reconciles it.

**What the retry is for.** A hold exists so the OTHER stacks keep releasing. The retry therefore
re-plans with the held pin kept at its last known-working revision and releases everything else
that is eligible — a normal release, with a normal image. Only when nothing else is eligible does
it fall back to proving the held composition once and publishing nothing, because there is then
nothing to release: the manifest already IS the last known-working composition.

That fallback reports one of three answers, and the difference matters. **passed** and **failed**
are both measurements, and either settles the retry — what changes is what you do next, not who
owes the work. **unproven** is neither, and it takes PRECEDENCE over how red the evidence looks:
the lane could not be reached, its artifact was not there, its JUnit would not parse, the
candidate's case list could not be read, the run was cancelled or timed out, the run that came
back was not the one dispatched, or the baseline ref moved while the proof was in flight. Any of
those means nothing about the composition was measured — even if the evidence in front of it is
failing — so nothing is concluded, the retry stays owed, and the run stops saying so. Only a
trustworthy run that actually measured a failure is **failed**. A missing artifact is an
infrastructure fault, and it must never be reported as a broken upstream.

**An attempt that wrote a hold stays open until its retry is SETTLED** — not until it is claimed.
Recovery used to close every attempt it settled, which put the obligation out of reach: `attempt`
issues are looked up by OPEN state, so a closed one answers "no attempt to recover" while the
policy still carries the hold. Now the index is restored and the branch deleted as before, but the
issue stays open, the summary says so, and it keeps blocking unrelated releases — except the one
retry it is owed, which is allowed past its own parent and nothing else's.

**A claim is not a settlement.** The claim only records that a child took the work; the parent is
settled when that child's own outcome is KNOWN — it released with the hold in place, or it proved
the held composition and measured a result. A child that is cancelled or stops halfway leaves the
obligation exactly where it was, deliberately: otherwise a child cancelled one second after
claiming would drop the retry silently and nobody would be answerable for it. The cost is that
such a case ends with a person closing the parent, which is the right party to decide. If no
retry ever runs, close it by hand once you have decided what to do with the hold (the incident
names the `freeze` lines to delete).

Two ways that obligation ends other than a green retry, both observed:

- **the retry crashes.** One hold gets one retry, and a crashed child has spent it: no other run
  may claim that incident. `recover` on the PARENT is the way out — it reconciles the child that
  did claim, settles the parent and stops it blocking. The hold itself stands until you thaw it.
- **the retry releases but `finalize` does not run** (cancelled, or skipped). Run
  **`finish` on the CHILD** — the attempt that released, whose id is in the incident and in the
  parent's record. Not on the parent: the parent was restored and released nothing, and `finish`
  refuses it for that reason, because pointing a repair at a rejected candidate would integrate
  and tag something no release stands behind. Finishing the child re-runs what is missing, closes
  it, and settles the parent with the child's own identity — you do not have to reconstruct the
  automatic dispatch's retry inputs, and the finish run's own id is never recorded as the retry.

Recovery settles before it restores. A rollback that raced a publisher still running would be
undone by it a minute later, so a writer that will not stop keeps the attempt open instead. A
publish whose own run id was never recorded — a dispatch whose reply was lost — is settled the
only way it can be: nothing is concluded about it while any build is still running.

Recovery reads `main` and the tag before deciding anything. A missing checkpoint never proves a
push did not happen — the reply may have been lost — and rolling binaries back under a released
controller would leave every box that self-updated pointing at an index that cannot satisfy it.
When those refs prove the release, recovery also **writes that state back** — but only over a
record that has not yet reached the commit point and is still open. A candidate that needed no
binary publish is `prepared` for its whole proof, so that is the shape most likely to be left
behind by a lost write, and leaving it there made the attempt permanently unfinishable and
permanently blocking. A `restored` attempt is deliberately **not** promoted: it was rolled back,
its binaries are out of the index, and a ref that happens to match is not evidence it released.
It also refuses to replace an index entry that is not the one this attempt published: another
publish in between is reported as a conflict, never overwritten.

## The token

One fine-grained personal access token, stored here as the repository secret
`AUTO_RELEASE_TOKEN`, with access to `loraham-pi-control`, `lhpc-binaries` and `loraham-images`
and these repository permissions: Contents read/write, Actions read/write, Issues read/write,
Pull requests read/write. It is never given administration; ruleset changes are the
maintainer's own.

The first stage checks it can authenticate and reach all three repositories before anything
else, and reports its expiry in the summary and in every issue. This repository's own
`GITHUB_TOKEN` writes the attempt and failure issues, so a run whose release token has expired
can still say that is what happened.

## Working on the bot

```sh
python -m pytest -q                     # offline: the remotes and GitHub are fakes
ruff check bot tests
python -m tests.policy_covers_manifest  # the one networked check: policy vs the live manifest
```

Decisions live in `bot/upstream.py`, `bot/manifest.py`, `bot/changelog.py`, `bot/attempt.py` and
the pure helpers in `bot/cli.py`; they are unit-tested. `bot/gh.py` holds the GitHub API calls
and `bot/cli.py` the stages. It is not the only code that reaches the network: `bot/upstream.py`
fetches upstream repositories with `git` and reads PyPI, and the stages clone and push with
`git`. What is true is that every stage's DECISION is a function that takes data.
