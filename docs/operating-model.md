# Operating model and current boundary

This worktree implements a **local simulation of release controls**, not a
deployed Foundry lab. All source data is fictional Contoso data. The approved
backlog still requires live evidence for Prompt, Hosted, and Microsoft Copilot
harness agents in dev, test, and labprod.

| Unit | Identity and ownership |
|---|---|
| Agent release | Independent agent/runtime version, source commit, canonical bundle SHA-256; development owns behavior |
| Component release | Contract digest, version, compatibility, owner; component owner controls mutation |
| Environment binding | Separate digest and resource references; platform owns scope and identity |
| Content | Independent snapshot/watermark, affected consumers; knowledge owner governs refresh |
| Learned state | Separate operation journal, scope, retention and checkpoints; memory/data owner governs mutation |
| Deployment/candidate | Environment-local ID; creation must not change serving |
| Serving | Exact approved candidate and generation; approver authorizes transition |
| Evidence | Attempt ID, timestamps, type, context and result; no implicit equivalence between simulated and observed |

The AI Engineer owns instructions, fixtures, evaluation policy and agent delivery
through labprod. The Platform Engineer owns the landing zone, networking, policy,
identity and provisioning. The user assigned **both roles to `@duongthaiha`**;
`.github/CODEOWNERS` records this choice. It is not separation of duties.
Component/knowledge/memory ownership follows the applicable behavior/platform
boundary; changes crossing it require both role responsibilities to be reviewed.

The private repository's plan initially rejected required-reviewer environment
protection (HTTP 422). After the user manually made it public, `dev`, `test`,
`labprod` and `platform` were configured with required reviewer `@duongthaiha`,
admin bypass disabled and only branch `main` allowed. Self-review is allowed
because the user explicitly selected a single owner for all lab roles.
CODEOWNERS alone does not enforce deployment approvals: deployment jobs must
actually reference these protected environments before OIDC is enabled.
The user approved an 80% quality floor, not an 80% safety or aggregate score.
Live safety/latency/cost/retention limits are recorded in the
[live gates](live-gates.md); their measured enforcement is still outstanding.

## Invariants

- Promote the same bundle bytes; never copy environment IDs or learned memory
  into portable inputs. A digest proves integrity, not signer authenticity.
- Evaluate and approve each environment-local candidate against its complete
  release, binding, dataset, policy, baseline, content and state context.
- Approval for another candidate/runtime, a missing metric, or failed readiness
  cannot authorize serving. Candidate creation is not approval.
- Serialize consumer and component writers across protected reads, mutation,
  verification and evidence. Local filesystem locks are not distributed locks.
- Keep previous dependencies while any serving or rollback consumer references
  them. Configuration rollback cannot roll back mutable content or user state.
- A trusted caller determines memory scope. Opaque names and model instructions
  are not authorization. Test fixtures do not prove a service enforces scope.
- No harness memory substitute: conversation history, files and workspaces do
  not implement Foundry Memory.

## Change review

Prompt-only changes need behavior/evaluation review; tool/schema, knowledge,
memory-policy and infrastructure changes also need their accountable owner's
review and affected-consumer evaluation. Live OIDC subjects must be bound to
this repository and protected environment. Runtime, component delivery and
serving permissions are separate; unavailable protections remain blockers.

No credentials, live records or sensitive prompts belong in code or artifacts.
Portable validation rejects known secret/environment fields, but it is not a
general secret scanner. Review every selected asset before building.
