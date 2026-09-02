# RevivePay release validation record template

This template defines the evidence fields and the required limitation text for a
generated release record (Requirements 17.1-17.7). `scripts/release_validate.py`
(task 11.2) fills it in from executed checks. `scripts/release_inputs.py` already
validates the input half: source tracking, baseline evidence, reviewed
replacement coverage, and the Cleanup Inventory.

A record is `ready` if and only if every mandatory check passes. A single
mandatory failure produces `not_ready` and names the failed check without
exposing secret material.

## Required evidence fields

| Field | Requirement | Content |
| --- | --- | --- |
| `repository_revision` | 17.1 | Git revision the validation ran against. |
| `validated_at` | 17.1 | Validation timestamp. |
| `environment_profile` | 17.1 | `local`, `demo`, `test`, `staging`, or `production`. |
| `schema_revision` | 17.1 | Applied database schema revision. |
| `source_tracking` | 17.1, 17.7 | Source Tracking Guard result, including any untracked or effectively ignored required runtime source. |
| `cleanup_inventory` | 17.1 | Cleanup Inventory disposition summary and any evidence gaps. |
| `backend_tests` | 17.2 | Command, passing count, failures, skips, duration, and environment. |
| `baseline_comparison` | 17.2 | Approved baseline count, observed count, and any reviewed replacement-coverage justification. |
| `frontend_checks` | 17.3 | Typecheck and production build commands, exit status, and environment. |
| `targeted_checks` | 17.4 | Migration, database-integrity, clock concurrency, job/outbox lifecycle, authorization, gateway availability, executor boundary, Copilot fallback, assurance, Judge Demo, accessibility, and responsive results. |
| `checks` | 17.5, 17.6 | Every check with its name, mandatory flag, status, and safe failure reason. |
| `status` | 17.5, 17.6 | `ready` or `not_ready`. |
| `caveats` | 17.6 | The required limitations below, retained even in a ready record. |

## Required limitations

A ready record retains all three statements verbatim. They are not optional
commentary: without them the record would read as a claim about real recovery
performance.

- Synthetic deterministic simulation results do not represent real payment recovery performance.
- Razorpay Sandbox verification observes provider test-environment state and does not move live money.
- Read-only synthetic projections and baseline comparisons are not actual recovered revenue.

`scripts/release_evidence.REQUIRED_RELEASE_CAVEATS` holds the same three strings,
and a test asserts this document and that constant agree.

## Blocking conditions

A release record must not be marked ready when any of the following holds
(Requirement 17.7):

- required runtime source remains untracked or effectively ignored;
- the database schema revision is unsupported, missing, or ahead of the application;
- production or staging security configuration is invalid;
- an unapproved real provider executor is enabled;
- the passing backend test count is below the approved baseline without a
  complete reviewed replacement-coverage record;
- the Cleanup Inventory contains an invalid record, a duplicate candidate, or a
  proposed removal the recorded evidence does not support.

## Release input commands

These commands are read-only. None starts a dev server, none makes an outbound
provider or Copilot request, and none is an Operational Mutation.

```powershell
# Required runtime source tracking.
.\.venv\Scripts\python.exe -m scripts.source_tracking_guard

# Reviewed Cleanup Inventory.
.\.venv\Scripts\python.exe -m scripts.cleanup_inventory

# Combined release inputs, including the baseline test-count gate.
.\.venv\Scripts\python.exe -m scripts.release_inputs --passing-tests <observed count>
```

Each command exits non-zero when its evidence does not pass, so a release
pipeline can treat them as gates.
