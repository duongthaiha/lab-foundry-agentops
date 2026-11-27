# Native dev -> test -> prod delivery and rollback

**Implemented, not yet exercised against all three live environments.** These
workflows call the real Foundry/Blob/Search adapters, not the simulator.
`tests/test_delivery_pipeline.py` exercises the complete orchestrator with
service fixtures. That is not Azure deployment evidence. The earlier successful
dev smoke remains separate evidence.

Scope: ordinary Prompt agents, two direct MCP dependencies, and the existing
`dev`, `test`, `labprod` GitHub environments. `labprod` targets
`foudnry-agentops-lab-prod`, an isolated synthetic lab, not a production tenant.
Hosted agents, harness agents, memory, percentage canaries and destructive
infrastructure rollback are not enabled by this path.

## Unit of deployment and release sequence

`promote.yml` packages one canonical `release.json` on reviewed `main`, once
per run. Its SHA256 covers instructions, model/version, publisher source hash,
tool contract, **MCP OCI image hash**, answer schema, evaluation policy and source
revision. Only that JSON is uploaded, never the PDF, source passages, private
bindings or model responses. Every stage downloads the same artifact and
verifies canonical bytes against the same digest. Environment resource IDs,
endpoints, identities and prices are separately bound by the reviewed policy.

The stage sequence is:

1. GitHub environment approval, then live run/branch/protection/policy checks
   **before Azure login**. The Entra token must belong to that environment's
   reviewed application, not an interactive operator.
2. Acquire the single shared Blob lease. Reserve bounded usage and persist
   intent before any cloud mutation. Never replace the historical journal.
3. Read back the model, blocking jailbreak policy, project identity, dependency
   endpoints, resource sizes and authentication settings. Reconcile immutable
   hash-named knowledge and release-local connections; reject existing drift.
4. On the first deployment only, create a separately authorized, tools-disabled
   "not ready" baseline. This initial version is immediately serving and is
   explicitly **not** an evaluated release. Existing unowned agents are refused.
5. Observe the stable native endpoint; create and invoke an isolated regular
   candidate by exact version; observe the unchanged stable endpoint again.
   Grade real citations, both MCP calls, release-bound authenticated tool caller,
   environment fixture, semantic quality and safety with the response-bound judge.
6. Reject without cutover if any grade fails. On success, recheck content,
   connections, identity, definition and evaluation freshness. Test also requires
   dev's identical digest and current serving read-back; prod requires test's.
7. Persist retained rollback intent, pin the native selector to the candidate
   at 100%, then invoke the stable endpoint with a fresh conversation and **no
   version override**. A missing/wrong service-reported version fails the stage.

There is no unconditional "implementation incomplete" exception in this
entrypoint. It remains closed until its actual authorization prerequisites are
met. The older generic `agentops.delivery probe` gate remains closed for the
unfinished three-runtime experiment.

## Platform preparation (once per environment)

Do not rebuild or tear down restored dev. Inventory its current resources and
reuse them. The original manual guide's sections 1-4 describe the foundation,
MCP, RBAC and tracing setup; the same templates now accept `environment=test`
and `environment=labprod`. Omitting the parameter preserves the dev names.
Use the minimal `dev-pilot*.bicep` templates for this pipeline, not the older
`environment.bicep` platform workflow, whose names and resource set differ.

For each missing target, the platform operator first reviews current quota,
global-name availability, policy and standing cost, then performs an
**Incremental** what-if/deployment. Example for test (repeat with `labprod` and
RG suffix `prod`):

```powershell
$Environment = 'test'
$Rg = 'foudnry-agentops-lab-test'
# Invoke-LabAz is the exit-code-checking wrapper in manual-experiment.md.
Invoke-LabAz deployment group what-if --resource-group $Rg `
  --template-file infra\dev-pilot.bicep --parameters environment=$Environment
Invoke-LabAz deployment group create --resource-group $Rg --name pipeline-base `
  --mode Incremental --template-file infra\dev-pilot.bicep --parameters environment=$Environment
$Base = Invoke-LabAz deployment group show --resource-group $Rg --name pipeline-base `
  --query properties.outputs -o json | ConvertFrom-Json
```

Never use Complete mode. Keep `SecurityControl=Ignore` on the RG and every
taggable resource, together with explicit Entra-only/local-auth-disabled,
HTTPS/TLS and nonanonymous-storage protections.

Build the MCP image once from reviewed source, or use the restored image after
reviewing its provenance. Import that **digest**, not a tag/rebuild, into each
environment's ACR. Confirm the imported OCI manifest hash is identical.
Deploy `dev-pilot-mcp.bicep` with `environment`, the environment-local immutable
image URI, tenant, its Entra MCP audience, and the **new project MI object ID**
as `allowedCaller`. The UAMI is for ACR pull, not tool invocation. Apply
`monitoring.bicep` and `tracing-access.bicep` using each target's own outputs,
as in manual-guide section 4.

Keep three separate CI apps, with no client secret and an exact environment
federation. This repository uses the ID-bearing subject template:
`repo:duongthaiha@2048899/lab-foundry-agentops@1472036346:environment:<environment>`.
Read back the current repository OIDC subject configuration; do not substitute
a branch wildcard or the simpler owner/repo subject. The issuer is
`https://token.actions.githubusercontent.com`; audience is `api://AzureADTokenExchange`.

Required scoped grants:

| Identity | Scope and role |
|---|---|
| Each environment CI app | Reader on its RG; Foundry User on its account; connection read/write on its project; Search Service Contributor and Search Index Data Contributor on its Search service |
| Every CI app | Reader on the **dev journal storage account** and Blob Data Contributor on its `release-locks` container only |
| Test CI / prod CI | Read-only native agent metadata on the preceding dev / test project only |
| Each project MI | Search Index Data Reader on its Search service; Monitoring Metrics Publisher on its App Insights |
| Each MCP UAMI | AcrPull on its own registry |

Reuse dev's existing grants instead of creating duplicate assignments. CI never
needs Owner, User Access Administrator, subscription Contributor or permission
to create role assignments. The existing dev connection-writer role is scoped
only to dev; create separately reviewed equivalents for test/prod with
`Microsoft.CognitiveServices/accounts/projects/connections/read` and `/write`.

For the preceding-project readback, a custom role needs only these permissions
at that preceding project; do **not** give the downstream deployment app
Foundry User on the upstream account:

```json
{
  "Actions": ["Microsoft.CognitiveServices/accounts/projects/read"],
  "DataActions": ["Microsoft.CognitiveServices/accounts/AIServices/agents/read"],
  "NotActions": [],
  "NotDataActions": []
}
```

Add a reviewed role name and exact assignable scope when creating that custom
role. `agents/read` is the provider's advertised native-agent read operation.
Verify effective get-agent/get-version access before enabling delivery.

## GitHub controls and private configuration

Restore and read back the owner reviewer, exact `main` branch policy and
`can_admins_bypass=false` on **all three environments**, following
[the existing restoration checklist](live-gates.md#temporary-reviewer-deferral).
The narrow dev-smoke unattended exception is not extended to full promotion.
Each stage and each rollback waits for the named human's environment approval;
the controller additionally checks that run's approval history.
The agent must never approve its own deployment.

Set the following separately in each GitHub environment:

| Setting | Meaning |
|---|---|
| `LIVE_DELIVERY_ENABLED` variable | `false` until bootstrap/configuration review is finished; then `true` |
| `DELIVERY_BINDING` secret | The private JSON configuration below |
| `DELIVERY_POLICY` variable | Canonical JSON policy binding the executing main SHA, approved release digests, configuration digest and bounds |

`DELIVERY_BINDING` has four fields:

```text
current: existing dev-smoke binding shape, but for this environment:
  tenant_id, subscription_id, client_id
  search_resource_id, storage_resource_id, tool_resource_id, tool_image
  target:
    environment, project_endpoint, project_resource_id, search_endpoint
    storage_endpoint, tool_mcp_url, tool_audience
    prices: input_per_million, output_per_million, tool_call_upper_bound_usd,
            safety_call_upper_bound_usd, provenance
upstream: null for dev; preceding environment's target object for test/prod
journal_endpoint: dev storage's Entra-authenticated Blob endpoint, identical in all three
journal_resource_id: exact ARM ID of that same dev storage account
```

Use live deployment outputs, not the pre-restoration MI/FQDN. Keep tenant and
subscription identical to the approved lab. Each target uses a distinct project.
`tool_image` must end in `@sha256:<the hash in the release>`. The shared journal
is still `release-locks/delivery-state.json`; the pipeline adds separate
`delivery_pipeline` and `native` state without changing `dev_smoke` history.

For a preview of the exact positive release digest on a clean reviewed checkout:

```powershell
$Revision = git rev-parse HEAD
$ToolHash = '<reviewed 64-character MCP manifest SHA256, without sha256:>'
python -m agentops.delivery_pipeline prepare --output .lab\release-preview `
  --source-revision $Revision --tool-image-sha256 $ToolHash
# Repeat in a NEW output directory with --negative to review the negative digest.
```

This is local packaging, not deployment. The workflow independently packages
the same canonical bytes and refuses any digest absent from the policy.
Use `agentops.contracts.fingerprint(parse_json(...))`, not a hash of
pretty-printed JSON, for the private configuration digest.

The policy schema is:

```json
{
  "mode": "prompt-delivery-v1",
  "id": "<new environment-specific policy ID>",
  "source_revision": "<current reviewed main SHA: execution code, including rollback>",
  "binding_digest": "<fingerprint of the complete DELIVERY_BINDING>",
  "release_digests": ["<reviewed release SHA256>"],
  "actions": ["promote", "rollback"],
  "valid_from": "<UTC timestamp>",
  "expires_at": "<UTC timestamp, no more than seven days later>",
  "price_checked_at": "<UTC timestamp, at most seven days old>",
  "spend_checked_at": "<UTC timestamp, at most one day old>",
  "spend_observed_usd": 0,
  "estimated_monthly_usd": 260,
  "max_operations": 10,
  "allow_bootstrap": true
}
```

The amounts are illustrative placeholders, **not observed spend or a quote**.
Replace them with current reviewed values; budget ingestion can lag. Use a
different policy ID for each environment/binding and each changed policy.
The executing revision must be current `main`; an older retained release may
be explicitly allowlisted for rollback under the current reviewed operator code.

The original **$30 review, $40 stop-new-requests, $500/month** limits have not
been raised. Admission stops before observed spend plus retained reservations
reaches $30. Each operation conservatively reserves $0.50, and every model
request is measured against the $0.05 case limit. Reservations are never
reset by changing policy IDs. At most ten pipeline stage/rollback attempts are
allowed across policies; this is separate from, and does not reset, the older
smoke's five consumed CI attempts. Eight operations cover A/B/C/rollback below.
These checks are not a provider billing hard cap: a charge can occur before
the client observes an error, and standing resource cost continues while idle.

## Run promotion and rollback

After both the code and environment configuration have been reviewed:

```powershell
gh workflow run promote.yml --repo duongthaiha/lab-foundry-agentops --ref main `
  -f tool_image_sha256=$ToolHash
```

Approve each environment in GitHub when requested. Dev/test/prod invoke the
same artifact and re-evaluate locally; a failed job blocks downstream jobs.
Keep the release artifact and private journal for the rollback retention window.
Artifacts have 90-day retention. This workflow requires that artifact to remain
available; archive the JSON for audit if needed, but an audit copy does not
extend GitHub's rollback-download window. Raw evaluation and rollback records remain in
Entra-protected Blob, not public workflow artifacts.

Demonstration: promote release A; make a reviewed instruction/source revision
for B and promote B; dispatch a separately allowlisted negative candidate C
with `-f negative=true`. C really disables tools; its observed missing calls
must produce `status=rejected`, a failing dev job and skipped test/prod.
Do not call a failed infrastructure request an evaluation-rejection demo.

Roll prod back from B to the retained, previously evaluated A:

```powershell
gh workflow run rollback.yml --repo duongthaiha/lab-foundry-agentops --ref main `
  -f environment=labprod -f artifact_run_id=<B-promotion-run-id> -f digest=<B-release-digest>
```

Approve this new run separately. It downloads B's existing manifest, not a
rebuild of A. The target version/digest comes only from the protected retained
receipt. It verifies both retained definitions and dependency/content/identity
context, switches the native selector, and verifies a fresh consumer request
executed A. Retained indexed content is checked against its original watermark;
rollback does not download today's PDF or re-ingest old content.
The structured result records both `release_digest` (B) and
`restored_release_digest` (A). No versions, sources, connections or infrastructure
are deleted, and the rollback does not roll back mutable user memory.

## Failure and pause behavior

An ordinary grading rejection is terminal and leaves serving unchanged.
A failure before the first target mutation is recorded as
`failed-before-mutation`; it consumes the operation allowance but does not block
a new authorized attempt. A timeout, partial creation, selector uncertainty or
failed consumer check after that boundary is `reconcile-required`, not a
successful release. Do not retry or clear the ledger in that state; inspect and
reconcile the target and journal before proceeding. The shared lease plus CAS
guards participating writers. It cannot prevent a portal administrator changing
native serving concurrently; such drift is rejected, not silently repaired.

An uncertain cutover can be recovered by the exact retained rollback operation.
It records recovery on the failed attempt without replaying the deployment.
Other uncertain operations need operator inspection/reconciliation; never clear
the ledger or create a new policy ID to retry them. A successful stage rerun
verifies the existing serving receipt instead of creating another version.
Rollback refuses a stale digest, missing prior evaluated release, changed old
version, missing dependency, altered content or changed MCP image. Keep the
dependency graph available for the rollback window.

To pause, close `LIVE_DELIVERY_ENABLED` and disable **both** `promote.yml` and
`rollback.yml`; disablement is rechecked by active writers. Changing a GitHub
variable alone does not rewrite variables already captured by a running job.
No cleanup or automatic teardown is scheduled by these workflows. Restored dev
and any subsequently provisioned test/prod resources stay available and continue
incurring standing cost until the operator explicitly chooses otherwise.
