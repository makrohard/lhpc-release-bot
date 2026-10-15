# Code report: bot-stability-1 (PLAN-bot-stability v4)

**Branch:** `cons/bot-stability-1-r1` on lhpc-release-bot `main` = d01d462. Eight commits, one per feature; the suite is green at each commit (321 → 382 passed). **v3** adds the round 12–13 notes and a delta read of v2 (table "v3"). **v2** folds gate-1 rounds 10 (packet A) and 11 (packet B) and the second read (12 points) into the commits they belong to; see "v2: findings folded".

## HOUSE RULES KEPT
```
$ python tools/check_houserules.py d01d462..ec5d9cb --fact "held_until" --fact "EXTERNAL-UNAVAILABLE what=" --fact "finish_run" --fact "degraded gate"
HOUSE RULES KEPT  d01d462..ec5d9cb
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
| 68bdacf | an unreachable upstream is skipped for the run (11) | upstream.py, report.py, test_upstream.py | red vs d01d462: "assert ('fault', 'fault') == ('skipped', 'skipped')"; two fault cases are controls. The plan-stage test lands with aba7948 (it needs the plan fake from b10346a); red vs d01d462: "bot.cli.Stop: watch: an upstream input could not be judged" |
| 8b35d44 | slow-build is required (B2c) | cli.py, test_proof.py | red: "assert ([] == ['slow-build: skipped']" |
| cd7251d | failure issues: event, inputs, failing jobs (D5–D7) | cli.py, gh.py, report.py, attempt.py, README, 3 tests | red: inputs "assert (0 == 1)"; opening "'dispatched' in 'The scheduled …'"; D7 "'…/actions/runs/6' in '5\\n6'" |
| b8442aa | auto-finish with `finish_run` claim states (10) | cli.py, attempt.py, release.yml (plan: actions write), README, test_attempt.py | red: "bot.cli.Stop: observe: an earlier attempt is unresolved"; v2 red vs v1 (3ef5797): "Failed: DID NOT RAISE Stop" for a stuck claim and an ended finish run |
| db1df37 | bot holds expire (7 d) and are thawed on a green release; a build failure holds only what moved (B2a/12/15) | upstream.py, autofreeze.py, cli.py, report.py, release.yml (finalize, finish-close: contents write), README, 2 tests | red: "assert False" (expired date still frozen); "assert []" (malformed held_until accepted); v2 red vs v1: "OSError: read-only file system", "GitHubError: PATCH /issues/62 -> 502", "assert []" (2026-13-45), "assert False" (refusal on stdout only) |
| a706b63 | a failed binary build names its failing job and last lines | cli.py, test_autofreeze.py | red: "assert '`build`' in 'https://example.invalid/build/777'" |
| 4b3b70f | degraded issues for skipped sources, counted once per run (the opener's body mark included), closed only when examined | cli.py, README, test_report.py, test_attempt.py | new invariant; v2 red vs v1: "assert [False, False, True, True] == [False, False, False, True]" |
| ec5d9cb | one re-run mechanism: runner-lost (first attempt only) + typed EXTERNAL, unproven-external (R) | gh.py, cli.py, README, test_rerun.py, test_proof.py | red vs its parent aba7948: "assert False" at the `unproven, external` line; v2 red vs v1: "assert [1, 2, 3] == [1, 2]", "assert [3] == []", "GitHubError: GET … -> 410: expired" |

**Identity rewrite (record only).** The shared clone's config carried `user.name = t` (left by the test fixtures in the rebase incident), so every commit had committer `t`. The chain was rewritten with committer makrohard: same trees (`git diff 559d5fb ec5d9cb` is empty), same messages. The packets keep the audited shas; old → new: b69b905 → 68bdacf, 68c1dbe → 8b35d44, 756acb8 → cd7251d, b10346a → b8442aa, a6abb30 → db1df37, ed4c07c → a706b63, aba7948 → 4b3b70f, 559d5fb → ec5d9cb.

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
| diff | `git diff --stat d01d462 ec5d9cb` (code commits only) | 16 files changed, 1298 insertions(+), 53 deletions(-) |
| file sizes | `wc -l bot/{cli,gh,upstream,autofreeze,report,attempt}.py` | 2330, 601, 399, 274, 159, 231 |
| concurrency (finish claim) | `grep -n -A2 '^concurrency' .github/workflows/release.yml` (unchanged since d01d462) | `50:concurrency:` / `51-  group: release` / `52-  cancel-in-progress: false   # never cancel a run that may have published something` |
| EXTERNAL contract | the message of the determinism packet's owner, 2026-10-16 | `EXTERNAL-UNAVAILABLE what=([a-z0-9][a-z0-9_.:-]*)(?=\s\|$)`, message + text, no `STACK-REGRESSION` |
