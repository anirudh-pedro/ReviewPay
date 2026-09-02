# Implementation Plan: Judge Demo Experience

## Overview

Implement the validated, additive Judge Demo evidence layer using the existing Python backend and TypeScript frontend contracts. Build source-bound read models and view models first, then compose the judge-facing route and reusable evidence components. The plan deliberately leaves the existing recovery system authoritative: the browser only renders validated server facts or an unavailable-evidence state.

### Non-negotiable constraints — apply to every task

- Do **not** modify existing recovery-workflow semantics, `PolicyEngine` decisions or rules, ERV calculations, Razorpay signature/provider-verification behavior, Autopilot or A–D scenario semantics, Virtual Clock behavior, existing HTTP-contract behavior, or existing test guarantees.
- Do **not** create fake AI, external-model calls, browser-side diagnosis/policy/probability/ERV/outcome logic, or browser business logic that fabricates evidence. Do not label deterministic behavior as AI.
- Keep backend changes strictly additive: new typed read models, read-only routes, and optional audit metadata only. Do not rewrite historical audit rows or insert audit events merely for presentation.
- Never add a guide/Strategy Lab mutation path for payments, cases, actions, outcomes, audit events, or clock state. Retain the existing explicit Razorpay verification and Autopilot operational commands unchanged.
- Render absent, invalid, inconsistent, or unreadable evidence as unavailable; never substitute cached, inferred, generated, or zero-valued facts.

## Tasks

- [ ] 1. Establish the protected-contract baseline and implementation test foundation
  - [ ] 1.1 Add a contract-baseline fixture/snapshot layer that captures the existing recovery, policy, ERV, Razorpay, Autopilot, Virtual Clock, Strategy Lab, audit, and A–D scenario observable contracts before judge-layer additions.
    - Use the current Python test suite and frontend fixtures only; encode the preserved contract rather than changing production behavior.
    - Assert the implementation boundary: no fake AI/model integration and no browser-owned recovery business decisions.
    - _Requirements: 1.3–1.4, 1.8, 13.1; Design: Overview, Scope and non-goals, Testing Strategy > Validation sequence_
  - [ ]* 1.2 Add the pinned judge-demo test tooling and deterministic fixture helpers required by the design (`vitest@2.1.8`, `fast-check@3.23.2`, `@testing-library/react@16.1.0`, `jsdom@25.0.1`, `@playwright/test@1.51.1`, and `hypothesis==6.125.3`), without changing frontend production dependencies.
    - Record pins in the project’s existing package/lock and Python dependency mechanisms; configure one-shot, non-watch test execution.
    - _Requirements: 13.1; Design: Testing Strategy > Test tools and boundaries_

- [ ] 2. Add the strictly additive backend evidence-reference contracts
  - [ ] 2.1 Create `app/schemas/judge_demo.py` response schemas for case and overview evidence references, including discriminated audit/action/outcome/policy references and nullable ambiguity-safe links.
    - Expose relationships and identifiers only; do not add totals, recommendations, calculations, decision booleans, or execution controls.
    - _Requirements: 1.5–1.7, 6.4–6.5, 7.4, 7.7, 9.3–9.9; Design: Architecture > Backend source boundaries, Strictly additive evidence-reference read models; Data Models > Response consistency rules_
  - [ ] 2.2 Add narrowly additive optional audit metadata at the existing emission points: diagnosis provenance for `DIAGNOSIS_COMPLETED` and `action_id` for existing `POLICY_*` audit events.
    - Preserve event types, sequence, timestamps, messages, all existing metadata, policy verdicts, and workflow decisions; leave historic events valid and unmodified when keys are absent.
    - _Requirements: 1.3, 4.1–4.8, 6.1–6.9, 9.5–9.8; Design: Architecture > Backend source boundaries, Strictly additive evidence-reference read models_
  - [ ] 2.3 Implement the read-only judge-evidence projection service and its case/overview evidence-reference GET handlers in `app/services/judge_evidence.py` and `app/api/routes/judge_demo.py`.
    - Resolve only persisted relations; return `null` for absent, duplicate, mismatched, or ambiguous action-to-policy/outcome links rather than guessing.
    - Do not call scoring, ERV, policy evaluation, simulator, workflow, clock, or any write service.
    - _Requirements: 1.1–1.8, 6.3–6.5, 7.4–7.7, 9.1–9.9; Design: Architecture > Backend source boundaries, Strictly additive evidence-reference read models; Error Handling > Missing/invalid/inconsistent evidence_
  - [ ] 2.4 Register the additive judge-demo router under the existing API prefix without changing existing route ordering, paths, handlers, request semantics, or error envelopes.
    - _Requirements: 1.3, 1.5; Design: Architecture > Backend source boundaries_

- [ ] 3. Add the detection-time, read-only Judge Strategy Lab wrapper
  - [ ] 3.1 Factor the existing Strategy Lab evaluation path to add `evaluate_at_detection` and expose `POST /recovery/cases/{case_id}/judge-counterfactual` as a typed, read-only detection-context wrapper.
    - Reuse the existing persisted-detection-context reconstruction, deterministic scorer, ERV calculator, PolicyEngine, and simulator projection; preserve existing `evaluate`, `/simulate`, values, and semantics unchanged.
    - Return only existing option fields plus `evaluation_basis`, `evaluation_case_id`, `read_only`, `data_source`, and `notice`; never invoke Recovery Intelligence/model services or any execution, mutation, audit, or clock operation.
    - _Requirements: 1.3–1.5, 5.1–5.9, 10.1–10.8; Design: Architecture > Backend source boundaries, Strictly additive evidence-reference read models; Correctness Property 4_

- [ ] 4. Extend the typed frontend transport boundary and operational-session handoff
  - [ ] 4.1 Add TypeScript types for the two evidence-reference responses, discriminated source locators, `Evidence<T>`, and the judge counterfactual response while preserving existing public response interfaces and field names.
    - Model unavailable evidence explicitly; retain `Money` objects without browser-side arithmetic.
    - _Requirements: 1.1–1.7, 5.1–5.8, 7.1–7.7, 11.1–11.9; Design: Architecture > Frontend source boundaries, Components and Interfaces > Evidence and source-locator model_
  - [ ] 4.2 Add validated API wrappers for evidence references and judge counterfactuals, plus complete runtime validators for their contracts and all guide-required Razorpay verification payment fields.
    - Route malformed, missing, or inconsistent data through the existing API error path; do not accept unvalidated transport data into presentation components.
    - _Requirements: 1.1–1.7, 3.2–3.7, 5.8, 10.6–10.8, 13.2–13.4; Design: Architecture > Frontend source boundaries; Components and Interfaces > Evidence and source-locator model_
  - [ ] 4.3 Extend `DemoDataContext` with an in-memory latest validated `AutopilotResponse`, explicit read-only publication/clearing APIs, and reset cleanup behavior.
    - Do not persist or synthesize batch data; a direct/reloaded guide must show Autopilot evidence unavailable until the existing operational page has returned a validated response.
    - _Requirements: 1.3–1.4, 8.1–8.11; Design: Architecture > Frontend source boundaries, Progressive Autopilot and audit timeline_

- [ ] 5. Build reusable source-bound evidence primitives and pure mappers
  - [ ] 5.1 Create `Evidence`, `SourceLocator`, `DataSourceDisclosure`, `GuideSection`, unavailable-evidence, and locale-safe formatting components, plus `evidenceViewModels.ts` as the sole response-combination layer.
    - Require at least one API-field or audit sequence/metadata locator for every available display model; use closed enum formatters and return unavailable evidence for missing/mismatched inputs.
    - Do not log or render callback signatures, credentials, contacts, or payment-instrument data.
    - _Requirements: 1.2, 1.6–1.7, 3.7, 4.1–4.8, 11.1–11.9, 12.1–12.4, 12.10; Design: Components and Interfaces > Evidence and source-locator model; Error Handling_
  - [ ] 5.2 Implement the pure `buildNoExecutionProof` view-model predicate and proof card model from validated action evidence, governing policy audit evidence, and ordered post-verdict audit events.
    - Emit a proof only when blocked/escalated status, null execution timestamp, absent action outcome, and no post-verdict `ACTION_EXECUTED`/`ACTION_FAILED` events all hold; otherwise emit incomplete/unavailable evidence.
    - Include locators for governing sequence, `executed_at`, action-specific outcome inspection, and inspected audit range; never infer proof from UI absence or case state.
    - _Requirements: 6.1–6.9, 8.5–8.7, 9.5–9.9, 11.5–11.7, 13.5–13.6; Design: Policy Governor and No-Execution Proof; Correctness Property 3_

- [ ] 6. Compose the Judge Demo surfaces without changing operational semantics
  - [ ] 6.1 Add the lazy `/judge-demo` route, primary “Judge Demo Guide” navigation item, page metadata, and an ordered guide shell with the exact required section sequence.
    - Include section purpose, source disclosure, safe next evidence destination/action, section-local unavailable states, and no reset prerequisite; suppress the shell reset shortcut only on this guide route.
    - _Requirements: 2.1–2.8, 12.3–12.4; Design: Architecture > Frontend source boundaries; Components and Interfaces > Page and section composition_
  - [ ] 6.2 Extract the existing Live Gateway callback/verification presentation into a shared `LiveGatewayJourney` component/hook and reuse it on the dedicated operational page and guide.
    - Keep browser callbacks provisional; after successful existing server verification display only allowed returned failed/captured fields with exact locators. On rejection/unavailability, show only safe errors and no provider/case/recovery claim. Keep raw callback values function-scoped and never log, serialize, or render them.
    - Do not alter order creation, signature checking, provider retrieval, idempotency, payment mutation behavior of the authoritative gateway handler, or Razorpay security behavior.
    - _Requirements: 3.1–3.9, 11.1–11.9; Design: Live Gateway provisional-to-verified state machine; Correctness Property 1_
  - [ ] 6.3 Implement `DeterministicDiagnosis` from validated case/audit/evidence-reference models.
    - Show diagnosis fields only after persisted evidence exists; label rule-based/fallback provenance only from exact references, display pending/unavailable states safely, and never make AI/model claims or calls.
    - _Requirements: 1.2, 1.6–1.7, 4.1–4.8, 11.8–11.9; Design: Deterministic diagnosis and Strategy/ERV presentation; Correctness Property 5_
  - [ ] 6.4 Implement `StrategyEvidence`, the read-only Judge Strategy Lab panel, `PolicyEvidence`, and `NoExecutionProof` presentation using backend-returned option/policy fields and the pure proof mapper.
    - Separate economic ranking from policy eligibility; display backend ERV minor units/formula explanation without recalculation; label non-candidates comparison-only, projections synthetic/read-only, and counterfactual controls read-only before submit.
    - Preserve last confirmed result on safe request error. Do not add action execution, approval override, payment mutation, audit/outcome creation, or clock controls; do not modify PolicyEngine, ERV, or Strategy Lab semantics.
    - _Requirements: 5.1–5.9, 6.1–6.9, 10.1–10.8, 11.3–11.9; Design: Deterministic diagnosis and Strategy/ERV presentation; Policy Governor and No-Execution Proof; Correctness Properties 3–5_
  - [ ] 6.5 Implement `CommandCenterEvidence` as an all-or-unavailable overview/baseline consistency group with record-level evidence locators.
    - Render returned money, rates, counts, ERV, and clock facts only; use locale formatting without calculations. Label baseline uplift as a synthetic deterministic benchmark—not actual recovery—and never recompute aggregates from references.
    - _Requirements: 7.1–7.7, 11.3–11.9; Design: Command Center money and baseline narrative; Correctness Property 2_
  - [ ] 6.6 Implement `AgentStory` and wire the existing Autopilot page to publish its validated existing response and reuse the story renderer.
    - Reveal only returned steps in `run_index` order; bind action, policy, wait/clock, executor, outcome, message, and final state to response/audit locators. Preserve Scenario A–D meanings, suppress claims on case errors, and never invoke Autopilot, advance the clock, or change scenario behavior from the guide.
    - _Requirements: 1.3–1.4, 2.5, 8.1–8.11, 11.3–11.9; Design: Progressive Autopilot and audit timeline; Correctness Property 6_
  - [ ] 6.7 Implement `JudgeAuditTimeline` that sequence-sorts immutable audit records and maps only supported evidence nodes for detection through outcome/stopping.
    - Distinguish executor status from verified outcomes; display recovered amounts only from a matching recovered, nonzero outcome. Render explicit missing/unavailable nodes rather than invented chronology and do not mutate audit data.
    - _Requirements: 1.2, 1.6–1.8, 9.1–9.9, 11.5–11.9; Design: Components and Interfaces > Page and section composition; Progressive Autopilot and audit timeline; Correctness Property 5_
  - [ ] 6.8 Apply the shared fintech evidence visual tokens, semantic structure, keyboard/focus behavior, safe retry/error preservation, reduced-motion behavior, and responsive layouts to all judge components.
    - Pair every state color with text, icon/shape, and accessible label; keep 320–767px cards single-column with reachable disclosures/controls and horizontally accessible tables; preserve fact order/meaning at 768px+.
    - _Requirements: 11.1–11.9, 12.1–12.10; Design: Components and Interfaces > Evidence and source-locator model; Progressive Autopilot and audit timeline; Error Handling_

- [ ] 7. Add backend property and integration regression coverage
  - [ ]* 7.1 Add Hypothesis property tests (minimum 100 cases per property) for evidence-reference projections, ambiguous-link nulling, no-write GET behavior, optional audit metadata compatibility, and source-closure inputs.
    - Include required feature/property tags. Assert read views leave `Payment`, `RecoveryCase`, `RecoveryAction`, `RecoveryOutcome`, `AuditEvent`, `GatewayWebhookEvent`, `PaymentAttempt`, and `VirtualClock` unchanged.
    - _Requirements: 1.3–1.8, 6.3–6.5, 9.8–9.9, 13.1, 13.5–13.7; Design: Correctness Properties 3–5; Testing Strategy > Proposed test files_
  - [ ]* 7.2 Extend Strategy Lab and Command Center integration tests for detection-time wrapper referential transparency, exact overview/baseline field preservation, unreadable global-metric unavailability, and repeated deterministic responses.
    - Snapshot persisted recovery/audit/clock state before and after Strategy Comparison/counterfactual calls; retain existing Strategy Lab behavior and prove A–D outcomes are unchanged after guide reads.
    - _Requirements: 5.1–5.9, 7.1–7.7, 10.1–10.8, 13.7–13.9; Design: Correctness Properties 2, 4, and 6; Testing Strategy > Proposed test files_
  - [ ]* 7.3 Extend existing Razorpay gateway integration tests for invalid signature, provider retrieval, order/payment relationship, amount, and currency cases.
    - Prove rejected verification creates no `GatewayWebhookEvent`, `PaymentAttempt`, or `RecoveryCase`; preserve gateway signature security, idempotency, safe error contracts, and authoritative behavior.
    - _Requirements: 3.2–3.9, 11.2, 11.6–11.7, 13.1–13.4, 13.11; Design: Correctness Property 1; Testing Strategy > Proposed test files_
  - [ ]* 7.4 Extend workflow and policy integration tests to prove blocked/escalated actions do not execute and audit metadata additions preserve existing sequences, fields, and deterministic scenario behavior.
    - Assert unchanged payment status/attempt count, null action execution timestamp, absent outcome, and zero post-verdict `ACTION_EXECUTED`/`ACTION_FAILED` events where policy refuses execution; retain existing Autopilot, Virtual Clock, policy, and A–D tests.
    - _Requirements: 1.3, 6.3–6.9, 8.3–8.11, 13.1, 13.5–13.6; Design: Correctness Properties 3 and 6; Testing Strategy > Proposed test files_

- [ ] 8. Add frontend property, component, and browser regression coverage
  - [ ]* 8.1 Add `evidenceViewModels` property tests (minimum 100 cases per property) for callback authority, metric all-or-unavailable gating, no-execution iff behavior, enum-only labels, no recovered claim without verified outcome, and source-closure/unavailable fallbacks.
    - _Requirements: 1.2, 1.4, 1.6–1.7, 3.2–3.6, 5.1–5.8, 6.3–6.5, 7.1–7.7, 11.5–11.9, 13.2, 13.5, 13.8; Design: Correctness Properties 1–5; Testing Strategy > Proposed test files_
  - [ ]* 8.2 Add component tests for the guide and shared Live Gateway state machine: ordered navigation, per-section/global error behavior, disclosures, reset independence, provisional/verified/rejected/captured branches, and no read-only execution controls.
    - Inspect rendered DOM, logs, and serialized browser-visible state to prove no Razorpay secret, webhook secret, non-public provider credential, customer contact detail, or payment-instrument credential leaks.
    - _Requirements: 2.1–2.8, 3.1–3.9, 10.1–10.8, 11.1–11.9, 13.2–13.4, 13.11; Design: Live Gateway provisional-to-verified state machine; Error Handling; Testing Strategy > Proposed test files_
  - [ ]* 8.3 Add component/property tests for `AgentStory` and `JudgeAuditTimeline` covering run-index/sequence ordering, locator completeness, missing-event/error suppression, execution-versus-outcome distinction, reduced-motion status announcements, and deterministic Scenario A–D outcomes.
    - Prove guide rendering and read-only evidence navigation do not mutate scenarios, Autopilot results, recovery records, audit state, or Virtual Clock state.
    - _Requirements: 8.1–8.11, 9.1–9.9, 11.3–11.9, 12.5–12.6, 13.9; Design: Correctness Properties 5–6; Testing Strategy > Proposed test files_
  - [ ]* 8.4 Add Playwright browser coverage at 320px and 768px for keyboard navigation, focus indicators, disclosure reachability, responsive tables, text/icon equivalents for states, accessible source locators/unavailable evidence, safe retries, and reduced motion.
    - _Requirements: 2.1–2.8, 11.1–11.9, 12.1–12.10, 13.10; Design: Testing Strategy > Proposed test files; Validation sequence_

- [ ] 9. Checkpoint — validate additive backend and typed frontend boundaries
  - Ensure all tests pass, ask the user if questions arise.
  - Confirm the implementation has not modified protected recovery, policy, ERV, gateway, Autopilot/scenario, Virtual Clock, or fake-AI/browser-business-logic boundaries.

- [ ] 10. Final checkpoint — complete validation
  - Ensure all tests pass, ask the user if questions arise.
  - Run the full backend pytest/Hypothesis suite, one-shot frontend unit/property suite, frontend typecheck/build, Playwright judge-demo browser suite, and retained gateway/command-center/policy/audit/clock/Autopilot/Strategy Lab/scenario/security regressions.
  - _Requirements: 13.1–13.11; Design: Testing Strategy > Validation sequence_

## Notes

- Tasks marked with `*` are optional test tasks. They are included in the dependency graph and should remain coupled to the implementation behavior they validate.
- Every implementation task is additive and source-bound; no task authorizes changing a protected system’s semantics or introducing fake AI/browser business logic.
- All claims must trace to exact validated response fields or immutable audit sequence/metadata fields. Invalid or missing evidence must render unavailable.
- The existing operational Razorpay and Autopilot commands remain the only explicitly user-initiated mutation paths; guide navigation and Strategy Lab/counterfactual presentation remain read-only.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2", "4.1", "4.3"] },
    { "id": 2, "tasks": ["2.3", "4.2"] },
    { "id": 3, "tasks": ["2.4", "3.1", "5.1"] },
    { "id": 4, "tasks": ["5.2", "6.2", "6.3", "6.5", "6.6", "6.7", "7.1", "7.2", "7.3", "7.4"] },
    { "id": 5, "tasks": ["6.4"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["6.8"] },
    { "id": 8, "tasks": ["8.1", "8.2", "8.3"] },
    { "id": 9, "tasks": ["8.4"] }
  ]
}
```
