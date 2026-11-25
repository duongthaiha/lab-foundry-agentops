# Foundry AgentOps lab

**Current implementation: local release-control simulation. Not a deployed
Foundry lab, and not evidence that Azure recommendations have been validated.**

The Python CLI builds immutable per-agent bundles and simulates dev -> test ->
labprod promotion for ordinary Prompt, Hosted, and Microsoft Copilot harness
tracks. It checks exact-candidate evaluation, approval, serving generations,
composite rollback, component retention, and synthetic state reconciliation.
All data is fictional Contoso data.

## Run locally

Python 3.11+; no third-party packages or cloud credentials required.
Run from this worktree in PowerShell:

```powershell
python -W error::ResourceWarning -m unittest discover -s tests -v
python -m agentops --mode simulated demo --output .lab\demo --source-revision (git rev-parse HEAD)
```

The demo persists bundles, binding/content/state records, fabricated evaluations,
attempt history, and `report.json` under its output directory. It refuses to
overwrite an existing demo. Use a new named output directory for another run.
Every result is labelled `simulated`; the metrics are fixture values, not model
measurements. Hosted image references are synthetic and have not been built.

`--mode live` fails before creating state. No Foundry deployment, runtime API
adapter, Entra/OIDC setup, or real serving endpoint exists here. The Foundry
dependency setup completed after explicit renewed approval. After the user made
the repository public, required-reviewer environments were configured. Live
delivery still needs reviewed deployment code on `main`, scoped OIDC, a complete
cost envelope and verified runtime integrations. The platform workflow is
disabled by default; no live agents or billable infrastructure have been deployed.

The public configuration example is in `environments/lab.example.json`: $500 USD/month,
Sweden Central, the exact `foudnry-agentops-lab` base name, and `@duongthaiha`
for both ownership roles. Keep actual tenant/subscription values and cloud
evidence in ignored `.lab/` files, not published source. Generated examples use the approved 80% quality
threshold, while all other fixture thresholds and measurements remain synthetic.
`infra/budget.bicep` defines a lab-resource-group-filtered budget alert, **not a
spending cutoff**. See the live-gates document for its observed deployment status.

## Read next

- [Runbook and recovery](docs/runbook.md)
- [Operating model and contracts](docs/operating-model.md)
- [Capability and reuse boundaries](docs/capabilities-and-reuse.md)
- [Cost, permissions, and teardown gates](docs/live-gates.md)
- [Backlog coverage and recommendation findings](docs/findings.md)

The local-only GitHub Actions definition runs tests and the synthetic demo; it
does not provision resources or grant permissions. Its remote execution is
unverified until the workflow is actually run.