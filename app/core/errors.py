"""Domain-safe errors mapped to stable API error envelopes."""

from __future__ import annotations

from app.core.enums import ActionType, CaseState


class RevivePayError(Exception):
    code = "REVIVEPAY_ERROR"
    http_status = 500
    headers: dict[str, str] | None = None

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RecordNotFound(RevivePayError):
    code = "NOT_FOUND"
    http_status = 404

    def __init__(self, entity: str, identifier: str) -> None:
        super().__init__(f"{entity} '{identifier}' was not found.")
        self.entity = entity
        self.identifier = identifier


class InvalidStateTransition(RevivePayError):
    code = "INVALID_STATE_TRANSITION"
    http_status = 409

    def __init__(self, source: CaseState, target: CaseState) -> None:
        super().__init__(f"Transition from {source.value} to {target.value} is not permitted.")
        self.source = source
        self.target = target


class CaseAlreadyTerminal(RevivePayError):
    code = "CASE_TERMINAL"
    http_status = 409

    def __init__(self, case_id: str, state: CaseState) -> None:
        super().__init__(f"Recovery case '{case_id}' is in terminal state {state.value}; no further runs are permitted.")
        self.case_id = case_id
        self.state = state


class ActionNotDue(RevivePayError):
    code = "ACTION_NOT_DUE"
    http_status = 200

    def __init__(self, action: ActionType, scheduled_at: str, now: str) -> None:
        super().__init__(f"{action.value} is scheduled for {scheduled_at}; simulation time is {now}.")
        self.action = action
        self.scheduled_at = scheduled_at
        self.now = now


class UnsupportedAction(RevivePayError):
    code = "UNSUPPORTED_ACTION"
    http_status = 400

    def __init__(self, action: ActionType) -> None:
        super().__init__(f"Action {action.value} is not supported by the configured executor.")
        self.action = action


__all__ = ["ActionNotDue", "CaseAlreadyTerminal", "InvalidStateTransition", "RecordNotFound", "RevivePayError", "UnsupportedAction"]
