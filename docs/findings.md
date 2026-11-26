# Backlog coverage and recommendation findings

**The full lab is incomplete. No recommendation is marked live-validated.**
Local tests exercise controller logic, synthetic state, delivery contracts and
localhost MCP transport, not Azure runtime behavior. The new
[three-track delivery milestone](delivery-demo.md) records the public PDF
fingerprint, implemented adapters and remaining native-serving/safety gates.
The received
backlog identifies the source as `docs\ai-ml\guide\foundry-agentops.md` with article
metadata date 2026-08-19; its exact Git revision has not been supplied/verified.
Do not treat this source map as a line-by-line review of an unread revision.

## Story coverage

| Story | Local deliverable | Remaining acceptance |
|---|---|---|
| AO-01 | Named roles/reviewer, $500 USD/month, target/network and live evaluation limits recorded | Enforce the agreed live operating model |
| AO-02 | Current regional documentation, model/quota/policy reads, harness-memory boundary | Actual runtime/API entitlement and behavior probes |
| AO-03 | Package/test/docs layout, approved CODEOWNERS, passing four-platform PR CI | Manual code review and merge |
| AO-04 | Budget/read-back; Bicep/ARM validation; create-only what-if; names and foundation cost preflight | Protected provisioning, runtime RBAC and repeatability |
| AO-05 | Reviewed main code; secretless scoped OIDC bootstrap; reviewer control temporarily deferred for dry-run only | Restore reviewers before live enablement; real authorization tests |
| AO-06 | Synthetic Contoso contracts/cases for three tracks | Real agent implementations and measured baselines |
| AO-07 | Deterministic bundle, change digests, integrity/path checks | Built hosted artifact, full real component provenance |
| AO-08 | Separate strict synthetic environment bindings | Validated real Azure bindings |
| AO-09 | Sorted process-shared lock keys and competing-writer tests | Shared distributed lease backend, live cancellation/reconciliation |
| AO-10 | Contract/binding checks and retained dependencies | Supported data-plane reconciliation/read-back/readiness |
| AO-11 | Non-serving candidate and readiness gates in local state | Real serving observation, identity/access, activation/final status |
| AO-12 | Inclusive 80% quality boundary, exact-context finite gates, expiry, rejection | Enforce approved live limits with actual candidate measurements |
| AO-13 | Same bytes across dev/test/labprod; explicit placeholder approvals with failed-evaluation rejection | Restore real approvals and prove caller-verified live serving transitions |
| AO-14 | Retained composite references, independent local rollback | Real dependencies/caller behavior/session recovery |
| AO-15 | Durable started/success/rejected/rollback attempt history | Remote immutable evidence, authenticated approvals and provenance |
| AO-16 | Replayable local CLI/runbook | Live demo and another team member's replay |
| AO-17 | This explicit coverage and findings map | Verified source revision and recommendation-level live evidence |
| AO-18 (P1) | No live drift implementation | Introduced drift, detected differences and reviewed repair |
| AO-19 (P1) | Local context attribution only | OpenTelemetry/KQL and real caller/dependency correlation |
| AO-20 (P1) | Local competing writers, rejection, interruption/replay | Complete isolated live A-O failure matrix |
| AO-21 (P1) | Monitoring remains untested | Agreed responder/alert policy and controlled demonstration |
| AO-22 | Hosted-shaped portable contract and digest constraint | Real hosted implementation/image/activation/session/trace proof |
| AO-23 (optional) | Excluded | Separate approval for percentage canary |
| AO-24 | Synthetic scope/allowlist/forget/expiry tests | Native extraction/consolidation/recall/ACL/retention on Prompt/Hosted |
| AO-25 | Harness-shaped contract, no surrogate memory | Actual endpoint/conversation/final-status/version/migration tests |
| AO-26 | Explicit definition-vs-instance reuse analysis | Current runtime/scope/identity/maturity research |
| AO-27 | Three knowledge topology alternatives and conditional decision | Validated support/ACL/costs, named owner, final architecture |
| AO-28 | Component contracts, external bindings, retention checks | Separate live component delivery/permissions and compatibility tests |
| AO-29 | Local multi-consumer reference isolation | Same actual KB instance, ACLs, freshness and independent live rollout |
| AO-30 | Toolbox contracts and retained side-by-side references | Tool traces/schema/auth failures and observed mutable-default effects |
| AO-31 | Durable synthetic journal, partial failure, repair, delete/expiry | Native writer capture, actual migration and lossless rollback proof |

## Source recommendation map

| Reference | Finding classification | Evidence or limitation |
|---|---|---|
| S1 Source of truth/composite release | Caveat; locally exercised | Canonical bytes and digests are not signed provenance or frozen live content/state |
| S2 Two-phase/read-back | Untested live | Local contract checks cannot establish infrastructure/data readiness |
| S3 Prompt CI/CD | Untested live | Local transitions only; no ordinary Prompt agent deployed |
| S4 Hosted/azd | Prerequisites observed; runtime untested | Setup/auth/preflight passed; synthetic image digest is not a built artifact |
| S5 Serving/rollback/canary | Caveat; locally exercised | Local atomic SQL update is not evidence of Foundry pin atomicity or data rollback |
| S6 Pipeline/coordination | Caveat; controller CI exercised | OS locks and SQL transactions are not distributed leases; remote CI has no Azure delivery credentials |
| S7 Environment strategy | Caveat; locally exercised | Synthetic scope rejection is not Azure account/network isolation evidence |
| S8 Evaluation | Caveat; locally exercised | Exact context and thresholds tested with fabricated metrics, not LLM quality |
| S9 Tools/toolboxes | Untested live | Shared mutable defaults, call identities, schemas/traces/approval behavior need actual observations |
| S10 Knowledge/Foundry IQ | Untested live | Reuse/ACL/ingestion ordering/content rollback claims remain conditional |
| S11 Memory | Caveat; synthetic recovery only | No native Memory tests; harness unsupported with no substitute; unjournaled writes block lossless-migration claims |
| S12 Security/identity | Bootstrap verified; live gate deferred | Four scoped grants and secretless federation; reviewer removal is dry-run-only, real workflow disabled |
| S13 Observability | Untested live | Attempt history is not runtime telemetry, monitoring or an alert demonstration |
| S14 Preview/constraints | Documentation and management plane checked | Selected models/quota observed; runtime/API entitlement still untested |

## Local evidence and limits

Run `python -W error::ResourceWarning -m unittest discover -s tests -v` and the
documented CLI demo. The demo persists source fixtures, byte-identical bundle
references, separate binding/content/state records, both failed and passed
fabricated reports, serving transitions, and six synthetic memory reconciliation
runs. Evidence is tagged `simulated` throughout; `live_validation` is false.

The public review commit `d182183dfbf73fc4247a98e09948feed43d71101`
passed all four combinations of Ubuntu/Windows and Python 3.11/3.13 in
[the pull-request workflow](https://github.com/duongthaiha/lab-foundry-agentops/actions/runs/45726488629).
Each ran the 27 tests and synthetic CLI replay; Ubuntu/Python 3.13 also compiled
all three Bicep templates. The separate push workflow also passed. These are
remote controller/build checks, not live Azure integration tests.

Required next observations include actual runtime identities and denial paths,
same-instance knowledge reuse, tool invocation traces/default changes, native
memory records/expiry/reconciliation, exact serving versions and session effects.
No proposed source wording should label these validated until those observations
exist. The safe interim wording is: "verify support and behavior for the selected
runtime, API version, identity and environment; configuration rollback does not
by itself restore content or learned state."
