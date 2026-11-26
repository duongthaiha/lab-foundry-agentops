targetScope = 'resourceGroup'

// Debug telemetry for one lab environment: Application Insights for Foundry server-side agent
// tracing, plus resource logs in the environment's capped Log Analytics workspace. It contains no
// role assignments; the operator grants ingestion with tracing-access.bicep. Deployable on its own
// against an existing environment, and used as a module by environment.bicep.

param location string = resourceGroup().location

@description('Name prefix shared by the environment resources, for example foudnry-agentops-lab-dev.')
param prefix string

param tags object

param accountName string
param projectName string
param searchName string
param storageName string
param workspaceName string

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: accountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: account
  name: projectName
}

resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchName
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageName
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: storage
  name: 'default'
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

// Workspace-based, so the workspace's daily ingestion cap also bounds trace volume.
resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-insights'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    IngestionMode: 'LogAnalytics'
    DisableLocalAuth: true
  }
}

// Connecting Application Insights turns on server-side tracing for Prompt agents. Local auth is
// disabled, so the project identity ingests with Entra auth and needs Monitoring Metrics
// Publisher on the component. A project accepts only one AppInsights connection.
resource tracing 'Microsoft.CognitiveServices/accounts/projects/connections@2025-10-01-preview' = {
  parent: project
  name: 'appinsights'
  properties: {
    category: 'AppInsights'
    target: insights.id
    // Bicep's 2025-10-01-preview type omits ProjectManagedIdentity; ARM accepts it (as used by
    // agentops/delivery.py connections()).
    #disable-next-line BCP036
    authType: 'ProjectManagedIdentity'
    isSharedToAll: false
    metadata: {
      ApiType: 'Azure'
      ResourceId: insights.id
      ApplicationInsightsConnectionString: insights.properties.ConnectionString
    }
  }
}

// The MCAPS SecurityControl=Ignore exclusion also skips the policy-deployed diagnostic settings,
// so the lab declares its own.
resource accountLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: account
  name: 'lab-logs'
  properties: {
    workspaceId: logs.id
    logs: [{ categoryGroup: 'allLogs', enabled: true }]
    metrics: [{ category: 'AllMetrics', enabled: true }]
  }
}

resource projectLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: project
  name: 'lab-logs'
  properties: {
    workspaceId: logs.id
    logs: [{ categoryGroup: 'allLogs', enabled: true }]
  }
}

resource searchLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: search
  name: 'lab-logs'
  properties: {
    workspaceId: logs.id
    logs: [{ categoryGroup: 'allLogs', enabled: true }]
  }
}

resource blobLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: blobs
  name: 'lab-logs'
  properties: {
    workspaceId: logs.id
    logs: [{ categoryGroup: 'allLogs', enabled: true }]
  }
}

output applicationInsightsId string = insights.id
output applicationInsightsName string = insights.name
output tracingConnectionName string = tracing.name
