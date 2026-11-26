targetScope = 'resourceGroup'

@allowed(['dev', 'test', 'labprod'])
param environment string

param location string = 'swedencentral'
param baseName string = 'foudnry-agentops-lab'

@description('Use a reviewed suffix only after checking global name availability.')
param nameSuffix string = ''

var environmentSuffix = environment == 'labprod' ? 'prod' : environment
var prefix = '${baseName}-${environmentSuffix}${nameSuffix}'
// SecurityControl=Ignore is the MCAPS governance policies' own exclusion tag. Without it
// SFI-NS2.2.1 modify forces storage public network access to Disabled, which blocks the
// GitHub-hosted runner. The tag also skips sibling MCAPS modify policies, so the
// compensating controls below (Entra-only auth with local/shared-key auth disabled, no
// anonymous blob access, HTTPS with TLS 1.2) are declared explicitly and must stay.
var tags = {
  workload: 'agentops-lab'
  environment: environment
  dataClassification: 'synthetic'
  SecurityControl: 'Ignore'
}

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: prefix
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: prefix
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
    networkAcls: {
      defaultAction: 'Allow'
      ipRules: []
      virtualNetworkRules: []
    }
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: '${prefix}-project'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'AgentOps ${environment}'
    description: 'Isolated synthetic AgentOps lab; not a production application.'
  }
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: 'gpt-5-mini'
  tags: tags
  sku: { name: 'DataZoneStandard', capacity: 10 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-5-mini', version: '2025-08-07' }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource embedding 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: 'text-embedding-3-small'
  tags: tags
  sku: { name: 'DataZoneStandard', capacity: 10 }
  properties: {
    model: { format: 'OpenAI', name: 'text-embedding-3-small', version: '1' }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [chat]
}

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: '${prefix}-search'
  location: location
  tags: tags
  sku: { name: 'basic' }
  identity: { type: 'SystemAssigned' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'Default'
    disableLocalAuth: true
    publicNetworkAccess: 'enabled'
    semanticSearch: 'free'
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stagentops${uniqueString(resourceGroup().id)}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
    containerDeleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [
  for containerName in ['knowledge', 'release-evidence', 'release-locks', 'state-journal']: {
    parent: blobs
    name: containerName
    properties: { publicAccess: 'None' }
  }
]

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: json('0.1') }
    features: { enableLogAccessUsingOnlyResourcePermissions: true }
  }
}

// Application Insights, the project tracing connection and resource diagnostic settings. The
// tracing ingestion role is granted separately by the operator with tracing-access.bicep.
module monitoring 'monitoring.bicep' = {
  name: 'agentops-monitoring'
  params: {
    location: location
    prefix: prefix
    tags: tags
    accountName: account.name
    projectName: project.name
    searchName: search.name
    storageName: storage.name
    workspaceName: logs.name
  }
  dependsOn: [blobs]
}

output projectId string = project.id
output accountId string = account.id
output projectPrincipalId string = project.identity.principalId
output searchId string = search.id
output searchPrincipalId string = search.identity.principalId
output storageId string = storage.id
output applicationInsightsId string = monitoring.outputs.applicationInsightsId
output applicationInsightsName string = monitoring.outputs.applicationInsightsName
