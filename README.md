# Foundry AgentOps lab

**Implemented: protected ordinary-Prompt dev -> test -> labprod promotion and
retained-release rollback**, alongside the simulator and verified dev-only CI
smoke. [The native pipeline runbook](docs/native-pipeline.md) covers immutable
packaging, environment identities/approvals, target evaluation, native serving
verification and rollback. Full multi-environment execution has **not** yet been
validated against Azure. The dev infrastructure was restored after the earlier
teardown; no automatic teardown is scheduled.

The Python CLI builds immutable per-agent bundles and simulates dev -> test ->
labprod promotion for ordinary Prompt, Hosted, and Microsoft Copilot harness
tracks. It checks exact-candidate evaluation, approval, serving generations,
composite rollback, component retention, and synthetic state reconciliation.
Simulator data is fictional Contoso data. The new delivery path uses a public
Microsoft PDF and a clearly labeled fictional environment-status tool.

## Run locally

Python 3.11+; the simulator needs no third-party packages or cloud credentials.
The complete test suite and new adapters use an isolated environment:
Run from this worktree in PowerShell:

```powershell
python -m venv .lab\.venv
.\.lab\.venv\Scripts\python.exe -m pip install -r requirements-live.txt
.\.lab\.venv\Scripts\python.exe -W error::ResourceWarning -m unittest discover -s tests -v
python -m agentops --mode simulated demo --output .lab\demo --source-revision (git rev-parse HEAD)
```

The demo persists bundles, binding/content/state records, fabricated evaluations,
attempt history, and `report.json` under its output directory. It refuses to
overwrite an existing demo. Use a new named output directory for another run.
Every result is labelled `simulated`; the metrics are fixture values, not model
measurements. Hosted image references are synthetic and have not been built.

`--mode live` on the simulator fails before creating state. The new
`agentops.delivery_pipeline` entrypoint implements the protected ordinary-Prompt
lifecycle. The generic three-runtime delivery path remains gated; start with the
[three-track operator walkthrough and remaining gates](docs/delivery-demo.md).
`python -m agentops.delivery prepare`, `readiness`, and `matrix` are usable;
`probe` is deliberately blocked pending complete preflight and authorization.
Live native-serving/rollback evidence and memory acceptance remain unfulfilled;
do not confuse the new service-fixture coverage with a live deployment.
The separate [dev-only unattended prompt smoke](docs/dev-smoke.md) now implements
an expiring, main-only deploy/graded-smoke workflow without requiring a reviewer
per run. It is currently disabled; another run requires verifying the restored
dev infrastructure/identity and a fresh reviewed cost policy/binding;
it never authorizes promotion or opens test/production. The native pipeline has
separate policies and requires restored environment reviewers.
Reviewed platform code is on `main`; secretless OIDC bootstrap and four lab
groups exist. The retained CI/MCP apps,
resource-group tag and private evidence survive; the dev data plane is restored.
Use current outputs rather than the old managed identity or MCP hostname.

**Temporary dry-run posture:** the user deferred GitHub environment reviewer
requirements. The real platform workflow is disabled and
`LIVE_PLATFORM_ENABLED=false`; main-only restrictions, disabled admin bypass and
scoped identity grants remain unchanged. Restore and verify reviewers before
general live delivery, following [the restoration checklist](docs/live-gates.md#temporary-reviewer-deferral).
The narrowly scoped dev smoke exception above has its own authorization policy.
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

- [Native dev/test/prod promotion and retained rollback](docs/native-pipeline.md)
- [Manual experiment: recovery, one run, Playground, and pause without teardown](docs/manual-experiment.md)
- [Runbook and recovery](docs/runbook.md)
- [Operating model and contracts](docs/operating-model.md)
- [Capability and reuse boundaries](docs/capabilities-and-reuse.md)
- [Cost, permissions, and teardown gates](docs/live-gates.md)
- [Backlog coverage and recommendation findings](docs/findings.md)

Local-control CI has passed on Ubuntu/Windows and Python 3.11/3.13.
The separate rehearsal uploads synthetic bundles, reports and state for review;
its placeholder approvals never count as live authorization.