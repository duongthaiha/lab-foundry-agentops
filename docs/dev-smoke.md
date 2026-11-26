# Dev-only unattended prompt deploy and graded smoke

**Dev foundation provisioned; CI enablement pending.** This is a separate, reversible
exception to the reviewer restoration requirement for one bounded **dev prompt
smoke**. It does not open the existing full-delivery or platform gates.
After authorization on 2026-11-26 the operator provisioned only the dev inventory
below and the dev CI identity, and rehearsed the smoke locally. Dev reviewers
remain deferred, exact-main restrictions remain, and admin bypass is disabled.

## What the user needs to authorize

1. Review the exact draft PR head and separately approve its merge. The workflow
   only runs code already on current `main`; this document does not authorize
   merging the rest of the draft.
2. Separately authorize the **dev-only foundation, identity and enablement**
   described below, after reviewing the cost assumptions and unresolved meters.
   Approval of the unattended approach is not that spending/credential approval.
3. After setup/read-back, approve one source/target/cost policy window (up to
   seven days and ten attempts). Runs within it need no human GitHub environment
   approval. A changed source commit, binding, limit or expired window requires
   a new reviewed policy, not a bypass. No relogin is needed now; authentication
   failure during authorized setup is the point to request `az login`.

The operator can perform the setup after this one-time authorization. The user
does not need to approve every run, manually create each Azure resource, or
resolve the unrelated harness track first.

## Minimal live scope and permissions

Use the already selected subscription, Sweden Central, and **only**
`foudnry-agentops-lab-dev`. Do not provision test/prod/shared or reuse the platform
application's broader four-group authority for this job.

| Resource | Proposed dev instance and bound |
|---|---|
| Foundry S0 account/project | `foudnry-agentops-lab-dev`, one isolated project, Entra-only |
| Model | `gpt-5-mini` / `2025-08-07`, DataZoneStandard capacity at most 100; no embedding deployment. Capacity is a pay-per-token rate limit, not a fixed charge: at 10 (10K TPM/10 RPM) the KB's internal planning calls received 429 from short-window enforcement, and 100 was the tested working value |
| Policy | `Microsoft.DefaultV2`, jailbreak prompt detection enabled and blocking; no policy relaxation |
| AI Search | One Basic unit, one replica and partition; one hash-named PDF index, source and model-free extractive IQ KB |
| MCP service | One Container Apps Consumption environment/app, 0.25 vCPU / 0.5 GiB, min 0 / max 1 replica; pinned reviewed image |
| Registry | One dev Basic ACR, admin credentials disabled; managed-identity image pull |
| Storage | One dev Standard_LRS account, no shared keys or public blobs; private `release-locks` container |
| Logs | One dev workspace, 30-day retention, proposed 0.1 GB/day ingestion cap; no publisher text/tokens |

Names must still be checked for availability before creation. Do not silently
suffix a private binding or switch subscription, region, model or SKU. The
existing `infra/environment.bicep` is **not** this minimal inventory: it includes
an embedding model and does not deploy the MCP Container App. The platform owner
must prepare/review the exact scoped bootstrap plan; do not dispatch the broad
platform template as an implicit substitute.

Create a **separate dev delivery app** with no password/certificate, issuer
`https://token.actions.githubusercontent.com`, audience
`api://AzureADTokenExchange`, and exact federation subject
`repo:duongthaiha/lab-foundry-agentops:environment:dev`. No PR/branch wildcard
federation, Owner, subscription Contributor or role-assignment write permission.
The deployment identity needs only the actual operations below, with allowed
and denied access checked before enablement:

| Principal | Necessary access boundary |
|---|---|
| Dev CI app | Read existing dev resource/model/policy metadata; create/read agent versions and endpoint pins only in dev; use the model for agent and judge calls |
| Dev CI app | Read/create the two release-local project RemoteTool connections, Search index/source/KB definitions and page data; lease/read/write dev journal blob |
| Foundry project managed identity | Read/query the dev Search KB and call the MCP application; no test/prod data permissions |
| MCP application identity | ACR image pull only; no tool-side write privileges |
| One-time platform operator | Create only the approved dev inventory and exact scoped role/federation setup; this authority is never assigned to the runtime workflow |

Verify current role definitions against those operations; don't assume an ARM
Contributor grant includes Foundry, Search or Blob data-plane access. Missing
roles fail visibly and are not auto-granted. Agent-native identity creation and
Search preview entitlement must succeed through supported project setup.
The MCP application must issue Entra v2 tokens, validate the exact tenant and
`api://` audience, and allow **only the project managed-identity object ID**.
The runtime's returned caller digest must match that ARM-observed identity.

## Cost proposal, not spending authorization

USD retail inputs refreshed 2026-11-26 from the
[Azure Retail Prices API](https://prices.azure.com/api/retail/prices),
Sweden Central. Use 31 days / 744 hours, without assuming free grants:

| Item/assumption | Calculation | Monthly USD |
|---|---|---:|
| Search Basic, continuously provisioned | 744 x $0.101/hour | 75.1440 |
| ACR Basic | 31 x $0.1666/day | 5.1646 |
| MCP compute, conservative continuously active maximum | 2,678,400 seconds x (0.25 x $0.000024 + 0.5 x $0.000003) | 20.0880 |
| Up to 1 million Container Apps requests | 1 x $0.40 | 0.4000 |
| Log ingestion, 0.1 GB/day | 3.1 x $2.99/GB | 9.2690 |
| Blob data, 10 GB | 10 x $0.0184/GB-month | 0.1840 |
| Blob operations, 10K each write/list/read/other | $0.05 + $0.05 + $0.004 + $0.004 | 0.1080 |
| Ten accepted smoke cases including evaluator | 10 x $0.05 | 0.5000 |
| **Illustrative subtotal** | | **110.8576** |

Propose a **$120/month dev allocation within the unchanged $500/month lab
ceiling**, conditional on checking the remaining meters against the $9.1424
headroom before creation. This is not a complete quote or a hard cutoff.
IQ/semantic retrieval billing/preview entitlement, image build/storage overage,
network transfer, taxes and agreement-specific pricing still need confirmation.
Unknown charges are not assumed free. Search keeps billing when no runs occur.
Scale-to-zero can lower MCP cost; the estimate does not depend on free grants.
The [Container Apps pricing page](https://azure.microsoft.com/pricing/details/container-apps/)
explains request/compute charging and subscription-shared free allowances.

The measured case uses GPT-5 mini **DataZone standard** prices of $0.275 input and
$2.20 output per million tokens, with cache discounts ignored. Meter IDs:
`ba8737fb-3392-5ead-80cf-14de6801f5fb` and
`68cae02f-c5bd-5272-96de-fcdddf816ef7`. Search Basic:
`0c873ca2-4113-4997-8cf6-ad5df5775599`; ACR:
`5c9e7a65-5784-494c-9718-7749d4075dd9`; log ingestion:
`e3669cc9-19b6-55fc-b9fe-782ab83615ab`.
The MCP call allowance must cover verified retrieval charges as well as requests.

The policy reserves a case allowance before requests, limits attempts, requests
at most two agent MCP calls, and checks measured agent+judge token costs plus
reviewed dependency allowances against $0.05. **Checks happen after consumption**:
token usage, unreturned/failed calls, server limit semantics and billing lag mean
this is not a prepaid spending cap. Failed/uncertain attempts consume allowance
and block subsequent attempts until reconciliation; don't reset the journal to
hide usage. Preserve/read back the existing $500 alert; budgets and logging caps
are alerts/usage controls, not guaranteed billing cutoffs.

## Configuration and execution after authorization

Keep `.github/workflows/dev-smoke.yml` disabled/off until the scope is authorized.
It is `workflow_dispatch` only, `environment: dev`, current `main` only, serialized
by workflow concurrency and a dev Blob lease/CAS journal. PR/local/simulated
contexts cannot authorize it. The protected job checks GitHub's actual run,
workflow, current main SHA, branch policy and admin-bypass setting before login.
After login it verifies the signed Entra management token's issuer, tenant,
audience and exact dev application ID, rejecting delegated user tokens. Merely
setting GitHub-looking environment variables alongside a personal CLI login
cannot substitute for the federated dev app.
Restored reviewers work automatically because GitHub gates job start.

Set these **dev environment** settings, not general PR-accessible credentials:

- Variable `LIVE_DEV_SMOKE_ENABLED=true` only after all setup/read-back succeeds.
- Variable `DEV_SMOKE_POLICY`: reviewed JSON below.
- Secret `DEV_SMOKE_BINDING`: private JSON below. Resource IDs are not credentials,
  but keeping the binding secret prevents the public job's environment log from
  publishing them. Identity values are additionally masked before Azure login.

Policy shape (replace every placeholder; not an executable approval):

```json
{
  "mode": "dev-unattended-v1",
  "id": "reviewed-dev-window",
  "source_revision": "<exact-current-main-40-hex-SHA>",
  "source_sha256": "<reviewed-FAQ-64-hex-SHA256>",
  "binding_digest": "<SHA256-of-canonical-private-binding>",
  "valid_from": "<UTC-ISO-timestamp>",
  "expires_at": "<UTC-ISO-timestamp-within-seven-days>",
  "price_checked_at": "<UTC-ISO-timestamp-no-more-than-seven-days-old>",
  "max_runs": 10,
  "monthly_ceiling_usd": 500,
  "estimated_monthly_usd": 120,
  "max_case_usd": 0.05
}
```

`DEV_SMOKE_BINDING` fields are `tenant_id`, `subscription_id`, `client_id`,
`search_resource_id`, `storage_resource_id`, `tool_resource_id`, `tool_image`
(immutable ACR digest), and `target`. Every dependency resource ID must be in
the same dev group/subscription. `target` uses the existing validated shape:
`environment: dev`, `project_endpoint`, `project_resource_id`, `search_endpoint`,
`storage_endpoint`, `tool_mcp_url` (HTTPS Container Apps `/mcp`), `tool_audience`,
and `prices`. Prices require `input_per_million`, `output_per_million`,
`tool_call_upper_bound_usd`, `safety_call_upper_bound_usd`, and the reviewed
Microsoft HTTPS `provenance` URL. The judge's actual token charge is added
separately, so the safety allowance can be zero when there is no other meter.
Compute binding digest with `agentops.contracts.fingerprint`, which includes
the canonical JSON trailing newline. Do not use a raw-file hash.

After authorized enablement:

```powershell
gh workflow run dev-smoke.yml --ref main
```

The job runs `python -m agentops.delivery_dev authorize`, OIDC login using the
separate dev app, then `python -m agentops.delivery_dev run`. There is no local
live fallback. The latter command, with the flag missing/off, fails before
downloading source or obtaining Azure credentials. `authorize` does not verify
Azure readiness or grant permissions.

## What a successful run proves, and does not

The operator first inspects existing ARM resources, endpoint ownership,
capacity, authentication, fixed model, jailbreak policy, MCP image/environment
and exact caller allowlist. It acquires the release's hash-pinned public PDF,
materializes/verifies the environment-local IQ KB, and reconciles two
release-local authenticated MCP connections.

It creates `dev-smoke-<release digest prefix>` with one ordinary prompt version
and an explicit native selector. This **release-local smoke endpoint is serving
from creation**, not an isolated candidate of `contoso-prompt`. A fresh
conversation invokes the endpoint without version/model/prior-response overrides.
The service must return the expected version. Both real MCP calls, returned
source page citation, correct typed fictional dev status, measured usage,
latency and expected authenticated caller/release evidence are mandatory.
An existing smoke agent must match exactly; its route is never silently repaired.

A second authenticated model request evaluates the observed answer. Runtime
citation markers (only exact `【…】` spans located by `url_citation`
annotations) are removed; other answer text is judged unchanged. The announcement
is judged against the cited PDF pages and the lab status fields against the
authenticated tool result that the structural grade already matched to the
fixture. Without that second evidence item, dev rehearsals scored the same
correct answer between 65 and 100 because the judge treated the lab status as
unsupported. It has no tools and strict JSON output, requires
semantic score >=80 and zero Hate/SelfHarm/Sexual/Violence severities. Its versioned
instructions/schema digest, subject/response digests, model, usage and result are
recorded. This is a **custom model-based smoke evaluator**, not a verified Foundry
catalog evaluator or calibrated safety certification. A single benign case and
a same-model judge do not establish full quality or adversarial safety.

All detailed evidence stays in Entra-protected `release-locks/delivery-state.json`
under `dev_smoke`; public logs show only a terse status. No publisher passages,
PDF bytes, raw answers, tokens or private IDs are published. Success always keeps
`full_gate_passed=false` and `promotion_authorized=false`. No native delivery
candidate/serving receipt is created. No contoso serving selector, test/prod,
Hosted/harness, memory, full evaluator, or composite rollback behavior is claimed.
The original `probe`, `verify-serving` and full promotion gates are unchanged.

## Live service behaviour observed in dev rehearsals

Operator rehearsals against the provisioned dev foundation (2026-11-26) found
these differences from the documented request shapes. The code now handles each
one without weakening a check:

- The `Microsoft.DefaultV2` RAI policy returns 404 by name, so preflight lists
  account policies and requires exactly one match and no `nextLink`.
- RemoteTool connections persist `isSharedToAll` as false. It is still sent, but
  excluded from read-back; access remains governed by project identity and RBAC.
- Prompt agent MCP tools persist `allowed_tools` as `{"tool_names": [...]}`;
  that canonical form is sent so read-back stays exact.
- Agent details may omit `instance_identity.status`. A missing status is treated
  as active when `state`/`configuration_state` are enabled and a principal ID is
  present; an explicit non-active status still fails.
- The Foundry MCP client probes `server/discover`, negotiates protocol
  `2025-11-25` down to `2025-06-18`, sends `_meta`, and uses chunked request
  bodies. The lab MCP server reads chunked bodies within its size limit.
- MCP outputs arrive as rendered text: the KB returns `{"documents": [...]}`;
  the lab tool returns its text JSON followed by an identical
  `{"structuredResponse": ...}`. Any mismatch between the two is rejected.
- `gpt-5-mini` used roughly 900-1,150 reasoning tokens per smoke turn, so all
  model calls allow 4,096 output tokens. The $0.05 case check is unchanged.

## Stop, teardown, reset and restoring reviewers

To stop new requests, turn `LIVE_DEV_SMOKE_ENABLED=false` and disable
`dev-smoke.yml`. Cancel active runs and verify terminal state before changing
trust or policy; a variable change alone does not rewrite a running job's
environment. The operator also rereads workflow/main/protection state before
each mutation/request. Cancellation or an uncertain service result still needs
journal/resource reconciliation, not blind retry.

Before any authorized teardown, inventory exact IDs and journal ownership:
the smoke agent/version/conversations, two digest-named connections, hash-named
KB/source/index, MCP app/environment, ACR image, storage containers/account,
logs, Foundry project/account/model, and the new dev app/federation/grants.
Check for other consumers before deleting retained knowledge/connections.
Delete only these owned resources in dependency order; retain private evidence
as agreed. Reconcile partially created names recorded in `planned_resources`.
Do not delete the whole resource group, shared journal or unrelated budget by
wildcard, and do not touch the previous platform federation or other environments.
The workflow deliberately has no delete-all/reset or grant-repair operation.

To reinstate the deferred reviewer, first stop/cancel as above. Restore the named
dev reviewer using the existing
[restoration procedure](live-gates.md#restore-before-general-live-use), preserving
exact-main/no-admin-bypass and other controls; GET/read back the environment and
branch policy. With the enablement flag still false, dispatch a verification run
and confirm the job waits before login; cancel it without approving. No code
change is needed: the workflow already names
`environment: dev`. Test/labprod/platform retain their existing restoration and
authorization requirements throughout.
