# Backlog coverage and recommendation findings

**The full lab is incomplete. No recommendation is marked live-validated.**
Local tests exercise controller logic, synthetic state, delivery contracts and
localhost MCP transport, not Azure runtime behavior. The new
[three-track delivery milestone](delivery-demo.md) records the public PDF
fingerprint, implemented adapters and remaining native-serving/safety gates.
The [bounded dev smoke](dev-smoke.md) adds a main-only unattended workflow,
read-only foundation preflight, actual prompt-deployment adapter, dual MCP
evidence checks and a response-bound model judge. Its offline tests are not live
evidence. The bounded dev foundation has since been provisioned for the pilot
(see [dev-smoke.md](dev-smoke.md)); no CI smoke result is claimed here.
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
| AO-05 | Scoped platform bootstrap; narrow expiring dev-smoke policy implemented without per-run reviewers | Separate dev identity/foundation authorization; general delivery still needs reviewer restoration |
| AO-06 | Synthetic Contoso contracts/cases for three tracks | Real agent implementations and measured baselines |
| AO-07 | Deterministic bundle, change digests, integrity/path checks | Built hosted artifact, full real component provenance |
| AO-08 | Separate strict synthetic environment bindings | Validated real Azure bindings |
| AO-09 | Local competing-writer tests; Blob lease/CAS adapter and loss guards | Distributed contention, runtime-writer quiescence and live recovery |
| AO-10 | Contract/binding checks, retained dependencies and normalized SDK read-back adapters | Azure data-plane reconciliation/read-back/readiness |
| AO-11 | Native candidate isolation and concrete before/during serving consumers contract-tested | Live version, identity/access, activation/final-status proof; harness candidate selection unresolved |
| AO-12 | Inclusive 80% quality boundary, exact-context finite gates, expiry, rejection | Enforce approved live limits with actual candidate measurements |
| AO-13 | Same-byte synthetic promotion; native shared-journal receipts and upstream checks | Full-quality grading, reviewed live authorization and Azure serving transitions |
| AO-14 | Native retained context, durable recovery and override-free rollback consumer checks | Live dependencies/caller behavior/session recovery and state reconciliation |
| AO-15 | Durable started/success/rejected/rollback attempt history | Remote immutable evidence, authenticated approvals and provenance |
| AO-16 | Replayable simulator; delivery prepare/readiness/matrix and disabled native diagnostic CLI | Remaining live lifecycle commands, full demo and another team member's replay |
| AO-17 | This explicit coverage and findings map | Verified source revision and recommendation-level live evidence |
| AO-18 (P1) | No live drift implementation | Introduced drift, detected differences and reviewed repair |
| AO-19 (P1) | Local context attribution only | OpenTelemetry/KQL and real caller/dependency correlation |
| AO-20 (P1) | Local competing writers, rejection, interruption/replay | Complete isolated live A-O failure matrix |
| AO-21 (P1) | Monitoring remains untested | Agreed responder/alert policy and controlled demonstration |
| AO-22 | Hosted Responses adapter, digest contract, CI image builds; native session/consumer tests | Pushed image provenance and live activation/session/trace proof |
| AO-23 (optional) | Excluded | Separate approval for percentage canary |
| AO-24 | Native scoped memory primitives, pending-operation recovery and SDK HTTP tests | Runtime caller mapping, live recall/ACL/retention; expiry-preserving migration blocked |
| AO-25 | Harness built-ins disabled; fresh agent-endpoint consumer wire tests; no surrogate memory | Live endpoint/session behavior and verified isolated native candidate selection |
| AO-26 | Explicit definition-vs-instance reuse analysis | Current runtime/scope/identity/maturity research |
| AO-27 | Three knowledge topology alternatives and conditional decision | Validated support/ACL/costs, named owner, final architecture |
| AO-28 | Component contracts, external bindings, retention checks | Separate live component delivery/permissions and compatibility tests |
| AO-29 | Local multi-consumer reference isolation | Same actual KB instance, ACLs, freshness and independent live rollout |
| AO-30 | Native release-local toolbox snapshots, pinned receipts, drift rejection and uncertain-create reconciliation | Runtime toolbox integration, live traces/schema/auth and observed mutable-default effects |
| AO-31 | Durable synthetic journal, partial failure, repair, delete/expiry | Native writer capture, actual migration and lossless rollback proof |

## Source recommendation map

| Reference | Finding classification | Evidence or limitation |
|---|---|---|
| S1 Source of truth/composite release | Caveat; locally exercised | Canonical bytes and digests are not signed provenance or frozen live content/state |
| S2 Two-phase/read-back | Untested live | Local contract checks cannot establish infrastructure/data readiness |
| S3 Prompt CI/CD | Untested live | Local transitions only; no ordinary Prompt agent deployed |
| S4 Hosted/azd | Packaged and contract-tested; runtime untested | Hosted Responses adapter and CI container builds do not prove deployed image identity, activation or caller authorization |
| S5 Serving/rollback/canary | Native SDK contract-tested; untested live | Concrete consumers omit version/session overrides before/during/after cutover and rollback; control-plane identity is not tool-caller identity; no service-side CAS or state-rollback proof |
| S6 Pipeline/coordination | Caveat; controller CI exercised | Blob lease/CAS adapter is not live distributed-contention evidence; uncoordinated runtime/portal writers remain outside the lease |
| S7 Environment strategy | Caveat; locally exercised | Synthetic scope rejection is not Azure account/network isolation evidence |
| S8 Evaluation | Caveat; locally exercised | Exact thresholds and new response-bound dev model-judge wire contract tested offline; no live grade or calibrated full-quality/safety gate |
| S9 Tools/toolboxes | Native lifecycle contract-tested; untested live | Version-pinned receipts and read-only default-resolution tests do not prove actual calls, schemas, authorization or shared-consumer effects |
| S10 Knowledge/Foundry IQ | Untested live | Reuse/ACL/ingestion ordering/content rollback claims remain conditional |
| S11 Memory | Native API contracts tested; untested live | Scoped extraction/deletion/reconciliation HTTP tests do not establish runtime isolation or expiry; nonempty migration cannot preserve original TTL; harness unsupported with no substitute |
| S12 Security/identity | Bootstrap verified; live gate deferred | Existing platform stays disabled; bounded unattended dev-smoke exception is implemented. Lab resources use the MCAPS `SecurityControl=Ignore` exclusion with compensating controls ([below](#tenant-governance-finding-mcaps-storage-network-modify)) |
| S13 Observability | Monitoring templated; live use in progress | `monitoring.bicep` adds Application Insights server-side agent tracing and resource diagnostic settings; attempt history alone is not runtime telemetry, and no alerting is demonstrated |
| S14 Preview/constraints | Documentation and management plane checked | Selected models/quota observed; runtime/API entitlement still untested |

## Tenant governance finding: MCAPS storage network modify

Observed live in the dev pilot on 2026-11-26. This is tenant-specific, not a
Foundry behaviour.

- **Finding.** The management-group initiative `MCAPSGovDeployPolicies` (v1.0.0)
  includes `StorageAccount_PublicNetwork_Modify`, "SFI-NS2.2.1 Secure PaaS
  Resources - Storage accounts (excluding NSP configured resources)", with
  enforcement Default. Its modify effect ran at 18:30:48-18:31:24Z and changed
  the dev storage account from the template's `publicNetworkAccess=Enabled` to
  `Disabled`. GitHub-hosted runners therefore could not reach the S6 Blob
  lease/CAS journal.
- **Lab resolution.** The policy skips resources whose own tag or resource-group
  tag is `SecurityControl=Ignore` (definition defaults; the assignment passes no
  overrides). At the subscription owner's direction, every taggable lab resource
  carries that tag in `infra/environment.bicep` and `infra/registry.bicep`. No
  policy exemption or assignment change is made.
- **Wider effect.** In the same initiative the tag also skips:
  - the storage local-auth (SFI-ID4.2.1) and anonymous-access (AzTB 2) modifies;
  - the Cognitive Services local-auth modify (AzTB 17);
  - the AI Foundry hub public-network modify (hubs only; the lab has none);
  - the deploy-if-not-exists diagnostic settings for Cognitive Services accounts
    and Foundry projects;
  - policies for resource types the lab does not use.

  Defender-plan policies do not honour the tag, and the separate audit/deny
  initiatives are unaffected.
- **Compensating controls, kept in code.** Entra RBAC-only data access, with no
  keys, SAS or anonymous access. Storage `allowSharedKeyAccess=false`,
  `allowBlobPublicAccess=false`, private containers, OAuth default, HTTPS with
  TLS 1.2. `disableLocalAuth` on the Foundry account, Search and Application
  Insights, and the ACR admin user disabled.
- **Residual gap.** Endpoints stay internet-reachable, protected only by Entra
  authentication. Newly tagged environments do not get the MCAPS policy
  diagnostic settings; `infra/monitoring.bicep` declares the lab's own
  `lab-logs` settings instead.
- **Production guidance.** Do not rely on the exclusion tag. Keep storage private
  and run delivery from private networking: self-hosted runners in a VNet with
  private endpoints, or managed-network runners.
- **Rejected alternatives.**
  - NSP inbound rules for GitHub-hosted IP ranges, which are effectively public.
  - A self-hosted runner for this public repository, which risks running
    untrusted code.
  - A policy exemption, which is outside the lab's authority.

## CI identity findings from the first dev-smoke dispatches

Observed on 2026-11-26 in the first three `dev-smoke.yml` runs. None reached
the release journal, so no attempt was recorded and no Azure state changed.

- **OIDC subject format.** Run 45903981856 failed at `azure/login` with
  AADSTS700213 (no matching federated identity record). The repository's OIDC
  subject customization uses `use_immutable_subject=true`, so the token subject is
  `repo:duongthaiha@2048899/lab-foundry-agentops@1472036346:environment:dev`, not
  the plain `owner/repo` form the runbook listed. The single dev federated
  credential was changed to that exact subject; issuer and audience are unchanged
  and no wildcard was added. Local rehearsals cannot catch this because they use
  the operator's credentials.
- **Azure CLI credential arguments.** Run 45904270748 logged in, then failed
  before any data-plane call: `AzureCliCredential(tenant_id=..., subscription=...)`
  makes azure-identity pass both `--tenant` and `--subscription` to
  `az account get-access-token`, which the CLI rejects ("Please specify only one
  of subscription and tenant, not both"). The credential now passes only the
  tenant; `azure/login` selects the subscription, and `verify_ci_identity` still
  checks the token's tenant and application. A unit test pins the constructor
  arguments.
- **ARM token audience.** Run 45905446127 failed in `verify_ci_identity` with
  "Dev CI identity token could not be verified". The signature and issuer were
  valid, but PyJWT raised `InvalidAudienceError`: azure-identity removes the
  `/.default` suffix before calling the CLI, so the ARM token's `aud` is
  `https://management.azure.com` with no trailing slash. The verifier now accepts
  that ARM audience alongside the slash and legacy `management.core.windows.net`
  forms. Other audiences, forged tokens, user tokens and other applications are
  still rejected. Rehearsals skipped this check because they ran as the operator.

## First journaled dev-smoke attempt

Run 45906360177 (2026-11-26) passed every gate, opened journal attempt
`45906360177-1`, created the release agent and connections, and received an
answer. Grading then rejected it with "Unexpected fields in object": the answer
JSON contained a key outside the fixed contract. The strict grader was right to
fail closed. The attempt is `reconcile-required` and blocks further runs until it
is reviewed. The public log could not show which key, and the journal did not
record the reason either. Two changes follow:

- the private journal now records the rejection `reason` and a sanitized
  `error_detail` (field names only, never values);
- Application Insights tracing and resource diagnostic settings were added
  (`infra/monitoring.bicep`; see
  [debugging](dev-smoke.md#debugging-with-application-insights-and-logs)) so
  the operator can inspect the agent's actual output in a protected store.

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

The subsequent native-consumer milestone is described in
[delivery-demo.md](delivery-demo.md). The native-consumer milestone's local suite contains 82 tests,
including the real Projects/OpenAI SDK HTTP serialization and bearer-auth flow
against offline responses for all three tracks. Serving observations retain
response/conversation/session IDs and selector fingerprints, not model output.
The `verify-serving` command is wired but still fails closed before artifacts
or Azure credentials when live preflight is not ready. It does not evaluate
quality, prove a release match, grant authorization or move a serving selector.
No live cells have been executed.

Required next observations include actual runtime identities and denial paths,
same-instance knowledge reuse, tool invocation traces/default changes, native
memory records/expiry/reconciliation, exact serving versions and session effects.
No proposed source wording should label these validated until those observations
exist. The safe interim wording is: "verify support and behavior for the selected
runtime, API version, identity and environment; configuration rollback does not
by itself restore content or learned state."
