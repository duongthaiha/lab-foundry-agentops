targetScope = 'resourceGroup'

param location string = 'swedencentral'
param registryName string = 'cragentops${uniqueString(resourceGroup().id)}'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  tags: { workload: 'agentops-lab', environment: 'shared' }
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

output registryId string = registry.id
output registryEndpoint string = registry.properties.loginServer
