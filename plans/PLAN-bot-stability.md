# PLAN bot-stability (v4): the release bot runs for weeks without a person

## Changes v3.1 → v4 (Work round W1b, item C, RED 8; folded into the code, no plan round)
| finding | verdict | change (as built) |
|---|---|---|
| C1 testlab job and pre-JUnit outages outside recovery | accepted as SCOPE | Only release-verify and slow-build write a per-attempt JUnit (the contract with the lanes, agreed with the determinism packet). A red `testlab` job, CI, or a transfer that failed before the JUnit exists stays an ordinary red. The lanes retry their own transfers long first (decision c1). Widening it is one table line plus a JUnit in that job. |
| C2 "ALL failures" needs non-empty evidence; mixed runner-loss/assertion | accepted | A job counts as external only with ≥ 1 failure or error in its JUnit for that attempt, ALL typed `EXTERNAL-UNAVAILABLE what=<token>` and none with `STACK-REGRESSION`. Empty, unreadable or absent JUnit is not evidence. Error elements count. Runner loss keeps its rule: every other failed job must be a collateral `needs` dependant. |
| C3 a build outage must not hold pins | accepted (already so) | A hold is written only from the builder's own attributable evidence (`<stack>.regression` at its compile/apply step, bound to run, attempt and candidate). An outage or a runner failure writes none: an ordinary stop, no policy line (existing control test). A smoke-boot failure is not attributable today, so it is named in the stop (failing job + log lines) but holds nothing: a deviation from v3's "build + boot" wording. |
| C4 a dispatch exception is not a refusal | accepted | Only an HTTP 4xx answer releases the `finish_run` claim; a network error or a 5xx keeps it (maybe accepted) and a later pass sends nothing. |
| C5 claimant | done in v3.1 | — |
| C6 escalation counts and closing | accepted | Occurrences = 1 + distinct run ids of the bot's marked comments (`<!--degraded-run:<id>-->`), once per run; a person's comment does not count; an issue closes only when the run EXAMINED the key and did not find it degraded. |
| C7 240/280-min bounds vs "never killed while progressing" | clarified | Hard limits exist: GitHub's job limit, slow-build's job timeout of 240 min (about 5× the ~45-min real runs) and the bot's 280-min testlab bound. They are stuck-lane guards. The slow-build budget itself judges the non-network part after the fact and kills nothing. A build that is still progressing past 240 min is treated as stuck. Raising the timeout is a controller change, not in this packet. |
| C8 proof specification | accepted | Five re-runs = six attempts (fixture). Parent baseline corrected: a red slow-build ALREADY failed the run's conclusion; what changes is that a missing or skipped slow-build job no longer counts as proof (that is the red-before). |
| numbers | corrected | Base suite at d01d462: 317 passed (v1 cited 280 from a stale checkout). |


## Change v3 → v3.1 (round 3 verdict GREEN WITH NOTES)
- 10: the claim records its claimant: `finish_run = "dispatching:<this workflow run id>"`, replaced by the finish run id on success; a later pass renders the claimant and does not dispatch (test).

## Changes v2 → v3 (round 2 verdict RED, F1–F3, all accepted)
| finding | change |
|---|---|
| F1 "any other red, no freeze" too broad | R: "any other UNMARKED red stops without a freeze; STACK-REGRESSION and builder attribution are unchanged" |
| F2 finish id before the dispatch | 10: claim `finish_dispatching = true` → dispatch → replace by the run id; a definite dispatch failure clears the claim; a crash between leaves the claim (no second dispatch, the summary names it); tests for both states |
| F3 persistence counter off by one | F6 block: occurrences = 1 (the opening) + the issue's comments; persistent at 3; fixture for 1, 2, 3 |
| note | R: the 0/1/2/5/10 index counts EXTERNAL re-runs only; the cap of 5 counts all re-runs |

## Changes v1 → v2 (round 1 verdict RED, F1–F6, all accepted, plus the handler's mixed-counter test)
| finding | change |
|---|---|
| F1 bound ignores the wait | R: a re-run is asked only while `time_left ≥ next_wait + last_attempt_duration` |
| F2 guarantee too broad | R: the guarantee is narrowed to typed EXTERNAL failures in the two JUnit jobs; everything else stays an ordinary unmarked red (no freeze); the acquisition step joins once it writes a typed JUnit line |
| F3 freeze on our own regression | B2a: a failed meshcom build holds only the meshcom sources this candidate MOVED; none moved → an internal-regression report, no freeze |
| F4 "once" without state | 10: `finish_dispatched` on the attempt record, set before the dispatch; a second pass dispatches nothing |
| F5 decisions not neutral | §5: each decision with its alternative and trade-off |
| F6 no escalation | 11 + R: one informational issue per skipped source / unproven gate, counted per run, flagged after 3 consecutive runs, closed when it clears |
| handler | R: red-before for a mixed runner-lost + EXTERNAL sequence on the shared counter |

**Base:** lhpc-release-bot `main` = d01d462 (`python -m pytest -q` → 280 passed). Inputs: BOT-STATE-2026-10-15 (D1–D8), DECISIONS-testlab-determinism (b, c1), PLAN-testlab-determinism v3 §2 M4 (the lane's `EXTERNAL-UNAVAILABLE` message) and §4, PLAN-s5-runner §6, NEXT-RUN items 10/11/12/14/15/17/21.

**Code after** determinism P1/P2 are on controller `dev`, so the lane messages the bot reads exist.

## 0. Facts the plan builds on (file:line at d01d462)
- **Re-run today:** `GitHub.wait` (bot/gh.py:147-183) re-runs a FIRST attempt's failed jobs ONCE when `runner_lost` (gh.py:185-230) finds GitHub's runner-loss annotation (`RUNNER_LOST`, gh.py:27-28). One bound covers both attempts, and a re-run is asked only while the time left ≥ the time already spent (gh.py:172). `_wait` (cli.py:199-222) moves the record to the new attempt and notes it.
- **Required jobs:** `REQUIRED_CI` / `REQUIRED_TESTLAB = ("testlab", "release-verify")` (cli.py:66-67). `BOUNDS["testlab"] = 280 min` (cli.py:69); the prove job's own timeout is 300 min (release.yml:124).
  - Controller testlab.yml job timeouts: testlab 120, release-verify 90, slow-build 240 min (testlab.yml:34, :125, :222). Slow-build runs on `release_verify` dispatches (testlab.yml:217), so it is already in every bot testlab run; only its verdict is not required.
- **Lane failure text:** the release-verify JUnit is read from artifact `testlab-logs-release-verify` / `junit-release.xml` (cli.py:550, 1038); `STACK-REGRESSION` markers → `af.attributed_stacks` (cli.py:1056). Slow-build's JUnit is `slow-build-evidence` / `junit-slow-build.xml` (testlab.yml:348, :412). The testlab job writes no JUnit.
- **Holds:**
  - `_builder_regression` (cli.py:919) blames a stack only from the builder's own `<stack>.regression` evidence at its compile step.
  - `_auto_freeze` (cli.py:1824) writes `freeze` under every source of that stack (`af.decide`, autofreeze.py:123; `af.freeze_edit`, :160) and retries once.
  - Freezes never expire (README.md:136, :190). #62 froze all three meshcom sources (policy.toml:35-45).
- **Stops:**
  - an unreadable upstream is a `fault` (upstream.py:226 "upstream not readable"), and any fault stops at `watch` (cli.py:301-306);
  - an attempt that owes only integrate/image blocks every `full` run until a person dispatches `finish` (cli.py:279-288; `owes`, attempt.py:116-125).
- **Report:**
  - `failure_issue` opens "The scheduled release run stopped …" for every event (report.py:100);
  - build/prove Stops pass no findings, so the Inputs table is empty (BOT-STATE D5).
- **Dry-run** = watch + prepare, the diff is shown, nothing is pushed or dispatched (cli.py:404-408; release.yml:28, :75). It does not reach build or prove.

## 1. Items in this packet
**R — ONE re-run mechanism** (c1 + the existing runner-loss re-run).
- `GitHub.wait` asks one function, `rerunnable(run) -> (reason, jobs)`:
  - `"runner-lost"`: today's rule, first attempt only, once;
  - `"external"`: every failed job is a job whose JUnit failures ALL start with `EXTERNAL-UNAVAILABLE`, read per attempt from a table `JUNIT = {"release-verify": ("testlab-logs-release-verify", "junit-release.xml"), "slow-build": ("slow-build-evidence", "junit-slow-build.xml")}`;
  - else `None`.
  - A job with any other failure, or with no JUnit (the testlab job, CI jobs), is never re-run for `external`.
- **Schedule** for `external`: waits of 0, 1, 2, 5, 10 min before EXTERNAL re-runs 1–5 (18 min of waiting in total), all inside the one existing bound. The wait index counts EXTERNAL re-runs only; the cap of 5 counts every re-run, a runner-lost one included.
  - The time rule generalises: a re-run is asked only while `time_left ≥ next_wait + last_attempt_duration` (the wait before it plus the duration of the attempt just judged); otherwise the attempt just judged is the result.
  - Re-run 6 is never asked. A runner-lost re-run still happens at most once (first attempt only) and shares the same counter.
- **After the schedule** (or when time runs out) with the last attempt still EXTERNAL: the prove result is `unproven-external`. No freeze, no hold, no incident. The issue says "unproven, external: <the EXTERNAL lines>"; the attempt restores and the next schedule tries again.
- A test body is never re-run for its own failure: the re-run is GitHub's `rerun-failed-jobs` of a job whose failures are all typed transfers (the decision).
- **The guarantee, exactly:** a typed `EXTERNAL-UNAVAILABLE` failure in release-verify or slow-build (the jobs that write JUnit) never fails the attempt as a regression and never freezes. Any other UNMARKED red stops the attempt without a freeze, as today; a STACK-REGRESSION marker and the builder's own attribution keep their freeze/hold exactly as today. That covers an outage inside the testlab job or CI, and a failure before the JUnit is written. When the acquisition step (determinism P3/P4) writes its typed line into a JUnit file of its job, that job joins the `JUNIT` table (one line).
- **Files:** bot/gh.py (wait, the classifier), bot/cli.py (`_wait` note, the prove outcome), README "What it does".
- **Red-before** (tests/test_rerun.py, new; the fake GitHub has the real call shapes):
  - a release-verify job with one EXTERNAL failure is re-run after the scheduled waits (sleep spy) and the green attempt is judged. Red at d01d462: no re-run, the run stays red;
  - a job with one EXTERNAL and one other failure is not re-run (control, green on both);
  - five EXTERNAL attempts end in `unproven-external` with no freeze;
  - the runner-loss case keeps its once rule (existing tests unchanged);
  - mixed: attempt 1 runner-lost → re-run 1; attempt 2 EXTERNAL → re-runs 2–5 with waits 0/1/2/5; attempt 6 still EXTERNAL → `unproven-external` (the counter is shared, the runner-lost re-run is not repeated);
  - near the bound: with time left < `next_wait + last_attempt_duration` no re-run is asked (red at d01d462 by construction: today the wait is not counted).

**B2c — slow-build required (decision b).**
- `REQUIRED_TESTLAB = ("testlab", "release-verify", "slow-build")`.
- **The generous budget is already there:** its job timeout is 240 min against ~45 min real runs (testlab.yml:219-222 comment), and the bot bound stays 280 min. A budget raise would touch the controller and the bot together, and nothing measured asks for it.
- **Red-before:** a testlab run whose slow-build job failed is judged red (today it is ignored: green with a red slow-build).
- **Item 14** (the controller ships the list): **deferred.** It needs a controller file and a reader. The constant is one line, and the controller's own required checks live in GitHub rulesets, not in the tree (docs/maintenance.md, "GitHub rulesets").

**B2a + item 12 + item 15 — a firmware move is held, not frozen; holds expire.**
- **A HOLD** is a bot-written `freeze` line plus `held_until = "<UTC date + 7 days>"` in policy.toml.
  - `freeze_of` (upstream.py:167) treats a source as frozen only while `today < held_until`.
  - A person's `freeze` without `held_until` never expires, as today.
  - `held_until` must be an ISO date (`YYYY-MM-DD`); a malformed one is a policy problem in `freeze_problems` (upstream.py:164), as fatal as a malformed freeze.
  - After expiry the source moves again (the weekly re-proof). When that release is green, the bot's own policy commit deletes the expired `freeze` + `held_until` lines (auto-thaw) and closes the hold's issue.
- **Meshcom rule:** when the meshcom binary build fails (`conclusion == "failure"`), the bot writes a HOLD on exactly the meshcom sources this candidate MOVED (`src/MeshCom-Firmware`, `src/meshcom-qemu-raspi`, `src/meshcom-loraham-bridge`, as moved) and opens ONE issue. The issue names:
  - the firmware ref;
  - the failing gate: the failing job and step names from the jobs API, e.g. the builder's compile or smoke boot;
  - the last error lines.
  - The existing one retry then runs without those moves.
  - When the candidate moved no meshcom source (e.g. a controller change broke the build), nothing is held: the issue reports an internal regression, and the attempt stops as an ordinary failure. Holding upstream pins that did not move cannot make a retry meaningful.
- **Item 15 "moves with":** with S5 the runner applies no patch. The coupling is that gate: the firmware moves only in a candidate whose meshcom build + smoke boot passed, because the build stage precedes the release. No `owned-by-pin` rule is needed.
- **Files:** bot/upstream.py (`freeze_of`), bot/autofreeze.py (`hold_edit`, `thaw_edit`), bot/cli.py (build-stage branch, release-stage thaw), README "Freeze a pin".
- **Red-before:**
  - (a) a failed meshcom build with the firmware moved writes `freeze` + `held_until` under `src/MeshCom-Firmware` only (exact TOML text). Red: today all three sources;
  - (b) `freeze_of` treats an expired hold as not frozen (red: frozen forever);
  - (c) a green release that moved an expired-hold source removes both lines (red: lines stay);
  - (d) a failed meshcom build with no meshcom source moved writes no policy line and reports an internal regression (red: today `_auto_freeze` holds all three).

**Item 10 — auto-finish.**
- In `plan` (cli.py:279-288), when every blocking attempt is past its commit point and `owes ⊆ {dev integration, the image}`, the scheduled run dispatches `release.yml mode=finish attempt=<id>`. It then ends with a summary "finishing #N" instead of a Stop issue.
- **Once:** the attempt record gains `finish_run` with three states: `""` (none), `"dispatching:<claimant run id>"` (claimed by this workflow run) and the finish run id.
  - The planner saves `"dispatching:<its own run id>"` BEFORE the dispatch, the way `retry_run` is claimed before sending (attempt.py:84, cli.py:317-322). It then dispatches and replaces the claim with the run id the dispatch returns (gh.py:121 returns it).
  - A definite dispatch failure (GitHubError from the dispatch call) clears the claim back to `""` and stops with that error.
  - A crash between claim and replace leaves `"dispatching:<claimant>"`: later passes dispatch nothing and the summary says "finish claimed by run <claimant>, no run id recorded — check that run". That is the claim-before-send trade-off the bot already makes for retries: never two finishes, at most one a person checks.
  - A record with a run id is not dispatched again; the summary says "finish run <id> in flight". A finish that failed leaves the attempt blocking, and a person settles it as today.
- **Red-before:** that state dispatches finish (red: Stop "an earlier attempt is unresolved"); a second pass over the record with a run id dispatches nothing; a pass over a `"dispatching:<id>"` record dispatches nothing and its summary names <id>; a dispatch that raises leaves `finish_run == ""` (the dispatch spy and the saved record are asserted).

**Item 11 — an unreachable remote is skipped for the week.** `examine` gives `status="skipped"` instead of `fault` only for the "upstream not readable" branch (upstream.py:223-227). Skipped sources do not move. The summary lists them, the release proceeds, and every other fault still stops. **Red-before:** an unreadable remote with another source moving gives a release plan with one skipped line (red: Stop at watch).

**Visibility of persistent degraded states (F6).**
- A skipped source and an `unproven-external` gate each keep ONE informational issue (label `degraded`, title `degraded: <key or gate>`). It is opened at the first occurrence, gets one comment per scheduled run that sees the state again, and gets the title prefix `PERSISTENT` when the occurrence count reaches 3. Occurrences = 1 (the run that opened it) + the issue's comments; a closed issue starts again at 1.
- The issue is closed by the first run that no longer sees the state. It never freezes, holds or blocks a release.
- **Red-before:** occurrences 1 and 2 leave the title without `PERSISTENT`; occurrence 3 adds it; a clean run closes the issue (red: no issue at all).

**B2e — report quality (D5, D6, D7).**
- D5: the attempt record gains one field, `inputs` (the plan's moved findings as rows: key, current, candidate, compare link), written at plan. Build and prove `Stop`s pass it as `findings`, so the Inputs table is filled. Today only `moved_keys` is recorded (attempt.py:79), and `Stop(..., findings=found)` is used at watch only (cli.py:306).
- D6: the first sentence comes from the event: "The scheduled release run …" / "The dispatched release run …" / "The retry of attempt N …" (report.py:100).
- D7: one new helper `GitHub.failing_jobs(repo, run_id, attempt)` (gh.py; `jobs()` + `/actions/jobs/{id}/logs`) returns per failing job its name, link and last 20 log lines. Prove and build put them into `diagnostics` (today build passes only the run URL, cli.py:785-811; prove the bare ids). B2a uses the same helper to name the failing gate.
- **Red-before:** the issue body for a prove stop has a non-empty Inputs table, the dispatch wording and a job line (red: empty table, "scheduled", bare ids). Asserts read the table rows and the job name tokens.

## 2. Deferred, with the reason
- **17** pip floors: the cure is in the controller lane (a typed pip-resolution line that the release lane must emit) or constraints regeneration in the controller's build steps; neither is bot code. → a determinism follow-up.
- **21** auto re-run of runs the bot does not wait on: it needs `workflow_run` workflows in three repositories plus a race rule. It is its own packet after this one has run a Monday.
- **14:** above.
- **D8** (cron lateness): GitHub's, nothing to do.

## 3. B3: thaw and closes, a documented procedure (no code)
After 0.12.10 publishes the meshcom binary with the S5 runner, and `index.json` shows the new components:
1. delete the three `freeze =` lines (policy.toml:37, 41, 45), one commit on bot `main`;
2. comment on and close #62 (thawed, with the release link);
3. close #61 and #64 with the texts in BOT-RECOVER-PROCEDURE.md;
4. `gh workflow run release.yml -f mode=watch-only` → the summary lists the three meshcom sources as movable.

## 4. Proof, packet, guardrails
- **Tests:** the bot suite (`python -m pytest -q`, `ruff check bot tests`) plus the red-before tests above. Each test file uses the existing fakes (tests/README.md of the bot).
- **Dry-run:** `gh workflow run release.yml -R makrohard/lhpc-release-bot --ref <branch> -f mode=dry-run` proves the plan-stage items (11 skipped line, 10 finish dispatch only in `full`; dry-run reports what it would dispatch). Build/prove/re-run/hold changes are proven by the unit tests and by the first scheduled run (Monday 2026-10-19 21:30Z).
- **Packet:** one branch `cons/bot-stability-r1`, est. 60–80 KB with diffs. If it exceeds 90 KB: P-A = R + B2c + B2e; P-B = holds (B2a/12/15) + 10 + 11, stacked on P-A (both touch cli.py, so not file-disjoint; stacked instead).
- **Guardrails:** no new module and no class; one classifier function replaces a branch in `wait`; one helper serves D7 and B2a; a hold is two TOML keys the existing parser already reads; the README section changes in place.
- **Est. lines:** gh.py +65, cli.py +120, attempt.py +8, upstream.py +15, autofreeze.py +50, report.py +30, tests +320.

## 5. Decisions for the maintainer (recommendation first, with the alternative)
1. **EXTERNAL re-runs:** five, waiting 0/1/2/5/10 min (18 min). *Alternative:* three, waiting 0/2/10 min. Fewer re-runs end a long outage sooner as `unproven-external` but ride out less of it. Both fit the 280 min bound because of the F1 rule.
2. **After the re-runs:** `unproven-external` (no release this week, retried next week). *Alternative:* release with the external gate marked unproven. That ships on time, but the release is then not proven by the lane it requires.
3. **Bot holds:** expire after 7 days, then a re-proof and auto-thaw on green. *Alternative:* no expiry, thawed by a person as today. That avoids re-trying a pin that is still broken weekly (one failed build per week) but needs a person for every hold.

## Numbers, measured
| figure | command | output |
|---|---|---|
| bot base | `git log -1 --format=%h origin/main` | d01d462 |
| bot suite | `python -m pytest -q` | 280 passed |
| file sizes | `wc -l bot/cli.py bot/gh.py bot/report.py bot/autofreeze.py bot/upstream.py` | 2005, 338, 148, 228, 341 |
| bounds | `sed -n 66-70p bot/cli.py` | testlab 280 min; required testlab, release-verify |
| job timeouts | `grep -n timeout-minutes` in release.yml / controller testlab.yml | prove 300; testlab 120, release-verify 90, slow-build 240 |
