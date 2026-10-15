# Gate 1: bot-stability-A v3 (lhpc-release-bot, plan v4)

**Request.** Judge the code commits below (four commits: 11, B2c, D5–D7, 10) against plan v4 (included; its v1–v3 change history omitted). This is v3. v2 folded the findings of rounds 10 and 11 (on the v1 packets A and B) and of a second read (report table "v2: findings folded"); v3 adds the notes of rounds 12 (A v2, GREEN WITH NOTES) and 13 (B v2, RED, two findings) and of a delta read of v2 (report table "v3"). Round 14 (C v2) was GREEN. That means:
- correctness of each behaviour, and that it changes only what the plan says;
- whether each red-before or new-invariant test can fail for the defect named;
- whether each earlier finding is closed by the change named;
- the README sentences;
- the report's claims against the diff.

The packet is one of three (stacked: A = b69b905..b10346a, B = a6abb30..ed4c07c, C = aba7948..559d5fb, each on top of the one before), split to stay under 90 KB (v1 was two packets; the v2 diff no longer fits in two). The report covers all three.

This file is your whole input: you have no repository access; use no connector, tool or web lookup.

**Answer form.**

| commit | verdict (OK / FINDING) | what |
|---|---|---|

Then numbered findings (file:line, why it matters, smallest fix), then one final line: GREEN / GREEN WITH NOTES / RED.

Redaction: none applied; the diff is `git diff` output verbatim and contains no home path, LAN address, host name or call sign.

## Commits (full messages, oldest first)
```
--- b69b905 bot-stability: an unreachable upstream is skipped for the run, not a stop

`examine` and `examine_extra` turn a read failure whose words say the
remote, DNS or network could not be reached (`UNREACHABLE`) into status
`skipped`: the pin stays, the summary lists it, the release proceeds.
Every other read failure (a missing ref, a 404) is still a fault and
still stops at watch.

Red-before against d01d462:
test_an_unreachable_upstream_is_skipped_and_any_other_read_failure_is_a_fault
gives "AssertionError: assert ('fault', 'fault') == ('skipped', 'skipped')"
for the two unreachable cases; the two fault cases are controls (green on
both).

The stage-level test, test_an_unreachable_source_beside_a_move_is_reported_and_the_plan_goes_on
(one unreachable source beside a move: the summary lists the skipped
source and the plan goes on past the fault gate), needs the plan-stage
fake that the finish commit adds, so it lands with the degraded-issue
commit. Red-before against d01d462: "bot.cli.Stop: watch: an upstream
input could not be judged".

--- 68c1dbe bot-stability: slow-build is a required testlab job

REQUIRED_TESTLAB gains "slow-build" (decision b). A red slow-build already
failed the run's conclusion; what changes is that a testlab run whose
slow-build job is missing or skipped is no longer proof. The generous
budget is the controller's job timeout (240 min, ~45 min real runs); the
bot's 280-min testlab bound is unchanged. The stage_prove fixture's lane
gains the green slow-build job the real workflow has.

Red-before against d01d462:
test_a_testlab_run_without_its_slow_build_job_is_not_proof gives
"AssertionError: assert ([] == ['slow-build: skipped']".

--- 756acb8 bot-stability: failure issues name the event, keep the inputs, show failing jobs

D5: the attempt record gains `inputs` (the moved findings as the plan saw
them); a stop after the plan renders them in the Inputs table.
D6: the first sentence names the event: scheduled, dispatched, or the
retry of attempt N (`_opening`).
D7: `GitHub.failing_jobs` returns each failing job of one attempt with its
link and the last 20 log lines (via the signed log download); a prove stop
lists every red run with them instead of bare run ids.

Red-before against d01d462 (bot/cli.py, report.py, attempt.py, gh.py of
d01d462 with these tests):
test_a_stop_after_the_plan_lists_the_inputs_the_attempt_was_moving gives
"assert (0 == 1)" (no Inputs row); the opening cases give
"AssertionError: assert 'dispatched' in 'The scheduled release run …'" and
the same for 'retry of attempt 1234' (the scheduled case is the control);
test_a_prove_stop_names_each_failing_job_with_its_last_lines gives
"AssertionError: assert 'https://github.com/…/actions/runs/6' in '5\n6'".

--- b10346a bot-stability: an attempt owing only integration and image is finished automatically

When every attempt blocking a `full` run is released and owes only the dev
integration and/or the image, the plan dispatches `release.yml
mode=finish` for each, once, and stops without a release. The record keeps
`finish_run`: "dispatching:<this run id>" is saved before the send (as the
retry claim is), replaced by the finish run id. Only a definite refusal (an
HTTP 4xx answer) releases the claim; a network error or a 5xx keeps it,
because the request may have been accepted with its reply lost. Runs of
release.yml share the concurrency group `release`, so a claim is read only
after the run that wrote it has ended: a claim with no run id, or a finish
run that ended with the attempt still owing, stops the run (`observe`) and
names it; a finish run still in flight is reported and the run ends. The
plan job gains `actions: write` for that dispatch.

Red-before against d01d462: test_an_attempt_owing_only_integration_and_image_is_finished_once
gives "bot.cli.Stop: observe: an earlier attempt is unresolved". The claim,
refusal and maybe-accepted cases test the new record states (new invariant:
the field does not exist on the parent).

Red-before against the first version of this commit (tree 3ef5797):
test_a_claim_without_a_run_id_stops_naming_its_claimant_and_sends_nothing
and test_a_finish_run_that_ended_with_the_attempt_still_owing_stops (three
conclusions) give "Failed: DID NOT RAISE Stop" (a silent green run).
```

## The report (all three packets)
# Code report: bot-stability-1 (PLAN-bot-stability v4)

**Branch:** `cons/bot-stability-1-r1` on lhpc-release-bot `main` = d01d462. Eight commits, one per feature; the suite is green at each commit (321 → 382 passed). **v3** adds the round 12–13 notes and a delta read of v2 (table "v3"). **v2** folds gate-1 rounds 10 (packet A) and 11 (packet B) and the second read (12 points) into the commits they belong to; see "v2: findings folded".

## HOUSE RULES KEPT
```
$ python tools/check_houserules.py d01d462..559d5fb --fact "held_until" --fact "EXTERNAL-UNAVAILABLE what=" --fact "finish_run" --fact "degraded gate"
HOUSE RULES KEPT  d01d462..559d5fb
changelog    +0 bullets (limit 2, each ≤ 3 lines; longest 0), top section 16 lines   OK
docs         1 files, +25 lines; fact "held_until" -> README.md; fact "EXTERNAL-UNAVAILABLE what=" -> README.md; fact "finish_run" -> README.md; fact "degraded gate" -> README.md   OK
tests        39 new tests; layers tests=NONE; red-before 8/8; unlayered tests/test_report.py   HARD
patterns     getsource 0 assert-True 0 source-read 0 sleep 0 startswith 3 network 0   WARN
markers      0 without slow   OK
attribution  authors makrohard; trailers 0; words 0   OK
modules      N/A (budget table absent)   OK
VERDICT      FAIL  (hard 1, warn 1)
```
- **tests HARD: not applicable.** The checker's layer table is the controller's (tests/README.md, "Where a new test goes"). The bot's own tests/README.md places tests by decision file; `tests/test_report.py` is new and registered there ("what a failure issue says").
- **patterns WARN (3 `startswith`):** the `PERSISTENT ` title prefix (the token the issue's state is) and the `- testlab: unproven, external` outcome line. Both are decision tokens, not sentences.
- **CHANGELOG:** none. The bot's CHANGELOG is "Milestones only"; this packet is not a milestone.
- **modules N/A:** the bot has no budget table.

## Commits
| commit | what | files | tests (red-before or new invariant) |
|---|---|---|---|
| b69b905 | an unreachable upstream is skipped for the run (11) | upstream.py, report.py, test_upstream.py | red vs d01d462: "assert ('fault', 'fault') == ('skipped', 'skipped')"; two fault cases are controls. The plan-stage test lands with aba7948 (it needs the plan fake from b10346a); red vs d01d462: "bot.cli.Stop: watch: an upstream input could not be judged" |
| 68c1dbe | slow-build is required (B2c) | cli.py, test_proof.py | red: "assert ([] == ['slow-build: skipped']" |
| 756acb8 | failure issues: event, inputs, failing jobs (D5–D7) | cli.py, gh.py, report.py, attempt.py, README, 3 tests | red: inputs "assert (0 == 1)"; opening "'dispatched' in 'The scheduled …'"; D7 "'…/actions/runs/6' in '5\\n6'" |
| b10346a | auto-finish with `finish_run` claim states (10) | cli.py, attempt.py, release.yml (plan: actions write), README, test_attempt.py | red: "bot.cli.Stop: observe: an earlier attempt is unresolved"; v2 red vs v1 (3ef5797): "Failed: DID NOT RAISE Stop" for a stuck claim and an ended finish run |
| a6abb30 | bot holds expire (7 d) and are thawed on a green release; a build failure holds only what moved (B2a/12/15) | upstream.py, autofreeze.py, cli.py, report.py, release.yml (finalize, finish-close: contents write), README, 2 tests | red: "assert False" (expired date still frozen); "assert []" (malformed held_until accepted); v2 red vs v1: "OSError: read-only file system", "GitHubError: PATCH /issues/62 -> 502", "assert []" (2026-13-45), "assert False" (refusal on stdout only) |
| ed4c07c | a failed binary build names its failing job and last lines | cli.py, test_autofreeze.py | red: "assert '`build`' in 'https://example.invalid/build/777'" |
| aba7948 | degraded issues for skipped sources, counted once per run (the opener's body mark included), closed only when examined | cli.py, README, test_report.py, test_attempt.py | new invariant; v2 red vs v1: "assert [False, False, True, True] == [False, False, False, True]" |
| 559d5fb | one re-run mechanism: runner-lost (first attempt only) + typed EXTERNAL, unproven-external (R) | gh.py, cli.py, README, test_rerun.py, test_proof.py | red vs its parent aba7948: "assert False" at the `unproven, external` line; v2 red vs v1: "assert [1, 2, 3] == [1, 2]", "assert [3] == []", "GitHubError: GET … -> 410: expired" |

## v2: findings folded
| finding | where | change | test |
|---|---|---|---|
| r10 F1, plan-stage proof of 11 | test_attempt.py | stage test: one unreachable source beside a move, real `examine`, the plan goes past the fault gate and lists the skipped source | red vs d01d462 (above) |
| r10 F2, second read 3 | cli.py `_thaw_proved` | the write is in a handler that catches `OSError` | `test_a_thaw_whose_policy_write_fails_reports_and_never_raises` |
| r10 F3, second read 3 | cli.py `_thaw_proved` | incidents are closed BEFORE the thaw is pushed; a failed close leaves policy line and incident together for the next release that moves the input; a failed push after the close leaves an expired line that holds nothing | `test_an_incident_that_cannot_be_closed_keeps_its_hold_line_for_the_next_release` |
| r10 F4 | README | "an attributable regression that holds the input again renews the date, and an unmarked red leaves it expired" | — |
| r10 note, second read 7 | cli.py `_auto_freeze`, tests | exact policy.toml of a builder hold; a refusal goes to the run summary | `test_a_build_failure_holds_only_what_it_moved_in_the_exact_policy` (coverage), `…_is_reported_not_held` (red) |
| r11 F1, second read 4 | gh.py `wait` | runner loss only when no re-run was made in this wait | `test_a_runner_loss_after_an_external_re_run_is_judged_as_it_is` |
| r11 F2, second read 8 | cli.py `_degraded` | occurrences = distinct marked runs in body + comments | r1, r1, r2, r3 → PERSISTENT at r3 only |
| r11 F3, second read 5 | cli.py `_external_jobs` | `GitHubError` → [] (not a transfer failure); direct unit tests; the outage stage fixture carries a typed line only | `test_only_a_failed_job_whose_own_junit_is_all_external_is_external` (5 cases) |
| second read 1 | cli.py `stage_prove` | a gate is examined only when its job succeeded on the judged attempt | `test_a_degraded_gate_closes_only_when_its_job_succeeded` |
| second read 2 | cli.py `_dispatch_finish` | a claim without a run id, or a finish run that ended with the attempt owing, raises `Stop("observe")`; an in-flight run is reported | `test_a_claim_without_a_run_id_stops…`, `test_a_finish_run_that_ended…` |
| second read 6 | packet | `af.REGRESSION` (unchanged) is quoted in packet B | — |
| second read 9 | commit message | 559d5fb names its parent, not abdd00a | — |
| second read 10 | upstream.py `_is_date` | `held_until` must be a real calendar date | `2026-13-45` case |
| second read 11 | — | **refuted:** `att.runs["binary:<stack>"]` is assigned three statements before the line (cli.py `stage_build`); `record_run` raising never reaches it | — |
| second read 12 | README | runner loss on a later attempt; `degraded gate` and when it closes; a stuck finish claim stops | — |
| report claims | this report | "EXTERNAL never attributes" and "one finish dispatch at most" are now stated with their scope (below) | — |

## v3: notes of rounds 12–13 and the delta read of v2
| finding | where | change | test |
|---|---|---|---|
| r12 note (A) | this report | the concurrency excerpt the finish claim rests on (Numbers) | — |
| r13 F1 (B) | report.py `incident` | the incident text states the README's rule: an attributable regression that holds the inputs again renews the date; an unmarked red leaves it expired | `test_an_expiring_incident_promises_renewal_only_on_an_attributable_regression`, red vs v2 |
| r13 F2 (B) | packet B | the `stage_build` lines behind the point-11 refutation are quoted (unchanged code section) | — |
| delta (a) | cli.py `_thaw_proved` | one comment: an incident closed before a later close failed stays named by an expired line, which holds nothing | — |
| delta (b) | gh.py `wait` docstring | the rule as coded: the first attempt THIS wait judges; `runner_lost` also refuses any `run_attempt` but 1 | — |
| delta (c) | cli.py `_external_jobs` | `zipfile.BadZipFile` is caught with `GitHubError` (a missing member already reads as b"") | "bad zip" case, red vs v2 |
| delta NEW | cli.py `stage_prove` | the degraded-gate report's jobs read is best-effort: an error examines nothing and never replaces the stop | `test_a_gate_report_that_cannot_read_its_jobs_never_stops_prove`, red vs v2 |

## The 6-point block
1. **Contracts:**
   - `GitHub.wait(…, external=None)` → run with `rerun` (`attempt`, `jobs`; shape unchanged), `reruns` (+ `reason`), `external_unresolved` (gh.py `wait`).
   - `external_whats(junit) -> list`: non-empty only when every failure/error is typed and carries no marker (cli.py).
   - Attempt gains `inputs` (moved findings, asdict) and `finish_run` ("" | "dispatching:<run>" | run id) (attempt.py); old records read with the defaults.
   - policy: `held_until = "YYYY-MM-DD"` only beside `freeze`.
   - `failure_issue(..., opening=)` (report.py); `incident(..., until=)`.
2. **Invariants:**
   - No hold without attributable evidence: `decide` unchanged except `moved_only` for builder evidence (test_autofreeze).
   - A person's freeze never expires (test_freeze).
   - An unproven external transfer attributes nothing: it goes into identity, and `lane_only` requires an empty identity (test_proof outage case, whose JUnit carries the typed line only).
   - A test body is never re-run: re-runs are jobs whose every failure is typed (test_rerun matrix).
   - At most one finish dispatch per attempt, given that runs of release.yml are serialised by its concurrency group `release` (cancel-in-progress false): the claim is saved before the send and every later run reads it (test_attempt covers the sequential runs; concurrency is GitHub's).
3. **Failure classes:**
   - Fakes keep the real signatures: `wait(repo, run_id, bound, external=None)`, `failing_jobs(repo, run_id, attempt, lines=20)`, `dispatch`.
   - A thaw that cannot read, write or push the policy, or close an incident, reports and returns: best-effort after the release (two failure tests).
   - `_degraded` swallows only `GitHubError`.
   - The dispatch keeps its claim on an ambiguous error.
   - Policy writes are never forced.
4. **Test rules:** behaviour via stages or pure functions; exact TOML text for the hold edit and the thaw; no network (fakes, `git` monkeypatched); the clock is a fixture.
5. **Runs:** `python -m pytest -q` → 382 passed; `ruff check bot tests` → All checks passed!; every commit's suite green (each commit exported with `git archive` and run outside the repository).
6. **Self-review (found and fixed):**
   - `asdict` was used and not imported (only caught by a test driving it).
   - `--unidiff-zero` hunk splitting misplaced one line while the commits were being split; caught by the per-commit runs and repaired before squashing.
   - The plan's B2c claim "ignored today" was wrong (a red slow-build already failed the run); the red-before is now "missing or skipped".
   - The plan's (d) "today freezes all three" was wrong (`decide` already refused); that case is a control.
   - v2: running the suite under `git rebase --exec` let the git fixtures write into the clone itself (the rebase's environment); the remote was untouched, and per-commit runs now use exported trees.

## Deviations from plan v4
- A smoke-boot failure of the builder is named but holds nothing: the builder writes no attributable evidence there (lhpc-binaries).
- The thaw runs in `finalize`, which gains `contents: write` with `finish-close`; recover was the only policy writer before.
- Plan v4 is 162 lines (target ≤ 150) because of the change tables.

## Proof not in this packet
- The dry-run (`gh workflow run release.yml -f mode=dry-run` on this branch) proves the plan-stage items only.
- Build, prove, re-run and hold behaviour are proven by the unit tests and by the first scheduled run (2026-10-19 21:30Z).
- The dry-run is to be dispatched after the merge on the handler's line: this branch is not `main`, and the bot refuses a non-main base for publishing modes only.

## Numbers, measured
| figure | command | output |
|---|---|---|
| base suite | `git checkout d01d462 && python -m pytest -q` | 317 passed |
| suite per commit | `git archive <c>` per commit of `d01d462..HEAD`, pytest in each | 321, 322, 327, 335, 352, 353, 357, 382 passed |
| diff | `git diff --stat d01d462 559d5fb` (code commits only) | 16 files changed, 1298 insertions(+), 53 deletions(-) |
| file sizes | `wc -l bot/{cli,gh,upstream,autofreeze,report,attempt}.py` | 2330, 601, 399, 274, 159, 231 |
| concurrency (finish claim) | `grep -n -A2 '^concurrency' .github/workflows/release.yml` (unchanged since d01d462) | `50:concurrency:` / `51-  group: release` / `52-  cancel-in-progress: false   # never cancel a run that may have published something` |
| EXTERNAL contract | the message of the determinism packet's owner, 2026-10-16 | `EXTERNAL-UNAVAILABLE what=([a-z0-9][a-z0-9_.:-]*)(?=\s\|$)`, message + text, no `STACK-REGRESSION` |


## The plan (v4, for reference; v1–v3 change history omitted)
````
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

````

## The full diff (`git diff d01d462 b10346a`)
```diff
diff --git a/.github/workflows/release.yml b/.github/workflows/release.yml
index 567c7b4..7edfca9 100644
--- a/.github/workflows/release.yml
+++ b/.github/workflows/release.yml
@@ -75,6 +75,10 @@ jobs:
       || inputs.mode == 'dry-run') }}
     runs-on: ubuntu-latest
     timeout-minutes: 30
+    permissions:
+      contents: read
+      issues: write
+      actions: write            # the ONE automatic `finish` dispatch for an attempt owing it
     outputs:
       proceed: ${{ steps.plan.outputs.proceed }}
       version: ${{ steps.plan.outputs.version }}
diff --git a/README.md b/README.md
index 5e5013d..0bbe180 100644
--- a/README.md
+++ b/README.md
@@ -115,8 +115,10 @@ the channel's typed message and offered the source build. Installed boxes are un
   Releases are cut from `main` only, and changes on `dev` do not influence a release: `dev`'s
   state, a merge-back pull request that is still open included, never gates, delays or shapes one.
 - **Something failed:** one issue **in this repository**, labelled `auto-release`, naming the
-  stage, the run, the observed state, the next action, the pin table with compare links, and
-  whatever diagnostics could be fetched. It lives here rather than in the controller so that a
+  event (scheduled, dispatched or the retry of an attempt), the stage, the run, the observed
+  state, the next action, the pin table with compare links (on a stop after the plan: the inputs
+  the attempt recorded), and whatever diagnostics could be fetched (for a prove stop: each red
+  run's failing jobs with the last lines of their logs). It lives here rather than in the controller so that a
   run whose release credential is the thing that failed can still report; this repository's own
   `GITHUB_TOKEN` writes it. Diagnostics are best-effort; the rest is never omitted.
 
@@ -260,7 +262,10 @@ Two ways out, both from the same issue:
 
 - the controller release exists and something after it is missing → `finish`, which re-runs
   the integration and the image in that order and closes the attempt if nothing is left. Both
-  stages are idempotent, so one that already completed is a no-op;
+  stages are idempotent, so one that already completed is a no-op. When EVERY attempt blocking a
+  `full` run owes only these two, that run dispatches `finish` itself, once per attempt (the
+  record keeps `finish_run`), and stops without a release. A claim that recorded no finish run,
+  or a finish run that ended with the attempt still owing, stops the run (`observe`) and names it;
 - nothing was released → `recover`, which cancels the children, WAITS for them to stop, puts the
   binary index back and deletes the candidate branch.
 
diff --git a/bot/attempt.py b/bot/attempt.py
index 6b3047e..c35822e 100644
--- a/bot/attempt.py
+++ b/bot/attempt.py
@@ -90,6 +90,12 @@ class Attempt:
     # the same commit as `main`, and that is still a rehearsal.
     base_ref: str = "main"
     notes: list = field(default_factory=list)
+    # The moved findings as the plan saw them (key, current, candidate, …): the Inputs table of a
+    # report written after the plan, when the stage that stops no longer has the findings.
+    inputs: list = field(default_factory=list)
+    # The ONE automatic `finish` for a released attempt that owes only integration and the image:
+    # "" none; "dispatching:<run id>" claimed by that run, before sending; else the finish run id.
+    finish_run: str = ""
 
     @property
     def rehearsal(self) -> bool:
diff --git a/bot/cli.py b/bot/cli.py
index 064f4b0..8ca4a76 100644
--- a/bot/cli.py
+++ b/bot/cli.py
@@ -16,6 +16,7 @@ import shutil
 import subprocess
 import sys
 import tempfile
+from dataclasses import asdict
 from pathlib import Path
 
 from . import autofreeze as af
@@ -64,7 +65,7 @@ BOT_URL = "https://github.com/" + BOT
 # Required jobs on the candidate commit. A skipped, neutral or missing one is NOT proof: the
 # release is authorised by an admin-bypass push, so nothing downstream re-checks these.
 REQUIRED_CI = ("test (3.11)", "test (3.12)", "test (3.13)", "pin-validation", "meshcore-host")
-REQUIRED_TESTLAB = ("testlab", "release-verify")
+REQUIRED_TESTLAB = ("testlab", "release-verify", "slow-build")
 
 BOUNDS = {"ci": 40 * 60, "binary": 190 * 60, "testlab": 280 * 60, "image": 330 * 60,
           "settle": 60 * 60}
@@ -249,6 +250,58 @@ def blocking_attempts(open_attempts, retry_of: str) -> list:
             if a.unresolved and not (retry_of and a.run_id == retry_of)]
 
 
+FINISHABLE_OWES = {"dev integration", "the image"}
+REFUSED = re.compile(r"-> 4\d\d\b")     # GitHubError text for an HTTP 4xx answer (gh.py request)
+
+
+def _finishable(att: Attempt) -> bool:
+    """A released attempt whose only debts are the ones `finish` pays."""
+    return att.past_commit_point and bool(att.owes) and set(att.owes) <= FINISHABLE_OWES
+
+
+def _dispatch_finish(ctx: Ctx, number: int, att: Attempt) -> None:
+    """Dispatch `finish` for this attempt at most once. The claim is written BEFORE the send, as
+    the retry's is: a run lost between the two leaves a claim naming itself, and no later run
+    sends a second finish on top of one that may be running."""
+    # Runs of this workflow share one concurrency group, so the run that wrote a claim has ended
+    # before this one reads it. A claim with no run id, or a finish run that ended with the
+    # attempt still owing, will not resolve by waiting: it stops this run, never a silent pass.
+    if att.finish_run.startswith("dispatching:"):
+        claimant = att.finish_run.split(":", 1)[1]
+        raise Stop("observe", f"finish of attempt {att.run_id} was claimed by run {claimant}, "
+                   f"which recorded no finish run id.",
+                   f"Check run {claimant}. If it started no `finish`, dispatch `finish` with "
+                   f"attempt {att.run_id} by hand; if it did, wait for that run.")
+    if att.finish_run:
+        run = ctx.bot_gh.run(BOT, int(att.finish_run))
+        if run.get("status") != "completed":
+            ctx.summary(f"\nfinish run {att.finish_run} for attempt {att.run_id} is in flight.")
+            return
+        raise Stop("observe", f"finish run {att.finish_run} for attempt {att.run_id} ended "
+                   f"({run.get('conclusion')}) and the attempt still owes {', '.join(att.owes)}.",
+                   f"Open that run, fix its cause, then dispatch `finish` with attempt "
+                   f"{att.run_id} by hand.")
+    att.finish_run = f"dispatching:{ctx.run_id}"
+    ctx.save_attempt(number, att)
+    try:
+        run_id = ctx.bot_gh.dispatch(BOT, RELEASE_WORKFLOW, "main",
+                                     {"mode": "finish", "attempt": att.run_id})
+    except GitHubError as exc:
+        # Only a definite refusal (an HTTP 4xx answer) proves nothing was started; a network
+        # error or a 5xx may have been accepted with its reply lost, so the claim stays.
+        if REFUSED.search(str(exc)):
+            att.finish_run = ""
+            ctx.save_attempt(number, att)
+        raise Stop("observe", f"attempt {att.run_id} owes only {', '.join(att.owes)}, but the "
+                   f"finish dispatch failed: {exc}",
+                   f"Dispatch `finish` with attempt {att.run_id} by hand"
+                   + ("." if not att.finish_run else f" after checking that run "
+                      f"{ctx.run_id} started none.")) from None
+    att.finish_run = str(run_id)
+    ctx.save_attempt(number, att)
+    ctx.summary(f"\nfinishing attempt {att.run_id} (issue #{number}): finish run {run_id}.")
+
+
 def stage_plan(ctx: Ctx) -> int:
     """Check access, refuse an unresolved attempt, read upstream, and (in `full`) push the
     candidate. Everything before the first push happens here, so a run that is going to stop
@@ -278,6 +331,13 @@ def stage_plan(ctx: Ctx) -> int:
 
     if ctx.mode == "full":
         blocking = blocking_attempts(ctx.open_attempts(), ctx.retry_of)
+        if blocking and all(_finishable(a) for _, a in blocking):
+            # Released attempts that owe only the dev integration and the image: what a person
+            # would do is dispatch `finish`, so this run does it, once per attempt, and stops.
+            for n, a in blocking:
+                _dispatch_finish(ctx, n, a)
+            ctx.out(proceed="false")
+            return 0
         if blocking:
             lines = [f"- issue #{n}: attempt {a.run_id}, state `{a.state}`"
                      + (f", still owes {', '.join(a.owes)}" if a.owes else "")
@@ -415,7 +475,7 @@ def stage_plan(ctx: Ctx) -> int:
     att = Attempt(run_id=ctx.run_id, state="prepared", version=version, base_sha=base_sha,
                   candidate_sha=candidate, branch=branch, dev_sha=dev_sha,
                   moved_keys=[f.key for f in moved], retry_of=ctx.retry_of,
-                  base_ref=base_ref(),
+                  base_ref=base_ref(), inputs=[asdict(f) for f in moved],
                   notes=[f"moves: {', '.join(f.key for f in moved)}"])
     # The record exists BEFORE the branch is pushed. A push whose reply is lost still happened,
     # and a branch no attempt names is a mutation nothing would ever clean up.
@@ -1065,12 +1125,34 @@ def stage_prove(ctx: Ctx) -> int:
                    + "\n".join(f"- {p}" for p in problems),
                    "Recovery restores whatever this attempt published and deletes the candidate "
                    "branch; nothing was released.",
-                   detail="\n".join(str(r.get("id")) for r in att.runs.values()))
+                   detail=_red_runs(ctx, att))
     ctx.summary(f"every required job succeeded on `{att.candidate_sha[:9]}`, and the release "
                 f"lane ran its cases.")
     return 0
 
 
+def _red_runs(ctx: Ctx, att: Attempt) -> str:
+    """Each recorded run with a failing job: a link, the failing jobs and the end of their logs.
+    What a maintainer opens first; a run whose jobs cannot be read says so instead."""
+    out = []
+    for name, rec in att.runs.items():
+        link = f"https://github.com/{rec['repo']}/actions/runs/{rec['id']}"
+        try:
+            failed = ctx.gh.failing_jobs(rec["repo"], int(rec["id"]), rec.get("attempt", 1))
+        except GitHubError as exc:
+            out.append(f"- {name}: {link} — its jobs could not be read ({exc})")
+            continue
+        if not failed:
+            continue
+        out.append(f"- **{name}**: {link}")
+        for job, url, tail in failed:
+            out.append(f"  - failing job `{job}` {url}".rstrip())
+            if tail:
+                out += ["", "    ```", *("    " + ln for ln in scrub(tail).splitlines()),
+                        "    ```", ""]
+    return "\n".join(out)
+
+
 def _run_problems(ctx: Ctx, att: Attempt, name: str, rec: dict, run: dict,
                   required) -> tuple:
     """`(identity, offlane, outcome)` — why this run is not evidence, split by KIND.
@@ -1995,6 +2077,15 @@ def _traceback_tail(limit: int = 2000) -> str:
     return "```\n" + traceback.format_exc()[-limit:] + "\n```"
 
 
+def _opening(ctx: Ctx) -> str:
+    """Who stopped, in the report's first words: a retry, a scheduled run or a dispatched one."""
+    if ctx.retry_of:
+        return f"The retry of attempt {ctx.retry_of}"
+    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
+        return "The scheduled release run"
+    return "The dispatched release run"
+
+
 def _report_stop(ctx: Ctx, stop: Stop) -> None:
     """Always produce a report. Everything that could fail on the way is optional."""
     att, number = Attempt(run_id=ctx.attempt_id), 0
@@ -2013,10 +2104,13 @@ def _report_stop(ctx: Ctx, stop: Stop) -> None:
     if number:
         observed += (f"\n\nThe attempt is issue #{number}, state `{att.state}`"
                      + (f", still owes {', '.join(att.owes)}" if att.owes else "") + ".")
+    # A stage after the plan stops without the findings in hand; the attempt kept them.
+    findings = stop.findings or [up.Finding(**{**d, "consumers": tuple(d.get("consumers") or ())})
+                                 for d in att.inputs]
     title, body = rp.failure_issue(
-        stage=stop.stage, run_url=ctx.run_url, attempt=att, findings=stop.findings,
+        stage=stop.stage, run_url=ctx.run_url, attempt=att, findings=findings,
         observed=observed, next_action=stop.next_action, diagnostics=stop.detail,
-        token_expiry=expiry)
+        token_expiry=expiry, opening=_opening(ctx))
     ctx.summary(f"## Stopped at {stop.stage}\n\n{observed}\n\n{stop.next_action}")
     try:
         marker = f"<!--auto-release:{att.run_id or ctx.run_id}-->"
diff --git a/bot/gh.py b/bot/gh.py
index 850ac40..f30197d 100644
--- a/bot/gh.py
+++ b/bot/gh.py
@@ -139,6 +139,24 @@ class GitHub:
                 if attempt else f"/repos/{repo}/actions/runs/{run_id}/jobs")
         return self.get(f"{path}?per_page=100")["jobs"]
 
+    def failing_jobs(self, repo: str, run_id: int, attempt: int, lines: int = 20) -> list:
+        """`(name, url, tail)` for each job of ONE attempt that did not succeed, where `tail` is
+        the last `lines` non-blank lines of its log — "" when the log cannot be read, because a
+        report must never fail on its own diagnostics."""
+        out = []
+        for job in self.jobs(repo, run_id, attempt):
+            if job.get("conclusion") in (None, "success", "skipped", "neutral"):
+                continue
+            try:
+                log = self._signed_download(
+                    f"{self._api}/repos/{repo}/actions/jobs/{job['id']}/logs"
+                ).decode("utf-8", "replace")
+                tail = "\n".join([ln for ln in log.splitlines() if ln.strip()][-lines:])
+            except GitHubError:
+                tail = ""
+            out.append((job.get("name", str(job.get("id"))), job.get("html_url", ""), tail))
+        return out
+
     def cancel(self, repo: str, run_id: int) -> None:
         # Already finished, or already cancelling: both are the state we wanted.
         with contextlib.suppress(GitHubError):
diff --git a/bot/report.py b/bot/report.py
index f346931..fa935d1 100644
--- a/bot/report.py
+++ b/bot/report.py
@@ -18,7 +18,7 @@ def _repo_of(remote: str) -> str:
 
 def findings_table(findings) -> str:
     """Every tracked input with its status — moved, at the pin, reported only, or faulty."""
-    icon = {"move": "→", "at-pin": "=", "manual": "·", "fault": "!", "frozen": "❄"}
+    icon = {"move": "→", "at-pin": "=", "manual": "·", "fault": "!", "frozen": "❄", "skipped": "~"}
     rows = ["| | input | tracks | now | upstream | note |", "|---|---|---|---|---|---|"]
     for f in findings:
         repo = _repo_of(f.remote)
@@ -50,13 +50,18 @@ def summary(findings, decision: str, extra: str = "") -> str:
     # Frozen inputs are counted apart from the movable ones and stay in the tracked total: a
     # deliberate hold must be visible every week without being mistaken for something to do.
     frozen = [f for f in findings if f.status == "frozen"]
+    skipped = [f for f in findings if f.status == "skipped"]
     head = [f"## {decision}", "", scope_note(), "",
             f"**{len(moved)} input(s) to move**, {len(faults)} fault(s), "
             + (f"{len(frozen)} frozen, " if frozen else "")
+            + (f"{len(skipped)} skipped, " if skipped else "")
             + f"{len(findings)} tracked in total.", ""]
     if frozen:
         head += ["Held on purpose, and not moved by this run:", ""]
         head += [f"- `{f.key}` — {f.detail or 'held'}" for f in frozen] + [""]
+    if skipped:
+        head += ["Not reachable this run; the pin stays and the next run looks again:", ""]
+        head += [f"- `{f.key}` — {f.detail}" for f in skipped] + [""]
     if extra:
         head += [extra, ""]
     return "\n".join(head) + findings_table(findings) + "\n"
@@ -93,11 +98,12 @@ def error_extract(log_text: str, tail: int = 80) -> str:
 
 
 def failure_issue(*, stage: str, run_url: str, attempt, findings, observed: str,
-                  next_action: str, diagnostics: str = "", token_expiry: str = "") -> tuple:
+                  next_action: str, diagnostics: str = "", token_expiry: str = "",
+                  opening: str = "The release run") -> tuple:
     """(title, body). Everything cheap is unconditional; `diagnostics` is what could be
     fetched."""
     title = f"auto-release: stopped at {stage}"
-    body = [f"The scheduled release run stopped at **{stage}**.", "",
+    body = [f"{opening} stopped at **{stage}**.", "",
             f"- run: {run_url}",
             f"- controller `main` at start: `{attempt.base_sha[:9] or '?'}`",
             f"- version it would have released: `{attempt.version or '?'}`",
diff --git a/bot/upstream.py b/bot/upstream.py
index 2a609c3..a928bd3 100644
--- a/bot/upstream.py
+++ b/bot/upstream.py
@@ -37,7 +37,7 @@ class Finding:
     which is exactly the thing a release must not imply."""
     key: str                       # source path, or extra.<name>
     track: str
-    status: str                    # "at-pin" | "move" | "manual" | "fault"
+    status: str                    # "at-pin" | "move" | "manual" | "frozen" | "skipped" | "fault"
     current: str = ""
     candidate: str = ""
     tag: str = ""
@@ -262,7 +262,24 @@ def examine(source, rule: dict, remote: Remote) -> Finding:
         described = tag or remote.describe(source.remote, source.branch, candidate)
         return Finding(status="move", candidate=candidate, tag=described, **base)
     except RuntimeError as exc:
-        return Finding(status="fault", detail=str(exc), **base)
+        return _unreadable(exc, base)
+
+
+# Words of a transfer that did not happen — the remote, DNS or the network, never the content.
+# Anything else a git or HTTP read says (a missing ref, a rewritten branch, a 404) stays a fault.
+UNREACHABLE = re.compile(
+    r"Could not resolve host|Temporary failure in name resolution|Name or service not known|"
+    r"Failed to connect|Connection (timed out|refused|reset)|timed out|"
+    r"The requested URL returned error: 5\d\d|HTTP Error 5\d\d|rate limit|"
+    r"RPC failed|early EOF", re.IGNORECASE)
+
+
+def _unreadable(exc: Exception, base: dict) -> Finding:
+    """An upstream that could not be REACHED is skipped for this run, not a stop: the pin stays
+    where it is and next week's run looks again. Every other read failure is a fault."""
+    if UNREACHABLE.search(str(exc)):
+        return Finding(status="skipped", detail=f"not reachable this run, pin kept ({exc})", **base)
+    return Finding(status="fault", detail=str(exc), **base)
 
 
 def _repo_of(remote_url: str) -> str:
@@ -312,7 +329,7 @@ def examine_extra(name: str, rule: dict, current: str, remote: Remote) -> Findin
         if frozen:
             return Finding(status="frozen",
                            detail=f"upstream not readable ({exc}) — held: {frozen}", **base)
-        return Finding(status="fault", detail=str(exc), **base)
+        return _unreadable(exc, base)
 
     if not latest:
         return Finding(status="fault", detail="upstream published nothing readable", **base)
diff --git a/tests/README.md b/tests/README.md
index cac0ce9..11bfd23 100644
--- a/tests/README.md
+++ b/tests/README.md
@@ -38,6 +38,7 @@ By the decision it protects:
   published image really is this release's.
 - **`test_proof.py`** — what counts as proof that THIS candidate is green, and how much
   credential a publishing run must have left.
+- **`test_report.py`** — what a failure issue says: who stopped, and the inputs it was moving.
 - **`test_integration_branch.py`** — the one conflict resolved automatically, against real git
   history with a real conflict.
 
diff --git a/tests/test_attempt.py b/tests/test_attempt.py
index 681f0b3..b6e8252 100644
--- a/tests/test_attempt.py
+++ b/tests/test_attempt.py
@@ -140,3 +140,110 @@ def test_a_mutated_record_must_say_what_it_dispatched():
         att.validate()
     att.dispatched = ["meshtastic"]
     att.validate()
+
+
+# ---- the automatic `finish` of a released attempt that owes only integration and the image ----
+
+class _PlanCtx:
+    """Only what `stage_plan` reaches for before the blocking check."""
+    token, mode, retry_of, run_id = "t" * 20, "full", "", "5000"
+
+    def __init__(self, att, dispatch_error=None, finish=None):
+        self.att, self.saved, self.sent, self.summaries = att, [], [], []
+        self.gh = self.bot_gh = self
+        self._error, self._finish = dispatch_error, finish or {"status": "in_progress"}
+
+    # Ctx
+    def open_attempts(self):
+        return [(7, self.att)]
+
+    def save_attempt(self, number, att):
+        self.saved.append(att.finish_run)
+        return number
+
+    def summary(self, text):
+        self.summaries.append(text)
+
+    def out(self, **kv):
+        pass
+
+    # GitHub
+    def whoami(self):
+        return {"login": "bot"}
+
+    def token_expiry(self):
+        return ""
+
+    def get(self, path):
+        return {}
+
+    def run(self, repo, run_id):
+        return dict(self._finish, id=run_id)
+
+    def dispatch(self, repo, workflow, ref, inputs=None):
+        self.sent.append(inputs)
+        if self._error:
+            raise self._error
+        return 8123
+
+
+def _owing(**over):
+    base = {"run_id": "4000", "state": "released", "version": "0.12.10", "base_sha": "b" * 40,
+            "candidate_sha": "c" * 40, "branch": "pins/0.12.10-4000", "image_tag": "",
+            "integration": ""}
+    return Attempt(**{**base, **over})
+
+
+def test_an_attempt_owing_only_integration_and_image_is_finished_once():
+    from bot import cli
+    ctx = _PlanCtx(_owing())
+    assert cli.stage_plan(ctx) == 0
+    assert ctx.sent == [{"mode": "finish", "attempt": "4000"}]
+    assert ctx.saved == ["dispatching:5000", "8123"]          # claimed before the send
+    second = _PlanCtx(ctx.att)                                 # the next scheduled run
+    assert cli.stage_plan(second) == 0 and second.sent == []
+
+
+def test_a_claim_without_a_run_id_stops_naming_its_claimant_and_sends_nothing():
+    # A green weekly run beside a claim nobody will ever resolve would hide it for good.
+    from bot import cli
+    ctx = _PlanCtx(_owing(finish_run="dispatching:4999"))
+    with pytest.raises(cli.Stop) as stop:
+        cli.stage_plan(ctx)
+    assert ctx.sent == [] and "4999" in stop.value.observed
+
+
+@pytest.mark.parametrize("conclusion", ["failure", "success", "cancelled"])
+def test_a_finish_run_that_ended_with_the_attempt_still_owing_stops(conclusion):
+    from bot import cli
+    ctx = _PlanCtx(_owing(finish_run="8123"),
+                   finish={"status": "completed", "conclusion": conclusion})
+    with pytest.raises(cli.Stop) as stop:
+        cli.stage_plan(ctx)
+    assert ctx.sent == [] and "8123" in stop.value.observed and conclusion in stop.value.observed
+
+
+def test_a_refused_finish_dispatch_releases_its_claim():
+    from bot import cli
+    from bot.gh import GitHubError
+    ctx = _PlanCtx(_owing(), dispatch_error=GitHubError("POST /repos/o/r/… -> 422: bad input"))
+    with pytest.raises(cli.Stop):
+        cli.stage_plan(ctx)
+    assert ctx.att.finish_run == "" and ctx.saved == ["dispatching:5000", ""]
+
+
+@pytest.mark.parametrize("said", ["POST /repos/o/r/… -> <urlopen error timed out>",
+                                  "POST /repos/o/r/… -> 502: bad gateway"])
+def test_a_finish_dispatch_that_may_have_been_accepted_keeps_its_claim(said):
+    # The request may have started a run whose reply was lost: never send a second one.
+    from bot import cli
+    from bot.gh import GitHubError
+    ctx = _PlanCtx(_owing(), dispatch_error=GitHubError(said))
+    with pytest.raises(cli.Stop):
+        cli.stage_plan(ctx)
+    assert ctx.att.finish_run == "dispatching:5000"
+    later = _PlanCtx(ctx.att)
+    with pytest.raises(cli.Stop):
+        cli.stage_plan(later)
+    assert later.sent == []
+
diff --git a/tests/test_proof.py b/tests/test_proof.py
index 3ae8924..bcadb4e 100644
--- a/tests/test_proof.py
+++ b/tests/test_proof.py
@@ -344,6 +344,10 @@ class _ProveCtx:
     def jobs(self, repo, run_id, attempt=1):
         return list(self._jobs_by_run[int(run_id)])
 
+    def failing_jobs(self, repo, run_id, attempt, lines=20):
+        return [(j["name"], f"https://example.invalid/job/{j['name']}", "E   the last error line")
+                for j in self._jobs_by_run[int(run_id)] if j["conclusion"] != "success"]
+
     def artifact_member(self, repo, run_id, name, member, attempt=1):
         cases = "".join(
             f'<testcase name="{c}">'
@@ -366,6 +370,7 @@ def _prove(*, ordinary="success"):
     from bot import cli
     green = [{"name": n, "conclusion": "success", "head_sha": CAND} for n in cli.REQUIRED_CI]
     lane = [{"name": "testlab", "conclusion": ordinary, "head_sha": CAND},
+            {"name": "slow-build", "conclusion": "success", "head_sha": CAND},
             {"name": cli.LANE_JOB, "conclusion": "failure", "head_sha": CAND}]
     ctx = _ProveCtx(jobs_by_run={5: green, 6: lane})
     with pytest.raises(cli.Stop):
@@ -584,3 +589,32 @@ def test_unreadable_and_red_are_never_both_reported():
                            REQUIRED_CASES)):
         unreadable, red = _release_case_problems(xml, required)
         assert not (unreadable and red), f"both reported for {xml[:20]!r}"
+
+
+def test_a_testlab_run_without_its_slow_build_job_is_not_proof():
+    # The release requires the slow-target build proof (decision b): a testlab run whose
+    # slow-build job was skipped concludes success, and must still not count.
+    lane = [{"name": n, "conclusion": "success", "head_sha": CAND} for n in REQUIRED_TESTLAB]
+    skipped = [dict(j, conclusion="skipped") if j["name"] == "slow-build" else j for j in lane]
+    identity, offlane, outcome = _run_problems(FakeCtx(skipped), att(), "testlab", rec(), run(),
+                                               REQUIRED_TESTLAB)
+    assert identity == ["slow-build: skipped"] and (offlane, outcome) == ([], [])
+
+
+def test_a_prove_stop_names_each_failing_job_with_its_last_lines():
+    """D7: the diagnostics are links to the red runs with their failing jobs and log tails, not
+    bare run ids."""
+    import pytest
+
+    from bot import cli
+    green = [{"name": n, "conclusion": "success", "head_sha": CAND} for n in cli.REQUIRED_CI]
+    lane = [{"name": "testlab", "conclusion": "success", "head_sha": CAND},
+            {"name": "slow-build", "conclusion": "success", "head_sha": CAND},
+            {"name": cli.LANE_JOB, "conclusion": "failure", "head_sha": CAND}]
+    ctx = _ProveCtx(jobs_by_run={5: green, 6: lane})
+    with pytest.raises(cli.Stop) as stop:
+        cli.stage_prove(ctx)
+    detail = stop.value.detail
+    assert "https://github.com/makrohard/loraham-pi-control/actions/runs/6" in detail
+    assert f"`{cli.LANE_JOB}`" in detail and "the last error line" in detail
+    assert "actions/runs/5" not in detail          # the green CI run is not listed
diff --git a/tests/test_report.py b/tests/test_report.py
new file mode 100644
index 0000000..31ba946
--- /dev/null
+++ b/tests/test_report.py
@@ -0,0 +1,71 @@
+"""What a failure issue says: who stopped, where, and which inputs it was moving.
+
+The issue is what a maintainer reads weeks later. Each case is one way it used to mislead: a
+retry reported as "the scheduled run", and an empty Inputs table on a stop after the plan.
+"""
+from __future__ import annotations
+
+from dataclasses import asdict
+
+import pytest
+
+from bot import cli
+from bot.attempt import Attempt
+from bot.upstream import Finding
+
+MOVED = Finding(key="src/meshcom-qemu-raspi", track="tip", status="move", current="a" * 40,
+                candidate="b" * 40, remote="https://github.com/makrohard/meshcom-qemu-raspi.git")
+
+
+class _Issues:
+    def __init__(self):
+        self.created = []
+
+    def open_issues(self, repo, label):
+        return []
+
+    def create_issue(self, repo, title, body, labels):
+        self.created.append(body)
+        return {"number": 1}
+
+    def comment(self, repo, number, body):
+        raise AssertionError("no issue was open, so nothing is commented")
+
+
+class _Ctx:
+    run_url, run_id, attempt_id, token = "https://example.invalid/run/9", "9", "9", ""
+
+    def __init__(self, retry_of=""):
+        self.retry_of = retry_of
+        self.gh, self.bot_gh = None, _Issues()
+        self.att = Attempt(run_id="9", state="prepared", version="0.12.10", base_sha="b" * 40,
+                           candidate_sha="c" * 40, branch="pins/0.12.10-9",
+                           moved_keys=[MOVED.key])
+        # Set after construction, so this file also runs against a record without the field.
+        self.att.inputs = [asdict(MOVED)]
+
+    def find_attempt(self, wanted=""):
+        return 3, self.att
+
+    def summary(self, text):
+        pass
+
+
+def test_a_stop_after_the_plan_lists_the_inputs_the_attempt_was_moving():
+    ctx = _Ctx()
+    cli._report_stop(ctx, cli.Stop("prove", "the candidate is not proven", "Recovery restores."))
+    body = ctx.bot_gh.created[0]
+    rows = [ln for ln in body.splitlines() if ln.startswith("| → |")]
+    assert len(rows) == 1 and f"`{MOVED.key}`" in rows[0]
+
+
+@pytest.mark.parametrize("retry_of, event, word", [
+    ("", "schedule", "scheduled"),
+    ("", "workflow_dispatch", "dispatched"),
+    ("1234", "workflow_dispatch", "retry of attempt 1234"),
+])
+def test_the_opening_names_the_event_that_started_the_run(monkeypatch, retry_of, event, word):
+    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
+    ctx = _Ctx(retry_of=retry_of)
+    cli._report_stop(ctx, cli.Stop("prove", "the candidate is not proven", "Recovery restores."))
+    assert word in ctx.bot_gh.created[0].splitlines()[0]
diff --git a/tests/test_upstream.py b/tests/test_upstream.py
index 5798d14..8cb6e62 100644
--- a/tests/test_upstream.py
+++ b/tests/test_upstream.py
@@ -231,3 +231,33 @@ def test_a_fork_carry_branch_is_tracked_at_its_tip_until_it_is_rebased(tmp_path)
     assert git(fork, "rev-parse", "HEAD") != pin
     f = judge("rebase")
     assert f.status == "fault" and not f.moves
+
+
+class _Unreadable(FakeRemote):
+    def __init__(self, said):
+        super().__init__([A])
+        self.said = said
+
+    def branch_tip(self, remote, branch):
+        raise RuntimeError(self.said)
+
+    def latest_pypi(self, package):
+        raise RuntimeError(self.said)
+
+
+@pytest.mark.parametrize("said, status", [
+    ("git -C x fetch -q --tags origin main: fatal: unable to access 'https://h/': "
+     "Could not resolve host: h", "skipped"),
+    ("cannot read PyPI p: <urlopen error [Errno -3] Temporary failure in name resolution>",
+     "skipped"),
+    ("git -C x fetch -q --tags origin main: fatal: couldn't find remote ref main", "fault"),
+    ("cannot read releases of o/r: HTTP Error 404: Not Found", "fault"),
+])
+def test_an_unreachable_upstream_is_skipped_and_any_other_read_failure_is_a_fault(said, status):
+    # A remote nobody could reach keeps its pin for this run; a remote that ANSWERED with
+    # something wrong (no such branch, no such repository) still stops the release.
+    git_source = examine(src(A), {"track": "tip"}, _Unreadable(said))
+    pypi_extra = examine_extra("cli", {"kind": "pypi", "package": "p", "track": "release"},
+                               "1.0.0", _Unreadable(said))
+    assert (git_source.status, pypi_extra.status) == (status, status)
+    assert not git_source.moves and not pypi_extra.moves
```
