# Requirements Document

## Introduction

`judge-demo-experience` adds a polished, judge-facing evidence layer around RevivePay's existing capabilities. The feature must help a reviewer understand the complete recovery story: a provider-verified Razorpay Sandbox failure, deterministic diagnosis, expected-recovery-value (ERV) comparison, policy governance, execution or refusal, independent verification, audited evidence, and measured synthetic outcomes.

The feature is additive. It must not replace, relax, duplicate, or silently reimplement the deterministic recovery workflow, Razorpay Sandbox integration, Policy_Engine, ERV calculator, Autopilot, Strategy_Lab, Virtual_Clock, seeded scenarios A–D, Audit_Service, security controls, HTTP contracts, or existing test coverage. The browser remains a presentation client: backend responses remain authoritative for diagnosis, probability, ERV, policy, execution, verification, scenario facts, and money values.

The feature has two deliberately distinct narratives:

1. **Razorpay Sandbox journey:** a real Sandbox provider interaction whose local status and failure classification are accepted only after server-side signature verification and authoritative provider retrieval. Razorpay Sandbox is not a live-money system and does not establish a recovery result.
2. **Deterministic simulation journey:** the seeded A–D scenarios, Autopilot, Strategy_Lab, baseline comparison, and recovery executor outcomes. These are synthetic, deterministic, and explicitly not real payment results.

No screen in this feature may invent an AI capability, a failure cause, a metric, a payment outcome, a policy decision, or a money-recovery claim. A presentation may summarize evidence in human-readable language only when the presentation can identify the persisted or server-returned fact supporting that language.

## Existing Capabilities and Gaps Baseline

| Area | Confirmed existing capability | Judge-facing gap this feature addresses |
| --- | --- | --- |
| Razorpay Sandbox | The API creates idempotent Sandbox orders, verifies checkout and webhook signatures, retrieves authoritative provider order and payment state, persists an allowlisted summary, and opens a Recovery_Case only for verified at-risk failures. | The Live Gateway page ends after server verification or a link to a case; it does not provide one guided, source-labelled failure-to-case journey for a judge. |
| Deterministic recovery | Risk detection, rule-based diagnosis, candidate generation, deterministic prediction, ERV, Policy_Engine, simulator execution, Outcome_Verifier, and immutable audit events already form the recovery pipeline. | Existing screens distribute the explanation across pages and include ambiguous AI-oriented presentation labels despite the deterministic default. |
| Policy safety | Policy outcomes, rule identifiers, reasons, limits, actions, and audit events are persisted. Existing tests prove blocked and escalated actions do not execute. | A judge does not receive a single explicit no-execution proof that joins the policy verdict to the absence of execution and outcome evidence. |
| Command Center | The existing overview supplies revenue at risk, verified recovered revenue, recovery rate, ERV, policy posture, and action/failure breakdowns. The baseline endpoint supplies synthetic uplift. | The Command Center does not provide a single judge-oriented money, recovery, and uplift narrative with source-specific disclosure. |
| Autopilot and scenarios | Autopilot runs the real workflow for deterministic scenarios A–D and progressively reveals backend-returned results. | The current batch presentation does not offer a concise guided agent-story that connects each outcome to the relevant policy, clock, and verification evidence. |
| Case intelligence and audit | Case Detail provides decision, ERV, policy, execution, verification, and a sequence-ordered audit timeline. | The raw event timeline lacks a dedicated evidence-first case narrative that makes the decision chain and refusal proof easy to scan during a demo. |
| Strategy_Lab | The existing read-only endpoint values comparable actions through the real deterministic scorer, ERV calculator, Policy_Engine, and simulator projection. Existing tests verify non-mutation. | The judge experience needs a clearer counterfactual explanation and stronger visible guarantees that simulations are projections, not execution. |
| Frontend foundation | The React Command Center already has routing, error boundaries, typed API clients, responsive layout patterns, loading states, and basic accessibility semantics. | There is no unified Judge_Demo_Guide route, no cross-surface source-disclosure model, and no dedicated presentation regression coverage. |

## Glossary

- **RevivePay**: The existing payment-recovery system and its HTTP API.
- **Judge_Demo_Experience**: The additive frontend and read-only presentation layer specified by this document.
- **Judge_Demo_Guide**: A guided route that directs a reviewer through verified evidence in a defined sequence.
- **Command_Center**: The existing executive dashboard that presents recovery metrics and operational summaries.
- **Live_Gateway_Journey**: A guided presentation of one Razorpay Sandbox checkout result from browser callback through server verification and optional Recovery_Case creation.
- **Razorpay_Sandbox**: The isolated Razorpay test environment used by the existing gateway integration; no live money moves through Razorpay_Sandbox.
- **Gateway_Verification**: Server-side checkout-signature or webhook-signature validation followed by retrieval and consistency checks against provider order and payment state.
- **Provider_State**: The authoritative Razorpay order and payment state obtained by the server after Gateway_Verification.
- **Deterministic_Recovery_Engine**: The existing Risk_Detector, deterministic diagnosis, candidate generation, deterministic predictor, ERV calculator, Decision_Engine, Policy_Engine, Action_Executor, Outcome_Verifier, and workflow orchestration boundary.
- **Deterministic_Diagnosis**: The existing rule-based diagnosis containing failure reason, category, transience, escalation requirement, and explanation.
- **Evidence_Bound_Explanation**: Human-readable text that identifies a specific API field, persisted diagnosis, policy result, audit event, or verified Provider_State as its source.
- **Expected_Recovery_Value**: The existing backend-calculated value `recovery_probability × payment_amount − intervention_cost − customer_friction_penalty` in Minor_Units.
- **Strategy_Comparison**: A read-only, backend-evaluated ranking of comparable recovery actions with probability, cost, friction, ERV, policy verdict, and deterministic simulation projection.
- **Counterfactual**: A read-only projection comparing actions against the same stored detection-time context.
- **Policy_Governor**: The existing Policy_Engine and the judge-facing presentation of its outcome, rule, reason, and configured limits.
- **No_Execution_Proof**: Evidence that a blocked or escalated decision did not reach Action_Executor, formed only from the persisted action, outcome, and audit records.
- **Autopilot**: The existing deterministic batch service that drives eligible non-terminal Recovery_Case records through the existing workflow.
- **Agent_Story**: A progressive visual narrative of an Autopilot response using only returned workflow stages, policy results, clock advances, execution results, and verified outcomes.
- **Case_Intelligence_Timeline**: A source-linked, sequence-ordered presentation of a Recovery_Case decision chain and Audit_Event records.
- **Audit_Event**: An immutable, persisted workflow record with a sequence number, stage, event type, message, metadata, and timestamp.
- **A_D_Scenarios**: The existing deterministic seeded demo cases A, B, C, and D.
- **Synthetic_Simulation**: Deterministic seeded data and Payment_Simulator results that do not represent real customer payments or real recovery performance.
- **Verified_Outcome**: A Recovery_Outcome determined by Outcome_Verifier from persisted payment state rather than an executor claim.
- **Data_Source_Disclosure**: A visible statement identifying whether displayed evidence comes from Razorpay_Sandbox, Synthetic_Simulation, or a read-only projection.
- **Accessibility_Contract**: The keyboard, semantic, color, motion, focus, screen-reader, and responsive behaviors required by this document.
- **Minor_Units**: Integer currency amounts in the smallest denomination, paise for INR.

## Requirements


### Requirement 1: Additive Evidence-Layer Boundary

**User Story:** As a judge, I want the WOW presentation to expose the existing recovery system rather than a parallel demo engine, so that every visible result remains trustworthy.

#### Acceptance Criteria

1. THE Judge_Demo_Experience SHALL obtain recovery decisions, policy results, execution results, verified outcomes, audit events, Autopilot results, Strategy_Comparison values, and overview metrics only from existing typed API responses.
2. THE Judge_Demo_Experience SHALL bind every displayed diagnosis, decision, policy result, execution result, verification result, scenario fact, monetary value, count, percentage, and narrative claim to the exact existing typed API response field or to an Audit_Event sequence number and metadata field.
3. THE Judge_Demo_Experience SHALL preserve the behavior and public contracts of the Deterministic_Recovery_Engine, Razorpay_Sandbox gateway, Policy_Governor, Expected_Recovery_Value calculator, Autopilot, Strategy_Comparison endpoint, Virtual_Clock, A_D_Scenarios, Audit_Event workflow, and existing HTTP endpoints.
4. THE Judge_Demo_Experience SHALL perform no probability calculation, Expected_Recovery_Value arithmetic, policy evaluation, simulated-outcome calculation, payment-status mutation, Virtual_Clock advancement, or recovery execution in browser code.
5. WHEN an existing typed API response lacks an exact fact required by a Judge_Demo_Guide view, THE Judge_Demo_Experience SHALL obtain the fact only from an additive typed read model or an existing read-only endpoint without changing the underlying recovery decision.
6. IF an exact typed response field or an Audit_Event record required for a displayed claim is absent, inconsistent, or unreadable, THEN THE Judge_Demo_Experience SHALL render an explicit unavailable-evidence state and SHALL not render a generated substitute value, inferred value, or fabricated narrative.
7. WHEN a Judge_Demo_Experience view renders facts from more than one endpoint, THE Judge_Demo_Experience SHALL display a source locator for each fact that identifies the exact typed response and field or the Audit_Event sequence number and metadata field from which the fact was rendered.
8. WHEN a judge visits a read-only Judge_Demo_Experience view, THE Judge_Demo_Experience SHALL leave the persisted Payment, Recovery_Case, RecoveryAction, Recovery_Outcome, Audit_Event, GatewayWebhookEvent, PaymentAttempt, and Virtual_Clock state unchanged, except for immutable access-audit logging when the existing system is configured to record access events; immutable access-audit logging SHALL not change recovery, payment, or Virtual_Clock state.

### Requirement 2: Guided Judge Demo Flow

**User Story:** As a judge, I want a concise guided flow through RevivePay’s strongest evidence, so that I can understand the product without locating and sequencing separate screens.

#### Acceptance Criteria

1. THE Judge_Demo_Guide SHALL provide a dedicated entry point from the primary application navigation.
2. THE Judge_Demo_Guide SHALL present the ordered sections Command_Center, Live_Gateway_Journey, deterministic recovery, Strategy_Comparison, Policy_Governor, Autopilot, and Case_Intelligence_Timeline.
3. WHEN the Judge_Demo_Guide presents a section, THE Judge_Demo_Guide SHALL display the section purpose, a Data_Source_Disclosure naming the exact typed response or Audit_Event evidence, and the next evidence-bearing action or destination.
4. WHEN Razorpay_Sandbox is unavailable according to the existing typed availability response or safe existing error response, THE Judge_Demo_Guide SHALL mark Live_Gateway_Journey as unavailable and SHALL keep the deterministic recovery sections usable.
5. WHEN an existing A_D_Scenarios response contains scenarios A, B, C, and D, THE Judge_Demo_Guide SHALL identify Scenario A as delayed recovery, Scenario B as recovery-budget stopping, Scenario C as high-value escalation, and Scenario D as alternative-payment-method recovery.
6. IF an authenticated demo reset is unavailable, THEN THE Judge_Demo_Guide SHALL not offer a reset control as a prerequisite for inspecting evidence.
7. WHEN the Judge_Demo_Guide presents an actionable control, THE Judge_Demo_Guide SHALL describe the control as a user-initiated operational action and SHALL distinguish the control from a read-only evidence view before the control is activated.
8. WHEN a section lacks the typed response or Audit_Event evidence required by the section, THE Judge_Demo_Guide SHALL mark the section evidence unavailable and SHALL keep the ordered guide navigable.

### Requirement 3: Server-Verified Razorpay Sandbox Failure Journey

**User Story:** As a judge, I want to see a Razorpay Sandbox failure enter RevivePay through verified provider state, so that the gateway claim has a concrete security boundary.

#### Acceptance Criteria

1. THE Live_Gateway_Journey SHALL label Razorpay_Sandbox checkout as a separate test-provider interaction and SHALL state that Razorpay_Sandbox is not a live-money flow.
2. WHEN a browser checkout callback arrives, THE Live_Gateway_Journey SHALL render the browser callback as provisional evidence and SHALL not render a verified Provider_State, normalized failure reason, recovered-revenue claim, or Recovery_Case result until Gateway_Verification returns a successful server response.
3. WHEN Gateway_Verification returns a successful response containing a failed Provider_State and a Recovery_Case identifier, THE Live_Gateway_Journey SHALL display only the server-returned payment status, normalized failure reason, provider status, and Recovery_Case identifier, each with the exact Gateway_Verification response field as the source locator, before linking to the existing case evidence.
4. WHEN Gateway_Verification returns a successful response containing a captured Provider_State, THE Live_Gateway_Journey SHALL display only the server-returned captured status with the exact Gateway_Verification response field as the source locator and SHALL not claim recovered revenue or a Recovery_Case result.
5. IF Gateway_Verification rejects a callback, webhook, provider retrieval, order relationship, payment relationship, amount relationship, or currency relationship, THEN THE Live_Gateway_Journey SHALL display the server-returned verification failure, SHALL not display a verified payment status, normalized failure reason, Provider_State, or Recovery_Case link, and SHALL not create a judge-facing recovery claim for the rejected interaction.
6. THE Live_Gateway_Journey SHALL obtain every displayed payment status and failure-cause value only from the successful Gateway_Verification response or persisted Recovery_Case evidence and SHALL display the exact response field or Audit_Event sequence and metadata field as the source locator.
7. THE Live_Gateway_Journey SHALL not expose a Razorpay key secret, webhook secret, non-public provider credential, customer contact detail, or payment-instrument credential in browser-visible state, rendered content, client-side logs, or visible error messages.
8. WHEN a verified Razorpay_Sandbox failure opens or reuses a Recovery_Case, THE Live_Gateway_Journey SHALL identify the subsequent recovery evaluation as the existing policy-gated workflow and SHALL not identify the evaluation as a Razorpay charge attempt.
9. WHEN Gateway_Verification rejects an interaction, THE Live_Gateway_Journey SHALL leave the browser presentation without a verified recovery claim, and the rejected interaction SHALL leave no new persisted GatewayWebhookEvent, PaymentAttempt, or Recovery_Case record attributable to the rejected verification.


### Requirement 4: Deterministic and Evidence-Bound Diagnosis

**User Story:** As a judge, I want a clear explanation of why RevivePay diagnosed a failure, so that the explanation is understandable without pretending to be AI-generated.

#### Acceptance Criteria

1. THE Judge_Demo_Experience SHALL wait for persisted Recovery_Case evidence or an existing typed read-only response before displaying any Deterministic_Diagnosis information, including failure reason, category, transience, escalation requirement, and explanation, and SHALL identify the exact response fields or Audit_Event records supporting each displayed value.
2. WHEN persisted diagnosis provenance identifies the existing RuleBasedDiagnosisEngine, THE Judge_Demo_Experience SHALL label the diagnosis source as rule-based deterministic diagnosis.
3. WHEN a diagnosis explanation cites attempt history, failed recovery actions, customer history, or payment state, THE Judge_Demo_Experience SHALL display only the cited facts supplied by Recovery_Context-derived typed response fields or by identified Audit_Event metadata fields.
4. IF a Recovery_Case has no persisted Deterministic_Diagnosis, THEN THE Judge_Demo_Experience SHALL display diagnosis pending and SHALL not infer a failure cause from a payment method, amount, user-interface event, or browser callback.
5. WHEN diagnosis provenance reports fallback behavior, THE Judge_Demo_Experience SHALL display the reported fallback provenance from the exact persisted field or Audit_Event metadata field and SHALL retain the deterministic diagnosis as the recovery authority.
6. THE Judge_Demo_Experience SHALL not label a deterministic diagnosis, deterministic predictor, fixed explanation template, or browser-generated sentence as artificial intelligence.
7. THE Judge_Demo_Experience SHALL not introduce a new external model call, paid model service, generative diagnosis provider, or fabricated model-confidence claim.
8. IF a diagnosis fact or diagnosis provenance field is absent, inconsistent, or unreadable, THEN THE Judge_Demo_Experience SHALL render unavailable evidence for that fact and SHALL not generate a diagnosis explanation or model claim.

### Requirement 5: Strategy and Expected-Recovery-Value Comparison

**User Story:** As a judge, I want to compare the considered recovery options and their economics, so that the selected action is visibly grounded in the existing ERV calculation.

#### Acceptance Criteria

1. THE Judge_Demo_Experience SHALL present Strategy_Comparison options only from the exact typed Strategy_Comparison response fields for action, probability, confidence, gross expected recovery, intervention cost, customer friction penalty, Expected_Recovery_Value, policy outcome, rule identifier, and policy reason.
2. THE Judge_Demo_Experience SHALL display Expected_Recovery_Value as the backend-calculated Minor_Units value returned by the exact typed response field, SHALL identify the existing backend formula, and SHALL not recalculate the value in the browser.
3. WHEN a Strategy_Comparison response identifies a recommended action, THE Judge_Demo_Experience SHALL display the backend-returned recommendation reason and SHALL distinguish the returned policy eligibility from the returned economic ranking.
4. WHEN a Strategy_Comparison response identifies an option that is not a generated candidate, THE Judge_Demo_Experience SHALL label the option as a comparison-only alternative and SHALL not label the option as an executable proposal.
5. WHEN a Strategy_Comparison option has a BLOCKED or ESCALATED Policy_Governor outcome, THE Judge_Demo_Experience SHALL display the exact returned Policy_Governor rule identifier and reason beside that option.
6. WHEN the Judge_Demo_Experience displays a Counterfactual, THE Judge_Demo_Experience SHALL label the Counterfactual as a read-only Synthetic_Simulation projection evaluated on the same detection-time context and SHALL display the exact typed response fields supporting that label.
7. IF a Strategy_Comparison response contains no policy-eligible action, THEN THE Judge_Demo_Experience SHALL display the returned no-recommendation reason and SHALL not promote a BLOCKED or ESCALATED option as an automatic action.
8. IF a required Strategy_Comparison, Counterfactual, policy, or Expected_Recovery_Value response field is absent, inconsistent, or unreadable, THEN THE Judge_Demo_Experience SHALL render unavailable evidence for the affected option or value and SHALL not infer an action, probability, policy verdict, or economic result.
9. WHEN the Judge_Demo_Experience renders a Strategy_Comparison or Counterfactual result, THE Judge_Demo_Experience SHALL leave the persisted Recovery_Case, RecoveryAction, Recovery_Outcome, Audit_Event, and Virtual_Clock state unchanged, SHALL leave Payment state unchanged unless an existing authoritative backend flow requires a Payment state change, and SHALL not create a new mutation path.

### Requirement 6: Policy Governor and No-Execution Proof

**User Story:** As a judge, I want visible proof that policy overrides a high-scoring action when required, so that autonomous recovery appears safe rather than uncontrolled.

#### Acceptance Criteria

1. THE Policy_Governor view SHALL display the selected action, Policy_Governor outcome, deciding rule identifier, reason, relevant configured limit, and resulting Recovery_Case state only from exact authoritative typed response fields or identified Audit_Event records.
2. WHEN a Policy_Governor outcome is APPROVED, THE Policy_Governor view SHALL state that Action_Executor authority begins only after the returned approval and that a recovered-revenue claim still requires identified Verified_Outcome evidence.
3. WHEN a Policy_Governor outcome is BLOCKED or ESCALATED, the associated persisted RecoveryAction has no execution timestamp, no Recovery_Outcome exists for the associated action, and the case audit sequence after the governing policy Audit_Event contains neither ACTION_EXECUTED nor ACTION_FAILED, THE Policy_Governor view SHALL display a No_Execution_Proof.
4. WHEN the Policy_Governor view displays a No_Execution_Proof, THE Policy_Governor view SHALL identify the governing policy Audit_Event sequence number, the associated RecoveryAction execution-timestamp field, the inspected Recovery_Outcome evidence, and the audit-event range inspected for ACTION_EXECUTED and ACTION_FAILED.
5. IF any evidence required for a No_Execution_Proof is absent, inconsistent, or contradictory, THEN THE Policy_Governor view SHALL display incomplete evidence and SHALL not claim that Action_Executor was skipped.
6. WHEN the Policy_Governor view displays Scenario B, THE Policy_Governor view SHALL identify the recovery-budget or retry-limit rule that stopped automatic recovery from the exact Policy_Governor response field or governing Audit_Event metadata field.
7. WHEN the Policy_Governor view displays Scenario C, THE Policy_Governor view SHALL identify the high-value escalation rule and resulting human-handling disposition from the exact Policy_Governor response field or governing Audit_Event metadata field.
8. THE Policy_Governor view SHALL not provide a presentation-only control that changes a BLOCKED or ESCALATED outcome to APPROVED.
9. WHEN a judge views a BLOCKED or ESCALATED policy result, THE Policy_Governor view SHALL leave payment status, payment attempt count, associated RecoveryAction execution timestamp, Recovery_Outcome count, and post-verdict ACTION_EXECUTED and ACTION_FAILED event count unchanged.

### Requirement 7: Command Center Money, Recovery, and Uplift Evidence

**User Story:** As a judge, I want the business value at a glance, so that the recovery engine’s impact is visible without overstating synthetic data.

#### Acceptance Criteria

1. THE Command_Center judge presentation SHALL display revenue at risk, verified revenue recovered, recovery rate, total Expected_Recovery_Value, policy-approved Expected_Recovery_Value, and Virtual_Clock timestamp only from the exact existing typed overview response fields.
2. THE Command_Center judge presentation SHALL display baseline-versus-RevivePay projected recovered revenue, recovery-rate uplift, and Expected_Recovery_Value uplift only from the exact existing typed baseline comparison response fields.
3. WHEN a Command_Center metric is monetary, THE Command_Center judge presentation SHALL display the returned currency and locale-safe rendering of the returned Minor_Units value without performing browser arithmetic.
4. WHEN a Command_Center metric represents verified revenue recovered, THE Command_Center judge presentation SHALL identify the exact overview response field and the referenced Verified_Outcome record or records as the metric source.
5. WHEN a Command_Center metric represents baseline uplift, THE Command_Center judge presentation SHALL label the metric as a Synthetic_Simulation benchmark, SHALL state that the strategy-selection rule differs while the deterministic scorer, valuation, Policy_Governor, and simulator remain shared, and SHALL not label the metric as actual recovered revenue.
6. IF any required overview or baseline response is unavailable, lacks a required field, or contains an unreadable field, THEN THE Command_Center judge presentation SHALL render all judge money, recovery, and uplift metrics as unavailable evidence and SHALL not replace any metric with zero, a cached estimate, or a fabricated uplift.
7. THE Command_Center judge presentation SHALL provide a direct source locator from every displayed policy-block count, escalation count, and recovered-revenue claim to the exact overview or baseline response field and to the corresponding existing case, action, Verified_Outcome, or Audit_Event evidence.


### Requirement 8: Progressive Autopilot Agent Story

**User Story:** As a judge, I want to watch the deterministic batch become an understandable story, so that the A–D outcomes are memorable without being scripted in the browser.

#### Acceptance Criteria

1. THE Agent_Story SHALL build every visible case transition only from an exact typed Autopilot response field, an exact typed Scenario response field, or a linked Audit_Event sequence number and metadata field.
2. WHEN an Autopilot response returns case steps, THE Agent_Story SHALL reveal the case steps in returned run-index order and SHALL preserve the returned selected action, policy outcome, rule identifier, execution status, waiting time, recovered amount, and message with a source locator for each displayed value.
3. WHEN an Autopilot response reports a Virtual_Clock advance, THE Agent_Story SHALL display the returned clock-advance count and the source-bound scheduled waiting evidence and SHALL not advance the Virtual_Clock from browser code.
4. WHEN Scenario A reaches RECOVERED in an existing typed Scenario or Autopilot response, THE Agent_Story SHALL identify RETRY_LATER, the scheduled retry, the Virtual_Clock progression, and the Verified_Outcome amount only from the identified response fields or linked Audit_Event records.
5. WHEN Scenario B reaches STOPPED in an existing typed Scenario or Autopilot response, THE Agent_Story SHALL identify the BLOCKED Policy_Governor outcome.
6. WHEN Scenario B reaches STOPPED in an existing typed Scenario or Autopilot response and the No_Execution_Proof conditions are satisfied, THE Agent_Story SHALL display the No_Execution_Proof.
7. WHEN Scenario C reaches ESCALATED in an existing typed Scenario or Autopilot response, THE Agent_Story SHALL identify the high-value Policy_Governor outcome and the human-handling disposition only from identified response fields or Audit_Event metadata and SHALL not claim a charge or recovery.
8. WHEN Scenario D reaches RECOVERED in an existing typed Scenario or Autopilot response, THE Agent_Story SHALL identify CHANGE_PAYMENT_METHOD and the returned Verified_Outcome amount only from identified response fields or Audit_Event metadata.
9. IF an Autopilot case result contains an error, THEN THE Agent_Story SHALL display the exact returned error and SHALL not synthesize a completion, action, policy result, waiting period, or recovery amount from the error result.
10. IF a required Autopilot, Scenario, Verified_Outcome, or Audit_Event field is absent, inconsistent, or unreadable, THEN THE Agent_Story SHALL render unavailable evidence for the affected step and SHALL not synthesize a transition or final scenario state.
11. WHEN the Agent_Story renders an already-returned Autopilot or Scenario response, THE Agent_Story SHALL leave Payment, Recovery_Case, RecoveryAction, Recovery_Outcome, Audit_Event, and Virtual_Clock persisted state unchanged.

### Requirement 9: Audit-Backed Case Intelligence Timeline

**User Story:** As a judge, I want a clear chronology from failure to outcome or refusal, so that each claim can be inspected against immutable workflow evidence.

#### Acceptance Criteria

1. THE Case_Intelligence_Timeline SHALL order displayed Audit_Event records by persisted sequence number ascending.
2. WHEN corresponding Audit_Event records exist, THE Case_Intelligence_Timeline SHALL present source-linked evidence nodes for revenue risk detection, diagnosis, options evaluated, decision selected, policy verdict, scheduling or execution, verification, recovery, and workflow stopping.
3. WHEN the Case_Intelligence_Timeline presents an Evidence_Bound_Explanation, THE Case_Intelligence_Timeline SHALL link the explanation to an identified Audit_Event sequence number and metadata field or to the exact typed response field supporting the explanation.
4. WHEN decision evidence exists, THE Case_Intelligence_Timeline SHALL display selected action, probability, confidence, Expected_Recovery_Value, alternatives, model version, and recorded decision explanation only from persisted decision metadata or the latest RecoveryAction and SHALL identify the exact source fields.
5. WHEN policy evidence exists, THE Case_Intelligence_Timeline SHALL display the persisted rule identifier, reason, evaluated action, and configured policy limits only from identified Policy_Governor response fields or Audit_Event metadata fields.
6. WHEN verification evidence exists, THE Case_Intelligence_Timeline SHALL distinguish Action_Executor status from Verified_Outcome status and SHALL display a recovered amount only from identified Verified_Outcome evidence.
7. IF an expected event is absent from the Audit_Event sequence, THEN THE Case_Intelligence_Timeline SHALL identify the missing evidence and SHALL not invent a timeline node, event type, event message, or timestamp.
8. THE Case_Intelligence_Timeline SHALL preserve existing immutable audit ordering and SHALL not create, modify, or delete Audit_Event records while rendering a case.
9. IF a required Audit_Event, RecoveryAction, Policy_Governor, or Verified_Outcome field is absent, inconsistent, or unreadable, THEN THE Case_Intelligence_Timeline SHALL render unavailable evidence for the affected node and SHALL not infer the missing decision, policy, execution, verification, or outcome fact.

### Requirement 10: Strengthened Read-Only Strategy Lab

**User Story:** As a judge, I want to test a counterfactual without touching the recovery case, so that strategy exploration remains visibly safe.

#### Acceptance Criteria

1. THE Strategy_Lab judge presentation SHALL identify every evaluation as read-only before submitting a Counterfactual request.
2. WHEN a judge supplies an allowed override, THE Strategy_Lab judge presentation SHALL display the backend-returned effective settings from the exact Counterfactual response fields and SHALL identify the override as scoped to the read-only evaluation.
3. WHEN an override changes policy eligibility or Expected_Recovery_Value, THE Strategy_Lab judge presentation SHALL display the returned comparison values, Policy_Governor outcome, and reason with exact response-field source locators and SHALL not modify the displayed case evidence.
4. WHEN a Strategy_Comparison response returns a simulated outcome projection, THE Strategy_Lab judge presentation SHALL label the projection as deterministic simulation evidence and SHALL not label the projection as a predicted live-money outcome.
5. THE Strategy_Lab judge presentation SHALL not expose a control that executes a Strategy_Comparison action, mutates a Payment, creates a RecoveryAction, records a Recovery_Outcome, appends an Audit_Event, or advances Virtual_Clock time.
6. IF a Counterfactual request fails validation or returns an API error, THEN THE Strategy_Lab judge presentation SHALL preserve the last confirmed read-only result, SHALL display the exact returned error, and SHALL not present an override as applied.
7. WHEN a judge submits a Strategy_Comparison or Counterfactual evaluation, THE Strategy_Lab judge presentation SHALL leave Payment, Recovery_Case, RecoveryAction, Recovery_Outcome, Audit_Event, and Virtual_Clock persisted state unchanged.
8. IF a Strategy_Comparison or Counterfactual field required for a displayed value is absent, inconsistent, or unreadable, THEN THE Strategy_Lab judge presentation SHALL render unavailable evidence and SHALL not infer an effective setting, policy verdict, Expected_Recovery_Value, or simulation result.


### Requirement 11: Real-versus-Simulated Disclosures and Claim Safety

**User Story:** As a judge, I want every value labelled by provenance, so that I can distinguish server-verified Sandbox facts from deterministic simulation and from projections.

#### Acceptance Criteria

1. THE Judge_Demo_Experience SHALL display a Data_Source_Disclosure adjacent to Live_Gateway_Journey, Command_Center uplift, Agent_Story, Strategy_Comparison, Counterfactual, and Case_Intelligence_Timeline evidence.
2. WHEN evidence originates from a successful Gateway_Verification response for Razorpay_Sandbox, THE Judge_Demo_Experience SHALL label the evidence as server-verified Razorpay Sandbox state, SHALL identify the exact response field or persisted Audit_Event field as the source, and SHALL state that Razorpay_Sandbox does not represent live money movement.
3. WHEN evidence originates from Synthetic_Simulation, THE Judge_Demo_Experience SHALL label the evidence as synthetic deterministic simulation, SHALL identify the exact Scenario, Autopilot, baseline, Strategy_Comparison, or Audit_Event source field, and SHALL state that the evidence does not represent real payment recovery performance.
4. WHEN evidence originates from a Counterfactual or baseline comparison, THE Judge_Demo_Experience SHALL label the evidence as a read-only synthetic projection, SHALL identify the exact response field, and SHALL not call the value an actual recovery result.
5. WHEN an identified Verified_Outcome reports recovered true and a nonzero recovered amount, THE Judge_Demo_Experience SHALL call the corresponding returned amount recovered.
6. IF a displayed amount lacks an identified Verified_Outcome reporting recovered true and a nonzero recovered amount, THEN THE Judge_Demo_Experience SHALL not call the amount recovered.
7. IF a displayed payment result is limited to a browser callback, Action_Executor status, or simulation projection, THEN THE Judge_Demo_Experience SHALL label the result as provisional, execution-only, or projection evidence as applicable and SHALL not label the result as verified recovery.
8. THE Judge_Demo_Experience SHALL not display a fabricated intelligence score, business uplift, root cause, customer insight, provider status, or recovery amount.
9. IF provenance or the exact evidence field required by a Data_Source_Disclosure is absent, inconsistent, or unreadable, THEN THE Judge_Demo_Experience SHALL display an unavailable-evidence disclosure and SHALL not infer a real, verified, simulated, or projected provenance.

### Requirement 12: Fintech Visual Quality, Accessibility, and Responsive Behavior

**User Story:** As a judge, I want the demo to feel credible and remain usable under live presentation conditions, so that visual polish does not hide or obstruct evidence.

#### Acceptance Criteria

1. THE Judge_Demo_Experience SHALL use consistent visual tokens to distinguish at-risk money, verified recovery, policy approval, policy blocking, escalation, and unavailable evidence.
2. THE Judge_Demo_Experience SHALL pair every color-coded policy or outcome state with visible text, an icon or shape, and an accessible label.
3. THE Judge_Demo_Experience SHALL provide keyboard-operable navigation, controls, disclosure panels, and focus indicators for every Judge_Demo_Guide interaction.
4. THE Judge_Demo_Experience SHALL expose semantic headings, lists, tables, controls, status messages, source locators, and chart summaries to assistive technology.
5. WHEN a progressive Agent_Story step is revealed, THE Judge_Demo_Experience SHALL announce the returned case state and source-bound evidence summary through a non-disruptive accessible status region.
6. WHERE reduced-motion preference is enabled, THE Judge_Demo_Experience SHALL remove nonessential reveal animation while preserving the same evidence order and source labels.
7. WHEN the viewport width is between 320 and 767 CSS pixels, THE Judge_Demo_Experience SHALL present one-column readable evidence cards, preserve horizontal access to data tables, and keep primary controls and Data_Source_Disclosures reachable without clipped content.
8. WHEN the viewport width is 768 CSS pixels or greater, THE Judge_Demo_Experience SHALL use the available width for comparative evidence without changing the order, source, or meaning of the underlying facts.
9. THE Judge_Demo_Experience SHALL meet WCAG 2.2 AA contrast requirements for normal text, controls, focus indicators, and state labels against the rendered background.
10. IF an API request fails, THEN THE Judge_Demo_Experience SHALL provide an accessible error state that preserves verified data already rendered, preserves displayed source locators for the verified data, and exposes a retry control when a retry is safe.

### Requirement 13: Security, Integrity, and Regression Coverage

**User Story:** As a maintainer, I want automated tests around the judge layer, so that presentation improvements cannot weaken the recovery system or convert synthetic evidence into unsafe claims.

#### Acceptance Criteria

1. THE Test_Suite SHALL retain existing gateway signature, provider-state, idempotency, deterministic recovery, Policy_Governor, audit-ordering, Virtual_Clock, A_D_Scenarios, Autopilot, Strategy_Lab, and security-contract tests.
2. THE Test_Suite SHALL verify that a Live_Gateway_Journey displays a verified failed status, normalized failure reason, provider status, and Recovery_Case reference only after a successful Gateway_Verification response and that the displayed facts name the exact response fields as sources.
3. THE Test_Suite SHALL verify that rejected gateway verification produces no verified payment claim, Provider_State, normalized failure reason, Recovery_Case link, persisted GatewayWebhookEvent, PaymentAttempt, or Recovery_Case mutation.
4. THE Test_Suite SHALL verify that frontend source text, source locators, client-side logs, and serialized browser-visible state contain no Razorpay key secret, webhook secret, non-public provider credential, customer contact detail, or payment-instrument credential.
5. THE Test_Suite SHALL verify that a BLOCKED or ESCALATED Case_Intelligence_Timeline displays No_Execution_Proof only when the associated action, post-verdict audit range, and Recovery_Outcome evidence satisfy the No_Execution_Proof definition and identify the governing policy Audit_Event sequence.
6. THE Test_Suite SHALL verify that a BLOCKED or ESCALATED decision leaves payment status, payment attempt count, action execution timestamp, Recovery_Outcome count, and ACTION_EXECUTED and ACTION_FAILED event count unchanged after the governing policy verdict.
7. THE Test_Suite SHALL verify that a Strategy_Comparison and a Counterfactual request leave Payment, Recovery_Case, RecoveryAction, Recovery_Outcome, Audit_Event, and Virtual_Clock persisted state unchanged.
8. THE Test_Suite SHALL verify that Command_Center revenue, recovery, and uplift displays equal the corresponding exact overview and baseline response fields and that unavailable or unreadable response fields produce unavailable-evidence states rather than numeric substitutes.
9. THE Test_Suite SHALL verify that every Agent_Story step maps to an exact returned Autopilot or Scenario field or linked Audit_Event and that every displayed scenario outcome matches the returned A_D_Scenarios state.
10. THE Test_Suite SHALL verify keyboard access, reduced-motion behavior, responsive rendering at 320 and 768 CSS pixels, accessible status announcements, text equivalents for judge-facing charts and policy states, and accessible source locators and unavailable-evidence states.
11. THE Test_Suite SHALL verify that a browser checkout callback remains provisional until Gateway_Verification returns a successful response and that a browser callback alone cannot produce a verified recovery, recovered-revenue claim, Provider_State, failure cause, or Recovery_Case result.


## Correctness Properties for Test Implementation

### Property 1: Gateway Verification Is the Only Live-Gateway State Authority

For any checkout callback or webhook fixture whose signature, provider retrieval, provider order relationship, provider payment relationship, amount, or currency validation fails, the before-and-after persisted sets of PaymentAttempt, GatewayWebhookEvent, and Recovery_Case records are equal. Any Judge_Demo_Experience state for that fixture contains a verification failure and no verified Provider_State, normalized failure reason, or Recovery_Case link.

### Property 2: Judge Metrics Preserve Backend Values

For every valid combination of overview and baseline response fixtures, every Judge_Demo_Experience money, percentage, count, policy limit, and uplift value equals its named server-response field after formatting. The presentation layer performs no derived monetary arithmetic beyond locale-safe rendering of the returned Minor_Units value.

### Property 3: Policy Refusal Implies No Execution Evidence

For every Recovery_Case whose latest Policy_Governor outcome is BLOCKED or ESCALATED, a displayed No_Execution_Proof exists if and only if the associated RecoveryAction has no execution timestamp, the associated RecoveryAction has no Recovery_Outcome, and the case audit sequence after the governing policy event contains neither ACTION_EXECUTED nor ACTION_FAILED. The proof must name the governing policy event sequence.

### Property 4: Read-Only Counterfactuals Are Referentially Transparent

For every valid ScenarioOverrides request and seeded Recovery_Case, a before-and-after database and clock snapshot is identical after Strategy_Comparison or Counterfactual evaluation. The returned options may differ only according to the request-scoped effective settings; repeated requests with the same case, settings, seed, and Virtual_Clock time return equivalent options and recommendations.

### Property 5: Evidence-Bound Narratives Cannot Invent Facts

For every displayed diagnosis, decision, policy, execution, verification, timeline, or Agent_Story sentence, the view model contains at least one source locator naming an API field or Audit_Event sequence. Rendering must use the unavailable-evidence state when the referenced source is absent.

### Property 6: Guided Demo Preserves Deterministic A–D Outcomes

For any reseed using the same simulation seed and Virtual_Clock start time, running the Judge_Demo_Guide does not modify A_D_Scenarios state. Running the existing Autopilot afterward produces the same A–D final states, selected actions, policy outcomes, recovered amounts, and audit event sequences as a run without a Judge_Demo_Guide visit.

## Non-Goals

- Replacing or modifying the Deterministic_Recovery_Engine, Decision_Engine, Policy_Engine, Expected_Recovery_Value calculator, Action_Executor, Outcome_Verifier, Audit_Service, Virtual_Clock, scenario generator, or existing workflow contracts.
- Sending a recovery action to Razorpay_Sandbox or treating a Razorpay Sandbox provider result as a RevivePay recovery outcome.
- Adding a paid model service, external LLM, generated diagnosis authority, browser-side recovery logic, fake AI label, fabricated metric, fabricated root cause, fabricated customer insight, or unverified live-money claim.
- Changing the semantics of Autopilot, Strategy_Lab, baseline comparison, seeded scenarios A–D, existing API routes, existing error envelopes, or existing security controls.
- Allowing Judge_Demo_Experience, Counterfactual, or Strategy_Lab presentation controls to execute recovery actions, change policy outcomes, advance time, reset data, or mutate persisted recovery records.
- Presenting synthetic projections, executor reports, browser callbacks, or Razorpay Sandbox checkout responses as verified recovered revenue.