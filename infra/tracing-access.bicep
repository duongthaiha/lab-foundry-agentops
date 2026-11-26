targetScope = 'resourceGroup'

// Operator-only grant that lets the Foundry project identity ingest traces into Application
// Insights with Entra auth. Kept out of environment.bicep because the platform workflow's
// resource-group Contributor identity must not write role assignments.

@description('Application Insights component created by monitoring.bicep.')
param applicationInsightsName string

@description('Object ID of the Foundry project system-assigned identity.')
param projectPrincipalId string

var monitoringMetricsPublisher = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '3913510d-42f4-4e42-8a64-420c390055eb'
)

resource insights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

resource publisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: insights
  name: guid(insights.id, projectPrincipalId, monitoringMetricsPublisher)
  properties: {
    roleDefinitionId: monitoringMetricsPublisher
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output roleAssignmentId string = publisher.id
