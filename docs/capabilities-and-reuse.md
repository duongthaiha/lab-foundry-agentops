# Capability and reuse decision record

**No agent runtime has been tested.** Dependency setup completed after explicit
renewed approval. Management-plane model/quota/policy checks succeeded and GitHub
required-reviewer environments are configured. See [live gates](live-gates.md).
Management-plane availability and documentation do not prove runtime behavior.

| Area | Prompt | Hosted | Microsoft Copilot harness |
|---|---|---|---|
| Versions, candidate isolation and serving update | Blocked live check | Blocked live check | Blocked live check |
| Artifact | Declarative bundle | Single OCI digest; build/runtime unverified | Declarative harness bundle |
| Tool/toolbox runtime authorization | Untested | Untested | Untested; built-in approval inventory required |
| Shared knowledge instance, citations and document ACLs | Untested | Untested | Untested |
| Memory | Proposed memory tool; unverified | Proposed direct APIs; unverified | Unsupported boundary; no replacement |
| Identity discovery and least privilege | Untested | Untested | Untested |
| Session/caller contract | Exact version unverified | Activation, new/existing sessions unverified | Agent endpoint/final status/fresh workspace unverified |
| Migration | Store reconciliation blocked | Store reconciliation blocked | Runtime change means separately named agent |

The regional management endpoint advertises `gpt-5-mini` `2025-08-07` and
`text-embedding-3-small` `1` in Sweden Central. Preserve `Microsoft.DefaultV2`
with enforced jailbreak
blocking; memory API `2025-11-15-preview` / `MemoryStores=V1Preview`;
knowledge API `2026-10-01`; harness `microsoft_copilot_preview` /
`MicrosoftCopilot=V1Preview`. None is a substitute for current capability,
quota, policy and network checks. Never weaken policy to make a deployment pass.

Current Microsoft Learn documentation retrieved 2026-11-25 lists Sweden Central
for [hosted agents](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents),
[Copilot harness](https://learn.microsoft.com/azure/foundry/agents/concepts/limits-quotas-regions#microsoft-copilot-harness-preview)
and [memory](https://learn.microsoft.com/azure/foundry/agents/concepts/what-is-memory#region-availability).
The harness limits explicitly say Foundry Memory is unsupported, invocations
require the agent endpoint and a conversation, and `previous_response_id` is
unsupported. These are documented capabilities, not observed subscription
entitlement or successful calls. Native memory write capture and the proposed
knowledge API still need verification.

## Sharing decision

Reuse definitions across environments, not running instances or learned records.
Within one environment, prefer a shared, owned knowledge-base version only if
all consumers' supported retrieval and authorization paths are verified.

| Pattern | Suitable condition | Important limitation |
|---|---|---|
| One knowledge base, multiple consumers | Same domain, access and retrieval contract | Shared blast radius/capacity/content changes; every runtime needs access evidence |
| Separate bases over shared sources/indexes | Different retrieval tuning with compatible source scope | Exact source/index sharing support and ACL propagation unverified |
| Isolated stacks | Different tenants/access/lifecycle/availability needs | More standing cost and ingestion/operations overhead |

Use side-by-side names for breaking tool/knowledge changes. Toolbox
`default_version` is mutable and cannot serve as an immutable consumer pin.
Consumer deployments resolve/read approved component bindings; they do not
mutate shared components. Retain versions needed for independent rollback.
Content snapshots are separate from configuration versions and may not be
restorable. Memory policy reuse never authorizes sharing records.

Knowledge is curated organizational content; memory is learned scoped context;
attachments are session inputs. One cannot silently replace another.

Research references supplied with the backlog (not fetched/validated here):

- [Foundry IQ concepts](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/what-is-foundry-iq)
- [Connect a knowledge base](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/foundry-iq-connect)

Live acceptance requires runtime/resource identity, permitted and denied users,
source-specific ACL enforcement, content readiness, independent adoption and
rollback, retention rejection, latency/cost observations, and separate content
refresh evidence. Missing identity forwarding blocks the associated sharing
claim; do not replace it with prompt filtering.
