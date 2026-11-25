# Local runbook and recovery

## Preconditions and evidence level

Use Python 3.11+ in the assigned worktree, with synthetic data only. No package
installation or Azure login is needed. `--mode simulated` is mandatory.
`--mode live` returns a nonzero exit with a capability error and does not create
local state. The CLI is not a production serving router or a substitute for
unsupported Foundry behavior.

The SQL databases and OS file locks are for a single shared **local filesystem**
state directory. Do not put them on network storage or give separate CLI/CI
machines independent databases and claim shared protection. SQLite serializes
short writes; lock keys distinguish agent/environment and component/environment.
Live coordination requires a verified distributed lease/ETag design.

## Replay the complete local demonstration

```powershell
python -W error::ResourceWarning -m unittest discover -s tests -v
python -m agentops --mode simulated demo --output .lab\demo --source-revision (git rev-parse HEAD)
```

Expected: exit 0, `evidence_type: simulated`, three runtime tracks and three
environments, rejected attempts, and `live_validation: false`.

Inspect `.lab\demo\report.json`. Each runtime has two independent immutable
release digests, each with dev/test/labprod candidates. For each release, the
digest is identical across environments while candidate IDs and binding digests
differ. Candidate creation records equal before/during/after serving snapshots.
The second candidate first fails its fabricated quality result without moving
serving, then passes a separate simulated evaluation and is promoted. Every
environment subsequently rolls back to the retained first candidate.

The demo also records rejected retirement of retained component contracts.
Prompt and Hosted fixture journals show partial-write divergence, blocked
rollback, durable repair, forget, and expiry. Harness memory is explicitly
`unsupported-no-substitute`.

This proves local state-machine and persistence behavior, **not** actual model
answers, tool calls, runtime identity, shared service instances, Foundry Memory,
or service endpoint atomicity. No HTTP call or real runtime activation occurs.

## Build and verify an editable example

```powershell
python -m agentops --mode simulated example --source .lab\prompt-source --runtime prompt --source-revision (git rev-parse HEAD)
$built = python -m agentops --mode simulated build --source .lab\prompt-source --output .lab\bundles | ConvertFrom-Json
python -m agentops --mode simulated verify --bundle $built.result.bundle --digest $built.result.digest
```

Choose `hosted` or `harness` for their independent fixture contracts. These are
portable lab inputs, **not verified Foundry deployment schemas**. Review the
selected source assets for secrets. The source revision is caller-supplied;
asset digests establish integrity but do not attest a clean source checkout,
authenticate a signer, or prove a hosted image exists.

After changing instructions, a tool contract, knowledge configuration, or memory
policy, build a new bundle. Promotion must consume an existing digest-named
bundle. Do not rebuild between environments or edit digest-named artifacts.

## Individual lifecycle commands

Use `python -m agentops --help` or each command's `--help` for arguments.
Global `--mode simulated` and `--state PATH` precede the command.

| Command | Inputs and invariant |
|---|---|
| `candidate` | Bundle + expected digest; binding, content, state, readiness JSON. No serving update |
| `candidate-info` | Exact candidate ID; returns immutable context and latest evaluation/approval |
| `evaluate` | Exact candidate report with completed status, all context digests and required finite metrics |
| `approve` | Exact candidate and synthetic reviewer label. Not authenticated approval |
| `serving` | Agent/environment; returns current candidate and generation |
| `promote` | Candidate, expected current candidate (`none` initially), expected generation |
| `rollback` | Previously served candidate, fresh evaluation/approval, expected current serving snapshot |
| `retire-component` | Environment/name/contract digest; rejects serving or rollback references |
| `history` | Every admitted attempt, including failed evaluations and rejected transitions |

Demo `records` and `evaluations` contain concrete examples. CLI JSON input rejects
duplicate keys and non-finite constants. Outputs use a `result` envelope and an
explicit evidence type. Errors go to stderr with nonzero exit status.

The fixture evaluation policy requires quality, unsafe rate, latency, and cost.
Quality uses the user-approved inclusive **0.8 (80%)** minimum. Unsafe rate,
latency and cost thresholds remain **local test constants**, not approved live
limits. Passing quality never overrides a safety failure or missing evidence.
The entire report context must match, including readiness, component, content,
state, dataset, policy, baseline and binding digests. Reports expire. Re-evaluation
invalidates approval; a failed recorded evaluation also clears the previous pass.
Approval is bound to the current serving generation. Promotion requires the
same digest in the preceding environment; rollback instead requires retained
serving history and a new approval.

## State and failure recovery

- A rejected operation leaves local serving unchanged and records a new attempt.
  Fix the input/capability issue and make a new explicit attempt; do not overwrite
  previous evidence. Input parsing/bundle preflight errors occur before admission
  and are returned on stderr, not represented as completed deployment attempts.
- On process death, OS locks are released and SQLite rolls back incomplete
  transactions. A persisted `started` attempt denotes interruption, not success.
  Inspect history and serving before retrying. Do not delete the database or
  remove lock files to resolve an active writer.
- Do not automatically retry after ambiguous remote side effects: there are no
  remote operations in this version. Future adapters need bounded reconciliation
  before retry, including final harness status and already-executed tool actions.
- Re-evaluate/reapprove stale candidates. Never rewrite timestamps to pass a gate.
- A component remains retained for every previously serving candidate. There is
  deliberately no automatic history pruning or forced retirement.
- The controller rejects a memory store/policy binding switch: its separate
  synthetic journal is not accepted as evidence for Foundry store migration.
- A serving agent cannot change runtime type in place. Create a separately
  named agent; switching to the harness cannot bypass the memory boundary.
- Synthetic journals preserve operation IDs, ordering, tombstones, absolute
  expiry and durable checkpoints. The allowlisted preference fixture is not a
  general poisoning detector or authentication implementation.
- Native memory extraction/consolidation and any other unjournaled writer must
  be covered by a supported capture/reconciliation mechanism before live
  migration can claim no data loss. Otherwise migration remains blocked.

## Teardown and handoff

No cloud resources or identities are created by these commands. Retain local
reports until review is complete. If discarding a local run, select only that
exact generated run directory after verifying no command is using it; never
remove the repository, session directory, or a wildcard resource group.

Live creation and teardown require the separate [gates](live-gates.md).
Another team member's successful runbook replay remains an outstanding acceptance
step; the author's own local test run cannot stand in for it.
