# Run the dev experiment manually, without teardown

## Current handoff: recovery is required

The live ordinary-Prompt experiment passed in
[CI run 45912758182](https://github.com/duongthaiha/lab-foundry-agentops/actions/runs/45912758182)
on 2026-11-26: both authenticated MCP dependencies, a real IQ citation, and the
response-bound judge passed. This is not dev-to-test/prod promotion evidence.

**The subsequent teardown was halted, but its resource-deletion commands had
finished before the halt reached the deployment session.** At the 2026-11-27
handoff the dev resource group contained zero resources. The Foundry account
was also purged. There is no running agent or old endpoint to open now.
The Entra CI and MCP apps, custom connection-writer role, resource group/tags,
deployment history and private evidence were preserved. The 3 December scheduled
teardown was cancelled. No reconstruction was run while writing this guide.

The workflow is disabled and `LIVE_DEV_SMOKE_ENABLED=false`. Its saved binding
is **stale**. Do not just enable the old workflow: the MCP hostname, project
identity, image and permissions must be rediscovered after recovery.

There are two manual experiences:

| Experience | What to do |
|---|---|
| Live graded repeat | Restore the dev foundation once, then manually dispatch **Bounded unattended dev smoke** from GitHub or PowerShell. The job creates the agent/KB/connections, grades one case, and leaves them in place. |
| Interactive experimentation | After that run, open its existing agent in Foundry Playground and send prompts yourself. These extra calls are operator experiments, not new graded CI receipts. |

The supported `agentops.delivery_dev run` CLI is **CI-only**. Setting
`GITHUB_ACTIONS=true` locally or using the old session-only `rehearse.py` is not
the supported repeat path: that rehearsal used an in-memory journal and stale
hard-coded endpoints. General `probe`, `verify-serving` and promotion remain
closed. Do not relax their gates.

## 1. Open PowerShell 7 and select the existing lab

Use a clean checkout of the reviewed `main` revision in
`duongthaiha/lab-foundry-agentops`, including the reviewed manual-runbook/template
change. Until that change is merged, review the guide but do not authorize a
feature-branch run. Keep the private operator handoff in ignored
`.lab\manual`, never in committed source. Python 3.11+, Azure CLI and GitHub CLI
are required. The platform operator needs authority to deploy into **dev** and
create the scoped role assignments below; the CI app must not receive that
broader authority.

The private handoff supplies `operator-context.json` with `tenant_id`,
`subscription_id`, `ci_client_id`, `mcp_app_id`, and `connection_role_id`.
These identify the retained lab identities; they are not passwords.

```powershell
$ErrorActionPreference = 'Stop'
$Repository = 'duongthaiha/lab-foundry-agentops'
$Rg = 'foudnry-agentops-lab-dev'
$State = Join-Path (Get-Location) '.lab\manual'
$Context = Get-Content (Join-Path $State 'operator-context.json') -Raw | ConvertFrom-Json
$Az = 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
$env:AZURE_CONFIG_DIR = Join-Path $HOME '.azure'
function Invoke-LabAz { & $Az @args; if ($LASTEXITCODE -ne 0) { throw 'Azure command failed; stop here.' } }
function Invoke-LabGh { & gh @args; if ($LASTEXITCODE -ne 0) { throw 'GitHub command failed; stop here.' } }

# Interactive login is performed by you, only if the current session needs it.
Invoke-LabAz login --tenant $Context.tenant_id
Invoke-LabAz account set --subscription $Context.subscription_id
$Account = Invoke-LabAz account show -o json | ConvertFrom-Json
if ($Account.id -ne $Context.subscription_id -or $Account.tenantId -ne $Context.tenant_id) {
    throw 'Wrong Azure target.'
}
Invoke-LabAz ad signed-in-user show --query id -o tsv
gh auth status
if ($LASTEXITCODE -ne 0) { throw 'Sign in with gh auth login before proceeding.' }
Invoke-LabAz resource list --resource-group $Rg -o table
```

On `InteractionRequired`/`TokenCreatedWithOutdatedPolicies`, stop and complete
the requested interactive sign-in in this same CLI/config context. Do not
repeat unattended logins, extract tokens, or switch identity to get around it.

Create the isolated Python environment only if it is missing, then install the
repository's pinned dependencies:

```powershell
if (-not (Test-Path '.lab\.venv\Scripts\python.exe')) {
    python -m venv .lab\.venv
    if ($LASTEXITCODE -ne 0) { throw 'venv creation failed.' }
}
$Python = (Resolve-Path '.lab\.venv\Scripts\python.exe').Path
& $Python -m pip install -r requirements-live.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$Revision = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot read checkout revision.' }
$Main = Invoke-LabGh api "repos/$Repository/git/ref/heads/main" --jq '.object.sha'
$Dirty = git status --porcelain --untracked-files=normal
if ($LASTEXITCODE -ne 0 -or $Dirty -or $Revision -ne $Main) {
    throw 'Use a clean checkout of current reviewed main. Do not discard unrelated work.'
}
```

## 2. Platform operator: reconstruct the minimal dev foundation

**This step starts billing.** Review current prices/quota and the
[dev scope and controls](dev-smoke.md#minimal-live-scope-and-permissions) first.
Stay in Sweden Central, dev only. Do not deploy `environment.bicep` or dispatch
`platform.yml` as a shortcut: those are the broader multi-environment design.

[`dev-pilot.bicep`](../infra/dev-pilot.bicep) preserves the pilot's minimal
bootstrap, with `SecurityControl=Ignore` on every taggable resource and the
working model capacity of 100. It deploys no embedding model, agent or KB.
[`dev-pilot-mcp.bicep`](../infra/dev-pilot-mcp.bicep) deploys only its MCP service.
These are the retained pilot templates updated for repeatability; the newly
packaged templates have not themselves been redeployed as part of this handoff.

The resource-group tag is still present. Merge it rather than replacing other
tags. It is a lab-specific MCAPS policy exclusion, not production guidance.
Keep shared keys/anonymous blobs disabled, TLS 1.2, Entra-only Foundry/Search,
and ACR admin credentials disabled.

```powershell
$Group = Invoke-LabAz group show --name $Rg -o json | ConvertFrom-Json
Invoke-LabAz tag update --resource-id $Group.id --operation Merge --tags SecurityControl=Ignore
Invoke-LabAz deployment group what-if --resource-group $Rg --template-file infra\dev-pilot.bicep
# Inspect the what-if. Continue only for the exact intended dev inventory.
Invoke-LabAz deployment group create --resource-group $Rg --name dev-pilot-base `
    --mode Incremental --template-file infra\dev-pilot.bicep --output none
$Base = Invoke-LabAz deployment group show --resource-group $Rg --name dev-pilot-base `
    --query properties.outputs -o json | ConvertFrom-Json
```

Never use Complete deployment mode or delete an existing name to fix a conflict.
If the group is not empty, reconcile its current inventory before applying.
Stop on policy, permission, model availability or quota errors; do not change
region, SKU or model silently.

## 3. Platform operator: restore MCP and the access boundaries

Reuse the retained apps, not a new application with a secret. Check the MCP app
still issues Entra v2 tokens and advertises its `api://` audience:

```powershell
$McpApp = Invoke-LabAz ad app show --id $Context.mcp_app_id -o json | ConvertFrom-Json
$Audience = "api://$($Context.mcp_app_id)"
if ($McpApp.api.requestedAccessTokenVersion -ne 2 -or $Audience -notin $McpApp.identifierUris) {
    throw 'MCP application configuration drift; review before proceeding.'
}
$CiPrincipal = Invoke-LabAz ad sp show --id $Context.ci_client_id --query id -o tsv
Invoke-LabAz ad app federated-credential list --id $Context.ci_client_id -o json
Invoke-LabGh api "repos/$Repository/actions/oidc/customization/sub"
```

The retained federation must match the repo's actual immutable subject:
`repo:duongthaiha@2048899/lab-foundry-agentops@1472036346:environment:dev`,
issuer `https://token.actions.githubusercontent.com`, audience
`api://AzureADTokenExchange`. A plain owner/repo subject does not match this
repository. Do not add branch/PR wildcards.

Build from the clean reviewed source, resolve the resulting digest, and deploy:

```powershell
$Tag = $Revision.Substring(0, 12)
Invoke-LabAz acr build --registry cragentopslabdev --file Dockerfile.mcp `
    --image "agentops/lab-tools:$Tag" .
$Digest = Invoke-LabAz acr repository show --name cragentopslabdev `
    --image "agentops/lab-tools:$Tag" --query digest -o tsv
if ($Digest -notmatch '^sha256:[0-9a-f]{64}$') { throw 'No immutable image digest.' }
$Image = "$($Base.registryServer.value)/agentops/lab-tools@$Digest"
Invoke-LabAz deployment group create --resource-group $Rg --name dev-pilot-mcp `
    --mode Incremental --template-file infra\dev-pilot-mcp.bicep `
    --parameters image=$Image tenantId=$($Context.tenant_id) audience=$Audience `
        allowedCaller=$($Base.projectPrincipalId.value) --output none
$Mcp = Invoke-LabAz deployment group show --resource-group $Rg --name dev-pilot-mcp `
    --query properties.outputs -o json | ConvertFrom-Json
```

**`allowedCaller` is the newly returned project managed-identity object ID. It is
not the CI service principal, the old project identity, or the UAMI.** The UAMI
only pulls the image. The project identity calls the two tools.

Restore the grants that teardown removed. The custom role definition survived;
verify its scope/actions against [the permission matrix](dev-smoke.md#minimal-live-scope-and-permissions)
before using it. Do not grant Owner or subscription Contributor to CI.

```powershell
Invoke-LabAz role definition list --name $Context.connection_role_id -o json
$FoundryUserRole = '53ca6127-db72-4b80-b1b0-d745d6d5456d' # Foundry User
Invoke-LabAz role assignment create --assignee-object-id $CiPrincipal --assignee-principal-type ServicePrincipal --role Reader --scope $Group.id --output none
Invoke-LabAz role assignment create --assignee-object-id $CiPrincipal --assignee-principal-type ServicePrincipal --role $FoundryUserRole --scope $Base.accountId.value --output none
Invoke-LabAz role assignment create --assignee-object-id $CiPrincipal --assignee-principal-type ServicePrincipal --role $Context.connection_role_id --scope $Base.projectId.value --output none
Invoke-LabAz role assignment create --assignee-object-id $CiPrincipal --assignee-principal-type ServicePrincipal --role 'Search Service Contributor' --scope $Base.searchId.value --output none
Invoke-LabAz role assignment create --assignee-object-id $CiPrincipal --assignee-principal-type ServicePrincipal --role 'Search Index Data Contributor' --scope $Base.searchId.value --output none
Invoke-LabAz role assignment create --assignee-object-id $CiPrincipal --assignee-principal-type ServicePrincipal --role 'Storage Blob Data Contributor' --scope $Base.locksId.value --output none
Invoke-LabAz role assignment create --assignee-object-id $Base.projectPrincipalId.value --assignee-principal-type ServicePrincipal --role 'Search Index Data Reader' --scope $Base.searchId.value --output none
$Operator = Invoke-LabAz ad signed-in-user show --query id -o tsv
Invoke-LabAz role assignment create --assignee-object-id $Operator --assignee-principal-type User --role $FoundryUserRole --scope $Base.accountId.value --output none
Invoke-LabAz role assignment create --assignee-object-id $Operator --assignee-principal-type User --role 'Storage Blob Data Contributor' --scope $Base.locksId.value --output none
```

Operator Foundry access is for Playground; container-scoped Blob Contributor is
for restoring/exporting the journal. These are distinct from CI's permissions.
Allow role propagation, then verify access; do not replace RBAC with keys/SAS.

### Preserve the previous attempt ledger

There have already been **five CI executions out of the original ten**. Some
failed before reserving an attempt in Blob, so do not infer the total solely
from the JSON journal. Retain both the GitHub run history and the saved journal.
The policy enforces `max_runs` per policy, not a global ten across new policy IDs.

The handoff includes `prior-evidence\journal-after-run5.json`. Restore that exact
file to the newly empty journal container, without overwriting any newer ledger:

```powershell
$Ledger = Join-Path $State 'prior-evidence\journal-after-run5.json'
if (-not (Test-Path $Ledger)) { throw 'Missing historical ledger; do not start an empty allowance.' }
Invoke-LabAz storage blob upload --account-name stagentopslabdev --auth-mode login `
    --container-name release-locks --name delivery-state.json --file $Ledger --overwrite false --output none
$SeedReadback = Join-Path $State 'seed-ledger-readback.json'
if (Test-Path $SeedReadback) { throw 'Keep the previous readback; choose a new filename.' }
Invoke-LabAz storage blob download --account-name stagentopslabdev --auth-mode login `
    --container-name release-locks --name delivery-state.json --file $SeedReadback --output none
if ((Get-FileHash $Ledger).Hash -ne (Get-FileHash $SeedReadback).Hash) { throw 'Journal readback differs.' }
```

If a blob already exists, stop and compare/reconcile; never overwrite it to
clear a failed attempt. Keep an external total (including preflight failures).
The single-run policy below permits one more attempt, not a fresh ten.

## 4. Restore tracing

Use the existing modules so the lab's policy exclusion does not leave telemetry
dependent on skipped policy-deployed settings:

```powershell
$Monitoring = @{
    location = @{ value = 'swedencentral' }
    prefix = @{ value = $Rg }
    tags = @{ value = @{ workload='agentops-lab'; environment='dev'; dataClassification='synthetic'; pilot='dev-smoke-v1'; SecurityControl='Ignore' } }
    accountName = @{ value = $Rg }
    projectName = @{ value = "$Rg-project" }
    searchName = @{ value = "$Rg-search" }
    storageName = @{ value = 'stagentopslabdev' }
    workspaceName = @{ value = $Base.workspaceName.value }
}
@{ '$schema'='https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'; contentVersion='1.0.0.0'; parameters=$Monitoring } |
    ConvertTo-Json -Depth 10 | Set-Content (Join-Path $State 'monitoring.parameters.json') -Encoding utf8NoBOM
Invoke-LabAz deployment group create --resource-group $Rg --name dev-pilot-monitoring `
    --mode Incremental --template-file infra\monitoring.bicep `
    --parameters "@$(Join-Path $State 'monitoring.parameters.json')" --output none
Invoke-LabAz deployment group create --resource-group $Rg --name dev-pilot-tracing-access `
    --mode Incremental --template-file infra\tracing-access.bicep `
    --parameters applicationInsightsName="$Rg-insights" projectPrincipalId=$($Base.projectPrincipalId.value) --output none
```

## 5. Developer/operator: build a fresh private binding and one-run policy

Do not run the old `build-ci-config.py` unchanged: it embeds the deleted
hostname and old image. Discover the new project endpoint from ARM:

```powershell
$Project = Invoke-LabAz resource show --ids $Base.projectId.value --api-version 2025-06-01 -o json | ConvertFrom-Json
$Endpoints = @($Project.properties.endpoints.PSObject.Properties.Value | Where-Object {
    $_ -match '^https://[a-z0-9-]+\.services\.ai\.azure\.com/api/projects/[a-z0-9-]+/?$'
})
if ($Endpoints.Count -ne 1) { throw 'Expected one verified Foundry project endpoint.' }
$Storage = Invoke-LabAz storage account show --name stagentopslabdev --resource-group $Rg -o json | ConvertFrom-Json
if ($Storage.publicNetworkAccess -ne 'Enabled' -or $Storage.allowSharedKeyAccess -ne $false -or
    $Storage.allowBlobPublicAccess -ne $false -or $Storage.minimumTlsVersion -ne 'TLS1_2') {
    throw 'Storage network/authentication gate failed.'
}
```

Check current [retail prices](https://prices.azure.com/api/retail/prices) using
the meters in [the cost proposal](dev-smoke.md#cost-proposal-not-spending-authorization).
The last measured DataZone rates were $0.275 input / $2.20 output per million
tokens and a $0.002 tool-call allowance. Re-enter the **reviewed** current values
below; an up-to-date timestamp alone is not a price check.

```powershell
$PriceCheckedAt = Read-Host 'UTC time of your completed price review (ISO 8601)'
$InputRate = [double](Read-Host 'Reviewed input USD per 1M tokens')
$OutputRate = [double](Read-Host 'Reviewed output USD per 1M tokens')
$ToolAllowance = [double](Read-Host 'Reviewed per-call dependency allowance in USD')
$Binding = @{
    tenant_id = $Context.tenant_id
    subscription_id = $Context.subscription_id
    client_id = $Context.ci_client_id
    search_resource_id = $Base.searchId.value
    storage_resource_id = $Base.storageId.value
    tool_resource_id = $Mcp.id.value
    tool_image = $Image
    target = @{
        environment = 'dev'
        project_endpoint = $Endpoints[0].TrimEnd('/')
        project_resource_id = $Base.projectId.value
        search_endpoint = "https://$Rg-search.search.windows.net"
        storage_endpoint = $Storage.primaryEndpoints.blob.TrimEnd('/')
        tool_mcp_url = "https://$($Mcp.fqdn.value)/mcp"
        tool_audience = $Audience
        prices = @{
            input_per_million=$InputRate; output_per_million=$OutputRate
            tool_call_upper_bound_usd=$ToolAllowance; safety_call_upper_bound_usd=0
            provenance='https://prices.azure.com/api/retail/prices'
        }
    }
}
$BindingPath = Join-Path $State 'binding.json'
$Binding | ConvertTo-Json -Depth 12 | Set-Content $BindingPath -Encoding utf8NoBOM
$BindingDigest = & $Python -c "import sys; from pathlib import Path; from agentops.contracts import read_json,fingerprint; from agentops.delivery_dev import validate_binding; print(fingerprint(validate_binding(read_json(Path(sys.argv[1])))))" $BindingPath
if ($LASTEXITCODE -ne 0) { throw 'Invalid binding.' }
$Now = [DateTimeOffset]::UtcNow
# Cancellation of teardown did not authorize an unlimited spending window.
$ReviewDeadline = [DateTimeOffset]::Parse('2026-12-03T12:00:00Z')
$End = $Now.AddHours(1)
if ($End -gt $ReviewDeadline) { $End = $ReviewDeadline }
if ($End -le $Now) { throw 'Review a new holding/spending window before running.' }
$Source = Get-Content docs\public-source.json -Raw | ConvertFrom-Json
$Policy = @{
    mode='dev-unattended-v1'; id=('manual-dev-' + $Now.ToString('yyyyMMddtHHmmss'))
    source_revision=$Revision; source_sha256=$Source.sha256; binding_digest=$BindingDigest
    valid_from=$Now.ToString('o'); expires_at=$End.ToString('o')
    price_checked_at=$PriceCheckedAt; max_runs=1
    monthly_ceiling_usd=500; estimated_monthly_usd=120; max_case_usd=0.05
}
$PolicyPath = Join-Path $State 'policy.json'
$Policy | ConvertTo-Json -Depth 10 | Set-Content $PolicyPath -Encoding utf8NoBOM
```

The binding digest is `agentops.contracts.fingerprint`, **not** a file hash.
The job will validate the policy against live GitHub reads, its actual run,
current main, immutable federation and the application token. Do not fabricate
a local GitHub run object to claim these checks passed.

Before enablement, run the same read-only Azure configuration inspection used
by the smoke. It does not create resources or invoke a model:

```powershell
@'
import sys
from pathlib import Path
from azure.identity import AzureCliCredential
from agentops.contracts import read_json
from agentops.delivery_azure import Foundry
from agentops.delivery_dev import inspect_dev, validate_binding

binding = validate_binding(read_json(Path(sys.argv[1])))
with AzureCliCredential(tenant_id=binding["tenant_id"]) as credential:
    foundry = Foundry(binding["target"], credential)
    try:
        inspect_dev(foundry, binding)
    finally:
        foundry.close()
print("Dev configuration inspection passed; no resources changed.")
'@ | & $Python - $BindingPath
if ($LASTEXITCODE -ne 0) { throw 'Azure preflight failed; keep admission closed.' }
Invoke-LabGh api "repos/$Repository/environments/dev"
Invoke-LabGh api "repos/$Repository/environments/dev/deployment-branch-policies"
$CurrentMain = Invoke-LabGh api "repos/$Repository/git/ref/heads/main" --jq '.object.sha'
if ($CurrentMain -ne $Revision) { throw 'Main changed; review a new source/image/binding/policy.' }
```

Read back exactly `main` as a branch policy, admin bypass disabled, and any
restored reviewers preserved. Confirm current prices, grants and
Entra-authenticated Blob access against [the full preflight](dev-smoke.md).
If anything fails, leave admission closed.

## 6. Manually dispatch one graded live run

This is the run action, not an instruction to recreate the foundation each time.
Set the private binding and policy as **dev environment** settings:

```powershell
Get-Content $BindingPath -Raw | gh secret set DEV_SMOKE_BINDING --repo $Repository --env dev
if ($LASTEXITCODE -ne 0) { throw 'Failed to set binding.' }
Get-Content $PolicyPath -Raw | gh variable set DEV_SMOKE_POLICY --repo $Repository --env dev
if ($LASTEXITCODE -ne 0) { throw 'Failed to set policy.' }
Invoke-LabGh workflow enable dev-smoke.yml --repo $Repository
Invoke-LabGh variable set LIVE_DEV_SMOKE_ENABLED --repo $Repository --env dev --body true
Invoke-LabGh workflow run dev-smoke.yml --repo $Repository --ref main
Invoke-LabGh run list --repo $Repository --workflow dev-smoke.yml --limit 5
```

Alternatively open GitHub **Actions > Bounded unattended dev smoke > Run
workflow**, select **main**, and run once. Use either the UI or CLI, not both.
The GitHub-hosted job signs into Azure using the dev app's OIDC federation; it
does not inherit your interactive PowerShell login.

Choose the newly dispatched run ID from its URL/list, not an unrelated run:

```powershell
$RunId = Read-Host 'ID of the run you just dispatched'
gh run watch $RunId --repo $Repository --exit-status
$RunExit = $LASTEXITCODE
# Pause new automated runs, but KEEP the experiment and all its data.
Invoke-LabGh variable set LIVE_DEV_SMOKE_ENABLED --repo $Repository --env dev --body false
Invoke-LabGh workflow disable dev-smoke.yml --repo $Repository
if ($RunExit -ne 0) { throw 'Run failed or watch was interrupted. Inspect its terminal state; do not blindly rerun.' }
```

A success log contains `{"promotion_authorized":false,"status":"smoke-passed"}`.
It means the agent, release-bound tool calls, source citation, exact serving
version, structural checks and custom judge passed for one case. It does not
enable test/labprod or prove full promotion, rollback, memory or safety.
After failure/cancellation, preserve the journal and check
`reconcile-required`; reconciliation involving deletion needs a separate
explicit cleanup decision, not an automatic reset.

## 7. Read the result and try the existing agent yourself

Export the protected journal before experimenting further:

```powershell
$JournalPath = Join-Path $State "journal-$RunId.json"
if (Test-Path $JournalPath) { throw 'Choose a new export filename; retain existing evidence.' }
Invoke-LabAz storage blob download --account-name stagentopslabdev --auth-mode login `
    --container-name release-locks --name delivery-state.json --file $JournalPath --output none
$Journal = Get-Content $JournalPath -Raw | ConvertFrom-Json
$Run = Invoke-LabGh api "repos/$Repository/actions/runs/$RunId" | ConvertFrom-Json
$RunKey = "$RunId-$($Run.run_attempt)"
$Attempt = $Journal.dev_smoke.PSObject.Properties[$Policy.id].Value.attempts.PSObject.Properties[$RunKey].Value
if (-not $Attempt -or $Attempt.status -ne 'smoke-passed') { throw 'No passing receipt for this run.' }
$Attempt | Select-Object status, agent_name, version, release_digest, full_gate_passed, promotion_authorized
```

In [Microsoft Foundry](https://ai.azure.com/), select the reconstructed dev
project, open **Agents**, then the exact `agent_name` from this new journal
entry. Open its Playground and start a fresh conversation. Do not save edits
to the pinned agent/version while comparing its deployment evidence.

Ask:

> What did Microsoft announce at Ignite 2024 about agents in Power Pages, and
> is that feature enabled in this lab environment? Cite the PDF page and
> distinguish product announcements from the lab fixture status.

Look for the PDF-backed announcement and the separate fictional dev fixture:
`feature_id=power-pages-agents`, `enabled=true`, `environment=dev`,
`fixture_revision=dev-1`. The known pinned-source passage is `p0027`; a citation
must actually come from the KB, not be inserted manually. The answer uses the
strict fields `announcement`, `citations`, `feature_id`, `enabled`,
`environment`, `fixture_revision`.

Inspect Application Insights/Foundry tracing after its ingestion delay. The
successful pilot showed `invoke_agent`, two `execute_tool` spans and the model
call. Filter by the new agent name, not the old deleted one:

```kusto
AppDependencies
| where TimeGenerated > ago(1h)
| where tostring(Properties["gen_ai.agent.name"]) == "<agent_name from journal>"
| project TimeGenerated, Name, Success, DurationMs, OperationId
| order by TimeGenerated asc
```

Reading traces requires workspace read permission (for example Log Analytics
Reader). Raw responses/conversations are caller-scoped: a response created by
the CI app may return 404 to your user identity. Use protected traces for that
run, or create your own new Playground conversation. Never publish raw answers,
PDF text, trace payloads, private bindings or tokens in public Actions logs.

Playground calls incur additional charges and do not execute the CI judge or
its per-policy attempt checks. Start with one prompt; record extra usage
separately. Do not batch requests or treat the historic passing score as a
grade for a changed question/agent.

## Leave it available; do not tear it down

Pausing automation means the flag is false and the workflow disabled. That
does **not** delete the agent, knowledge, image, identities or Azure resources.
Do not run the old teardown scripts, a purge, or the deletion-based reconciliation
procedure merely to finish a manual session. No scheduled teardown is enabled
by this guide.

Once reconstructed, Search and ACR keep billing while idle; the earlier
near-idle estimate was about **$2.6/day**, not a quote or hard cap. ACR builds,
model calls, retrieval, logs and traffic add usage. Continue the $500/month
lab ceiling, $30 review and $40 stop-new-requests thresholds. Budget data lags
and alerts are not spend cutoffs. At a threshold/window expiry, pause new
requests and review holding costs; do not silently delete the experiment or
extend the budget.

For a no-Azure exercise while recovery is pending, the simulator is runnable:

```powershell
$Output = '.lab\manual-sim-' + [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmss')
& $Python -m agentops --mode simulated demo --output $Output --source-revision (git rev-parse HEAD)
if ($LASTEXITCODE -ne 0) { throw 'Simulator failed.' }
```

Its metrics and approvals are synthetic, not a live-agent substitute.
