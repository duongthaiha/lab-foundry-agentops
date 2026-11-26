targetScope = 'subscription'

@description('Lab-owned budget name. Never reuse a pre-existing subscription budget.')
param budgetName string = 'foudnry-agentops-lab-monthly'

@description('Monthly amount in the subscription billing currency, verified as USD for this lab.')
@minValue(1)
@maxValue(500)
param amount int = 500

@description('First day of the current month in YYYY-MM-DD format.')
param startDate string

@description('Exact lab resource group names. This filter excludes unrelated subscription spend.')
@minLength(1)
param resourceGroupNames array

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: budgetName
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: startDate
    }
    filter: {
      dimensions: {
        name: 'ResourceGroupName'
        operator: 'In'
        values: resourceGroupNames
      }
    }
    notifications: {
      actual50: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: []
        contactRoles: ['Owner']
      }
      actual80: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: []
        contactRoles: ['Owner']
      }
      actual100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: []
        contactRoles: ['Owner']
      }
    }
  }
}

output budgetId string = budget.id
