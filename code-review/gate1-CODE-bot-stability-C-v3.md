# Gate 1: bot-stability-C v3 (lhpc-release-bot, plan v4)

**Request.** Judge the code commits below (two commits: degraded issues, the re-run mechanism) against plan v4 (included; its v1–v3 change history omitted). This is v3. v2 folded the findings of rounds 10 and 11 (on the v1 packets A and B) and of a second read (report table "v2: findings folded"); v3 adds the notes of rounds 12 (A v2, GREEN WITH NOTES) and 13 (B v2, RED, two findings) and of a delta read of v2 (report table "v3"). Round 14 (C v2) was GREEN. That means:
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
--- aba7948 bot-stability: a source skipped week after week becomes a PERSISTENT degraded issue

`_degraded` keeps one informational issue (label `degraded`) per degraded
state: opened at the first occurrence, one marked comment per later run
that sees it (`<!--degraded-run:<id>-->`, once per run), `PERSISTENT` in the
title once occurrences (distinct marked runs, the opener's mark in the
body included) reach 3, and closed only
by a run that EXAMINED the key and did not find it degraded. A person's
comment is not an occurrence. It never holds, freezes or blocks. The plan
stage of a `full` run reports its skipped sources this way.

New invariant (the function does not exist on the parent): the tests drive
occurrences 1, 2, the same run twice (no PERSISTENT), 3 (PERSISTENT), a run
that never examined the key (stays open), a recovered key (closed), and
human comments (not counted).

Red-before against the first version of this commit (tree 3ef5797):
test_a_re_run_of_the_opening_run_is_not_a_second_occurrence (r1, r1, r2,
r3) gives "assert [False, False, True, True] == [False, False, False, True]".

--- 559d5fb bot-stability: one re-run mechanism for lost runners and external transfers

`GitHub.wait` re-runs the failed jobs of the attempt just judged for one of
two reasons: `runner-lost` (today's rule: first attempt, once, at once) or
`external` (every failed job is release-verify or slow-build and EVERY
failure and error in its JUnit for that attempt carries
`EXTERNAL-UNAVAILABLE what=<token>` and no STACK-REGRESSION — the contract
with the lanes, determinism M4; an empty or unreadable JUnit is not
evidence). External re-runs wait 0, 1, 2, 5, 10 min; at most five re-runs
of either kind (six attempts); each only while the time left covers its
wait plus the last attempt's duration. A transfer still unavailable after
that makes prove stop as `unproven, external` in identity, so nothing is
attributed or held; its gate is a `degraded gate` issue. A red testlab job,
CI, or a failure before the JUnit is written stays an ordinary red.

Runner loss is re-run on the first attempt this wait judges only. A
`degraded gate` closes only in a run in which its job succeeded. Evidence
that cannot be read (GitHubError) is no transfer failure.

Red-before against the parent (the degraded-issue commit):
test_an_external_outage_that_outlasted_the_re_runs_is_unproven_and_blames_nobody
(its JUnit now carries only the typed transfer line) fails at its
`unproven, external` line with "assert False". Against the first version of
this commit (tree 3ef5797):
test_a_runner_loss_after_an_external_re_run_is_judged_as_it_is gives
"assert [1, 2, 3] == [1, 2]"; test_a_degraded_gate_closes_only_when_its_job_succeeded
gives "assert [3] == []"; test_only_a_failed_job_whose_own_junit_is_all_external_is_external
(the 410 case) gives "GitHubError: GET … -> 410: expired".
The GitHub.wait cases use the new `external` parameter (a new invariant on
the parent: TypeError only); the runner-loss cases are unchanged and green.

v3: a JUnit artifact that is not a zip is unreadable evidence, not a
transfer failure, and the degraded-gate report's own jobs read is
best-effort (an API error closes nothing and never replaces the stop the
evidence earned). Red-before against v2 (tree f63802f): the "bad zip" case
of test_only_a_failed_job_whose_own_junit_is_all_external_is_external gives
"zipfile.BadZipFile: File is not a zip file";
test_a_gate_report_that_cannot_read_its_jobs_never_stops_prove gives
"GitHubError: GET /actions/runs/6/jobs -> 502".
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

## Unchanged code the diff relies on (bot/autofreeze.py at d01d462, lines 18–25)
```python
# What the release lane writes at a genuine per-stack assertion. The lane owns the grammar; this
# is the only place that reads it, and an annotation that does not match is not attribution.
# The grammar `lhpc_testlab.release.stack_regression` publishes, copied deliberately: the lane
# owns it and documents it, and this is the only program that reads it. Searched, never anchored
# — pytest prefixes explanation lines with "E   " and the message with "AssertionError: ". The
# trailing boundary matters: without it `phase=installx` would read as `install`.
REGRESSION = re.compile(r"STACK-REGRESSION stack=(?P<stack>[a-z0-9][a-z0-9_-]*) "
                        r"phase=(?P<phase>install|build|start|readiness)(?=\s|$)")
```


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

## The full diff (`git diff ed4c07c 559d5fb`)
```diff
diff --git a/README.md b/README.md
index 5b975ad..9effd22 100644
--- a/README.md
+++ b/README.md
@@ -90,7 +90,7 @@ proved.
 | image | tags `loraham-images`, waits for both variants | a red build, a draft release, missing evidence, or a tag that no longer names this release's controller |
 | finalize | closes the attempt | anything still owed: it stays open instead |
 
-A run the bot waits on (controller CI, test lab, binary build, image build) whose first attempt is red only because a job lost its runner has its failed jobs re-run once, within the same time bound, and the second attempt is the one judged. Runner loss is what GitHub itself annotates on the job — "The runner has received a shutdown signal", "lost communication with the server" or "was not acquired by Runner" — and every other failed job must `needs` a lost one, directly or through other jobs (read from the run's own workflow file at its commit), and have started after it ended. The attempt issue notes the re-run. Any other red, a workflow file that cannot be read, too little time left, and any second attempt are judged as they are. Evidence read from the re-run's artifacts is the second attempt's own upload, or one from a carried-over job that finished before any failed job started; anything else reads as absent.
+A run the bot waits on (controller CI, test lab, binary build, image build) whose first attempt is red only because a job lost its runner has its failed jobs re-run once, within the same time bound, and the second attempt is the one judged. Runner loss is what GitHub itself annotates on the job — "The runner has received a shutdown signal", "lost communication with the server" or "was not acquired by Runner" — and every other failed job must `needs` a lost one, directly or through other jobs (read from the run's own workflow file at its commit), and have started after it ended. The attempt issue notes the re-run. Any other red, a workflow file that cannot be read, too little time left, and a runner lost on any later attempt are judged as they are. In the test lab's `release-verify` and `slow-build` jobs (the two that write a JUnit), a job whose every failure carries the lanes' typed line `EXTERNAL-UNAVAILABLE what=<token>` — and no `STACK-REGRESSION` — failed on an external transfer, not on the candidate: its failed jobs are re-run after waits of 0, 1, 2, 5 and 10 minutes, at most five re-runs of either kind in one wait (six attempts), each only while the time left covers its wait plus the last attempt's duration. If the transfer is still unavailable after that, the release stops as `unproven, external`: nothing is attributed or held, the next scheduled run tries again, and a `degraded gate: <job>` issue tracks it. A red `testlab` job, CI, or a transfer that failed before the JUnit was written is judged as an ordinary red (the lanes retry their own downloads first). Evidence read from the re-run's artifacts is the second attempt's own upload, or one from a carried-over job that finished before any failed job started; anything else reads as absent.
 
 When a stage before the commit point fails, recovery restores the index and deletes the candidate branch. If the failure named the stack that broke, it also holds that stack and retries once — see [Freeze a pin](#freeze-a-pin).
 
@@ -121,6 +121,12 @@ the channel's typed message and offered the source build. Installed boxes are un
   run's failing jobs with the last lines of their logs). It lives here rather than in the controller so that a
   run whose release credential is the thing that failed can still report; this repository's own
   `GITHUB_TOKEN` writes it. Diagnostics are best-effort; the rest is never omitted.
+- **Something keeps not working, without failing:** one issue labelled `degraded` per state — a
+  source skipped as unreachable (`degraded source: <key>`), or a test-lab gate left unproven by an
+  external outage (`degraded gate: <job>`, closed only by a run in which that job succeeded) —
+  opened at the first run that sees it,
+  commented by every later one, titled `PERSISTENT …` from the third, and closed by the first run
+  that no longer sees it. It holds, freezes and blocks nothing.
 
 ## Freeze a pin
 
diff --git a/bot/cli.py b/bot/cli.py
index 58f0ffc..2b85f2b 100644
--- a/bot/cli.py
+++ b/bot/cli.py
@@ -17,6 +17,7 @@ import subprocess
 import sys
 import tempfile
 import tomllib
+import zipfile
 from dataclasses import asdict
 from pathlib import Path
 
@@ -198,18 +199,79 @@ class Ctx:
 # ---------------------------------------------------------------------------- stage: plan
 
 
-def _wait(ctx, rec: dict, bound: float, att: Attempt | None = None, number: int = 0) -> dict:
+# The lane's typed transfer failure (the contract with the testlab lanes, determinism M4): the
+# first line of an assertion message, searched in the failure's message and text.
+EXTERNAL = re.compile(r"EXTERNAL-UNAVAILABLE what=([a-z0-9][a-z0-9_.:-]*)(?=\s|$)")
+# The only jobs that write a JUnit the bot can read per attempt: (artifact, member).
+EXTERNAL_JUNIT = {"release-verify": ("testlab-logs-release-verify", "junit-release.xml"),
+                  "slow-build": ("slow-build-evidence", "junit-slow-build.xml")}
+
+
+def external_whats(junit: bytes) -> list:
+    """The `what=` of every failing case when EVERY failure and error in this JUnit is a typed
+    external transfer and none carries a regression marker; [] otherwise — no JUnit, no failure
+    at all, an unreadable file, or one failure that is anything else."""
+    if not junit:
+        return []
+    import xml.etree.ElementTree as ET  # noqa: S405
+    try:
+        root = ET.fromstring(junit)     # noqa: S314
+    except ET.ParseError:
+        return []
+    whats = []
+    for case in root.iter("testcase"):
+        for bad in (e for e in case if e.tag in ("failure", "error")):
+            text = (bad.get("message") or "") + "\n" + (bad.text or "")
+            found = EXTERNAL.search(text)
+            if not found or af.REGRESSION.search(text):
+                return []
+            whats.append(found.group(1))
+    return whats
+
+
+def _external_jobs(ctx, rec: dict, run: dict) -> list:
+    """`<job>: <what>` for each failed job of this attempt when EVERY failed job is one with a
+    JUnit and failed only on typed external transfers; [] otherwise (nothing to re-run)."""
+    attempt = run.get("run_attempt", 1)
+    try:
+        failed = [j for j in ctx.gh.jobs(rec["repo"], int(rec["id"]), attempt)
+                  if j.get("conclusion") not in ("success", "skipped", "neutral")]
+        out = []
+        for job in failed:
+            where = EXTERNAL_JUNIT.get(job.get("name", ""))
+            if not where or job.get("conclusion") != "failure":
+                return []
+            whats = external_whats(ctx.gh.artifact_member(rec["repo"], int(rec["id"]),
+                                                          where[0], where[1], attempt))
+            if not whats:
+                return []
+            out += [f"{job['name']}: {w}" for w in whats]
+    except (GitHubError, zipfile.BadZipFile):
+        return []               # evidence that cannot be read is no transfer failure: a red
+    return out
+
+
+def _wait(ctx, rec: dict, bound: float, att: Attempt | None = None, number: int = 0,
+          external: bool = False) -> dict:
     """The one wait for a run this bot judges. When GitHub re-ran a first attempt that lost its
     runner (`GitHub.wait`), the record moves to the new attempt — every judge compares the run
     against the attempt recorded — and the re-run is written down where a maintainer reads."""
-    run = ctx.gh.wait(rec["repo"], int(rec["id"]), bound)
+    run = (ctx.gh.wait(rec["repo"], int(rec["id"]), bound,
+                       external=lambda r: _external_jobs(ctx, rec, r))
+           if external else ctx.gh.wait(rec["repo"], int(rec["id"]), bound))
     if run.get("rerun"):
         # The attempt THIS bot asked for, not whatever GitHub reports now: a third attempt
         # somebody else started is not the one judged, and the identity check must say so.
         rec["attempt"] = run["rerun"]["attempt"] + 1
-        note = (f"{rec['repo']} run {rec['id']}: attempt {run['rerun']['attempt']} lost its "
-                f"runner ({', '.join(run['rerun']['jobs'])}); the failed jobs were re-run once "
-                f"and attempt {rec['attempt']} is the one judged")
+        steps = run.get("reruns") or [dict(run["rerun"], reason="runner-lost")]
+        said = {"runner-lost": "lost its runner", "external": "failed on an external transfer"}
+        note = (f"{rec['repo']} run {rec['id']}: "
+                + "; ".join(f"attempt {s['attempt']} {said.get(s.get('reason'), 'failed')} "
+                            f"({', '.join(s['jobs'])})" for s in steps)
+                + (f"; the failed jobs were re-run once and attempt {rec['attempt']} is the one judged"
+                   if len(steps) == 1 else
+                   f"; the failed jobs were re-run {len(steps)} times and attempt "
+                   f"{rec['attempt']} is the one judged"))
     elif run.get("rerun_error"):
         note = (f"{rec['repo']} run {rec['id']} lost its runner, but the re-run was refused: "
                 f"{run['rerun_error']}")
@@ -251,6 +313,52 @@ def blocking_attempts(open_attempts, retry_of: str) -> list:
             if a.unresolved and not (retry_of and a.run_id == retry_of)]
 
 
+DEGRADED = "degraded"
+PERSISTENT_AFTER = 3        # occurrences of the same degraded state before its issue says so
+
+
+def _degraded(ctx: Ctx, kind: str, seen: dict, examined) -> None:
+    """One informational issue per degraded state of this kind (a source skipped as unreachable,
+    a gate left unproven by an external outage): opened at the first occurrence, a comment per
+    run that sees it again, `PERSISTENT` in the title from the third occurrence, closed by the
+    first run that no longer sees it. It never holds, freezes or blocks anything.
+
+    Occurrences = the distinct run ids of the bot's own marks (`<!--degraded-run:<id>-->`) in the
+    body and the comments; a person's comment is not one, and a run counts once. An issue is closed only
+    for a key this run EXAMINED and did not find degraded — a run that never reached it proves
+    nothing. Best-effort: a report that cannot be written must not stop a release."""
+    prefix = f"degraded {kind}: "
+    mark = f"<!--degraded-run:{ctx.run_id}-->"
+    try:
+        issues = [i for i in ctx.bot_gh.open_issues(BOT, DEGRADED)
+                  if i.get("title", "").replace("PERSISTENT ", "", 1).startswith(prefix)]
+        by_key = {i["title"].replace("PERSISTENT ", "", 1)[len(prefix):]: i for i in issues}
+        for key, why in sorted(seen.items()):
+            issue = by_key.get(key)
+            if issue is None:
+                ctx.bot_gh.create_issue(BOT, prefix + key,
+                                        f"Seen in {ctx.run_url}: {why}\n\nInformational: it "
+                                        f"holds and blocks nothing, and closes itself when a run "
+                                        f"no longer sees it.\n{mark}", [DEGRADED])
+                continue
+            notes = [issue.get("body") or ""] + [
+                c.get("body", "") for c in ctx.bot_gh.comments(BOT, issue["number"])]
+            if not any(mark in n for n in notes):
+                ctx.bot_gh.comment(BOT, issue["number"], f"Seen again in {ctx.run_url}: {why}\n{mark}")
+                notes.append(mark)
+            # The opening run's mark is in the body, so a re-run of that run counts once too.
+            occurrences = len({m for n in notes
+                               for m in re.findall(r"<!--degraded-run:([^>]+)-->", n)})
+            if occurrences >= PERSISTENT_AFTER and not issue["title"].startswith("PERSISTENT "):
+                ctx.bot_gh.update_issue(BOT, issue["number"], title="PERSISTENT " + prefix + key)
+        for key, issue in by_key.items():
+            if key in examined and key not in seen:
+                ctx.bot_gh.comment(BOT, issue["number"], f"Cleared in {ctx.run_url}.")
+                ctx.bot_gh.update_issue(BOT, issue["number"], state="closed")
+    except GitHubError as exc:
+        print(f"the {kind} degraded issues could not be updated: {exc}", file=sys.stderr)
+
+
 FINISHABLE_OWES = {"dev integration", "the image"}
 REFUSED = re.compile(r"-> 4\d\d\b")     # GitHubError text for an HTTP 4xx answer (gh.py request)
 
@@ -368,6 +476,9 @@ def stage_plan(ctx: Ctx) -> int:
 
     ctx.summary(rp.summary(found, "No pin has moved" if not moved else
                            f"{len(moved)} pin(s) to move"))
+    if ctx.mode == "full":
+        _degraded(ctx, "source", {f.key: f.detail for f in found if f.status == "skipped"},
+                  examined={f.key for f in found})
     if ctx.mode == "watch-only":
         ctx.out(proceed="false")
         print("watch-only: reported, nothing else.")
@@ -1088,9 +1199,26 @@ def stage_prove(ctx: Ctx) -> int:
         if not rec:
             identity.append(f"{name}: this attempt never recorded a run")
             continue
-        run = _wait(ctx, rec, bound, att, number)
+        run = _wait(ctx, rec, bound, att, number, external=(name == "testlab"))
         got_identity, got_offlane, got_outcome = _run_problems(ctx, att, name, rec, run,
                                                                 required)
+        if name == "testlab" and not run.get("timed_out"):
+            # A transfer that stayed unavailable through every re-run proves nothing either way:
+            # `unproven, external` — in identity, so it can never attribute a stack. It is
+            # retried by the next scheduled run, and its gate is reported as degraded.
+            unresolved = run.get("external_unresolved") or []
+            if unresolved:
+                identity.append("testlab: unproven, external — " + "; ".join(unresolved))
+            # A gate is examined only when its job succeeded on the attempt judged: a job that
+            # was red for any other reason says nothing about the outage, so it closes nothing.
+            try:
+                green = {j.get("name") for j in ctx.gh.jobs(LHPC, int(rec["id"]),
+                                                            run.get("run_attempt", 1))
+                         if j.get("conclusion") == "success"}
+            except GitHubError:
+                green = set()           # a report that cannot be read closes nothing
+            _degraded(ctx, "gate", {u.split(":", 1)[0]: u for u in unresolved},
+                      examined=set(EXTERNAL_JUNIT) & green)
         # A measured red OUTSIDE the release lane disqualifies an attribution exactly as a broken
         # identity does, so it joins the same list here: the lane did not name it, and holding an
         # upstream pin for it would freeze the wrong project.
diff --git a/bot/gh.py b/bot/gh.py
index f30197d..b0e802a 100644
--- a/bot/gh.py
+++ b/bot/gh.py
@@ -26,6 +26,10 @@ TERMINAL = ("completed",)
 # GitHub's own words for a job whose runner went away. Nothing else counts as runner loss.
 RUNNER_LOST = ("The runner has received a shutdown signal", "lost communication with the server",
                "was not acquired by Runner")
+# The waits before each re-run of a job that failed only on an external transfer (decision c1:
+# at once, then growing), and the cap on re-runs of any kind in one wait.
+EXTERNAL_WAITS = (0, 60, 120, 300, 600)
+MAX_RERUNS = 5
 
 
 class GitHubError(RuntimeError):
@@ -163,38 +167,70 @@ class GitHub:
             self.request("POST", f"/repos/{repo}/actions/runs/{run_id}/cancel")
 
     def wait(self, repo: str, run_id: int, timeout_s: float, poll_s: float = 30.0,
-             rerun: bool = True) -> dict:
+             rerun: bool = True, external=None) -> dict:
         """Block until the run is terminal. A timeout returns the run as it stands — the caller
         must then settle the writer, because a run that timed out here is still running there.
 
-        A first attempt that only lost a runner (`runner_lost`) has its failed jobs re-run ONCE
-        and is waited on again under the same id; the returned run then carries `rerun`
-        (the attempt that was re-run and its lost jobs). Any other red comes back as it is.
-        ONE bound covers both attempts — the caller's job has its own timeout around it — so a
-        re-run is asked for only while the time left is at least the time already spent.
+        ONE re-run mechanism, two reasons, re-running only the failed jobs of the attempt just
+        judged and waiting again under the same id:
+          * `runner-lost` — the first attempt THIS wait judges (no re-run made yet), when its
+            failed jobs only lost their runner (`runner_lost`, which also refuses any
+            `run_attempt` but 1): once, at once;
+          * `external` — every failed job is one `external(run)` names (typed transfer failures
+            only; the caller reads the evidence): after waits of `EXTERNAL_WAITS`, one per such
+            re-run.
+        At most `MAX_RERUNS` re-runs of either kind, and ONE bound covers every attempt: a re-run
+        is asked only while the time left covers its wait plus the duration of the attempt just
+        judged. The returned run carries `rerun` (the last re-run: the attempt re-run and its
+        jobs) and `reruns` (each, with its reason); when the last attempt still failed only on
+        an external transfer, `external_unresolved` names the jobs.
         `rerun=False` for runs that are being settled, not judged."""
         start = time.monotonic()
-        deadline, reran = start + timeout_s, None
+        deadline, attempt_start, reruns = start + timeout_s, start, []
         while True:
             run = self.run(repo, run_id)
-            if reran:
-                run["rerun"] = reran
+            if reruns:
+                run["rerun"] = {"attempt": reruns[-1]["attempt"], "jobs": reruns[-1]["jobs"]}
+                run["reruns"] = [dict(r) for r in reruns]
             # After the re-run request the run still reads as the old, finished attempt until
             # GitHub has started the new one; that old answer is not the result.
             done = (run.get("status") in TERMINAL
-                    and not (reran and run.get("run_attempt", 1) <= reran["attempt"]))
+                    and not (reruns and run.get("run_attempt", 1) <= reruns[-1]["attempt"]))
             if done:
-                lost = [] if (reran or not rerun) else self.runner_lost(repo, run)
+                if not rerun:
+                    return run
+                reason, jobs = "", []
+                if not reruns:                  # the first attempt this wait judges, only
+                    jobs = self.runner_lost(repo, run)
+                    reason = "runner-lost" if jobs else ""
+                if not reason and external is not None and run.get("conclusion") == "failure":
+                    jobs = external(run)
+                    reason = "external" if jobs else ""
+                if not reason:
+                    return run
+                done_external = sum(r["reason"] == "external" for r in reruns)
+                wait_s = EXTERNAL_WAITS[done_external] if (
+                    reason == "external" and done_external < len(EXTERNAL_WAITS)) else 0
                 # Measured AFTER the classification: its HTTP calls spend the same bound.
                 now = time.monotonic()
-                if not lost or deadline - now < now - start:
+                if (len(reruns) >= MAX_RERUNS
+                        or (reason == "external" and done_external >= len(EXTERNAL_WAITS))
+                        or deadline - now < wait_s + (now - attempt_start)):
+                    if reason == "external":
+                        run["external_unresolved"] = jobs
                     return run
+                if wait_s:
+                    time.sleep(wait_s)
                 try:
                     self.request("POST", f"/repos/{repo}/actions/runs/{run_id}/rerun-failed-jobs")
                 except GitHubError as exc:
                     run["rerun_error"] = str(exc)
+                    if reason == "external":
+                        run["external_unresolved"] = jobs
                     return run
-                reran = {"attempt": run.get("run_attempt", 1), "jobs": lost}
+                reruns.append({"attempt": run.get("run_attempt", 1), "jobs": jobs,
+                               "reason": reason})
+                attempt_start = time.monotonic()
             elif time.monotonic() >= deadline:
                 run["timed_out"] = True
                 return run
diff --git a/tests/test_attempt.py b/tests/test_attempt.py
index b6e8252..0f08c17 100644
--- a/tests/test_attempt.py
+++ b/tests/test_attempt.py
@@ -247,3 +247,35 @@ def test_a_finish_dispatch_that_may_have_been_accepted_keeps_its_claim(said):
         cli.stage_plan(later)
     assert later.sent == []
 
+# ---- one unreachable upstream does not stop the others from moving ----
+
+class _Reached(Exception):
+    """Raised where the plan goes on to claim and build: it got past the fault gate."""
+
+
+def test_an_unreachable_source_beside_a_move_is_reported_and_the_plan_goes_on(tmp_path,
+                                                                              monkeypatch):
+    from bot import cli
+    from bot.upstream import examine
+    from tests.test_upstream import A, B, FakeRemote, _Unreadable, src
+    unreachable = _Unreadable("git -C x fetch -q --tags origin main: fatal: unable to access "
+                              "'https://h/': Could not resolve host: h")
+    found = [examine(src(A, path="src/a"), {"track": "tip"}, unreachable),
+             examine(src(A, path="src/b"), {"track": "tip"}, FakeRemote([A, B]))]
+    (tmp_path / "loraham-pi-control").mkdir()
+    (tmp_path / "loraham-pi-control" / cli.MANIFEST.split("/")[-1]).write_text("")
+    monkeypatch.setattr(cli, "MANIFEST", cli.MANIFEST.split("/")[-1])
+    monkeypatch.setattr(cli, "git", lambda *a, **k: "b" * 40)
+    monkeypatch.setattr(cli, "_findings", lambda ctx, text, policy: (found, None))
+    def note(ctx, kind, seen, examined):
+        ctx.degraded.append((kind, sorted(seen), sorted(examined)))
+    monkeypatch.setattr(cli, "_degraded", note, raising=False)       # absent before the change
+    monkeypatch.setattr(cli, "_check_parent", lambda ctx, frozen: (_ for _ in ()).throw(_Reached))
+    ctx = _PlanCtx(_owing(state="complete"))
+    ctx.degraded = []
+    ctx.clone = lambda repo, ref="", token="": tmp_path / "loraham-pi-control"
+    ctx.ref = lambda repo, ref: "d" * 40
+    with pytest.raises(_Reached):
+        cli.stage_plan(ctx)
+    assert any("Not reachable this run" in s and "`src/a`" in s for s in ctx.summaries)
+    assert ctx.degraded == [("source", ["src/a"], ["src/a", "src/b"])]
diff --git a/tests/test_proof.py b/tests/test_proof.py
index bcadb4e..11c3211 100644
--- a/tests/test_proof.py
+++ b/tests/test_proof.py
@@ -6,6 +6,8 @@ loudly as one that proved something. Each case here is one of those mistakes.
 """
 from __future__ import annotations
 
+import pytest
+
 from bot.attempt import Attempt
 from bot.cli import (
     LANE_JOB,
@@ -305,12 +307,12 @@ def _split(**over):
 class _ProveCtx:
     """Only what `stage_prove` reaches for. The GitHub seam is the only thing faked."""
 
-    attempt_id = "1"
+    attempt_id = run_id = "1"
     run_url = "https://example.invalid/run/1"
 
     def __init__(self, *, jobs_by_run):
         from bot.attempt import Attempt
-        self.gh = self
+        self.gh = self.bot_gh = self
         self._jobs_by_run = jobs_by_run
         self.summaries, self.saved = [], []
         self.att = Attempt(run_id="1", version="0.3.7", base_sha="b" * 40, candidate_sha=CAND,
@@ -335,7 +337,7 @@ class _ProveCtx:
     def dispatch(self, repo, workflow, ref, inputs=None):
         return 6
 
-    def wait(self, repo, run_id, bound):
+    def wait(self, repo, run_id, bound, external=None):
         # A run is red whenever any of its jobs is, which is what GitHub does.
         red = any(j["conclusion"] != "success" for j in self._jobs_by_run[int(run_id)])
         return {"head_sha": CAND, "workflow_id": 42, "run_attempt": 1,
@@ -344,6 +346,13 @@ class _ProveCtx:
     def jobs(self, repo, run_id, attempt=1):
         return list(self._jobs_by_run[int(run_id)])
 
+    def open_issues(self, repo, label):
+        return []
+
+    def create_issue(self, repo, title, body, labels):
+        self.summaries.append(f"issue: {title}")
+        return {"number": 1}
+
     def failing_jobs(self, repo, run_id, attempt, lines=20):
         return [(j["name"], f"https://example.invalid/job/{j['name']}", "E   the last error line")
                 for j in self._jobs_by_run[int(run_id)] if j["conclusion"] != "success"]
@@ -618,3 +627,126 @@ def test_a_prove_stop_names_each_failing_job_with_its_last_lines():
     assert "https://github.com/makrohard/loraham-pi-control/actions/runs/6" in detail
     assert f"`{cli.LANE_JOB}`" in detail and "the last error line" in detail
     assert "actions/runs/5" not in detail          # the green CI run is not listed
+
+
+def test_an_external_outage_that_outlasted_the_re_runs_is_unproven_and_blames_nobody():
+    """The lane's red is only a transfer that stayed unavailable: the attempt stops, nothing is
+    attributed (so nothing is held), and the reason says `unproven, external`."""
+    import pytest
+
+    from bot import cli
+    green = [{"name": n, "conclusion": "success", "head_sha": CAND} for n in cli.REQUIRED_CI]
+    lane = [{"name": "testlab", "conclusion": "success", "head_sha": CAND},
+            {"name": "slow-build", "conclusion": "success", "head_sha": CAND},
+            {"name": cli.LANE_JOB, "conclusion": "failure", "head_sha": CAND}]
+
+    class _Outage(_ProveCtx):
+        def wait(self, repo, run_id, bound, external=None):
+            run = super().wait(repo, run_id, bound)
+            if int(run_id) == 6:
+                run["external_unresolved"] = ["release-verify: binary:meshcom"]
+            return run
+
+        def artifact_member(self, repo, run_id, name, member, attempt=1):
+            # What the lane writes on an outage: a typed transfer failure, never a marker.
+            return EXTERNAL_JUNIT
+
+    ctx = _Outage(jobs_by_run={5: green, 6: lane})
+    with pytest.raises(cli.Stop) as stop:
+        cli.stage_prove(ctx)
+    assert ctx.att.regression == []
+    assert any(line.startswith("- testlab: unproven, external") for line in
+               stop.value.observed.splitlines())
+
+
+EXTERNAL_JUNIT = (b'<testsuite><testcase name="test_release_kiss"><failure message="EXTERNAL-'
+                  b'UNAVAILABLE what=binary:meshcom">fetch failed</failure></testcase></testsuite>')
+
+
+class _JobsGh:
+    def __init__(self, jobs, junit, error=None):
+        self._jobs, self._junit, self._error = jobs, junit, error
+
+    def jobs(self, repo, run_id, attempt=1):
+        return self._jobs
+
+    def artifact_member(self, repo, run_id, name, member, attempt=1):
+        if self._error:
+            raise self._error
+        return self._junit
+
+
+@pytest.mark.parametrize("name, conclusion, junit, error, want", [
+    ("release-verify", "failure", EXTERNAL_JUNIT, None, ["release-verify: binary:meshcom"]),
+    ("testlab", "failure", EXTERNAL_JUNIT, None, []),            # a job with no JUnit
+    ("release-verify", "cancelled", EXTERNAL_JUNIT, None, []),
+    ("release-verify", "failure", b"", None, []),                # the artifact is absent
+    ("release-verify", "failure", EXTERNAL_JUNIT, "GET … -> 410: expired", []),
+    ("release-verify", "failure", EXTERNAL_JUNIT, "bad zip", []),   # not a zip archive
+])
+def test_only_a_failed_job_whose_own_junit_is_all_external_is_external(name, conclusion, junit,
+                                                                      error, want):
+    import zipfile
+    from types import SimpleNamespace
+
+    from bot import cli
+    from bot.gh import GitHubError
+    raised = {None: None, "bad zip": zipfile.BadZipFile("File is not a zip file")}
+    gh = _JobsGh([{"name": name, "conclusion": conclusion}], junit,
+                 raised[error] if error in raised else GitHubError(error))
+    got = cli._external_jobs(SimpleNamespace(gh=gh), {"repo": "o/r", "id": 6}, {"run_attempt": 1})
+    assert got == want
+
+
+@pytest.mark.parametrize("verify, closed", [("failure", []), ("success", [3])])
+def test_a_degraded_gate_closes_only_when_its_job_succeeded(verify, closed):
+    """A red lane for any other reason (here a marked regression) says nothing about the outage."""
+    from bot import cli
+    green = [{"name": n, "conclusion": "success", "head_sha": CAND} for n in cli.REQUIRED_CI]
+    lane = [{"name": "testlab", "conclusion": "failure", "head_sha": CAND},
+            {"name": "slow-build", "conclusion": "failure", "head_sha": CAND},
+            {"name": cli.LANE_JOB, "conclusion": verify, "head_sha": CAND}]
+
+    class _Gate(_ProveCtx):
+        closes = []
+
+        def open_issues(self, repo, label):
+            return ([{"number": 3, "title": "degraded gate: release-verify"}]
+                    if label == cli.DEGRADED else [])
+
+        def comment(self, repo, number, body):
+            pass
+
+        def update_issue(self, repo, number, **fields):
+            self.closes.append(number)
+
+    ctx = _Gate(jobs_by_run={5: green, 6: lane})
+    with pytest.raises(cli.Stop):
+        cli.stage_prove(ctx)
+    assert ctx.closes == closed
+
+
+def test_a_gate_report_that_cannot_read_its_jobs_never_stops_prove():
+    """The degraded-gate report is best-effort: an API error there must not replace the stop
+    the evidence earned (or stop a proven candidate)."""
+    from bot import cli
+    from bot.gh import GitHubError
+    green = [{"name": n, "conclusion": "success", "head_sha": CAND} for n in cli.REQUIRED_CI]
+    lane = [{"name": "testlab", "conclusion": "success", "head_sha": CAND},
+            {"name": "slow-build", "conclusion": "success", "head_sha": CAND},
+            {"name": cli.LANE_JOB, "conclusion": "failure", "head_sha": CAND}]
+
+    class _Flaky(_ProveCtx):
+        reads = 0
+
+        def jobs(self, repo, run_id, attempt=1):
+            if int(run_id) == 6:
+                self.reads += 1
+                if self.reads == 2:                    # the gate report's own read
+                    raise GitHubError("GET /actions/runs/6/jobs -> 502")
+            return super().jobs(repo, run_id, attempt)
+
+    ctx = _Flaky(jobs_by_run={5: green, 6: lane})
+    with pytest.raises(cli.Stop) as stop:
+        cli.stage_prove(ctx)
+    assert "the candidate is not proven" in stop.value.observed
diff --git a/tests/test_report.py b/tests/test_report.py
index 17f8dc2..e3bf7cd 100644
--- a/tests/test_report.py
+++ b/tests/test_report.py
@@ -71,6 +71,72 @@ def test_the_opening_names_the_event_that_started_the_run(monkeypatch, retry_of,
     assert word in ctx.bot_gh.created[0].splitlines()[0]
 
 
+# ---- a degraded state that persists is visible, never blocking ----
+
+class _Store:
+    def __init__(self):
+        self.issues, self.notes, self.n = {}, {}, 0
+
+    def open_issues(self, repo, label):
+        return [{"number": n, "title": i["title"], "body": i["body"]}
+                for n, i in self.issues.items() if i["state"] == "open"]
+
+    def create_issue(self, repo, title, body, labels):
+        self.n += 1
+        self.issues[self.n] = {"title": title, "state": "open", "body": body}
+        self.notes[self.n] = []
+        return {"number": self.n}
+
+    def comment(self, repo, number, body):
+        self.notes[number].append(body)
+
+    def comments(self, repo, number):
+        return [{"body": b} for b in self.notes[number]]
+
+    def update_issue(self, repo, number, **fields):
+        self.issues[number].update(fields)
+
+
+class _RunCtx:
+    def __init__(self, store, run_id):
+        self.bot_gh, self.run_id = store, run_id
+        self.run_url = f"https://example.invalid/run/{run_id}"
+
+
+def test_a_skipped_source_is_persistent_from_its_third_run_and_closes_when_seen_no_more():
+    store = _Store()
+    seen, examined = {"src/x": "not reachable this run, pin kept"}, {"src/x", "src/y"}
+    titles = []
+    for run in ("r1", "r2", "r2", "r3"):           # r2 twice: one run counts once
+        cli._degraded(_RunCtx(store, run), "source", seen, examined)
+        titles.append(store.issues[1]["title"])
+    assert [t.startswith("PERSISTENT ") for t in titles] == [False, False, False, True]
+    assert len(store.issues) == 1                      # one issue, not one per run
+    cli._degraded(_RunCtx(store, "r4"), "source", {}, set())     # never examined src/x
+    assert store.issues[1]["state"] == "open"
+    cli._degraded(_RunCtx(store, "r5"), "source", {}, examined)  # examined, and recovered
+    assert store.issues[1]["state"] == "closed"
+
+
+def test_a_persons_comment_is_not_an_occurrence():
+    store = _Store()
+    seen = {"src/x": "not reachable"}
+    cli._degraded(_RunCtx(store, "r1"), "source", seen, {"src/x"})
+    store.comment("o/r", 1, "I looked at this; the host is down for maintenance.")
+    store.comment("o/r", 1, "Still down.")
+    cli._degraded(_RunCtx(store, "r2"), "source", seen, {"src/x"})
+    assert not store.issues[1]["title"].startswith("PERSISTENT ")
+
+
+def test_a_re_run_of_the_opening_run_is_not_a_second_occurrence():
+    store = _Store()
+    titles = []
+    for run in ("r1", "r1", "r2", "r3"):           # GitHub re-runs keep the run id
+        cli._degraded(_RunCtx(store, run), "source", {"src/x": "not reachable"}, {"src/x"})
+        titles.append(store.issues[1]["title"].startswith("PERSISTENT "))
+    assert titles == [False, False, False, True]
+
+
 def test_an_expiring_incident_promises_renewal_only_on_an_attributable_regression():
     # The same rule as the README: an unmarked red writes no hold, so it renews nothing.
     from bot import report as rp
diff --git a/tests/test_rerun.py b/tests/test_rerun.py
index acca172..06b8192 100644
--- a/tests/test_rerun.py
+++ b/tests/test_rerun.py
@@ -387,3 +387,107 @@ def test_the_time_spent_classifying_counts_against_the_bound(clock):
     got = g.wait("o/r", 77, 200, poll_s=30)
     assert g.posts == []
     assert got["run_attempt"] == 1 and "rerun" not in got
+
+
+# ---- the one re-run mechanism: typed external transfer failures (decision c1) ----
+
+from bot.cli import external_whats  # noqa: E402
+
+TYPED = "AssertionError: EXTERNAL-UNAVAILABLE what=binary:meshcom\nurlopen error [Errno -3]"
+
+
+def junit(*failures, tag="failure"):
+    cases = "".join(f'<testcase name="c{i}"><{tag} message="{m}">{m}</{tag}></testcase>'
+                    for i, m in enumerate(failures))
+    return f"<testsuite>{cases}<testcase name='ok'/></testsuite>".encode()
+
+
+@pytest.mark.parametrize("doc, whats", [
+    (junit(TYPED), ["binary:meshcom"]),
+    (junit(TYPED, tag="error"), ["binary:meshcom"]),                   # a setup error counts
+    (junit(TYPED, "Failed: EXTERNAL-UNAVAILABLE what=deb:graywolf"), ["binary:meshcom",
+                                                                      "deb:graywolf"]),
+    (b"", []),                                                         # no evidence
+    (b"<testsuite><testcase name='ok'/></testsuite>", []),             # red job, no failure
+    (junit(TYPED, "AssertionError: assert 1 == 2"), []),              # one real failure
+    (junit(TYPED + "\nSTACK-REGRESSION stack=kiss phase=start"), []),  # both: not external
+    (junit("EXTERNAL-UNAVAILABLE what=Binary"), []),                  # not the grammar
+    (b"<testsuite", []),                                               # unreadable
+])
+def test_only_a_junit_whose_every_failure_is_a_typed_transfer_is_external(doc, whats):
+    assert external_whats(doc) == whats
+
+
+class Scripted(ghmod.GitHub):
+    """One run whose attempts end as scripted; a re-run POST starts the next attempt."""
+
+    def __init__(self, outcomes, lost_on=()):
+        super().__init__("t")
+        self.outcomes, self.attempt, self.posts, self.lost_on = outcomes, 1, [], set(lost_on)
+
+    def run(self, repo, run_id):
+        return {"id": 77, "status": "completed", "run_attempt": self.attempt,
+                "conclusion": self.outcomes[self.attempt - 1]}
+
+    def runner_lost(self, repo, run):
+        return ["testlab"] if run["run_attempt"] in self.lost_on else []
+
+    def request(self, method, path, body=None, accept="application/vnd.github+json"):
+        assert method == "POST" and path == RERUN
+        self.posts.append(self.attempt)
+        self.attempt += 1
+
+
+def external_until(n):
+    """The external classifier of a lane that is red on a transfer until attempt `n`."""
+    return lambda run: ["release-verify: binary:meshcom"] if run["run_attempt"] < n else []
+
+
+def test_a_pure_external_red_is_re_run_at_once_and_the_green_attempt_is_judged(clock):
+    g = Scripted(["failure", "success"])
+    got = g.wait("o/r", 77, 6000, external=external_until(2))
+    assert (g.posts, got["run_attempt"], got["conclusion"]) == ([1], 2, "success")
+    assert got["reruns"] == [{"attempt": 1, "jobs": ["release-verify: binary:meshcom"],
+                              "reason": "external"}]
+    assert "external_unresolved" not in got
+
+
+def test_five_external_re_runs_mean_six_attempts_and_then_unproven(clock):
+    g = Scripted(["failure"] * 6)
+    got = g.wait("o/r", 77, 100_000, external=external_until(99))
+    assert g.posts == [1, 2, 3, 4, 5] and got["run_attempt"] == 6
+    assert clock[0] == sum(ghmod.EXTERNAL_WAITS) + 5 * 30   # the waits + one poll per re-run
+    assert got["external_unresolved"] == ["release-verify: binary:meshcom"]
+
+
+def test_a_runner_loss_and_external_failures_share_one_cap(clock):
+    # Attempt 1 lost its runner (re-run at once, once); attempts 2–5 failed on a transfer
+    # (waits 0, 1, 2, 5 min: the EXTERNAL index starts at its own 0); attempt 6 still did:
+    # five re-runs in all, then unproven.
+    g = Scripted(["failure"] * 6, lost_on={1})
+    got = g.wait("o/r", 77, 100_000, external=external_until(99))
+    assert g.posts == [1, 2, 3, 4, 5]
+    assert [r["reason"] for r in got["reruns"]] == ["runner-lost"] + ["external"] * 4
+    assert clock[0] == sum(ghmod.EXTERNAL_WAITS[:4]) + 5 * 30
+    assert got["external_unresolved"]
+
+
+
+def test_a_runner_loss_after_an_external_re_run_is_judged_as_it_is(clock):
+    # Runner loss is re-run on the first attempt only; attempt 3 losing its runner is a red.
+    g = Scripted(["failure"] * 4, lost_on={3})
+    got = g.wait("o/r", 77, 100_000, external=external_until(3))
+    assert g.posts == [1, 2] and got["run_attempt"] == 3 and got["conclusion"] == "failure"
+
+def test_no_external_re_run_when_its_wait_and_the_last_attempt_no_longer_fit(clock):
+    # Attempt 1 took 0 s here; the second external re-run waits 60 s, and only 30 s are left.
+    g = Scripted(["failure"] * 3)
+    got = g.wait("o/r", 77, 30, external=external_until(99))
+    assert g.posts == [1]                               # the first (0 s wait) still fitted
+    assert got["external_unresolved"]
+
+
+def test_a_job_that_is_not_purely_external_is_never_re_run(clock):
+    g = Scripted(["failure", "success"])
+    got = g.wait("o/r", 77, 6000, external=lambda run: [])
+    assert g.posts == [] and got["conclusion"] == "failure" and "external_unresolved" not in got
```
