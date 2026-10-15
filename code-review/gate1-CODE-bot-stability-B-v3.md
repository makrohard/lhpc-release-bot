# Gate 1: bot-stability-B v3 (lhpc-release-bot, plan v4)

**Request.** Judge the code commits below (two commits: the hold model, build gate naming) against plan v4 (included; its v1–v3 change history omitted). This is v3. v2 folded the findings of rounds 10 and 11 (on the v1 packets A and B) and of a second read (report table "v2: findings folded"); v3 adds the notes of rounds 12 (A v2, GREEN WITH NOTES) and 13 (B v2, RED, two findings) and of a delta read of v2 (report table "v3"). Round 14 (C v2) was GREEN. That means:
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
--- a6abb30 bot-stability: bot holds expire after a week; a build failure holds only what moved

A hold the bot writes carries `held_until` (seven days, UTC). `freeze_of`
treats it as frozen until that date, then the input moves again; a malformed
date or a date without a freeze is a policy problem. A person's freeze has
no date and never expires. Writing the hold again renews only the bot's own
date. When the attribution is the binary builder's own evidence, `decide`
holds only the inputs the candidate moved (the lane's attribution still
holds the stack's composition). `finalize` thaws a proved hold: an expired
hold on an input this green release moved loses its two lines and its
incident is closed when no hold of it remains (finalize and finish-close
gain contents: write). The incident text names the expiry date.

Red-before against d01d462: test_a_bot_hold_whose_date_has_passed_lets_the_pin_move
gives "AssertionError: assert False" (the input stays frozen);
test_a_malformed_held_until_is_a_policy_problem gives "assert []" for both
rules. The other new cases exercise new functions and parameters (today,
moved_only, until, thaw_edit, _thaw_proved): a new invariant, they fail on
the parent with AttributeError/TypeError only. Plan deviation: a meshcom
build failure with no meshcom input moved was already refused by `decide`
on the parent ("moved nothing this run") — a control, not a red-before.

Red-before against the first version of this commit (tree 3ef5797):
test_a_thaw_whose_policy_write_fails_reports_and_never_raises gives
"OSError: read-only file system" (finalize would turn red after the
release); test_an_incident_that_cannot_be_closed_keeps_its_hold_line_for_the_next_release
gives "GitHubError: PATCH /issues/62 -> 502" after the thaw was pushed
(the incident orphaned) — incidents are now closed before the push;
test_a_malformed_held_until_is_a_policy_problem with 2026-13-45 gives
"assert []"; test_a_build_failure_that_moved_nothing_of_its_stack_is_reported_not_held
gives "assert False" (the refusal reached only stdout).
test_a_build_failure_holds_only_what_it_moved_in_the_exact_policy is
coverage: the exact policy.toml a builder hold writes.

v3: the incident text states the README's rule (an attributable regression
that holds the inputs again renews the date; an unmarked red leaves it
expired). Red-before against v2 (tree f63802f):
test_an_expiring_incident_promises_renewal_only_on_an_attributable_regression
gives "assert 'attributable regression that holds them again renews' in
'…a red one renews it for another week…'".

--- ed4c07c bot-stability: a failed binary build names its failing job and last log lines

The build stage's failure stop passes `_red_runs` for its builder run as
diagnostics (now taking a dict of runs; prove passes att.runs), so the gate
a firmware or runner move failed on — the builder's compile, apply step or
smoke boot — is in the report. The run URL stays the fallback.

Red-before against d01d462: test_a_failed_build_names_its_failing_job_and_last_lines
gives "AssertionError: assert '`build`' in 'https://example.invalid/build/777'".
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

## Unchanged code the report relies on (bot/cli.py `stage_build` at ed4c07c, lines 834–864: the point-11 refutation)
```python
    att.runs[f"binary:{stack}"] = ctx.record_run(BIN, run_id)
    ctx.save_attempt(number, att)
    run = _wait(ctx, att.runs[f"binary:{stack}"], BOUNDS["binary"], att, number)

    entry = _candidate_entry(ctx, att.runs[f"binary:{stack}"], stack, att.candidate_sha)
    if entry:
        att.published[stack] = entry
        ctx.save_attempt(number, att)

    if run.get("timed_out"):
        raise Stop("build", f"the {stack} binary build did not finish within its bound.",
                   "Recovery settles the run before deciding anything; the attempt stays open "
                   "until it can.", detail=run.get("html_url", ""))
    if run.get("conclusion") != "success":
        # A red builder is not by itself an upstream fault: it is just as likely to be the
        # runner, the network, or a cancellation. It attributes only when the build ITSELF says
        # the recipe broke — the same marker the release lane emits, written by the builder at
        # its own compile step and read here, bound to this stack, this run and this candidate.
        att.regression = _builder_regression(ctx, stack, run_id, run, att)
        if att.regression:
            att.evidence = (f"binary build run {run_id} for {stack} on "
                            f"{att.candidate_sha[:9]}")
            ctx.save_attempt(number, att)
        # The failing gate (the builder's compile, its smoke boot, …) is named by the job and its
        # last log lines — what a firmware or runner move failed on, without opening the run.
        raise Stop("build", f"the {stack} binary build did not succeed "
                   f"({run.get('conclusion')}).",
                   "Recovery restores the index for whatever this attempt published; nothing "
                   "was released.",
                   detail=_red_runs(ctx, {f"binary:{stack}": att.runs[f"binary:{stack}"]})
                   or run.get("html_url", ""))
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

## The full diff (`git diff b10346a ed4c07c`)
```diff
diff --git a/.github/workflows/release.yml b/.github/workflows/release.yml
index 7edfca9..b816da7 100644
--- a/.github/workflows/release.yml
+++ b/.github/workflows/release.yml
@@ -203,6 +203,9 @@ jobs:
     # Not `always()`: closing an attempt is the one thing a CANCELLED run must never do. An
     # operator who stops a run wants what it did left visible and repairable, not tidied away.
     if: ${{ !cancelled() && needs.release.result == 'success' }}
+    permissions:
+      contents: write           # the auto-thaw of a proved, expired hold in policy.toml
+      issues: write
     runs-on: ubuntu-latest
     timeout-minutes: 20
     steps:
@@ -288,6 +291,9 @@ jobs:
     # nothing is owed.
     needs: [finish-integrate, finish-image]
     if: ${{ always() && inputs.mode == 'finish' }}
+    permissions:
+      contents: write           # the auto-thaw of a proved, expired hold in policy.toml
+      issues: write
     runs-on: ubuntu-latest
     timeout-minutes: 20
     env:
diff --git a/README.md b/README.md
index 0bbe180..5b975ad 100644
--- a/README.md
+++ b/README.md
@@ -135,8 +135,9 @@ freeze = "Upstream startup regression; hold the tested revision until the fix is
 
 The held value is whatever the controller manifest already pins — it is never copied into policy,
 so there is one source of truth. Every run still reports the input, its hold and what upstream has
-done since, and never counts it as something to move. Delete the line to thaw. There is no expiry:
-time passing is not evidence that the problem is fixed.
+done since, and never counts it as something to move. Delete the line to thaw. A hold you write
+has no expiry: time passing is not evidence that the problem is fixed. Only the holds the bot
+writes itself carry `held_until` (below).
 
 - **Set or lift a hold while the bot is idle.** Policy is read from the revision a run checked
   out, so a change cannot reach an attempt that has already prepared a candidate. Settle any open
@@ -152,7 +153,8 @@ time passing is not evidence that the problem is fixed.
 
 If the release lane fails and its evidence NAMES the stack that failed, the bot holds that
 stack's composition itself, opens an incident and retries once with everything else still
-advancing. It never guesses: it acts only on an assertion the lane marked as that stack's own
+advancing. When the evidence is the binary builder's own (a stack's binary build failed at its
+compile step), only the inputs this candidate MOVED are held; the stack's other inputs keep moving. It never guesses: it acts only on an assertion the lane marked as that stack's own
 install, build, start or readiness, so an infrastructure failure, a cancelled run, or a case that
 failed while stopping its predecessor produces an ordinary failure report and no hold.
 
@@ -189,8 +191,11 @@ exactly one retry. The retry cannot retry — a chain would peel stacks off one
 something passed. The incident carries the rejected candidate, the retained one and the retry
 link, and it does not block later releases, because by then the attempt is settled.
 
-Lifting it is the same explicit thaw as any other hold. Nothing expires, and a newer upstream
-release is not evidence that the problem is fixed.
+Every hold the bot writes carries `held_until`, seven days later. Until then it holds; from that
+date the input moves again and the next run proves it. A green release that moved it deletes the
+`freeze` and `held_until` lines and closes the incident (`finalize`); an attributable regression
+that holds the input again renews the date, and an unmarked red leaves it expired. To
+lift it sooner, delete both lines, as with any other hold.
 
 **Close the incident when you thaw, not later.** A hold and its incident are two pieces of state,
 and deleting the `freeze` lines without closing the issue leaves a trap that fires on the NEXT
diff --git a/bot/autofreeze.py b/bot/autofreeze.py
index 9ddb226..78a09e8 100644
--- a/bot/autofreeze.py
+++ b/bot/autofreeze.py
@@ -120,7 +120,8 @@ def unattributed_failures(evidence: str) -> list:
     return sorted({m["case"] for m in UNATTRIBUTED.finditer(evidence or "")})
 
 
-def decide(attributed, moved_keys, manifest_text: str, policy: dict, unattributed=()) -> tuple:
+def decide(attributed, moved_keys, manifest_text: str, policy: dict, unattributed=(),
+           moved_only: bool = False) -> tuple:
     """`(keys_to_hold, refusal)` — what to freeze for these stacks, or why nothing may be.
 
     Five ways this refuses, and every one is a case where a hold would be a guess or a lie:
@@ -154,10 +155,14 @@ def decide(attributed, moved_keys, manifest_text: str, policy: dict, unattribute
     if unmoved:
         return {}, (f"{', '.join(unmoved)} failed but moved nothing this run — a stack that "
                     f"broke with no changed input of its own needs investigation, not a hold")
+    if moved_only:
+        # A BUILD failure is blamed on what changed, not on the stack's whole composition: the
+        # inputs this candidate moved are held, the others keep moving.
+        keys = {k: v for k, v in keys.items() if k in moved}
     return keys, ""
 
 
-def freeze_edit(policy_text: str, keys: dict, reason: str) -> str:
+def freeze_edit(policy_text: str, keys: dict, reason: str, until: str = "") -> str:
     """`policy.toml` with a `freeze` added under each key that has none.
 
     Written under the key's own `track` line, so the entry still reads as what it tracks with a
@@ -183,10 +188,19 @@ def freeze_edit(policy_text: str, keys: dict, reason: str) -> str:
         end = len(text) if end is None else end.start()
         block = text[start:end]
         if re.search(r"^freeze\s*=", block, re.M):
+            # A hold somebody else wrote stays exactly as it is. Only an expiring hold of this
+            # bot's own (one that carries `held_until`) is renewed when it is written again.
+            old_until = re.search(r"^held_until\s*=.*$", block, re.M)
+            if until and old_until:
+                block = block[:old_until.start()] + f'held_until = "{until}"' \
+                    + block[old_until.end():]
+                text = text[:start] + block + text[end:]
             continue
         # json.dumps produces a TOML-compatible basic string, so a quote or a backslash in the
         # reason cannot end the value early and leave a file that does not parse.
         line = f"freeze = {json.dumps(f'{reason} — {keys[key]}')}\n"
+        if until:
+            line += f'held_until = "{until}"\n'
         track = re.search(r"^track\s*=.*\n", block, re.M)
         at = start + (track.end() if track else len(found.group()) + 1)
         text = text[:at] + line + text[at:]
@@ -194,6 +208,38 @@ def freeze_edit(policy_text: str, keys: dict, reason: str) -> str:
     return text
 
 
+def thaw_edit(policy_text: str, keys) -> str:
+    """`policy.toml` without the `freeze` and `held_until` lines of each key — only in entries
+    that carry `held_until` (a hold this bot wrote), never a person's freeze. Parsed and checked
+    like `freeze_edit`."""
+    text = policy_text
+    for key in sorted(keys):
+        header = (f'[source."{key}"]' if not key.startswith("extra.") else f"[{key}]")
+        found = re.search(rf"^{re.escape(header)}[ \t]*$", text, re.M)
+        if not found:
+            raise ValueError(f"policy.toml has no entry {header}")
+        start = found.start()
+        end = re.compile(r"^\[", re.M).search(text, found.end())
+        end = len(text) if end is None else end.start()
+        block = text[start:end]
+        if not re.search(r"^held_until\s*=", block, re.M):
+            continue
+        block = re.sub(r"^(freeze|held_until)\s*=.*\n", "", block, flags=re.M)
+        text = text[:start] + block + text[end:]
+    before, after = tomllib.loads(policy_text), tomllib.loads(text)
+    if set(after) != set(before):
+        raise ValueError("the thaw changed the policy's top-level keys")
+    for key in keys:
+        table, name = (("extra", key.split(".", 1)[1]) if key.startswith("extra.")
+                       else ("source", key))
+        was, now = before[table][name], after[table][name]
+        if "held_until" in was and ("freeze" in now or "held_until" in now):
+            raise ValueError(f"the thaw left the hold on {key}")
+        if now.get("track") != was.get("track"):
+            raise ValueError(f"the thaw changed what {key} tracks")
+    return text
+
+
 def _verify_edit(before_text: str, after_text: str, keys: dict) -> None:
     """The edit did what it said: each key holds a freeze INSIDE its own entry, its tracking rule
     survived, and nothing else appeared."""
diff --git a/bot/cli.py b/bot/cli.py
index 8ca4a76..58f0ffc 100644
--- a/bot/cli.py
+++ b/bot/cli.py
@@ -16,6 +16,7 @@ import shutil
 import subprocess
 import sys
 import tempfile
+import tomllib
 from dataclasses import asdict
 from pathlib import Path
 
@@ -853,10 +854,14 @@ def stage_build(ctx: Ctx) -> int:
             att.evidence = (f"binary build run {run_id} for {stack} on "
                             f"{att.candidate_sha[:9]}")
             ctx.save_attempt(number, att)
+        # The failing gate (the builder's compile, its smoke boot, …) is named by the job and its
+        # last log lines — what a firmware or runner move failed on, without opening the run.
         raise Stop("build", f"the {stack} binary build did not succeed "
                    f"({run.get('conclusion')}).",
                    "Recovery restores the index for whatever this attempt published; nothing "
-                   "was released.", detail=run.get("html_url", ""))
+                   "was released.",
+                   detail=_red_runs(ctx, {f"binary:{stack}": att.runs[f"binary:{stack}"]})
+                   or run.get("html_url", ""))
     if not entry:
         raise Stop("build", f"the {stack} build reported success but published no fragment this "
                    f"attempt can claim.",
@@ -1125,17 +1130,17 @@ def stage_prove(ctx: Ctx) -> int:
                    + "\n".join(f"- {p}" for p in problems),
                    "Recovery restores whatever this attempt published and deletes the candidate "
                    "branch; nothing was released.",
-                   detail=_red_runs(ctx, att))
+                   detail=_red_runs(ctx, att.runs))
     ctx.summary(f"every required job succeeded on `{att.candidate_sha[:9]}`, and the release "
                 f"lane ran its cases.")
     return 0
 
 
-def _red_runs(ctx: Ctx, att: Attempt) -> str:
+def _red_runs(ctx: Ctx, runs: dict) -> str:
     """Each recorded run with a failing job: a link, the failing jobs and the end of their logs.
     What a maintainer opens first; a run whose jobs cannot be read says so instead."""
     out = []
-    for name, rec in att.runs.items():
+    for name, rec in runs.items():
         link = f"https://github.com/{rec['repo']}/actions/runs/{rec['id']}"
         try:
             failed = ctx.gh.failing_jobs(rec["repo"], int(rec["id"]), rec.get("attempt", 1))
@@ -1697,6 +1702,62 @@ def _find_image_run(ctx: Ctx, tag: str) -> int:
 # ---------------------------------------------------------------------------- stage: finalize
 
 
+def _thaw_proved(ctx: Ctx, att: Attempt) -> None:
+    """A release that MOVED an input whose bot-written hold had expired has proved it: delete the
+    hold from `policy.toml` and close each incident none of whose holds remain. Best-effort after
+    the release — a thaw that fails leaves an expired hold, which already holds nothing."""
+    try:
+        bot = ctx.clone(BOT, "main", token=ctx.bot_token or ctx.token)
+        policy_p = bot / "policy.toml"
+        policy = up.load_policy(policy_p)
+    except (RuntimeError, OSError, ValueError) as exc:
+        ctx.summary(f"\nThe policy could not be read for a thaw ({exc}); nothing was thawed.")
+        return
+    keys = sorted(set(up.expired_holds(policy)) & set(att.moved_keys))
+    if not keys:
+        return
+
+    def rule(key):
+        return (policy["extra"][key.split(".", 1)[1]] if key.startswith("extra.")
+                else policy["source"][key])
+    incidents = {int(n) for k in keys for n in re.findall(r"/issues/(\d+)", rule(k)["freeze"])}
+    try:
+        thawed = af.thaw_edit(policy_p.read_text(), keys)
+    except (OSError, ValueError) as exc:
+        ctx.summary(f"\nThe proved holds on {', '.join(keys)} could not be thawed ({exc}); "
+                    f"they have expired and hold nothing. Delete their lines by hand.")
+        return
+    left = tomllib.loads(thawed)
+    # Each incident is closed BEFORE the policy is pushed: an incident stays open while a line
+    # naming it is in the policy, so a close that fails leaves both for the next release that
+    # moves the input, never an open incident whose hold is already gone. (An incident closed
+    # before a later one failed is named by an expired line until then: harmless, it holds nothing.)
+    try:
+        for number in sorted(incidents):
+            still = [k for entries in (left.get("source", {}), left.get("extra", {}))
+                     for k, r in entries.items() if f"/issues/{number}" in str(r.get("freeze", ""))]
+            if still:
+                continue
+            ctx.bot_gh.comment(BOT, number, f"Thawed: {', '.join(keys)} moved in {att.version} "
+                                            f"and every required check passed ({ctx.run_url}).")
+            ctx.bot_gh.update_issue(BOT, number, state="closed")
+    except GitHubError as exc:
+        ctx.summary(f"\nThe incidents of the proved holds on {', '.join(keys)} could not be closed "
+                    f"({exc}); nothing was thawed. The holds have expired and hold nothing; the "
+                    f"next release that moves them thaws them again.")
+        return
+    try:
+        policy_p.write_text(thawed)
+        git("add", "policy.toml", cwd=bot)
+        git("commit", "-q", "-m", f"auto-thaw: {', '.join(keys)} proved by {att.version}", cwd=bot)
+        git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=bot)      # never forced
+    except (RuntimeError, OSError) as exc:
+        ctx.summary(f"\nThe proved holds on {', '.join(keys)} could not be thawed ({exc}); "
+                    f"they have expired and hold nothing. Delete their lines by hand.")
+        return
+    ctx.summary(f"\nThawed the proved holds on {', '.join(keys)}.")
+
+
 def stage_finalize(ctx: Ctx) -> int:
     """The ONE place an attempt is closed, and only when nothing is owed.
 
@@ -1718,6 +1779,7 @@ def stage_finalize(ctx: Ctx) -> int:
         return 0
     att.state = "complete"
     ctx.save_attempt(number, att)
+    _thaw_proved(ctx, att)
     report_retry_outcome(ctx, f"released {att.version} with the hold in place — the held stack "
                               f"and every other required case passed", att)
     # A retry that RELEASED has discharged its obligation too. Same settlement as the
@@ -1903,6 +1965,14 @@ def stage_recover(ctx: Ctx, run_id: str = "") -> int:
     return 0
 
 
+HOLD_DAYS = 7      # a hold this bot writes is re-proved after a week; a person's freeze never
+
+
+def _hold_until(days: int) -> str:
+    import datetime
+    return (datetime.date.fromisoformat(up.today()) + datetime.timedelta(days=days)).isoformat()
+
+
 def _auto_freeze(ctx: Ctx, number: int, att: Attempt) -> None:
     """Hold the stack this run's evidence blamed, say so in an incident, and retry once.
 
@@ -1949,13 +2019,17 @@ def _auto_freeze(ctx: Ctx, number: int, att: Attempt) -> None:
     policy_p = bot / "policy.toml"
     keys, refusal = af.decide(att.regression, att.moved_keys, manifest,
                               up.load_policy(policy_p),
-                              unattributed=af.unattributed_failures(att.evidence))
+                              unattributed=af.unattributed_failures(att.evidence),
+                              moved_only=att.evidence.startswith("binary build run"))
     if refusal:
-        print(f"no automatic hold: {refusal}")
+        # In the run's summary, not only on stdout: a refused build hold is the internal-regression
+        # report (a failed build that moved nothing of its own stack).
+        ctx.summary(f"\nno automatic hold: {refusal}")
         return
 
     incident = af.already_open(ctx.bot_gh.open_issues(BOT, af.LABEL), att.regression)
-    body = rp.incident(att, keys, ctx.run_url)
+    until = _hold_until(HOLD_DAYS)
+    body = rp.incident(att, keys, ctx.run_url, until=until)
     if incident:
         ctx.bot_gh.update_issue(BOT, incident, body=body)
     else:
@@ -1971,7 +2045,7 @@ def _auto_freeze(ctx: Ctx, number: int, att: Attempt) -> None:
     reason = (f"Automatic hold after {att.evidence or 'a failed release'}; "
               f"see {BOT_URL}/issues/{incident}")
     try:
-        policy_p.write_text(af.freeze_edit(policy_p.read_text(), keys, reason))
+        policy_p.write_text(af.freeze_edit(policy_p.read_text(), keys, reason, until=until))
         if git("status", "--porcelain", "policy.toml", cwd=bot).strip():
             git("add", "policy.toml", cwd=bot)
             git("commit", "-q", "-m",
diff --git a/bot/report.py b/bot/report.py
index fa935d1..44617f5 100644
--- a/bot/report.py
+++ b/bot/report.py
@@ -123,7 +123,7 @@ def failure_issue(*, stage: str, run_url: str, attempt, findings, observed: str,
     return title, "\n".join(body)
 
 
-def incident(att, keys: dict, run_url: str) -> str:
+def incident(att, keys: dict, run_url: str, until: str = "") -> str:
     """The body of an automatic-freeze incident: what is held, why, and how to lift it.
 
     It has to answer one question weeks later — is this still needed? — so it names the rejected
@@ -148,7 +148,12 @@ def incident(att, keys: dict, run_url: str) -> str:
         "prove every stack — including the held one — before anything is published. Whether it "
         "was actually dispatched is appended below; nothing above this line asserts it.",
         "",
-        "**This does not expire.** Neither a newer upstream release nor closing this issue lifts "
-        "it. When the upstream fix is verified, delete the `freeze` lines named above from "
-        "`policy.toml` and let the next run prove the result.",
+        (f"**The hold expires on {until}** (`held_until`). From then on the held inputs move "
+         f"again and the next run proves them: a green release that moved them deletes the hold "
+         f"and closes this issue; an attributable regression that holds them again renews it for "
+         f"another week, and an unmarked red leaves it expired. To lift it sooner, delete its "
+         f"`freeze` and `held_until` lines from `policy.toml`." if until else
+         "**This does not expire.** Neither a newer upstream release nor closing this issue lifts "
+         "it. When the upstream fix is verified, delete the `freeze` lines named above from "
+         "`policy.toml` and let the next run prove the result."),
     ])
diff --git a/bot/upstream.py b/bot/upstream.py
index a928bd3..9ed6e9e 100644
--- a/bot/upstream.py
+++ b/bot/upstream.py
@@ -164,6 +164,27 @@ def policy_gaps(policy: dict, pinned_paths) -> list:
     return gaps + freeze_problems(policy)
 
 
+HELD_UNTIL = re.compile(r"\d{4}-\d{2}-\d{2}")
+
+
+def _is_date(value) -> bool:
+    """A real YYYY-MM-DD calendar date: `2026-13-45` has the shape and is not one."""
+    import datetime
+    if not (isinstance(value, str) and HELD_UNTIL.fullmatch(value)):
+        return False
+    try:
+        datetime.date.fromisoformat(value)
+    except ValueError:
+        return False
+    return True
+
+
+def today() -> str:
+    """The UTC date a hold's `held_until` is compared with. A function so tests can set it."""
+    import datetime
+    return datetime.datetime.now(datetime.UTC).date().isoformat()
+
+
 def freeze_of(rule: dict, key: str) -> tuple:
     """`(reason, problem)` for one policy entry. A nonblank reason is a hold; a problem is fatal.
 
@@ -173,8 +194,13 @@ def freeze_of(rule: dict, key: str) -> tuple:
     and a derived input moves with its owner, so a hold written here would hold nothing while
     reading as though it did.
     """
+    until = rule.get("held_until")
+    if until is not None and "freeze" not in rule:
+        return "", f"{key}: held_until without a freeze"
     if "freeze" not in rule:
         return "", ""
+    if until is not None and not _is_date(until):
+        return "", f"{key}: held_until must be a YYYY-MM-DD date, got {until!r}"
     value = rule["freeze"]
     if not isinstance(value, str) or not value.strip():
         return "", f"{key}: freeze must be a nonblank reason string, got {value!r}"
@@ -184,9 +210,24 @@ def freeze_of(rule: dict, key: str) -> tuple:
         owner = rule.get("owner", "?")
         return "", (f"{key}: freeze its owner {owner} instead — this input moves with that pin, "
                     f"so a hold here would not hold anything")
+    if until is not None and today() >= until:
+        # A hold the BOT wrote expires: the pin moves again, and a green release thaws it. A
+        # person's freeze has no `held_until` and never expires.
+        return "", ""
     return value.strip(), ""
 
 
+def expired_holds(policy: dict) -> list:
+    """The keys whose bot-written hold has expired (`held_until` reached)."""
+    out = []
+    for table in ("source", "extra"):
+        for name, rule in (policy.get(table) or {}).items():
+            until = (rule or {}).get("held_until")
+            if _is_date(until) and today() >= until:
+                out.append(name if table == "source" else f"extra.{name}")
+    return sorted(out)
+
+
 def freeze_problems(policy: dict) -> list:
     out = []
     for table in ("source", "extra"):
diff --git a/tests/test_autofreeze.py b/tests/test_autofreeze.py
index e3f8c33..f4757d8 100644
--- a/tests/test_autofreeze.py
+++ b/tests/test_autofreeze.py
@@ -364,6 +364,27 @@ def test_a_refused_attribution_neither_opens_an_incident_nor_retries(freeze_ctx)
     assert freeze_ctx.gh.dispatched == [] and not freeze_ctx.bot_gh.issues
 
 
+
+def test_a_build_failure_holds_only_what_it_moved_in_the_exact_policy(freeze_ctx, monkeypatch,
+                                                                      tmp_path):
+    """Builder evidence holds the moved input alone (the lane's evidence holds both, above)."""
+    from bot import cli
+    monkeypatch.setattr(cli.up, "today", lambda: "2026-10-16")
+    cli._auto_freeze(freeze_ctx, 5, _att(evidence="binary build run 77 for meshcore on ccccccccc"))
+    assert (tmp_path / "lhpc-release-bot" / "policy.toml").read_text() == (
+        '[source."src/openhop-core"]\ntrack = "tip"\nfreeze = "Automatic hold after binary build '
+        'run 77 for meshcore on ccccccccc; see https://github.com/makrohard/lhpc-release-bot/'
+        'issues/42 \\u2014 holds meshcore"\nheld_until = "2026-10-23"\n\n'
+        '[source."src/meshcore-cli"]\ntrack = "tag"\n')
+
+
+def test_a_build_failure_that_moved_nothing_of_its_stack_is_reported_not_held(freeze_ctx):
+    from bot import cli
+    cli._auto_freeze(freeze_ctx, 5, _att(evidence="binary build run 77 for meshcore on ccccccccc",
+                                         moved_keys=["src/unrelated"]))
+    assert freeze_ctx.gh.dispatched == [] and not freeze_ctx.bot_gh.issues
+    assert any("no automatic hold" in s for s in freeze_ctx.summaries)
+
 # ------------------------------------------------------------------ the cascade the lane warns of
 
 def test_an_unexplained_failure_beside_a_marked_one_refuses():
@@ -641,6 +662,9 @@ class _RedBuilderGh(FakeGh):
         # The VISIBLE name the builder writes; a dotfile would never have survived the upload.
         return self.marker if suffix.endswith(".regression") else b""
 
+    def failing_jobs(self, repo, run_id, attempt, lines=20):
+        return [("build", f"https://example.invalid/job/{run_id}", "ERROR: firmware compile failed")]
+
     def file_at(self, repo, path, sha):
         return BUILD_MANIFEST
 
@@ -1620,3 +1644,108 @@ def test_a_hand_run_finish_still_tells_the_incident_what_happened(tmp_path):
     assert any("Retry 200:" in b and "released" in b for b in said), \
         f"the incident must be told, with the CHILD's id, not the finish run's: {said}"
     assert not any("Retry 900:" in b for b in said), "never the finish run's own id"
+
+
+# ---- the hold a BUILD failure writes, its expiry, and its thaw ----
+
+PTEXT = ('[source."src/openhop-core"]\ntrack = "tip"\n\n'
+         '[source."src/meshcore-cli"]\ntrack = "tag"\nfreeze = "a person\'s hold"\n')
+
+
+def test_a_build_failure_holds_only_the_inputs_the_candidate_moved():
+    keys, refusal = af.decide(["meshcore"], ["src/openhop-core"], MANIFEST, POLICY,
+                              moved_only=True)
+    assert (sorted(keys), refusal) == (["src/openhop-core"], "")
+    # The lane's own attribution keeps holding the stack's whole composition (control).
+    lane, _ = af.decide(["meshcore"], ["src/openhop-core"], MANIFEST, POLICY)
+    assert sorted(lane) == ["src/meshcore-cli", "src/openhop-core"]
+
+
+def test_an_expiring_hold_is_written_with_its_date_and_renewed_but_a_persons_is_not():
+    held = af.freeze_edit(PTEXT, {"src/openhop-core": "holds meshcore"}, "R", until="2026-10-23")
+    assert ('[source."src/openhop-core"]\ntrack = "tip"\nfreeze = "R \\u2014 holds meshcore"\n'
+            'held_until = "2026-10-23"\n') in held
+    renewed = af.freeze_edit(held, {"src/openhop-core": "x", "src/meshcore-cli": "x"}, "R2",
+                             until="2026-10-30")
+    assert 'held_until = "2026-10-30"' in renewed and "R2" not in renewed
+    assert renewed.count("held_until") == 1          # the person's freeze got no date
+
+
+def test_a_thaw_removes_only_a_bot_hold():
+    held = af.freeze_edit(PTEXT, {"src/openhop-core": "holds meshcore"}, "R", until="2026-10-23")
+    thawed = af.thaw_edit(held, ["src/openhop-core", "src/meshcore-cli"])
+    assert thawed == PTEXT                            # the bot hold is gone, the person's stays
+
+
+class _ThawCtx(FakeCtx):
+    def __init__(self, tmp_path, policy_text):
+        super().__init__(tmp_path)
+        self.bot_token = "t" * 20
+        d = tmp_path / "lhpc-release-bot"
+        d.mkdir(parents=True, exist_ok=True)
+        (d / "policy.toml").write_text(policy_text)
+        self.closed = []
+        self.gh.update_issue = lambda repo, n, **f: self.closed.append((n, f.get("state")))
+
+    def clone(self, repo, ref="", token=""):
+        return self._tmp / "lhpc-release-bot"
+
+
+def test_a_green_release_that_moved_an_expired_hold_thaws_it_and_closes_its_incident(
+        tmp_path, monkeypatch):
+    from bot import cli, upstream
+    monkeypatch.setattr(upstream, "today", lambda: "2026-10-23")
+    monkeypatch.setattr(cli, "git", lambda *a, **k: "")
+    policy = af.freeze_edit(PTEXT, {"src/openhop-core": "holds meshcore"},
+                            "see https://github.com/x/y/issues/62", until="2026-10-23")
+    ctx = _ThawCtx(tmp_path, policy)
+    cli._thaw_proved(ctx, _att(state="complete", moved_keys=["src/openhop-core"]))
+    assert (tmp_path / "lhpc-release-bot" / "policy.toml").read_text() == PTEXT
+    assert ctx.closed == [(62, "closed")]
+
+
+def _expired(tmp_path, monkeypatch):
+    from bot import cli, upstream
+    monkeypatch.setattr(upstream, "today", lambda: "2026-10-23")
+    monkeypatch.setattr(cli, "git", lambda *a, **k: "")
+    policy = af.freeze_edit(PTEXT, {"src/openhop-core": "holds meshcore"},
+                            "see https://github.com/x/y/issues/62", until="2026-10-23")
+    return _ThawCtx(tmp_path, policy), policy
+
+
+def test_a_thaw_whose_policy_write_fails_reports_and_never_raises(tmp_path, monkeypatch):
+    """Finalize runs the thaw after the attempt is saved complete: a raise here turns a release
+    red."""
+    from bot import cli
+    ctx, _ = _expired(tmp_path, monkeypatch)
+    monkeypatch.setattr(cli.Path, "write_text",
+                        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only file system")))
+    cli._thaw_proved(ctx, _att(state="complete", moved_keys=["src/openhop-core"]))
+    assert any("could not be thawed (read-only file system)" in s for s in ctx.summaries)
+
+
+def test_an_incident_that_cannot_be_closed_keeps_its_hold_line_for_the_next_release(
+        tmp_path, monkeypatch):
+    """An open incident and its policy line go together, so the next release that moves the
+    input can still find the incident and close it."""
+    from bot import cli
+    ctx, policy = _expired(tmp_path, monkeypatch)
+
+    def refuse(repo, n, **f):
+        raise cli.GitHubError("PATCH /issues/62 -> 502")
+    ctx.gh.update_issue = refuse
+    cli._thaw_proved(ctx, _att(state="complete", moved_keys=["src/openhop-core"]))
+    assert (tmp_path / "lhpc-release-bot" / "policy.toml").read_text() == policy
+    assert any("nothing was thawed" in s for s in ctx.summaries)
+
+
+def test_a_failed_build_names_its_failing_job_and_last_lines(tmp_path, monkeypatch):
+    """The gate a firmware or runner move failed on is in the report without opening the run."""
+    from bot import cli
+    monkeypatch.setenv("BINARY_STACK", "meshtastic")
+    monkeypatch.setattr(cli, "MANIFEST", "m.toml")
+    monkeypatch.setattr(cli.up, "load_policy", lambda p: BUILD_POLICY)
+    ctx = _BuildCtx(tmp_path, b"")
+    with pytest.raises(cli.Stop) as stop:
+        cli.stage_build(ctx)
+    assert "`build`" in stop.value.detail and "firmware compile failed" in stop.value.detail
diff --git a/tests/test_freeze.py b/tests/test_freeze.py
index 3ba5561..ddf9800 100644
--- a/tests/test_freeze.py
+++ b/tests/test_freeze.py
@@ -107,3 +107,34 @@ def test_only_the_unfrozen_input_of_a_mixed_run_is_eligible():
                 examine(src(A, path="src/free"), {"track": "tip"}, FakeRemote([A, B]))]
     moved = [f for f in findings if f.moves]
     assert [f.key for f in moved] == ["src/free"]
+
+
+# ---- a hold this bot wrote expires (`held_until`); a person's freeze never does ----
+
+@pytest.mark.parametrize("today, frozen", [("2026-10-22", True), ("2026-10-23", False),
+                                          ("2026-11-30", False)])
+def test_a_bot_hold_holds_until_its_date_and_then_the_pin_moves_again(monkeypatch, today, frozen):
+    from bot import upstream
+    monkeypatch.setattr(upstream, "today", lambda: today)
+    rule = {"track": "tip", "freeze": HELD, "held_until": "2026-10-23"}
+    assert (freeze_of(rule, "src/x")[0] == HELD) is frozen
+    assert examine(src(A), rule, FakeRemote([A, B])).moves is not frozen
+
+
+def test_a_persons_freeze_never_expires(monkeypatch):
+    from bot import upstream
+    monkeypatch.setattr(upstream, "today", lambda: "2099-01-01")
+    assert freeze_of({"track": "tip", "freeze": HELD}, "src/x") == (HELD, "")
+
+
+@pytest.mark.parametrize("rule", [{"track": "tip", "held_until": "2026-10-23"},
+                                  {"track": "tip", "freeze": HELD, "held_until": "next week"},
+                                  {"track": "tip", "freeze": HELD, "held_until": "2026-13-45"}])
+def test_a_malformed_held_until_is_a_policy_problem(rule):
+    assert policy_gaps({"source": {"src/x": rule}}, ["src/x"])
+
+
+def test_a_bot_hold_whose_date_has_passed_lets_the_pin_move():
+    # No clock seam: a date long past. On a bot that knew no expiry this input stayed frozen.
+    rule = {"track": "tip", "freeze": HELD, "held_until": "2000-01-01"}
+    assert examine(src(A), rule, FakeRemote([A, B])).moves
diff --git a/tests/test_report.py b/tests/test_report.py
index 31ba946..17f8dc2 100644
--- a/tests/test_report.py
+++ b/tests/test_report.py
@@ -69,3 +69,14 @@ def test_the_opening_names_the_event_that_started_the_run(monkeypatch, retry_of,
     ctx = _Ctx(retry_of=retry_of)
     cli._report_stop(ctx, cli.Stop("prove", "the candidate is not proven", "Recovery restores."))
     assert word in ctx.bot_gh.created[0].splitlines()[0]
+
+
+def test_an_expiring_incident_promises_renewal_only_on_an_attributable_regression():
+    # The same rule as the README: an unmarked red writes no hold, so it renews nothing.
+    from bot import report as rp
+    att = Attempt(run_id="9", version="0.12.10", base_sha="b" * 40, candidate_sha="c" * 40,
+                  regression=["meshcore"])
+    body = rp.incident(att, {"src/openhop-core": "holds meshcore"}, "https://example.invalid/r/9",
+                       until="2026-10-23")
+    assert "attributable regression that holds them again renews" in body
+    assert "an unmarked red leaves it expired" in body and "a red one renews" not in body
```
