import type { StatusTone } from '@/components/ui';
import type {
  AuditEventType,
  CaseState,
  ExecutionStatus,
  PolicyOutcome,
  RiskLevel,
} from '@/types/api';

/** Presentation-only mappings for server-issued recovery statuses. */
export function caseStateTone(state: CaseState | string): StatusTone {
  switch (state) {
    case 'RECOVERED':
      return 'success';
    case 'ESCALATED':
      return 'violet';
    case 'BLOCKED':
    case 'FAILED':
      return 'danger';
    case 'STOPPED':
      return 'neutral';
    case 'DETECTED':
    case 'DIAGNOSING':
    case 'DIAGNOSED':
    case 'EVALUATING':
    case 'DECISION_READY':
    case 'POLICY_CHECK':
      return 'warning';
    case 'APPROVED':
    case 'SCHEDULED':
    case 'EXECUTING':
    case 'VERIFYING':
      return 'info';
    default:
      return 'neutral';
  }
}

export function policyOutcomeTone(outcome: PolicyOutcome | string | null | undefined): StatusTone {
  switch (outcome) {
    case 'APPROVED':
      return 'success';
    case 'BLOCKED':
      return 'danger';
    case 'ESCALATED':
      return 'violet';
    default:
      return 'neutral';
  }
}

export function riskLevelTone(level: RiskLevel | string | null | undefined): StatusTone {
  switch (level) {
    case 'HIGH':
      return 'danger';
    case 'MEDIUM':
      return 'warning';
    case 'LOW':
      return 'info';
    default:
      return 'neutral';
  }
}

export function executionStatusTone(status: ExecutionStatus | string | null | undefined): StatusTone {
  switch (status) {
    case 'SUCCEEDED':
      return 'success';
    case 'FAILED':
      return 'danger';
    case 'ESCALATED':
      return 'violet';
    case 'SCHEDULED':
      return 'info';
    case 'STOPPED':
      return 'neutral';
    default:
      return 'neutral';
  }
}

export function auditEventTone(eventType: AuditEventType | string): StatusTone {
  switch (eventType) {
    case 'REVENUE_RECOVERED':
    case 'OUTCOME_VERIFIED':
    case 'POLICY_APPROVED':
      return 'success';
    case 'POLICY_ESCALATED':
      return 'violet';
    case 'POLICY_BLOCKED':
    case 'ACTION_FAILED':
      return 'danger';
    case 'WORKFLOW_STOPPED':
      return 'neutral';
    default:
      return 'info';
  }
}
