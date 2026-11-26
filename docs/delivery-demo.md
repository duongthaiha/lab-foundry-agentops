# Three-track delivery demo: implemented milestone and remaining gates

**This is not a completed live demo.** The new operator prepares real portable
intent and checks current controls. SDK adapters are implemented but not
Azure-validated. `probe` deliberately cannot execute, even if platform gates are
later restored: runtime, identity, cost, safety and operation-specific approval
preflight still require implementation and review. There is no new live workflow,
credential grant, approval submission or automatic provisioning.

## Run the usable milestone

Use a dedicated virtual environment; the pinned live SDK generation can conflict
with older globally installed Agent Framework packages.

```powershell
python -m venv .lab\.venv
.\.lab\.venv\Scripts\python.exe -m pip install -r requirements-live.txt
.\.lab\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.lab\.venv\Scripts\python.exe -m agentops.delivery prepare --output .lab\delivery --source-revision (git rev-parse HEAD) --runtime prompt
.\.lab\.venv\Scripts\python.exe -m agentops.delivery prepare --output .lab\delivery --source-revision (git rev-parse HEAD) --runtime harness
.\.lab\.venv\Scripts\python.exe -m agentops.delivery readiness
.\.lab\.venv\Scripts\python.exe -m agentops.delivery matrix
```

Preparation downloads the first-party [Microsoft Copilot Studio FAQ](https://adoption.microsoft.com/files/copilot-studio/Microsoft-Copilot-Studio_FAQ.pdf)
only into ignored `.lab`. Its observed hash, page count and presenter-topic
locator are in [public-source.json](public-source.json). A hash establishes bytes,
not permission to redistribute them. Do not commit the PDF, extracted passages,
raw model responses or private service telemetry. Source manifests contain URLs,
hashes and locators only. A future ingestion must check the expected source hash.

The presenter asks: **What did Microsoft announce at Ignite 2024 about agents in
Power Pages, and is that feature enabled in this lab environment?** Every runtime
must independently retrieve the KB passage and call the separate read-only
`get_lab_feature_status(feature_id="power-pages-agents")` MCP tool.

The tool backend is intentionally fictional: dev returns enabled/`dev-1`, test
returns disabled/`test-2`, and labprod returns disabled/`labprod-1`. These are not
Microsoft product availability statements. The HTTP transport is real JSON-RPC;
unit tests run actual localhost servers, not Azure agents. Production handler
authentication requires signed Entra v2 tokens, exact tenant/audience and caller
object-ID allowlist. Configure the resource application to issue v2 tokens:
the token audience is the application GUID, while the connection audience is
its `api://` URI. Never expose an unauthenticated deployment or use test tokens.

For Hosted, `Dockerfile.hosted` runs the official Responses 2.0 adapter and
preserves upstream MCP output items and usage, rather than returning an echo or
stripping the trace into text. `Dockerfile.mcp` packages the distinct tool backend.
Local image builds were attempted but blocked by a TLS handshake failure fetching
PyPI wheels inside Docker; certificate verification was not disabled. CI builds
both containers and checks non-root imports without network/runtime credentials.
No image has been pushed or deployed. Hosted preparation requires a
real ACR digest via `--image`; tags are rejected. A syntactically valid digest
does not prove image existence and is not deployment evidence.

## Release, components and evidence boundaries

`agentops.delivery_contracts` creates canonical digest-named release files.
Environment endpoints, tenant/resource identifiers, state and prices are separate
private bindings. Reuse identical release bytes across dev, test and labprod;
never rebuild during promotion. At present the source commit is caller-supplied;
signed provenance and source-to-image attestation are still missing.

`delivery_knowledge` defines a hash-named Search index, search-index knowledge
source and model-free IQ KB. It compares desired properties and exact page
contents, waits boundedly for newly indexed pages, and rejects drift rather than
silently overwriting existing content. Partial ingestion requires operator
reconciliation; it does not erase or replace a retained KB.

`delivery_azure` provides credential-scoped HTTP without bearer redirects,
read-back comparison, and an environment Blob lease/CAS journal. The journal is
not a serving pointer and does not control Foundry traffic. Lease behavior has
not been verified against Azure or competing remote writers.

`delivery` binds TWO explicitly allowlisted RemoteTool connections to each
track: the IQ MCP endpoint and the distinct tool endpoint. These bindings use
project managed identity. That is not proof of runtime/end-user identity
forwarding, cross-environment isolation, or least-privilege access. Native
release-local toolbox packaging and shared-default experiments are not yet
implemented.

`delivery_evaluation` rejects absent/failed calls, wrong fixture identity,
unreturned citations, missing token usage, route drift and exceeded limits.
Its five-check **structural score is not semantic answer quality**. Keyword
presence cannot establish that an announcement is true. Authenticated semantic
and safety evaluation, server-confirmed executed version, freshness, actual
price provenance and release-correlated traces are still missing. Consequently
the rubric never sets `full_gate_passed=true`, including for an 80% structural
score or caller-supplied zero safety values. Missing safety is never inferred
from a completed model response.

## Required native serving behavior: not substituted

The current [native selector](https://learn.microsoft.com/azure/foundry/agents/how-to/configure-agent)
supports one `FixedRatio` rule at 100%. Default routing follows latest. Preserve
and pin the previous serving version **before** creating a regular candidate.
[Draft versions](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent)
cannot be traffic targets; converting one creates a different version, which must
be evaluated independently. A separate probe agent's endpoint is callable and
does not prove non-serving creation on the actual serving agent.

| Required proof | Prompt | Hosted | Copilot harness |
|---|---|---|---|
| Exact candidate while previous version serves | Version-reference request needs live verification | Version-bound session and activation need verification | No verified request-specific candidate override on agent endpoint |
| Native exact-version cutover and rollback | Unfulfilled | Unfulfilled | Unfulfilled |
| Before/during/after runtime identity | Unfulfilled | Unfulfilled | Unfulfilled |
| Fresh session and old-session behavior | Unfulfilled | Activation/drain unfulfilled | Fresh conversation/endpoint integration unfulfilled |
| Native scoped memory/migration/rollback | Unfulfilled | Unfulfilled | Unsupported; no substitute |

Agent-specific endpoints and fresh conversations are preserved for the harness;
no Hosted session API or `previous_response_id` fallback is used. The native
candidate issue remains an acceptance blocker, not permission to substitute an
operator Blob pointer or legacy Agent Applications.

## Planned nine-cell execution and stopping rules

For each of **Prompt, Hosted, Harness x dev, test, labprod**, retain the same
release digest, KB hash/page, typed tool request/result, actual caller identity,
bindings, exact runtime version, gate decision and timestamp. All nine cells are
currently **not run**. Preparation and HTTP unit tests do not count as any cell.

Once the missing adapters and authorization are reviewed, each cell must show:
retained previous serving snapshot; isolated regular candidate; both dependency
calls; a deliberately rejected candidate; independently measured passing quality
at least 80%, zero unsafe responses, latency at most 60 seconds and cost at most
$0.05 per case; native cutover; fresh-session serving verification; and rollback
to the retained composite release with before/during/after evidence. Expire
evidence after one hour. Stop on any unknown charge, unsupported API, missing
identity, lease loss, content drift or missing evidence. Do not weaken policy.

## Reset, teardown and live authorization

There is no destructive operator command. Local preparation reuses only the
same cached PDF bytes and canonical releases; use a distinct named output for a
new run. Keep the legacy simulator's reset rules separate.

Before any future live creation, present an exact inventory/cost/permission
plan covering the existing three environment groups, shared registry, Search,
Foundry, storage, tool hosting and required runtime data-plane roles. Refresh
the standing-cost estimate including MCP hosting and model/tool/evaluation
usage against the **$500 USD/month** ceiling. The existing Azure budget is an
alert, not a spending cutoff. Obtain operation-specific authorization; broad
demo intent does not override the previously declined platform run.

Teardown must first stop dispatch and verify no active writers/sessions, then
inventory exact owned IDs and retained serving/rollback consumers. Obtain
approval for deleting only obsolete release-local objects/indices/scopes or
the explicitly enumerated lab deployment. Preserve unrelated resources,
bootstrap identities, budget and retained evidence unless separately authorized.
Never issue a blanket subscription or wildcard deletion.

## Implementation references

- [IQ connection and identity contract](https://learn.microsoft.com/azure/foundry/agents/how-to/foundry-iq-connect)
- [Knowledge base definition](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-create-knowledge-base)
- [Search-index knowledge source](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-search-index)
- [Official hosted protocol adapter](https://learn.microsoft.com/azure/foundry/agents/how-to/add-protocol-adapter)
- [Current live controls and restoration](live-gates.md)
