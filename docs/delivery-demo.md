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
object-ID allowlist. Successful tool responses include a server-generated trace
ID and a digest of the authenticated principal (never the token or object ID).
Matching that digest against the expected deployed caller remains a live
acceptance requirement. Release-local connections bind to
`/mcp/releases/<release-sha256>`; both their connection target and runtime tool URL
use that exact path. Tool evidence and structured completion logs carry this
server-observed release binding. The grader rejects a different release digest.
Bare `/mcp` remains available for transport diagnostics, but cannot supply
release-bound evidence. These records are neither signed export attestations
nor substitutes for native serving/session verification.
Configure the resource application to issue v2 tokens:
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
never rebuild during promotion. `prepare` verifies that the requested source
commit is the executing checkout's HEAD and that tracked and untracked source
are clean before acquiring the source or producing a release. This is local
source verification, not signed provenance or source-to-image attestation;
those remain missing.

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

`delivery_evaluation` rejects absent/failed calls, undeclared runtime capabilities, wrong fixture identity,
unreturned citations, missing token usage, route drift and exceeded limits.
Its five-check **structural score is not semantic answer quality**. Keyword
presence cannot establish that an announcement is true. Authenticated semantic
and safety evaluation, server-confirmed executed version, freshness, actual
price provenance and release-correlated traces are still missing. Consequently
the rubric never sets `full_gate_passed=true`, including for an 80% structural
score or caller-supplied zero safety values. Missing safety is never inferred
from a completed model response.

## Native controller and memory primitives

`delivery_native.NativeRuntime` implements native pinned-selector snapshots,
regular candidate reconciliation, version-reference requests, explicit Hosted
version-bound session activation and owned-session drain. Native identity must
be active and the agent enabled. Each mutating SDK call checks the writer lease.
The controller saves rollback intent **before** changing the selector, so failed
consumer verification or an uncertain response does not discard the previous
version. A failed reevaluation invalidates an earlier passing record.

`NativeDelivery` keeps dev, test and labprod records in **one shared coordination
journal**, not three independent locks. Test requires the identical digest's dev
promotion receipt and a fresh upstream native-serving read-back; labprod requires
the same from test. Repeated successful promotion is idempotent. Rollback retains
separate previous/current dependency and state fingerprints, rejects drift and
unrelated serving versions, and restores a retained previous promotion receipt
when available. These checks coordinate participating writers; they are not a
service-side compare-and-swap guarantee against portal or administrator changes.

These are library primitives with mocked-service contract coverage, **not a
wired live operator**. Integration must supply authenticated context inspection,
grading, upstream observation, and an actual consumer request through the
serving endpoint **without a version override**. Do not substitute an
exact-version candidate request for that consumer check. A reviewed baseline
must already exist and be explicitly pinned; bootstrap of a new agent is
immediately serving and is not presented as isolated candidate creation.

The harness disables all default filesystem, shell, web and subagent tools using
the current SDK's `microsoft_copilot_toolset_preview` settings block. Only the two
declared MCP integrations remain. A harness request uses an agent-specific
endpoint and a fresh conversation. Its `agent_reference` field is only a
capability probe: even an echoed matching reference cannot authorize promotion
until independent native candidate-selection evidence is established. The
controller records this as an explicit blocking condition.

`delivery_memory.NativeMemory` implements create-if-absent policy read-back,
fixed synthetic preference extraction, scoped recall/enumeration, confirmed scope
deletion and non-mutating migration planning. Store TTL is 86,400 seconds;
procedural and chat-summary extraction are disabled. Scope comes from an
authenticated, allowlisted caller, never model/user text. Prompt tool binding
uses `{{$userId}}`; its equivalence to the caller scope still needs live
verification. Hosted uses direct APIs; no trusted Hosted caller forwarding or
automatic runtime memory wiring is claimed.

Extraction sends explicit `type: message`, preserves the raw service completion
status/usage rather than the SDK's synthesized zero-usage fallback, and waits at
most five minutes. `MemoryDelivery` durably journals the start and native
update ID before waiting; it does not deserialize opaque continuation tokens.
A timeout does **not** cancel the remote update. The coordinator blocks another
extraction or deletion until an authenticated read of that operation reports
a terminal outcome. Reconciliation uses the same `api-version=v1` status route
as the pinned SDK, checks the returned update ID, and never replays extraction.
The real SDK authentication/URL pipeline and redirect refusal are exercised
offline at the HTTP boundary.

A missing update ID, superseded operation, or uncertain deletion remains blocked
for explicit reconciliation rather than guessing or retrying. These controls
cover participating writers only; quiescence of automatic runtime memory writes
and Hosted caller forwarding remain unverified.

Nonempty memory migration is explicitly blocked: native `create_memory` exposes
no original timestamp/expiry parameter, so replay could extend retention or
resurrect expired state. An empty-scope plan is not a completed migration. Do not
claim lossless memory migration/rollback, TTL-expiry observation, or harness
memory support from these contract tests.

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
| Native exact-version cutover and rollback | Controller contract-tested; not live | Controller contract-tested; not live | Controller refuses unverified candidate promotion |
| Before/during/after runtime identity | SDK boundary checks; not live | SDK boundary checks; not live | SDK boundary checks; not live |
| Fresh session and old-session behavior | Fresh conversation; not live | Version binding/activation/drain contract-tested | Fresh conversation/endpoint contract-tested; selection unverified |
| Native scoped memory/migration/rollback | Native API primitives; migration blocked | Native API primitives; caller wiring/migration blocked | Unsupported; no substitute |

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
- [Hosted session version binding](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-sessions?pivots=python)
- [Harness built-in capabilities and defaults](https://learn.microsoft.com/azure/foundry/agents/how-to/use-tools-skills-copilot-harness?pivots=sdk)
