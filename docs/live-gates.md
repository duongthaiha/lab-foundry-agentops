# Live execution, cost and teardown gates

**Current state: governance prepared; live delivery not enabled.**
Foundry dependency setup and its hosted/harness environment preflight completed
after renewed user approval. Fresh ARM and azd authentication succeeded; no
relogin is required. No billable lab resources or OIDC identities were created.

## Confirmed configuration and observed preflight

The user clarified the ambiguous "500k" as **500 USD per month**, not 500,000 USD.
`environments/lab.example.json` records the public-safe configuration shape,
Sweden Central, exact `foudnry-agentops-lab` spelling, per-environment resource
group names, and `@duongthaiha` for both AI Engineer and Platform Engineer.
Actual subscription/tenant identifiers and cloud evidence are kept in ignored
`.lab/` files and must not be published.
The user approved public endpoints with Entra authentication, isolated environment
resources and synthetic data only. Approved live limits are **quality >=80%,
unsafe responses 0%, latency <=60 seconds and cost <=$0.05 per case**, evidence
fresh for one hour, memory retention one day and asynchronous completion within
five minutes. Missing measurements still reject promotion. These approvals do
not convert synthetic measurements into live evaluations.

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

No approval architecture substitution has been authorized. Before OIDC/live
delivery, read back these rules and verify the reviewed deployment jobs reference
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

Repository/environment-specific GitHub/Entra OIDC, protected environments and
named reviewers are required. Separate deployment, component mutation, runtime
dependency access, and serving-change authority. Verify allowed and denied
actions using the actual caller identity at each hop.

The local-check workflow has only `contents: read` and no OIDC/cloud calls.
It does not establish protected-environment enforcement, live workload identity
or delivery permissions. No Entra app, federated credential or role assignment
has been created. The four required-reviewer environments have been independently
read back successfully.

`platform.yml` is a **disabled-by-default reviewed deployment workflow**. Its
deployment job explicitly references `environment: platform`, only admits
`refs/heads/main`, and also requires repository variable `LIVE_PLATFORM_ENABLED`
to equal `true`. That variable has not been set. It has no PR trigger. Its default
operation is `what-if`; applying requires an explicit dispatch input.

Before enabling it, merge reviewed public-safe code, refresh name/quota/policy/
cost checks, bootstrap the four exact resource groups and a dedicated platform
OIDC principal, then grant Contributor only on those groups. The workflow cannot
create resource groups or write RBAC assignments and must not receive Owner or
subscription-wide Contributor. Federation must use issuer
`https://token.actions.githubusercontent.com`, audience `api://AzureADTokenExchange`
and subject `repo:duongthaiha/lab-foundry-agentops:environment:platform`. Store IDs
as protected environment configuration. Validate allowed and denied operations.

The environment templates use keyless Foundry/Search/Storage, Basic Search,
DataZoneStandard model deployments (capacity 10 each), capped log ingestion, and
30-day telemetry retention. `registry.bicep` provides one Basic registry with
admin credentials disabled. They deliberately do **not** grant runtime or data
roles, create agents, deploy content or implement distributed leases. Configure
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

Current allowed nonbillable creation scope is only the lab-filtered budget:
`/subscriptions/<target-subscription>/providers/Microsoft.Consumption/budgets/foudnry-agentops-lab-monthly`
and its subscription deployment record. Teardown of that budget requires explicit
confirmation and must preserve the two pre-existing budgets. No resource-group,
Foundry, Search, Storage, ACR, telemetry or Entra deletion is currently needed.

## Capability blockers that cannot be replaced silently

Unsupported explicit serving pin/atomic update, cross-runtime knowledge/ACL
integration, network-isolated memory, durable native memory write capture, or
required runtime availability blocks that claim. Seek a design/scope decision;
do not add an unapproved router, substitute store, weakened policy, cross-
environment data sharing, or fake runtime output.
