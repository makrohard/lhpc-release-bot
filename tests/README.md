# Tests

The bot decides three things: which upstream commit a pin may move to, how the manifest and the
changelog are edited, and what a failed run is allowed to undo. Those decisions are pure
functions, and this is where they are proven. Everything here runs offline.

## The rules

They are [the controller's rules](https://github.com/makrohard/loraham-pi-control/blob/main/tests/README.md),
because this bot writes to the controller's repositories. The ones that bite here:

1. **Behaviour, not implementation.** Assert the decision — a status, a refusal reason, the
   commit that was chosen — never the shape of the code that made it.
2. **Exact where exactness is the contract.** A pin is compared byte for byte, and so is the set
   of manifest lines an edit is allowed to change. A human sentence is not: assert the state or
   the command an operator is told to run.
3. **One canonical owner per behaviour.** Fold permutations into `parametrize`; never split one
   rule across two files.
4. **No network and no real GitHub.** `FakeRemote` and small fakes standing in for the API
   replace them. Real `git` IS used where the behaviour is about git: the integration-branch
   cases build a temporary repository with a genuine conflict, because a resolver tested against
   a hand-written string is tested against the wrong thing. The single networked check lives
   outside the suite: `python -m tests.policy_covers_manifest`.
5. **A test must be able to fail.** No conditional body that can do nothing, no assertion that
   holds whatever the code does.

## Where a test goes

By the decision it protects:

- **`test_upstream.py`** — what may become a candidate, and every reason to refuse one.
- **`test_manifest_edit.py`** — moving a pin and the Graywolf version without touching anything
  else.
- **`test_changelog.py`** — the version scalars and the changelog, including the one conflict
  with `dev` that is resolved automatically.
- **`test_attempt.py`** — what a run owes the world, and what a recovery may undo.
- **`test_transaction.py`** — which binary entry this attempt may restore, and whether a
  published image really is this release's.
- **`test_proof.py`** — what counts as proof that THIS candidate is green, and how much
  credential a publishing run must have left.
- **`test_integration_branch.py`** — the one conflict resolved automatically, against real git
  history with a real conflict.

## What is NOT proven here

That a published binary is good, that a stack starts, that an image boots. Those are the
controller's own gates: the builder's smoke and clean-runtime tests, the
[release-verification lane](https://github.com/makrohard/loraham-pi-control/blob/main/docs/testlab.md),
and the box test matrix. This bot's job is to refuse to release when any of them is not green,
and that refusal is what these tests cover.
