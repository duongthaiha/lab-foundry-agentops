targetScope = 'resourceGroup'

@allowed(['swedencentral'])
param location string = 'swedencentral'

@description('Reviewed ACR image reference pinned by sha256 digest, not a tag.')
param image string

param tenantId string
param audience string

@description('Current Foundry PROJECT managed-identity object ID, not the CI service principal.')
param allowedCaller string

var prefix = 'foudnry-agentops-lab-dev'

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: '${prefix}-mcp-id'
}

resource cae 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: '${prefix}-cae'
}

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: '${prefix}-mcp'
  location: location
  tags: {
    workload: 'agentops-lab'
    environment: 'dev'
    dataClassification: 'synthetic'
    pilot: 'dev-smoke-v1'
    SecurityControl: 'Ignore'
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uami.id}': {} }
  }
  properties: {
    managedEnvironmentId: cae.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8080
        transport: 'http'
        allowInsecure: false
      }
      registries: [{ server: 'cragentopslabdev.azurecr.io', identity: uami.id }]
    }
    template: {
      containers: [
        {
          name: 'lab-tools'
          image: image
          args: ['--environment', 'dev']
          env: [
            { name: 'AZURE_TENANT_ID', value: tenantId }
            { name: 'MCP_AUDIENCE', value: audience }
            { name: 'MCP_ALLOWED_CALLER_IDS', value: allowedCaller }
          ]
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

output id string = app.id
output fqdn string = app.properties.configuration.ingress.fqdn
