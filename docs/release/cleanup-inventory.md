# RevivePay Cleanup Inventory

Every cleanup candidate passes through this reviewed record before any source is
removed. The record is the input to task 10.1; validating it removes nothing.

The rule is fail-closed: a candidate is eligible for removal review only when
every required reference search was performed and found nothing, the candidate
carries no public HTTP contract and no Protected Capability relationship, and no
evidence gap, unreadable search, or contradiction remains. Any other state
retains the candidate with the reason recorded (Requirements 2.1-2.4, 2.6, 2.7).

Two rules deserve emphasis because they are the ones most easily rationalized
away:

- A capability is never removed because the UI does not navigate to it. A record
  whose only removal justification is `NAVIGATION_NOT_EXPOSED` is retained.
- A dependency is removed only after runtime, build, migration, and test paths
  have each been checked and found clear.

## Current inventory

No cleanup candidate has been reviewed yet. The reviewed set below is
intentionally empty: the remediation tracks required runtime source (tasks 1.1
and 1.3) and establishes protected-contract coverage before any removal is
proposed.

| Candidate | Category | Disposition | Reviewer |
| --- | --- | --- | --- |
| _none reviewed_ | — | — | — |

## Record fields

| Field | Requirement | Meaning |
| --- | --- | --- |
| `candidate` | 2.1 | Repository path or fully qualified symbol under review. |
| `category` | 2.1 | `FILE`, `SYMBOL`, `ROUTE`, `DEPENDENCY`, `ASSET`, or `CONFIGURATION_ENTRY`. |
| `references_searched` | 2.1, 2.2 | One entry per reference class, each with the search performed and its result. |
| `public_contract_status` | 2.3 | `NONE`, `PUBLIC_HTTP_CONTRACT`, or `UNKNOWN`. `UNKNOWN` retains the candidate. |
| `protected_capability_status` | 2.3, 2.6 | `NONE`, `PROTECTED_CAPABILITY_DEPENDENCY`, or `UNKNOWN`. `UNKNOWN` retains the candidate. |
| `test_coverage` | 2.1, 2.5 | Test identities that exercise the candidate's behavior. |
| `proposed_disposition` | 2.1 | The reviewer's proposal, `RETAINED` or `ELIGIBLE_FOR_REMOVAL_REVIEW`. Validation derives the real classification from the evidence and reports a conflict when the proposal is unsupported. |
| `reviewer`, `reviewed_at` | 2.1 | Who reviewed the evidence and when. Missing reviewer evidence retains the candidate. |
| `evidence_gaps` | 2.4 | Anything the reviewer could not establish. A non-empty list retains the candidate. |
| `dependency_path_scopes_checked` | 2.7 | Required for `DEPENDENCY`: `RUNTIME`, `BUILD`, `MIGRATION`, `TEST`. |
| `removal_justification` | 2.6 | Optional reasons. `NAVIGATION_NOT_EXPOSED` alone retains the candidate. |

## Required reference searches

Each of these reference classes must appear in `references_searched` with a
result of `FOUND`, `NONE_FOUND`, `UNREADABLE`, or `INCONCLUSIVE`. A missing
class counts as missing evidence, and `FOUND`, `UNREADABLE`, or `INCONCLUSIVE`
each retain the candidate.

| Reference class | What is searched |
| --- | --- |
| `RUNTIME_IMPORT` | Python or frontend import graph reachable from a supported entrypoint. |
| `HTTP_ROUTE` | Public API route registration and request handling. |
| `CONFIGURATION` | Settings keys, environment variables, container and compose configuration. |
| `MIGRATION` | Alembic revisions and model metadata a migration depends on. |
| `TEMPLATE` | Server-rendered or build-time templates. |
| `STATIC_ASSET` | Frontend static assets and public files. |
| `DOCUMENTATION_COMMAND` | Documented commands and runbook steps. |
| `TEST` | Supported backend and frontend tests. |
| `SUPPORTED_RUNTIME` | Any other supported runtime path: scripts, workers, seeds, demo flows. |

## Machine-readable inventory

`docs/release/cleanup-inventory.schema.json` is the companion schema, and
`scripts/cleanup_inventory.py` is the executable authority for the same
contract. The fenced block below is the reviewed record set.

<!-- revivepay:cleanup-inventory -->

```json
[]
```

Record shape, for reference when a candidate is proposed:

```text
{
  "candidate": "app/example/module.py",
  "category": "FILE",
  "references_searched": [
    { "reference_type": "RUNTIME_IMPORT", "query": "search performed", "result": "NONE_FOUND", "locations": [] }
  ],
  "public_contract_status": "NONE",
  "protected_capability_status": "NONE",
  "test_coverage": [],
  "removal_justification": ["NO_REFERENCE_FOUND"],
  "proposed_disposition": "ELIGIBLE_FOR_REMOVAL_REVIEW",
  "reviewer": "reviewer identity",
  "reviewed_at": "YYYY-MM-DD",
  "evidence_gaps": []
}
```

## Commands

```powershell
# Validate and classify the reviewed inventory.
.\.venv\Scripts\python.exe -m scripts.cleanup_inventory

# Validate the inventory together with source tracking and the baseline record.
.\.venv\Scripts\python.exe -m scripts.release_inputs --passing-tests 687
```

Both commands are read-only. Neither is an Operational Mutation, and neither
deletes source: removal happens only under task 10.1, from an inventory that
already validates clean.
