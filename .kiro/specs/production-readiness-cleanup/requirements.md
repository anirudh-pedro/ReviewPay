# Requirements Document

## Introduction

`production-readiness-cleanup` remediates release-readiness gaps in RevivePay without replacing its established recovery behavior. The feature turns the existing working system into a traceable, testable, honest, and environment-safe release candidate by bringing required runtime source under version control, removing only proven-dead code, implementing the already-approved `judge-demo-experience` specification, strengthening operational boundaries, and documenting/validating the resulting release.

This feature preserves the existing deterministic recovery engine, Razorpay Sandbox server-verification boundary, Command Center, Autopilot, Strategy Lab, deterministic A–D scenarios, immutable audit system, Virtual Clock, local intelligence implementations, and the additive `judge-demo-experience` specification. The deterministic workflow, Policy Engine, Outcome Verifier, and persisted evidence remain authoritative. No browser feature, optional copilot, provider callback, or Command Center calculation may bypass those authorities.

### Fresh Baseline

The remediation begins from the following verified baseline:

- The backend Test Suite has **595 passing tests**.
- The frontend TypeScript typecheck passes.
- The frontend production build passes.
- Required runtime source under the models area and the Razorpay integration source are currently untracked by version control.

The feature must preserve this baseline while adding targeted coverage. A later test count may exceed 595; a release must not use a lower passing-test result as evidence of equivalent coverage.

### Scope Boundaries

- Razorpay Sandbox is an optional test-provider verification integration. It does not establish a live-money recovery result and it is not an Action Executor.
- The existing Payment Simulator remains the default and only permitted recovery executor until an explicitly configured Safe Provider Executor satisfies this document.
- The Judge Demo is an evidence-first implementation of the existing approved specification, not a replacement recovery engine or a second source of truth.
- An optional AI Copilot may assist a human-facing explanation only within the bounded, validated, non-authoritative conditions in this document. It may not select, approve, execute, or verify recovery actions.
- Production readiness work must remain additive or behavior-preserving unless a documented, reviewed cleanup explicitly removes proven-unreachable code.

## Glossary

- **RevivePay**: The existing deterministic revenue-recovery application and its HTTP API.
- **Production_Readiness_Cleanup**: The additive remediation feature specified by this document.
- **Baseline_Evidence**: The recorded pre-remediation result of 595 passing backend tests plus passing frontend typecheck and production build.
- **Version_Control_Repository**: The repository that records RevivePay source, tests, migrations, specifications, and release documentation.
- **Runtime_Source**: A source, migration, template, static asset, configuration schema, or generated-at-build input that the application imports, executes, loads, or requires to build a supported release.
- **Source_Tracking_Guard**: The release check that identifies required Runtime_Source files absent from Version_Control_Repository tracking or accidentally excluded by ignore rules.
- **Cleanup_Inventory**: A reviewed record of candidate files, symbols, routes, dependencies, assets, and configuration entries proposed for removal, including references searched and preservation evidence.
- **Protected_Capability**: An existing supported capability that this feature must preserve: the deterministic recovery engine, Razorpay Sandbox verification, Command Center, Autopilot, Strategy Lab, A–D scenarios, immutable audit system, Virtual Clock, local intelligence, and `judge-demo-experience` behavior.
- **Deterministic_Recovery_Engine**: The existing Risk Detector, rule-based diagnosis, deterministic prediction, Expected Recovery Value calculator, decision engine, Policy Engine, Action Executor boundary, Outcome Verifier, workflow, and audit flow.
- **Policy_Engine**: The existing authoritative component that approves, blocks, or escalates a selected recovery action.
- **Outcome_Verifier**: The existing authoritative component that determines Recovery Outcome status from persisted payment state.
- **Payment_Simulator**: The existing deterministic, synthetic Action Executor used for demo and test recovery behavior.
- **Action_Executor**: The only integration boundary permitted to execute a recovery action after Policy Engine approval.
- **Safe_Provider_Executor**: An explicitly configured Action Executor whose provider mode, credentials, idempotency, authorization, policy gate, audit records, independent outcome verification, network allowlist, and failure handling are validated before the executor can be enabled for an environment.
- **Razorpay_Sandbox**: Razorpay’s isolated test environment; it does not move live money for RevivePay claims.
- **Gateway_Verification**: Existing server-side callback or webhook signature validation followed by authoritative provider retrieval and relationship, amount, and currency consistency checks.
- **Gateway_Availability_Status**: The explicit presentation state `AVAILABLE`, `UNAVAILABLE`, or `INCONCLUSIVE` for an attempted Razorpay Sandbox validation.
- **Judge_Demo_Experience**: The approved additive, evidence-first frontend and read-only presentation layer defined by the `judge-demo-experience` specification.
- **Evidence_Bound_Claim**: A displayed statement that identifies an exact validated API response field or immutable Audit Event sequence and metadata field supporting the statement.
- **Data_Source_Disclosure**: A visible statement that classifies displayed evidence as server-verified Razorpay Sandbox state, synthetic deterministic simulation, read-only synthetic projection, or unavailable evidence.
- **Synthetic_Simulation**: Seeded deterministic scenario data and Payment Simulator results that do not represent real customer payments or real recovery performance.
- **Verified_Outcome**: A Recovery Outcome determined by Outcome Verifier from persisted payment state.
- **AI_Copilot**: An optional, bounded, non-authoritative assistant that produces a structured human-facing explanation from approved, redacted context.
- **Copilot_Response_Schema**: The versioned, allowlisted structured data contract required before an AI Copilot response can be displayed.
- **Deterministic_Fallback**: The existing rule-based diagnosis, deterministic scorer, and fixed evidence templates used when AI Copilot evidence is unavailable, invalid, unsafe, or disabled.
- **Environment_Profile**: A named runtime environment with its own authentication, authorization, secret, transport, executor, logging, and migration settings.
- **Operational_Mutation**: An API operation that changes payment, recovery, policy, clock, job, outbox, scenario, or demo-reset state.
- **Migration**: A versioned, ordered database schema transition executed by the approved migration mechanism.
- **Schema_Revision**: The persisted identifier of the Migration set applied to a database.
- **Database_Integrity_Constraint**: A database-enforced uniqueness, foreign-key, check, or state-consistency rule protecting persisted recovery records.
- **Virtual_Clock**: The existing deterministic simulation clock advanced only by authorized explicit operations.
- **Clock_Advance_Request**: One authorized request to move Virtual Clock time forward by a validated nonnegative duration.
- **Background_Job**: A persisted unit of deferred work with a lifecycle, lease, idempotency key, correlation identifier, result, and failure record.
- **Outbox_Event**: A persisted, idempotent event produced transactionally with a domain change for later delivery or processing.
- **Command_Center_Assurance_Value**: A labelled operational integrity value derived from persisted authoritative records and exposed by the backend for Command Center presentation.
- **Frontend_Quality_Contract**: The accessibility, responsive, type-safety, error-handling, performance, and source-disclosure behaviors required of RevivePay frontend surfaces.
- **Release_Validation**: The documented final execution of applicable backend tests, frontend checks, migration checks, security checks, and release review evidence.
- **Test_Suite**: The existing backend and frontend automated test suites plus tests added by this feature.

## Requirements

### Requirement 1: Baseline Preservation and Runtime Source Tracking

**User Story:** As a maintainer, I want every required runtime input tracked and the known-good baseline preserved, so that a release can be reproduced and reviewed from version-controlled source.

#### Acceptance Criteria

1. THE Source_Tracking_Guard SHALL identify every Runtime_Source required by supported backend, frontend, migration, and test execution.
2. THE Version_Control_Repository SHALL track every identified Runtime_Source, including the required models source and the Razorpay integration source.
3. WHEN an ignore rule matches an identified Runtime_Source, THE Source_Tracking_Guard SHALL report the matching rule and SHALL fail release validation until the Runtime_Source is tracked or the rule is narrowed.
4. WHEN a Runtime_Source is imported by application startup, API routing, migration execution, frontend build configuration, or a supported test command, THE Source_Tracking_Guard SHALL classify the Runtime_Source as required.
5. IF a required Runtime_Source is untracked, missing, or unreadable, THEN THE Release_Validation SHALL fail and SHALL identify the path and the discovery evidence.
6. THE Production_Readiness_Cleanup SHALL retain Baseline_Evidence as the comparison point for remediation validation.
7. WHEN the completed remediation Test_Suite reports fewer than 595 passing backend tests, THEN THE Release_Validation SHALL fail unless a reviewed replacement test record identifies the removed test, its reason for removal, and equivalent retained coverage.

### Requirement 2: Evidence-Based Dead-Code Cleanup

**User Story:** As a maintainer, I want unused implementation removed only after evidence-based review, so that cleanup reduces risk without deleting supported behavior.

#### Acceptance Criteria

1. THE Cleanup_Inventory SHALL record each cleanup candidate’s path or symbol, candidate category, repository references searched, public-contract status, test coverage, and proposed disposition.
2. WHEN a cleanup candidate has an import, route, configuration, migration, template, static asset, documentation command, test, or supported-runtime reference, THE Cleanup_Inventory SHALL classify the candidate as retained until the reference is removed through an approved behavior-preserving change.
3. WHEN a cleanup candidate has no identified Runtime_Source reference, no public HTTP contract reference, no migration dependency, and no Protected_Capability dependency, THE Cleanup_Inventory SHALL classify the candidate as eligible for removal review.
4. IF cleanup evidence is incomplete, conflicting, or unreadable, THEN THE Production_Readiness_Cleanup SHALL retain the candidate and SHALL record incomplete cleanup evidence.
5. WHEN an eligible cleanup candidate is removed, THE Test_Suite SHALL verify the associated supported behavior and public contracts before Release_Validation accepts the removal.
6. THE Production_Readiness_Cleanup SHALL not remove, rename, or weaken a Protected_Capability solely because a presentation surface does not currently navigate to the Protected_Capability.
7. THE Production_Readiness_Cleanup SHALL remove unused Runtime_Source dependencies only when the dependency is absent from supported runtime, build, migration, and test paths.

### Requirement 3: Protected Capability and Contract Preservation

**User Story:** As a product owner, I want remediation to preserve existing recovery and evidence capabilities, so that readiness work cannot regress the demonstrated product.

#### Acceptance Criteria

1. THE Production_Readiness_Cleanup SHALL preserve the deterministic decisions, Policy Engine outcomes, Expected Recovery Value calculations, Payment Simulator outcomes, Outcome Verifier authority, and audit ordering produced by unchanged persisted state, configuration, seed, and Virtual Clock time.
2. THE Production_Readiness_Cleanup SHALL preserve the existing Razorpay Sandbox Gateway Verification boundary and SHALL not make a browser callback authoritative.
3. THE Production_Readiness_Cleanup SHALL preserve the Command Center, Autopilot, Strategy Lab, A–D scenarios, immutable audit system, Virtual Clock, and local intelligence public behavior unless an additive documented contract explicitly supersedes a behavior.
4. WHEN remediation changes a typed API response, THE API Layer SHALL preserve existing response fields and error-envelope semantics for existing consumers.
5. IF a remediation change would alter an existing Protected_Capability decision, policy result, audit sequence, public route, or persisted record semantics, THEN THE Release_Validation SHALL fail until an approved migration and compatibility record identify the intentional change and its validation evidence.

### Requirement 4: Judge Demo Experience Implementation

**User Story:** As a judge, I want the approved Judge Demo Experience available as a polished evidence-first flow, so that I can inspect RevivePay’s capabilities without trusting browser-generated claims.

#### Acceptance Criteria

1. THE Judge_Demo_Experience SHALL implement the accepted requirements, design decisions, source-locator model, and correctness properties in the `judge-demo-experience` specification.
2. THE Judge_Demo_Experience SHALL provide the ordered judge flow Command Center, Live Gateway Journey, deterministic recovery, Strategy Comparison, Policy Governor, Autopilot, and Case Intelligence Timeline.
3. THE Judge_Demo_Experience SHALL obtain displayed decisions, policies, execution evidence, verified outcomes, audit events, scenario facts, Strategy Lab results, and Command Center values only from validated typed API responses or immutable Audit Event evidence.
4. WHEN a Judge_Demo_Experience view combines facts from multiple responses, THE Judge_Demo_Experience SHALL identify an exact source locator for each displayed fact.
5. IF required evidence is absent, malformed, inconsistent, or unreadable, THEN THE Judge_Demo_Experience SHALL display unavailable evidence and SHALL not substitute a generated narrative, inferred value, zero value, or cached claim.
6. THE Judge_Demo_Experience SHALL perform no browser-side recovery probability calculation, Expected Recovery Value arithmetic, policy evaluation, simulated-outcome calculation, payment-status mutation, Virtual Clock advance, recovery execution, or policy override.
7. WHEN a Judge_Demo_Experience control opens an existing Operational Mutation surface, THE Judge_Demo_Experience SHALL identify the control as user-initiated operational activity before activation and SHALL distinguish the control from a read-only evidence view.
8. THE Judge_Demo_Experience SHALL not label a deterministic diagnosis, deterministic predictor, fixed explanation template, or browser-generated text as artificial intelligence.

### Requirement 5: Real-versus-Simulated Presentation Integrity

**User Story:** As a judge or operator, I want every result labelled by provenance, so that Sandbox facts, simulations, projections, and verified outcomes cannot be confused.

#### Acceptance Criteria

1. THE Judge_Demo_Experience and Command Center SHALL display a Data_Source_Disclosure adjacent to all gateway, recovery, uplift, Strategy Lab, Autopilot, scenario, and audit evidence.
2. WHEN evidence originates from successful Gateway Verification, THE presentation layer SHALL label the evidence as server-verified Razorpay Sandbox state and SHALL state that Razorpay Sandbox does not represent live money movement.
3. WHEN evidence originates from Synthetic Simulation, THE presentation layer SHALL label the evidence as synthetic deterministic simulation and SHALL state that the evidence does not represent real recovery performance.
4. WHEN evidence originates from a baseline comparison or Strategy Lab Counterfactual, THE presentation layer SHALL label the evidence as a read-only synthetic projection and SHALL not label the evidence as actual recovered revenue.
5. WHEN an identified Verified Outcome reports recovered true with a nonzero recovered amount, THE presentation layer SHALL label the identified amount as recovered.
6. IF a displayed amount lacks an identified Verified Outcome reporting recovered true with a nonzero recovered amount, THEN THE presentation layer SHALL not label the amount as recovered.
7. IF provenance is absent, malformed, inconsistent, or unreadable, THEN THE presentation layer SHALL render unavailable evidence and SHALL not infer a real, verified, simulated, or projected provenance.
8. THE presentation layer SHALL not display fabricated intelligence scores, business uplift, provider status, failure causes, customer insights, or recovery amounts.

### Requirement 6: Safe Razorpay Sandbox Availability and Verification

**User Story:** As a demo operator, I want Razorpay Sandbox validation to be safe and candid about its availability, so that a missing credential or network condition never becomes a false gateway claim.

#### Acceptance Criteria

1. THE Gateway Verification service SHALL validate Razorpay Sandbox callback or webhook signatures on the server before retrieving and presenting authoritative provider state.
2. WHEN Gateway Verification succeeds after signature, provider retrieval, provider relationship, amount, and currency validation, THE Live Gateway Journey SHALL present only the validated server-returned payment status, normalized failure reason, provider status, and optional Recovery Case reference with exact response-field locators.
3. WHEN a browser callback is received before successful Gateway Verification, THE Live Gateway Journey SHALL label the callback as provisional and SHALL not display a verified provider state, failure reason, Recovery Case result, recovered-revenue claim, or verified recovery claim.
4. IF Gateway Verification rejects a signature, provider retrieval, provider relationship, payment relationship, amount, or currency validation, THEN THE Live Gateway Journey SHALL display the safe returned verification failure and SHALL display no verified payment status, provider state, failure reason, or Recovery Case reference.
5. WHEN Razorpay Sandbox credentials are absent, invalid, or disabled, THE Gateway_Availability_Status SHALL be `UNAVAILABLE` and SHALL identify the integration as not configured without exposing secret values.
6. WHEN Razorpay Sandbox provider reachability, DNS, transport, timeout, or remote response integrity cannot be established, THE Gateway_Availability_Status SHALL be `INCONCLUSIVE` and SHALL not state that Razorpay Sandbox verification passed or failed.
7. WHEN Razorpay Sandbox validation is available, THE Gateway_Availability_Status SHALL be `AVAILABLE` only after an authenticated, non-mutating capability check or successful existing Gateway Verification response validates the configured integration boundary.
8. THE frontend, API response, audit metadata, logs, error messages, client-side state, and source locators SHALL exclude Razorpay key secrets, webhook secrets, raw callback signatures, non-public provider credentials, customer contact data, and payment-instrument credentials.
9. WHEN Gateway Verification rejects an interaction, THE Gateway Verification service SHALL leave no new Gateway Webhook Event, Payment Attempt, or Recovery Case record attributable to the rejected verification.

### Requirement 7: Recovery Execution Safety Boundary

**User Story:** As a risk owner, I want recovery execution restricted to proven-safe executors, so that release readiness does not introduce unreviewed real-money behavior.

#### Acceptance Criteria

1. THE Payment Simulator SHALL remain the default Action Executor for local, demo, test, and unconfigured production-like environments.
2. THE Razorpay Sandbox gateway integration SHALL not act as an Action Executor and SHALL not convert a gateway verification result into a recovery execution result.
3. WHEN no Safe Provider Executor is explicitly configured and validated for an Environment Profile, THE Action Executor boundary SHALL reject real provider recovery execution and SHALL preserve the existing simulated execution behavior.
4. WHEN a Safe Provider Executor is enabled, THE Safe Provider Executor SHALL require explicit environment configuration, authorized Operational Mutation access, idempotency handling, Policy Engine approval, immutable audit records, independent Outcome Verifier evidence, bounded network destinations, and safe failure handling before executing a provider operation.
5. IF a Safe Provider Executor cannot establish all required safety conditions, THEN THE Action Executor boundary SHALL block the provider execution, SHALL record the safe blocking reason, and SHALL not create a recovered-revenue claim.
6. WHEN an Action Executor reports successful provider handling without an identified Verified Outcome, THE presentation layer SHALL label the result as execution-only evidence and SHALL not label the result as recovered.
7. THE Production_Readiness_Cleanup SHALL not enable a real-money provider executor by default in any Environment Profile.

### Requirement 8: Bounded Optional AI Copilot

**User Story:** As an operator, I want an optional copilot explanation that remains bounded and non-authoritative, so that intelligence assistance never displaces deterministic safety controls.

#### Acceptance Criteria

1. THE AI_Copilot SHALL remain disabled unless an Environment Profile explicitly enables the AI Copilot.
2. WHEN the AI Copilot receives context, THE AI Copilot SHALL receive only allowlisted, redacted, pre-action context fields required by the Copilot Response Schema.
3. THE AI_Copilot SHALL return a response conforming to the versioned Copilot Response Schema before the presentation layer displays any AI Copilot content.
4. WHEN an AI Copilot response conforms to the Copilot Response Schema and identified evidence, THE presentation layer SHALL label the response as optional advisory explanation and SHALL identify its bounded source and schema version.
5. IF the AI Copilot is disabled, unavailable, times out, exceeds a configured resource bound, returns malformed data, contains unallowlisted content, or conflicts with authoritative deterministic evidence, THEN THE presentation layer SHALL use Deterministic Fallback and SHALL identify the fallback reason without inventing a copilot result.
6. THE AI_Copilot SHALL not select an action, alter an Expected Recovery Value, override Policy Engine results, execute an action, mutate a payment, advance Virtual Clock time, create an audit event, or establish a Verified Outcome.
7. WHEN an AI Copilot interaction is recorded, THE audit record SHALL contain only allowlisted provenance, schema-version, fallback, and safety-status fields and SHALL exclude prompts, secrets, customer contact data, payment-instrument data, and unredacted provider payloads.
8. THE AI_Copilot SHALL enforce configured request-time, response-size, and invocation-count bounds for each request and each Environment Profile.

### Requirement 9: Environment-Aware Authentication, Authorization, and Security

**User Story:** As a security owner, I want environment-specific protection that remains usable for local demos and fail-closed for production, so that operational power is controlled without weakening development workflows.

#### Acceptance Criteria

1. THE Environment Profile SHALL distinguish local, demo, test, staging, and production settings for authentication, authorization, secret requirements, transport security, executor availability, logging, and reset permissions.
2. WHERE the Environment Profile is local, demo, or test, THE API Layer SHALL permit the documented development authentication mode and SHALL identify the mode in non-secret operational status evidence.
3. WHERE the Environment Profile is production, THE API Layer SHALL require authenticated authorized principals for every Operational Mutation and SHALL reject disabled authentication configuration during startup.
4. WHEN an authenticated principal invokes an Operational Mutation, THE API Layer SHALL require the configured operation scope before delegating the mutation.
5. WHEN a principal requests demo reset, THE API Layer SHALL require a dedicated reset scope and SHALL reject the request outside an explicitly resettable Environment Profile.
6. THE API Layer SHALL apply configured CORS origins, request-size limits, pagination limits, correlation identifiers, and security headers to supported HTTP responses.
7. IF a request contains an invalid credential, missing scope, malformed authorization header, or disallowed origin, THEN THE API Layer SHALL return the standard safe error envelope and SHALL not expose credential values, configuration values, stack traces, or internal exception details.
8. THE Configuration Service SHALL load provider credentials, API keys, and secret material only from approved secret configuration and SHALL exclude secret material from logs, responses, browser bundles, documentation examples, and committed environment files.
9. WHEN production startup detects missing required security configuration, THE Configuration Service SHALL fail startup before serving operational routes.

### Requirement 10: Migration Discipline and Database Integrity

**User Story:** As an operator, I want schema changes and persistence constraints managed explicitly, so that release deployment preserves recovery evidence and prevents invalid records.

#### Acceptance Criteria

1. THE Migration system SHALL represent every supported schema change as an ordered, versioned Migration.
2. WHEN an Environment Profile is production or staging, THE application startup SHALL verify the required Schema Revision and SHALL not invoke schema-creating or destructive bootstrap behavior.
3. WHEN a Migration is applied, THE Migration system SHALL record the resulting Schema Revision and SHALL preserve compatible persisted recovery, audit, job, outbox, and Virtual Clock data.
4. IF a database Schema Revision is missing, ahead of the supported application revision, or incompatible with the running application, THEN the application SHALL report a safe readiness failure and SHALL not accept Operational Mutations.
5. THE database SHALL enforce unique Recovery Case, action, job idempotency, outbox idempotency, and per-case audit-sequence identities according to their authoritative keys.
6. THE database SHALL enforce relationships from Recovery Case to payment, Recovery Action to Recovery Case, Recovery Outcome to Recovery Action, Audit Event to Recovery Case, Background Job to its supported aggregate, and Outbox Event to its aggregate where those records are present.
7. WHEN a persisted record violates a Database Integrity Constraint, THE persistence boundary SHALL reject the write atomically and SHALL return or record a safe domain error without partial recovery state.
8. THE Audit Service SHALL preserve immutable Audit Event content and increasing sequence order for each Recovery Case.
9. THE Production_Readiness_Cleanup SHALL validate Migration upgrade behavior from a supported initialized database and from a supported pre-remediation database fixture.

### Requirement 11: Virtual Clock Concurrency and Time Integrity

**User Story:** As a demo operator, I want concurrent clock operations to remain deterministic and auditable, so that scheduled recovery behavior cannot race or move backward.

#### Acceptance Criteria

1. THE Virtual Clock SHALL store one authoritative current simulation time for each configured simulation scope.
2. WHEN an authorized Clock Advance Request is accepted, THE Virtual Clock SHALL atomically apply the validated nonnegative duration to the authoritative current simulation time.
3. WHEN concurrent Clock Advance Requests target the same simulation scope, THE Virtual Clock SHALL serialize the accepted requests and SHALL assign each request a unique ordered result.
4. IF a Clock Advance Request uses a negative duration, malformed duration, stale concurrency token, or unauthorized principal, THEN THE Virtual Clock SHALL reject the request and SHALL leave the authoritative current simulation time unchanged.
5. WHEN a workflow reads or writes a scheduled action, THE workflow SHALL use the authoritative Virtual Clock time and SHALL not use wall-clock time for simulation decisions.
6. WHEN a Clock Advance Request completes, THE API Layer SHALL return the resulting authoritative time and an evidence identifier sufficient to correlate the update with audit or operational records.
7. THE Test Suite SHALL verify that concurrent accepted Clock Advance Requests produce the same final Virtual Clock time as the equivalent ordered sequence of durations.

### Requirement 12: Background Job and Outbox Lifecycle

**User Story:** As an operator, I want durable jobs and outbox records to have explicit bounded lifecycles, so that asynchronous work can be inspected, retried, and recovered safely.

#### Acceptance Criteria

1. THE Background Job lifecycle SHALL define the persisted states `PENDING`, `RUNNING`, `RETRY`, `COMPLETED`, `FAILED`, and `CANCELLED`.
2. THE Background Job service SHALL persist an idempotency key, aggregate identifier, request correlation identifier, attempt count, maximum attempt count, availability time, lease fields, result summary, and safe failure summary for every Background Job.
3. WHEN a duplicate Background Job submission uses the same idempotency key and supported aggregate, THE Background Job service SHALL return the existing active or completed Background Job and SHALL not create a second active execution.
4. WHEN a worker claims a due Background Job, THE Background Job service SHALL atomically transition the Background Job to `RUNNING` and SHALL assign a bounded lease owner and lease expiry.
5. WHEN a worker completes a claimed Background Job successfully, THE Background Job service SHALL transition the Background Job to `COMPLETED`, SHALL record a result summary, and SHALL clear the active lease.
6. WHEN a claimed Background Job fails before its maximum attempt count, THE Background Job service SHALL transition the Background Job to `RETRY`, SHALL record a safe failure summary, and SHALL assign a bounded next availability time.
7. WHEN a Background Job reaches its maximum attempt count, THE Background Job service SHALL transition the Background Job to `FAILED` and SHALL preserve the correlation and failure evidence.
8. WHEN a lease expires without completion, THE Background Job service SHALL make the Background Job eligible for safe reclaim according to its retry bound and SHALL not allow simultaneous successful execution by multiple workers.
9. WHEN a terminal Recovery Case is associated with a pending Background Job, THE Background Job service SHALL transition the Background Job to `CANCELLED` or `COMPLETED` without invoking recovery execution.
10. THE Outbox Event service SHALL persist an Outbox Event atomically with its originating domain change and SHALL use an idempotency key to prevent duplicate published effects.
11. WHEN an Outbox Event is delivered or processed successfully, THE Outbox Event service SHALL record the delivery result without modifying the originating immutable Audit Event.
12. IF a Background Job or Outbox Event cannot be processed safely, THEN the service SHALL retain inspectable lifecycle evidence and SHALL not bypass the Policy Engine, Action Executor boundary, or Outcome Verifier.

### Requirement 13: Derived Command Center Assurance Values

**User Story:** As a judge or operator, I want clearly derived assurance values beside business metrics, so that Command Center claims show their evidence and limitations.

#### Acceptance Criteria

1. THE Command Center service SHALL derive each Command Center Assurance Value from authoritative persisted records, validated configuration, or a versioned migration/readiness result.
2. THE Command Center service SHALL expose an exact typed source field, derivation label, data-source classification, observation time, and unavailable state for every Command Center Assurance Value.
3. THE Command Center service SHALL derive verified recovered revenue only from identified Verified Outcome records with recovered true and nonzero recovered amount.
4. THE Command Center service SHALL derive policy-block and escalation assurance values only from persisted authoritative Policy Engine outcomes and associated audit evidence.
5. THE Command Center service SHALL derive audit-completeness assurance values from persisted required event sequences and SHALL identify missing or inconsistent evidence rather than treating absence as success.
6. THE Command Center service SHALL derive job, outbox, migration, and Virtual Clock assurance values from their respective persisted lifecycle or readiness records.
7. WHEN a Command Center Assurance Value includes a percentage, total, count, or currency amount, THE backend SHALL calculate the value from its declared authoritative inputs and SHALL return the value with a field-level derivation label.
8. THE frontend SHALL display a Command Center Assurance Value only from the returned typed backend field and SHALL not recalculate, aggregate, or infer the value in browser code.
9. IF an authoritative input, derivation record, or source reference for a Command Center Assurance Value is absent, malformed, inconsistent, or unreadable, THEN the Command Center SHALL display unavailable evidence and SHALL not display a default, cached, or fabricated assurance value.
10. WHEN a Command Center Assurance Value is based on Synthetic Simulation or a read-only projection, THE Command Center SHALL present the required Data Source Disclosure and SHALL not describe the value as real recovery performance.

### Requirement 14: Frontend Accessibility and Quality

**User Story:** As a user presenting or operating RevivePay, I want frontend surfaces to remain accessible, resilient, and evidence-preserving, so that visual polish does not hide safety or data-quality limits.

#### Acceptance Criteria

1. THE Frontend Quality Contract SHALL provide keyboard-operable navigation, controls, disclosure panels, tables, retry actions, and visible focus indicators for Command Center, Judge Demo Experience, Gateway, Autopilot, Strategy Lab, and case evidence surfaces.
2. THE Frontend Quality Contract SHALL expose semantic headings, lists, tables, controls, status messages, errors, source locators, charts, and policy/outcome states to assistive technology.
3. THE Frontend Quality Contract SHALL pair every color-coded policy, execution, outcome, availability, or evidence state with visible text, a non-color visual indicator, and an accessible label.
4. THE Frontend Quality Contract SHALL meet WCAG 2.2 AA contrast requirements for rendered normal text, controls, focus indicators, and state labels.
5. WHERE a user enables reduced-motion preference, THE frontend SHALL remove nonessential animation while preserving evidence order, state changes, and source disclosures.
6. WHEN a progressive Autopilot or Judge Demo step becomes visible, THE frontend SHALL announce the returned state and evidence-bound summary through a non-disruptive accessible status region.
7. WHEN the viewport width is from 320 through 767 CSS pixels, THE frontend SHALL provide readable one-column evidence layouts, reachable controls and disclosures, and horizontal access to data tables without clipped content.
8. WHEN the viewport width is 768 CSS pixels or greater, THE frontend SHALL use available space for comparisons without changing the underlying evidence order, source, or meaning.
9. IF a frontend API request fails after validated evidence is displayed, THEN the frontend SHALL retain the validated evidence and source locators, SHALL show an accessible safe error state, and SHALL offer a retry control only when retrying is safe.
10. THE frontend SHALL validate typed API response boundaries before rendering authoritative claims and SHALL render unavailable evidence for invalid response fields.
11. THE frontend SHALL exclude secret material, raw callback signatures, payment-instrument credentials, and customer contact details from rendered content, browser storage, telemetry, and client-side logs.

### Requirement 15: Automated Regression and Safety Coverage

**User Story:** As a maintainer, I want targeted automated coverage of readiness boundaries, so that cleanup and new presentation features cannot weaken deterministic recovery or security.

#### Acceptance Criteria

1. THE Test Suite SHALL retain the Baseline Evidence backend tests and SHALL add regression tests for Runtime Source tracking, cleanup preservation, migration behavior, database integrity, Virtual Clock concurrency, job lifecycle, outbox lifecycle, environment authorization, and secret exclusion.
2. THE Test Suite SHALL verify that unchanged deterministic recovery inputs produce unchanged decisions, Policy Engine outcomes, Payment Simulator results, Outcome Verifier results, and audit ordering.
3. THE Test Suite SHALL verify that Gateway Verification rejects invalid signature, provider retrieval, relationship, amount, and currency cases without creating verified gateway claims or rejected-interaction records.
4. THE Test Suite SHALL verify the `AVAILABLE`, `UNAVAILABLE`, and `INCONCLUSIVE` Gateway Availability Status behaviors without exposing Razorpay secrets or provider credentials.
5. THE Test Suite SHALL verify that no real provider recovery execution occurs when a Safe Provider Executor is absent, unconfigured, unauthorized, or fails required validation.
6. THE Test Suite SHALL verify that AI Copilot malformed, timed-out, over-bound, unsafe, disabled, and contradictory responses use Deterministic Fallback and cannot mutate recovery state or authority.
7. THE Test Suite SHALL verify the Judge Demo Experience source locators, unavailable-evidence behavior, real-versus-simulated disclosures, no-execution proof predicate, provisional gateway handling, and read-only Strategy Lab behavior required by the `judge-demo-experience` specification.
8. THE Test Suite SHALL verify that Command Center Assurance Values equal their declared authoritative inputs or render unavailable evidence when an input is invalid, missing, or inconsistent.
9. THE Test Suite SHALL verify keyboard access, reduced-motion behavior, accessible status messages, responsive behavior at 320 and 768 CSS pixels, text equivalents for visual states, and accessible source locators.
10. THE Test Suite SHALL run supported backend tests without outbound network dependency by using controlled provider and copilot fixtures.
11. WHEN a property-based test is appropriate for a pure deterministic mapper, lifecycle transition, source-binding predicate, or concurrency invariant, THE Test Suite SHALL run at least 100 generated cases and SHALL record the associated requirement identifier.

### Requirement 16: Documentation and Operational Runbooks

**User Story:** As a developer or evaluator, I want accurate documentation for supported modes and release checks, so that the system can be run without unsafe assumptions.

#### Acceptance Criteria

1. THE Documentation set SHALL describe the deterministic recovery architecture, Policy Engine authority, Outcome Verifier authority, Payment Simulator default, Razorpay Sandbox boundary, AI Copilot boundary, Judge Demo Experience, and real-versus-simulated disclosures.
2. THE Documentation set SHALL document required Runtime Source tracking checks, Cleanup Inventory review, migration upgrade procedure, rollback limitations, readiness checks, and final Release Validation commands.
3. THE Documentation set SHALL document Environment Profile configuration for local, demo, test, staging, and production, including authentication mode, required scopes, executor restrictions, reset restrictions, secret handling, and network expectations.
4. THE Documentation set SHALL document the Razorpay Sandbox `AVAILABLE`, `UNAVAILABLE`, and `INCONCLUSIVE` meanings and SHALL state that unavailable or inconclusive validation does not demonstrate provider failure or successful verification.
5. THE Documentation set SHALL document the Background Job and Outbox Event lifecycle states, leases, idempotency, retry limits, failure inspection, and operational recovery procedure.
6. THE Documentation set SHALL document Command Center Assurance Values, their declared sources, their unavailable state, and their synthetic or projection disclosures.
7. THE Documentation set SHALL not include secret values, live credentials, raw provider payloads, customer contact data, payment-instrument data, or instructions that bypass authorization, policy, or outcome verification.
8. WHEN a documented command mutates state, THE Documentation set SHALL identify the command as an Operational Mutation and SHALL state its environment and authorization preconditions.

### Requirement 17: Final Release Validation

**User Story:** As a release owner, I want a complete, repeatable validation record, so that production-readiness claims are based on evidence rather than visual inspection.

#### Acceptance Criteria

1. THE Release_Validation SHALL record the Version Control Repository revision, tracked Runtime Source result, Cleanup Inventory disposition, Environment Profile, database Schema Revision, and validation timestamp.
2. THE Release_Validation SHALL execute the supported backend Test Suite and SHALL record the passing test count, failures, skips, duration, and environment.
3. THE Release_Validation SHALL execute the frontend typecheck and production build and SHALL record their exit status and environment.
4. THE Release_Validation SHALL execute targeted migration, database-integrity, Virtual Clock concurrency, job/outbox lifecycle, authorization, gateway availability, Safe Provider Executor boundary, AI Copilot fallback, Command Center assurance, Judge Demo Experience, accessibility, and responsive checks.
5. WHEN any mandatory Release Validation check fails, THE Release_Validation SHALL mark the release not ready and SHALL identify the failed check without exposing secret material.
6. WHEN all mandatory Release Validation checks pass, THE Release_Validation SHALL mark the release ready with the evidence record and SHALL not claim that Synthetic Simulation, Razorpay Sandbox, or read-only projections prove real payment recovery performance.
7. THE Release_Validation SHALL not mark the release ready when required Runtime Source remains untracked, an unsupported Schema Revision is detected, production security configuration is invalid, or an unapproved real provider executor is enabled.

## Correctness Properties for Test Implementation

### Property 1: Required Runtime Sources Are Release-Tracked

For every file identified as Runtime Source by startup imports, API routes, migration invocation, frontend build configuration, or supported test execution, Source Tracking Guard reports the file as tracked and not excluded by an effective ignore rule. If any identified Runtime Source is untracked or excluded, Release Validation is not ready.

### Property 2: Cleanup Does Not Alter Protected Deterministic Behavior

For every unchanged seeded payment, configuration, and Virtual Clock time, a cleanup build produces the same deterministic decision, Policy Engine outcome, Payment Simulator result, Outcome Verifier result, and per-case Audit Event sequence as the preserved baseline build.

### Property 3: Gateway Availability and Verification Do Not Manufacture Facts

For every Sandbox configuration and controlled provider response, `AVAILABLE` occurs only after a successful safe capability check or successful Gateway Verification; unavailable credentials produce `UNAVAILABLE`; indeterminate transport or provider integrity produces `INCONCLUSIVE`; and rejected verification produces no verified provider state, normalized failure reason, Recovery Case link, or rejected-interaction persistence.

### Property 4: Unsafe Executors Cannot Create Recovery Claims

For every Environment Profile in which a Safe Provider Executor is absent, disabled, unauthorized, or fails its safety validation, a recovery request never invokes a real provider operation and produces no recovered claim without an identified Verified Outcome.

### Property 5: Copilot Is Non-Authoritative and Falls Back Deterministically

For every AI Copilot response that is missing, malformed, oversized, timed out, unallowlisted, contradictory, or disabled, the rendered output uses Deterministic Fallback and persisted recovery, policy, payment, Virtual Clock, audit, and outcome state is unchanged.

### Property 6: Clock Advances Are Linearizable

For every finite set of accepted nonnegative Clock Advance Requests targeting one simulation scope, the final Virtual Clock time equals the initial time plus the sum of accepted durations and equals the result of applying those requests in their recorded order.

### Property 7: Job and Outbox Idempotency Is Preserved

For every repeated Background Job submission or Outbox Event publication with the same supported idempotency key, the persisted system contains at most one active or completed represented operation and no duplicate recovery execution or published effect.

### Property 8: Command Center Assurance Values Are Source-Closed

For every Command Center Assurance Value, the displayed value equals its named typed backend field and declared authoritative inputs after presentation formatting; if any required input or source reference is invalid, missing, or inconsistent, the display is unavailable and contains no synthesized replacement.

### Property 9: Judge Presentation Cannot Misclassify Evidence

For every Judge Demo Experience, Command Center, Gateway, Autopilot, and Strategy Lab evidence fixture, recovered labels occur only for identified recovered Verified Outcomes with nonzero amount, and every gateway, simulation, projection, and unavailable state displays its required Data Source Disclosure.

## Non-Goals

- Replacing the Deterministic Recovery Engine, Policy Engine, Expected Recovery Value calculator, Payment Simulator, Outcome Verifier, Audit Service, Virtual Clock, Autopilot, Strategy Lab, baseline comparison semantics, or A–D scenario behavior.
- Converting Razorpay Sandbox verification into a payment recovery executor or treating Sandbox provider state as a verified RevivePay recovery outcome.
- Enabling a real-money provider executor by default or allowing any executor to bypass Policy Engine approval and Outcome Verifier evidence.
- Giving AI Copilot decision, policy, execution, payment-mutation, clock-advance, audit-authority, or recovery-verification authority.
- Deleting Runtime Source, public API contracts, migrations, or Protected Capabilities based solely on absent navigation, stylistic preference, or an unreviewed static-analysis result.
- Presenting synthetic simulation, read-only projection, browser callback, Action Executor status, or Razorpay Sandbox state as a real payment recovery result.
- Implementing code during requirements creation; implementation is deferred until subsequent approved workflow phases.
