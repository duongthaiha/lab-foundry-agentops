// Reviewed lab foundation; defaults preserve the restored dev resources.
targetScope = 'resourceGroup'

@allowed(['dev', 'test', 'labprod'])
param environment string = 'dev'

@allowed(['swedencentral'])
param location string = 'swedencentral'

var suffix = environment == 'labprod' ? 'prod' : environment
var prefix = 'foudnry-agentops-lab-${suffix}'
var tags = {
  workload: 'agentops-lab'
  environment: environment
  dataClassification: 'synthetic'
  pilot: environment == 'dev' ? 'dev-smoke-v1' : 'prompt-delivery-v1'
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
    networkAcls: { defaultAction: 'Allow', ipRules: [], virtualNetworkRules: [] }
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: '${prefix}-project'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'AgentOps ${environment} pilot'
    description: 'Isolated synthetic AgentOps ${environment} smoke; not a production application.'
  }
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: 'gpt-5-mini'
  tags: tags
  sku: { name: 'DataZoneStandard', capacity: 100 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-5-mini', version: '2025-08-07' }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [project]
}

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: '${prefix}-search'
  location: location
  tags: tags
  sku: { name: 'basic' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'Default'
    disableLocalAuth: true
    publicNetworkAccess: 'enabled'
    semanticSearch: 'free'
  }
}

// The MCAPS tag also skips local-auth policies; retain these controls explicitly.
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stagentopslab${suffix}'
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
}

resource locks 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: 'release-locks'
  properties: { publicAccess: 'None' }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'cragentopslab${suffix}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource mcpIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-mcp-id'
  location: location
  tags: tags
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, mcpIdentity.id, '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: mcpIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

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

resource cae 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${prefix}-cae'
  location: location
  tags: tags
  properties: {
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

output accountId string = account.id
output projectId string = project.id
output projectPrincipalId string = project.identity.principalId
output searchId string = search.id
output storageId string = storage.id
output locksId string = locks.id
output registryServer string = registry.properties.loginServer
output registryId string = registry.id
output storageName string = storage.name
output mcpIdentityId string = mcpIdentity.id
output workspaceName string = logs.name
output caeId string = cae.id
