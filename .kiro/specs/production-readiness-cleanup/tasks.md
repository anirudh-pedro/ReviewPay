# Implementation Plan: Production Readiness Cleanup

## Overview

Implement the production-readiness remediation in dependency order: establish version-control and release evidence first; preserve existing contracts while adding environment and persistence safeguards; complete clock/job/outbox and external safety boundaries; execute the approved Judge Demo plan as a dependent workstream; then add assurance presentation, perform only evidence-approved cleanup, and generate the release evidence.

The implementation remains additive or behavior-preserving. The deterministic recovery workflow, Policy Engine, Expected Recovery Value calculation, Payment Simulator, Outcome Verifier, immutable audit system, Virtual Clock semantics, Razorpay Sandbox verification boundary, Command Center, Autopilot, Strategy Lab, and A–D scenarios remain authoritative. No task introduces a real provider executor, external Copilot provider, browser-side recovery calculation, or browser-side operational authority.

## Tasks

- [x] 1. Establish source-control evidence and release-input guards before any cleanup
  - [x] 1.1 Implement `scripts/source_tracking_guard.py` to discover required runtime inputs from Python startup/import/router paths, Alembic, supported scripts/tests, and frontend build inputs; emit stable non-secret JSON with discovery evidence, Git tracking state, and effective ignore-rule provenance.
    - Classify `app/models/**` as runtime source independently of the root `/models/` ignore pattern; fail for missing, unreadable, untracked, or effectively ignored required files.
    - _Requirements: 1.1–1.6, 15.1, 17.1, 17.5, 17.7_
  - [x] 1.2 Implement cleanup-inventory and release-evidence schemas/validators plus a non-mutating release-input report that consumes the Source Tracking Guard output, baseline evidence, and reviewed replacement-coverage records.
    - Add machine-readable validation for candidate category, searched references, public-contract/protected-capability status, coverage, disposition, reviewer evidence, and incomplete-evidence retention; do not delete source from this task.
    - _Requirements: 1.6–1.7, 2.1–2.4, 2.6–2.7, 16.2, 17.1–17.2, 17.5, 17.7_
  - [x] 1.3 Correct repository tracking for every Source Tracking Guard finding, including required `app/models/`, Razorpay integration, gateway route/schema, and their required test/build inputs; narrow only an ignore rule proven to exclude a required source.
    - Preserve root-level generated-model artifact ignores and retain a clean checkout that can run supported backend, frontend, migration, and test commands.
    - _Requirements: 1.1–1.5, 1.7, 17.1, 17.7_
  - [x]* 1.4 Write property-based tests for **Property 1: Runtime Source and Release Baseline Are Closed**, with at least 100 generated repository/import/ignore/test-count cases.
    - Verify discovery evidence, effective ignore-rule reporting, untracked/unreadable failures, and the below-595 replacement-coverage gate.
    - **Validates: Requirements 1.1–1.7, 15.1, 17.1–17.2, 17.5, 17.7**
  - [x]* 1.5 Write property-based tests for **Property 2: Cleanup Classification Fails Closed**, with at least 100 generated candidate/reference-evidence cases.
    - Verify runtime, HTTP, migration, config, documentation-command, test, and Protected Capability references retain a candidate; incomplete, conflicting, or unreadable evidence must also retain it.
    - **Validates: Requirements 2.1–2.4, 2.6–2.7**

- [ ] 2. Preserve contracts and implement environment-aware security/readiness configuration
  - [ ] 2.1 Extend `app/core/config.py`, `app/api/auth.py`, `app/main.py`, `app/api/routes/health.py`, and `app/db/init_db.py` with normalized `local`, `demo`, `test`, `staging`, and `production` profile policy.
    - Enforce startup failure for missing production/staging security configuration; retain documented local/demo/test authentication status without secrets; require scoped principals for Operational Mutations; gate reset to resettable profiles; retain safe error envelopes, CORS, request bounds, correlation IDs, and security headers.
    - Reject production/staging schema-creating bootstrap paths while retaining explicitly documented local/test bootstrap behavior.
    - _Requirements: 3.4–3.5, 7.7, 9.1–9.9, 10.2, 10.4, 14.11, 17.5, 17.7_
  - [x]* 2.2 Add protected-contract baseline regression fixtures for existing recovery decisions, policy outcomes, ERV values, simulator/outcome behavior, audit ordering, public response fields, and standard error-envelope semantics.
    - Snapshot unchanged seeded inputs, configuration, and Virtual Clock time without changing production behavior or public routes.
    - _Requirements: 3.1–3.5, 15.1–15.2_
  - [ ]* 2.3 Write property-based tests for **Property 3: Unchanged Deterministic Recovery Is Stable**, with at least 100 seeded-input combinations.
    - Compare decision, Policy Engine result, ERV, Payment Simulator result, Outcome Verifier result, and per-case audit sequence against preserved baseline fixtures.
    - **Validates: Requirements 3.1, 3.3, 15.2**

- [ ] 3. Add ordered migrations, integrity constraints, and schema readiness gates
  - [x] 3.1 Create migration `20260829_04_readiness_integrity` with preflight checks and forward-only database uniqueness, foreign-key, check/state, and immutable audit-sequence protections.
    - Support SQLite batch operations and PostgreSQL transactional DDL; reject invalid writes atomically and do not rewrite historical audit content.
    - _Requirements: 10.1, 10.5–10.8, 15.1, 17.4_
  - [ ] 3.2 Add `SimulationClock` and `ClockAdvanceEvent` models and migration `20260829_05_virtual_clock_state`, including one-time legacy JSON/default-clock seeding, scope uniqueness, versioning, and ordered append-only advance evidence.
    - Fail safely on malformed legacy clock input in staging/production; do not rewrite recovery/audit history.
    - _Requirements: 10.1, 10.3, 11.1–11.6, 17.4_
  - [ ] 3.3 Extend `BackgroundJob` and `OutboxEvent` models and create migration `20260829_06_job_outbox_lifecycle` for closed lifecycle, bounded retry/lease, idempotency, delivery, and inspectable result/failure fields.
    - Include deterministic legacy-state preflight/mapping and block upgrades for unknown or invalid legacy rows rather than guessing.
    - _Requirements: 10.1, 10.3, 10.5–10.8, 12.1–12.12, 17.4_
  - [ ] 3.4 Implement `app/db/schema_readiness.py` and wire safe revision compatibility checks into startup/readiness responses before staging/production accepts Operational Mutations.
    - Return only typed safe readiness states; do not expose connection strings, credentials, SQL, migrations internals, or exceptions.
    - _Requirements: 9.3, 9.9, 10.2–10.4, 13.6, 17.1, 17.4–17.5, 17.7_
  - [ ]* 3.5 Add migration, schema-readiness, and database-integrity tests for initialized and pre-remediation fixtures.
    - Verify forward upgrade, schema mismatch blocking, no staging/production `create_all`, FK/unique/check atomic rejection, and immutable increasing per-case audit ordering.
    - _Requirements: 10.1–10.9, 15.1, 17.4–17.5_

- [ ] 4. Replace runtime file-clock authority with transactional database Virtual Clock operations
  - [ ] 4.1 Evolve `app/core/clock.py` behind the existing `VirtualClock` interface and add `DatabaseVirtualClock`, `app/services/clock_service.py`, container wiring, and scoped read/advance API handlers.
    - Atomically apply only authorized nonnegative advances with profile-required concurrency tokens; return prior/current time, version, and an ordered event ID; keep simulation scheduling free of wall-clock time and retain JSON only as controlled migration/bootstrap compatibility input.
    - _Requirements: 3.1, 10.3, 11.1–11.6, 15.1, 17.4_
  - [ ]* 4.2 Write property-based and concurrent transactional tests for **Property 9: Clock Advances Are Linearizable**, with at least 100 generated accepted-request sets.
    - Verify sum/order equivalence, unique evidence records, stale-token/negative/malformed/unauthorized no-op rejection, and absence of wall-clock scheduling decisions.
    - **Validates: Requirements 10.3, 11.1–11.7, 15.1**

- [ ] 5. Complete durable job and transactional outbox lifecycles
  - [ ] 5.1 Implement closed Background Job transitions in `app/services/job_service.py` and complete persistence model behavior for idempotent submission, conditional claim, bounded lease/reclaim, retry, terminal failure, cancellation, and safe result/failure summaries.
    - Preserve correlation IDs and prevent terminal Recovery Cases from triggering recovery execution; do not bypass Policy Engine, Action Executor, or Outcome Verifier.
    - _Requirements: 10.5–10.8, 12.1–12.9, 12.12, 15.1_
  - [ ] 5.2 Add `app/services/outbox_service.py`, safe inspection handlers, and `scripts/worker.py` as an explicit bounded worker command.
    - Persist outbox records transactionally with their originating change, claim/deliver idempotently, record delivery results without modifying immutable audit events, and retain safe lifecycle evidence on failure.
    - _Requirements: 12.2, 12.4–12.12, 16.5, 16.8, 17.4_
  - [ ]* 5.3 Write property-based lifecycle tests for **Property 10: Job and Outbox Lifecycles Preserve Idempotency and Safety**, with at least 100 generated duplicate/claim/retry/lease/terminal-case transitions.
    - Verify one represented active/completed operation or delivered effect per idempotency identity, bounded transitions, immutable originating audit content, and no unauthorized recovery path.
    - **Validates: Requirements 10.5–10.8, 12.1–12.12**

- [ ] 6. Harden Sandbox, executor, Copilot, and security boundaries
  - [ ] 6.1 Add typed `GatewayAvailabilityResponse`, `GatewayAvailabilityService`, and the additive read-only Razorpay availability route while retaining existing server-side signature-first gateway verification.
    - Emit `AVAILABLE` only after a safe authenticated non-mutating capability check or successful existing verification; emit safe `UNAVAILABLE`/`INCONCLUSIVE` states without provider payloads, callback signatures, credentials, contacts, or instrument data.
    - _Requirements: 3.2, 6.1–6.9, 7.2, 9.8, 15.3–15.4_
  - [ ]* 6.2 Write property-based controlled-provider tests for **Property 5: Gateway Availability and Rejection Never Manufacture Facts**, with at least 100 configuration/provider-fixture cases.
    - Verify status classification, rejection rollback/no persistence, no verified claim from callbacks, safe response allowlists, and no outbound network dependency.
    - **Validates: Requirements 3.2, 6.1–6.9, 15.3–15.4**
  - [ ] 6.3 Constrain `app/core/config.py`, `app/core/container.py`, and `app/integrations/action_executor.py` to simulator-only resolution and fail closed for provider executor configuration or registry attempts.
    - Preserve Payment Simulator defaults in every unconfigured profile; do not treat Razorpay verification as execution; expose only a safe block reason when safety validation is absent.
    - _Requirements: 7.1–7.7, 9.1, 9.8–9.9, 15.5, 17.7_
  - [ ]* 6.4 Write property-based tests for **Property 6: Executor Configuration Fails Closed to the Simulator**, with at least 100 profile/configuration/authorization combinations.
    - Verify no provider invocation or recovered claim occurs without an independently identified Verified Outcome.
    - **Validates: Requirements 7.1–7.7, 15.5, 17.7**
  - [ ] 6.5 Add versioned Copilot schemas plus a disabled adapter, context redactor, bound/schema validator, deterministic fallback selector, and allowlisted audit projection.
    - Do not add an external model client or a Copilot route; reject unallowlisted/unsafe/oversized/late/contradictory responses and preserve all deterministic recovery authority.
    - _Requirements: 8.1–8.8, 9.8, 15.6_
  - [ ]* 6.6 Write property-based tests for **Property 7: Copilot Is Redacted, Bounded, and Non-Authoritative**, with at least 100 generated context/response/boundary cases.
    - Verify deterministic fallback, safe reason/projection fields, no secret/PII propagation, and no changes to recovery, policy, payment, clock, audit, or outcome state.
    - **Validates: Requirements 8.1–8.8, 15.6**
  - [ ]* 6.7 Write property-based security/readiness tests for **Property 8: Environment Security and Release Gates Fail Closed**, with at least 100 profile/configuration/principal/request combinations.
    - Verify authentication, scope, CORS/origin, request-bound, schema-readiness, and startup failures return safe envelopes without credentials, secrets, stack traces, or configuration disclosure.
    - **Validates: Requirements 9.1, 9.3–9.9, 10.2, 10.4, 17.5, 17.7**

- [ ] 7. Execute the approved Judge Demo implementation plan as an external dependent workstream
  - [ ] 7.1 Complete every implementation and validation wave in [`../judge-demo-experience/tasks.md`](../judge-demo-experience/tasks.md) unchanged, after source tracking and protected-contract baseline work is complete.
    - Treat that approved plan as the sole implementation plan for its route, evidence-reference contracts, source locators, disclosures, read-only counterfactual, and Judge Demo tests; do not duplicate, rename, or redefine its tasks, design, routes, or sources of truth here.
    - _Requirements: 4.1–4.8, 5.1–5.8, 14.1–14.11, 15.7_
  - [ ]* 7.2 Add only production-readiness integration coverage for **Property 4: Evidence Claims Are Provenance-Closed**, reusing the approved Judge Demo fixtures, source-locator primitives, and browser tests rather than creating a parallel presentation model.
    - Verify recovered-label iff semantics, typed source closure, unavailable-evidence behavior, source disclosure across gateway/simulation/projection states, and no Command Center browser recalculation.
    - **Validates: Requirements 4.3–4.8, 5.1–5.8, 13.8–13.10, 14.10, 15.7**

- [ ] 8. Add source-closed Command Center assurance read models and presentation
  - [ ] 8.1 Create `app/schemas/assurance.py`, `app/services/assurance_service.py`, and an additive Command Center assurance endpoint that derives values only from persisted outcomes, policy/audit records, job/outbox lifecycle data, clock records, and schema readiness.
    - Include typed status, declared value, derivation label, data-source classification, observation time, exact source references, and unavailable reason; retain existing overview field names and semantics.
    - _Requirements: 3.4, 5.1–5.7, 13.1–13.10, 15.8_
  - [ ] 8.2 Extend frontend API types, validators, wrappers, and Command Center cards to render only validated returned assurance fields using the Judge Demo disclosure/source-locator primitives.
    - Locale-format returned money only; do not aggregate, infer, cache, or recalculate assurance values in browser code; preserve prior validated evidence after a safe refresh failure.
    - _Requirements: 4.3–4.6, 5.1–5.8, 13.2, 13.7–13.10, 14.1–14.11, 15.8_
  - [ ]* 8.3 Write property-based tests for **Property 11: Assurance Values Are Source-Closed**, with at least 100 generated authoritative-record sets.
    - Verify declared backend derivation, typed sources/disclosures, unavailable output for missing/malformed/inconsistent inputs, and no client-side replacement value.
    - **Validates: Requirements 13.1–13.10, 15.8**

- [ ] 9. Apply the frontend quality contract across existing evidence surfaces
  - [ ] 9.1 Extend shared frontend layout, state, and error primitives for Command Center, Judge Demo, Gateway, Autopilot, Strategy Lab, and case evidence surfaces.
    - Provide keyboard access, visible focus, semantic controls/status/errors/source locators, non-color state cues, reduced-motion behavior, 320–767px one-column/table access, 768px+ comparison layouts, typed invalid-data unavailable states, and secret-safe browser state/logging.
    - _Requirements: 4.7, 5.1–5.8, 6.8, 8.4–8.5, 9.6–9.8, 13.8–13.10, 14.1–14.11, 15.9_
  - [ ]* 9.2 Add one-shot component and browser regression coverage for keyboard/focus/semantics/status announcements, 320px and 768px layouts, reduced motion, text equivalents, source locators, retained evidence/retry, and secret exclusion.
    - Reuse the approved Judge Demo Playwright coverage where applicable and add Command Center readiness cases without duplicating Guide test scenarios.
    - _Requirements: 14.1–14.11, 15.7, 15.9_

- [ ] 10. Perform only inventory-approved cleanup after preservation gates are in place
  - [ ] 10.1 Use the validated Cleanup Inventory and Source Tracking Guard to remove or update only candidates classified eligible with complete evidence; update dependent imports, routes, config, migration/test paths, and packages atomically with each approved removal.
    - Retain every candidate with incomplete/conflicting evidence or any runtime/public-contract/migration/test/Protected Capability reference; do not remove a capability merely because navigation does not expose it.
    - _Requirements: 1.1–1.5, 2.1–2.7, 3.1–3.5, 15.1–15.2, 17.1, 17.5, 17.7_
  - [ ]* 10.2 Add targeted regression tests for every approved removal and retain the protected-contract suite before accepting the deletion.
    - Verify associated supported behavior, public contracts, deterministic baseline behavior, and source tracking remain valid after each removal.
    - _Requirements: 2.5–2.7, 3.1–3.5, 15.1–15.2_

- [ ] 11. Implement release documentation, validation automation, and evidence records
  - [ ] 11.1 Update the release/baseline/cleanup and operational runbook sources with the supported architecture, profile matrix, migration/readiness process, clock/job/outbox lifecycle, Sandbox availability meanings, Copilot/executor boundaries, assurance sources, limitations, and mutation preconditions.
    - Keep examples secret-free; clearly distinguish Synthetic Simulation, read-only projections, Razorpay Sandbox facts, execution-only evidence, and real verified recovery outcomes.
    - _Requirements: 5.1–5.8, 6.5–6.7, 7.1–7.7, 8.1–8.8, 9.1–9.9, 10.1–10.9, 11.1–11.7, 12.1–12.12, 13.1–13.10, 16.1–16.8_
  - [ ] 11.2 Implement `scripts/release_validate.py` and release-record generation to run non-mutating source tracking, cleanup validation, migration/readiness fixtures, backend/property tests, frontend typecheck/build, browser checks, and secret-safe evidence collection.
    - Record repository revision, environment, schema revision, commands, test count/failures/skips/duration, tracking/inventory results, and required Sandbox/synthetic/projection caveats; never start a dev server, make outbound provider/Copilot requests, or mark readiness after a mandatory failure.
    - _Requirements: 1.6–1.7, 9.9, 10.2–10.4, 15.1–15.11, 16.2–16.8, 17.1–17.7_
  - [ ]* 11.3 Write property-based tests for **Property 12: Release Readiness Requires Every Mandatory Evidence Check**, with at least 100 generated release-check maps.
    - Verify readiness iff every mandatory source-tracking, baseline, migration/schema, security, executor, backend/frontend, targeted regression, and documentation check passes; verify non-real-performance caveats persist in ready records.
    - **Validates: Requirements 15.10–15.11, 16.1–16.8, 17.1–17.7**
  - [ ]* 11.4 Add release-tool and documentation-contract tests for required runbook sections, non-secret examples, declared Operational Mutation preconditions, generated-record fields, failure reporting, and one-shot command manifests.
    - _Requirements: 16.1–16.8, 17.1–17.7_

- [ ] 12. Final checkpoint — ensure all tests pass, ask the user if questions arise.
  - Run the full one-shot backend/property suite, controlled gateway/Copilot fixtures, migration upgrade/readiness/integrity checks, frontend unit/property tests, frontend typecheck/build, and targeted browser accessibility/responsive suites through release validation.
  - Confirm the release record remains not ready for untracked runtime source, unsupported schema revisions, invalid production security, failed mandatory checks, or an unapproved provider executor; a ready record must retain Sandbox/synthetic/projection limitations.
  - _Requirements: 1.1–1.7, 3.1–3.5, 4.1–4.8, 5.1–5.8, 6.1–6.9, 7.1–7.7, 8.1–8.8, 9.1–9.9, 10.1–10.9, 11.1–11.7, 12.1–12.12, 13.1–13.10, 14.1–14.11, 15.1–15.11, 16.1–16.8, 17.1–17.7_

## Notes

- Tasks marked with `*` are optional automated-test tasks. They are included in the dependency graph and remain directly coupled to the behavior they validate.
- Every property task runs at least 100 generated cases and carries the feature/property tag specified by the design. Fixture-based gateway and Copilot tests must not make outbound network calls.
- Task 7 is an explicit cross-spec dependency. Execute the approved Judge Demo plan from its own `tasks.md`; this plan neither duplicates nor changes it.
- Cleanup is intentionally late: tracking, inventory validation, migrations, protected-contract coverage, and release gates must exist before any deletion is accepted.
- The final checkpoint is not a graph node because it is a completion gate, not an independent leaf implementation task.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4"] },
    { "id": 2, "tasks": ["1.5", "2.1", "2.2", "3.1"] },
    { "id": 3, "tasks": ["2.3", "3.2", "6.1", "6.3"] },
    { "id": 4, "tasks": ["3.3", "4.1", "6.2", "6.4", "6.5"] },
    { "id": 5, "tasks": ["3.4", "5.1", "6.6", "7.1"] },
    { "id": 6, "tasks": ["3.5", "4.2", "5.2", "5.3", "6.7", "7.2"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["8.2"] },
    { "id": 9, "tasks": ["8.3", "9.1"] },
    { "id": 10, "tasks": ["9.2"] },
    { "id": 11, "tasks": ["10.1"] },
    { "id": 12, "tasks": ["10.2", "11.1", "11.2"] },
    { "id": 13, "tasks": ["11.3", "11.4"] }
  ]
}
```
