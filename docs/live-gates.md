# Live execution, cost and teardown gates

**Current update:** dev infrastructure has been restored following the successful
dev smoke. The [ordinary-Prompt native pipeline](native-pipeline.md) is
implemented but has not run across live dev/test/prod. All-environment reviewer
restoration and fresh native-delivery policies are still required. The
historical preflight/bootstrap notes below are not a current resource inventory.

**Historical bootstrap state: no live deployment; reviewer control temporarily deferred.**
The reviewed design now permits a separate [dev-only unattended prompt smoke](dev-smoke.md)
without a reviewer per run, but its foundation/identity/cost authorization and
enablement have not occurred. This exception does not open platform, test,
labprod or full agent promotion.
Foundry dependency setup and its hosted/harness environment preflight completed
after renewed user approval. Fresh ARM and azd authentication succeeded; no
relogin was required. No billable lab resources were created. A secretless
single-tenant platform app, one exact environment federation, four empty lab
groups and four resource-group-scoped Contributor grants were created and read
back. No Owner/subscription grant, password, certificate or requested API
permission was added. Actual OIDC login has not run.

## Temporary reviewer deferral

At the user's request on 2026-11-26, the `required_reviewers` protection was
removed from `dev`, `test`, `labprod` and `platform`. Independent read-back
confirmed the environments were preserved, their exact `main` branch policies
were unchanged and `can_admins_bypass` remained `false`.

**This active setting is not approval to deploy.** Before removing the rules,
the real platform workflow was disabled at GitHub and
`LIVE_PLATFORM_ENABLED` was set to `false`. Its only deployment run,
[45728748173](https://github.com/duongthaiha/lab-foundry-agentops/actions/runs/45728748173),
was cancelled at the reviewer gate, with zero executed steps. All four resource
groups were then independently verified empty. No pending approval was submitted.
The separate `simulated-rehearsal.yml` contains no cloud login, environment
binding or `id-token: write`; its placeholder permits synthetic work only.

### Restore before general live use

1. Keep `platform.yml` disabled and `LIVE_PLATFORM_ENABLED=false`. Inventory every
   workflow with cloud credentials or OIDC permissions and all queued, waiting
   or running deployments; cancel unintended live work and verify terminal state.
2. Restore each of the four environments using the environment REST PUT endpoint
   with `reviewers: [{"type": "User", "id": 2048899}]` (`@duongthaiha`),
   `prevent_self_review: false`, `can_admins_bypass: false`, and
   `deployment_branch_policy: {"protected_branches": false, "custom_branch_policies": true}`.
   Preserve unrelated controls and the existing exact `main` branch rule; use
   the pre-change snapshot rather than deleting/recreating environments.
   Self-review is allowed only because the approved lab owner holds both roles.
3. GET every environment and its `deployment-branch-policies`; verify the named
   required reviewer, main-only rule, no admin bypass and preserved other rules.
   Do not mistake CODEOWNERS or a successful mock job for this verification.
4. Review deployment code on `main`, its explicit `environment: platform`
   binding, the exact federation subject and four scoped grants. Refresh
   name/quota/policy/cost and teardown evidence. Restore reviewers before
   enabling either the workflow or `LIVE_PLATFORM_ENABLED`.
5. With explicit live authorization, enable `platform.yml` and the repository
   flag, dispatch the reviewed revision, and confirm it pauses for the real
   environment reviewer **before** login or provisioning. The named human must
   approve the particular run. Recheck actual allowed/denied identity actions.
   Any unexpected execution or failed read-back closes both live switches again.

The same restoration is required for general dev/test/labprod
agent-delivery jobs. Only the bounded dev smoke has an explicit alternate,
expiring unattended policy; it cannot provide full promotion authorization.
Raw before/after settings and scoped bootstrap/teardown
IDs stay in ignored `.lab/` evidence, never the public repository.

## Confirmed configuration and observed preflight

The user clarified the ambiguous "500k" as **500 USD per month**, not 500,000 USD.
`environments/lab.example.json` records the public-safe configuration shape,
Sweden Central, exact `foudnry-agentops-lab` spelling, per-environment resource
group names, and `@duongthaiha` for both AI Engineer and Platform Engineer.
Actual subscription/tenant identifiers and cloud evidence are kept in ignored
`.lab/` files and must not be published.
The user approved public endpoints with Entra authentication, isolated environment
resources and synthetic data only. Initially approved live limits were **quality >=80%,
unsafe responses 0%, latency <=60 seconds and cost <=$0.05 per case**, evidence
fresh for one hour, memory retention one day and asynchronous completion within
five minutes. Missing measurements still reject promotion. These approvals do
not convert synthetic measurements into live evaluations.

The later [ordinary-Prompt native pipeline](native-pipeline.md) has explicit
operator approval to remove its aggregate observed-spend check and $0.05 case
cap. Its v2 contract retains measured usage, the separate operation reservation,
monthly estimate and all non-spend controls. The older dev-smoke/probe limits
above are not changed by that scoped update.

Read-only checks on 2026-11-25 observed:

- The target subscription and deployment access were verified.
- No resource groups matching the lab base name exist. This does not reserve
  names or establish global Foundry/Search/ACR/Storage name availability.
- Sweden Central advertises `gpt-5-mini` version `2025-08-07` and
  `text-embedding-3-small` version `1`, including GlobalStandard and
  DataZoneStandard. Available quota was observed; exact subscription usage stays
  local. Returned quota units are `Count`, not measured token use.
- The target policy requires jailbreak detection **enabled and blocking**.
  Preserve this and `Microsoft.DefaultV2`; validate actual deployment policy
  before provisioning rather than inferring compliance from the model name.
- The private GitHub repository rejected the required-reviewer environment PUT
  with HTTP 422: "Please ensure the billing plan supports the required reviewers
  protection rule." The failed PUT left an empty, unprotected `dev` environment;
  it was removed and a fresh read confirmed zero environments.
- The agent's visibility-change request was denied and was not bypassed.
  The user subsequently made the repository public manually. Required-reviewer
  protection was then configured for `dev`, `test`, `labprod` and `platform`:
  `@duongthaiha`, admin bypass disabled, self-review allowed by the single-owner
  lab decision, and deployment branch `main` only.

The temporary reviewer deferral and the narrow dev smoke exception above supersede
the original requirement only within their stated scopes. Before general OIDC/live
delivery, restore and read back the rules and verify reviewed deployment jobs reference
the correct environment. Do not issue credentials to PR code or widen trust to
arbitrary branches. CODEOWNERS is not a substitute. Because both lab roles have
the same owner, this lab does not claim independent approver separation.

## Preconditions

1. Foundry dependency/setup prerequisite is now satisfied. Read each applicable
   workflow and rerun authentication/preflight if its context changes.
2. Tenant, subscription, group names, owners, reviewer, network and budget are
   confirmed. Global names still need availability checks immediately before
   provisioning. Runtime integration and agent delivery remain unimplemented.
3. Verify exact API/model/runtime capabilities, quotas, identity/network access,
   and policy. Preserve `Microsoft.DefaultV2` and required jailbreak blocking;
   surface policy denials instead of weakening controls.
4. Obtain current regional pricing and an explicit usage envelope. Publish the
   estimate and exact scoped teardown inventory before any creation.
5. Use the approved limits above for live evaluation. Record content watermarks
   and native asynchronous completion, rather than treating successful HTTP
   submission or elapsed waiting time as readiness.

## Proposed cost inventory, not a quote

| Proposed item | Quantity/boundary | Cost input still needed |
|---|---|---|
| Foundry account/project | One per dev/test/labprod | Applicable feature meters and regional support |
| Model deployments | Same requirements, separate environment deployments | Actual deployment SKU/capacity, token usage and availability |
| AI Search Basic | Three isolated instances | Regional standing rate, replica/partition minimum, ingestion/query costs |
| ACR | Proposed shared immutable artifact registry | Tier, storage, transfer and isolation/role design |
| Log Analytics / App Insights | Environment-separated observations | Ingest volume, retention, sampling and region |
| Storage | One per environment for leases/journals/evidence | Redundancy, capacity, transactions, retention, network |
| Hosted runtime / harness | Three environment instances per applicable runtime | Active compute/session/feature pricing and usage |
| Knowledge / memory previews | Supported environments/runtimes only | Retrieval/extraction/model/storage meters, quotas and network limits |

Include currency, meter URLs/retrieval date, usage assumptions, standing versus
variable charges, evaluation/negative-test volume, remaining unknowns, and the
user's spending ceiling. Absence of a quoted meter does not mean it is free.
Do not create resources before a complete enough estimate can be reviewed.

### Retrieved standing-cost subtotal (not an authorization to deploy)

Azure Retail Prices retrieved 2026-11-25 for Sweden Central, USD:

| Meter | Rate and assumption | Subtotal |
|---|---|---|
| AI Search Basic Unit, `0c873ca2-4113-4997-8cf6-ad5df5775599` | $0.101/hour x 730 hours x 3 instances, one unit each | $221.19/month |
| ACR Basic Registry Unit, `5c9e7a65-5784-494c-9718-7749d4075dd9` | $0.1666/day x 31 days x 1 registry | $5.1646/month |

Combined illustrative standing subtotal is **$226.3546/month**, leaving at most
$273.6454 of the $500 envelope before other charges. Storage, logs, model tokens,
hosted/harness sessions, knowledge/memory features, build/storage overages,
transfer and taxes are **not included**. This is not a complete lab estimate.
Rates use the [Azure Retail Prices API](https://prices.azure.com/api/retail/prices);
AI Search uses the retail service label `Azure Cognitive Search`.

The subsequent 31-day foundation estimate is **$260.8456**: Search $225.432,
ACR $5.1646, 9.3 GB log ingestion at $2.99/GB ($27.807), 30 GB hot LRS storage
($0.552), and the stated operation allowance ($1.89: 300K writes, 300K reads,
300K other operations and 30K list operations). This is an estimate under those
usage assumptions, not a hard cap; logging caps and budgets may lag.
ARM validation succeeded and subscription what-if contained 44 creates with no
updates; all ten global names were available at preflight. These observations
expire and do not authorize provisioning during the dry-run phase.
Hosted/harness, inference, memory and knowledge traffic remain separately gated.

`infra/budget.bicep` defines a separate $500 monthly budget filtered to exactly
the three environment groups plus the lab shared group. Actual-cost alerts at
50%, 80% and 100% target subscription Owners. Never overwrite pre-existing
subscription budgets; their details remain in local evidence.
An Azure Budget **does not stop consumption**; alert evaluation and billing
records can lag. Notification delivery is not proven by resource creation.
The budget deployment/read-back outcome must be recorded below before claiming
that the alert exists.

### Budget deployment outcome

The nonbillable `foudnry-agentops-lab-budget` subscription deployment succeeded.
ARM read-back confirmed `foudnry-agentops-lab-monthly`, **500 USD / Monthly**,
the exact four resource-group filters, enabled actual-cost notifications at
50/80/100% to `Owner`, and $0 recorded lab spend. Both pre-existing budgets retain
their prior amounts. The API defaulted the alert period to 2026-11-01 through
2036-11-01; this is an alert lifecycle, not authorization to keep lab workloads
running for that period. No test notification was sent.

Local evidence: `.lab/budget-deployment.json`, `.lab/budget-readback.json`.
To reproduce with a new explicitly approved budget name, build
`infra/budget.bicep`, pass the amount, first-of-month start date and exact group
names, validate and inspect `what-if`, then deploy at subscription scope.
For the existing lab alert, read it back rather than creating a duplicate:

```powershell
$config = Get-Content -Raw .lab\live-config.json | ConvertFrom-Json
az rest --method get --url "https://management.azure.com/subscriptions/$($config.subscription_id)/providers/Microsoft.Consumption/budgets/$($config.monthly_budget.name)?api-version=2023-11-01"
```

## Identity and CI gate

Repository/environment-specific GitHub/Entra OIDC and protected environments are
required. Named reviewers remain required outside the explicit bounded dev smoke
exception. Separate deployment, component mutation, runtime
dependency access, and serving-change authority. Verify allowed and denied
actions using the actual caller identity at each hop.

The local-check workflow has only `contents: read` and no OIDC/cloud calls.
It does not establish protected-environment enforcement, live workload identity
or delivery permissions. A platform app/federation and exactly four scoped
Contributor assignments were subsequently created and read back. The original
reviewer rules were verified, then temporarily removed as described above.

`platform.yml` is a **disabled-by-default reviewed deployment workflow**. Its
deployment job explicitly references `environment: platform`, only admits
`refs/heads/main`, and also requires repository variable `LIVE_PLATFORM_ENABLED`
to equal `true`. The variable is currently `false`, and the workflow itself is
disabled at GitHub. It has no PR trigger. Its default
operation is `what-if`; applying requires an explicit dispatch input.

The initial public-safe code was merged to `main` in commit
`55f8c3d13ca13c961270e060b957812efc01db11`, and scoped bootstrap is complete.
Before enabling it, restore reviewers and refresh name/quota/policy/cost checks.
Keep Contributor limited to the four exact groups. The workflow cannot
create resource groups or write RBAC assignments and must not receive Owner or
subscription-wide Contributor. Federation must use issuer
`https://token.actions.githubusercontent.com`, audience `api://AzureADTokenExchange`
and subject `repo:duongthaiha@2048899/lab-foundry-agentops@1472036346:environment:platform`
(the repository uses GitHub's immutable OIDC subject; see
[dev-smoke.md](dev-smoke.md#minimal-live-scope-and-permissions)). Store IDs
as protected environment configuration. Validate allowed and denied operations.

The environment templates use keyless Foundry/Search/Storage, Basic Search,
DataZoneStandard model deployments (capacity 10 each), capped log ingestion, and
30-day telemetry retention. `monitoring.bicep` (a module of `environment.bicep`)
adds workspace-based Application Insights, the project's `AppInsights` tracing
connection and `lab-logs` diagnostic settings. `registry.bicep` provides one Basic registry with
admin credentials disabled. They deliberately do **not** grant runtime or data
roles, create agents, deploy content or implement distributed leases. The one
tracing grant (Monitoring Metrics Publisher for the project identity on
Application Insights) is in the separate operator-only `tracing-access.bicep`
and is never run by the platform workflow. Configure
those separate identities and scoped grants only after interface verification.
No deployment succeeded merely because these templates compile.

Per-agent delivery jobs for dev/test/labprod do not exist yet. Do not create
their federated credentials or treat platform provisioning as agent promotion.
GitHub job concurrency is not the required shared CLI/CI distributed lease.

## Teardown contract before creation

Prepare an inventory containing the exact subscription, resource-group and
resource IDs, creation ownership, environment, expected standing cost, dependency
references, rollback/session retention, and deletion eligibility. Record newly
created Entra/OIDC/role-assignment IDs separately from Azure resources.

Only delete resources created by the lab and explicitly approved for teardown.
Never delete pre-existing/shared resources, a whole subscription, wildcard
resource groups, or dependencies still needed by serving/rollback sessions.
Export evidence first, revoke only lab-owned identity grants, enumerate retained
items and their ongoing cost, and verify the final inventory after deletion.
Deletion needs explicit confirmation; deployment approval is not teardown approval.

The original nonbillable budget resource is:
`/subscriptions/<target-subscription>/providers/Microsoft.Consumption/budgets/foudnry-agentops-lab-monthly`
and its subscription deployment record. The four empty groups, platform app/
service principal, exact federation and four scoped grants now also exist.
Their exact IDs are recorded separately in the ignored bootstrap inventory.
Teardown requires explicit confirmation and must preserve pre-existing budgets
and all unrelated resources. No billable lab resource currently needs deletion.

## Capability blockers that cannot be replaced silently

Unsupported explicit serving pin/atomic update, cross-runtime knowledge/ACL
integration, network-isolated memory, durable native memory write capture, or
required runtime availability blocks that claim. Seek a design/scope decision;
do not add an unapproved router, substitute store, weakened policy, cross-
environment data sharing, or fake runtime output.
