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

`--mode live` fails before creating state. No Foundry runtime adapter or serving
endpoint exists here. Reviewed platform code is on `main`; a nonbillable,
secretless OIDC bootstrap and four empty lab groups exist. No live agents or
billable infrastructure have been deployed.

**Temporary dry-run posture:** the user deferred GitHub environment reviewer
requirements. The real platform workflow is disabled and
`LIVE_PLATFORM_ENABLED=false`; main-only restrictions, disabled admin bypass and
scoped identity grants remain unchanged. Restore and verify reviewers before
any live use, following [the restoration checklist](docs/live-gates.md#temporary-reviewer-deferral).
The independent **Simulated approval rehearsal** workflow needs no manual
approval and has no Azure credentials, environment binding or OIDC permission.

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

Local-control CI has passed on Ubuntu/Windows and Python 3.11/3.13.
The separate rehearsal uploads synthetic bundles, reports and state for review;
its placeholder approvals never count as live authorization.