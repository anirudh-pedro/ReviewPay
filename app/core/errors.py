"""Domain errors.

Domain code raises these; the API layer maps them to HTTP responses. Nothing
under ``app/services``, ``app/ml``, ``app/workflows``, or ``app/integrations``
imports ``fastapi``, which keeps the domain runnable without an HTTP request or a
FastAPI application instance (Requirement 27.8).
"""

from __future__ import annotations

from app.core.enums import ActionType, CaseState


class RevivePayError(Exception):
    """Base class for every domain error.

    ``code`` is the stable, machine-readable identifier surfaced in the API error
    envelope; ``http_status`` is the status the API layer should return.
    """

    code = "REVIVEPAY_ERROR"
    http_status = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RecordNotFound(RevivePayError):
    """A referenced record does not exist (Requirement 24.8)."""

    code = "NOT_FOUND"
    http_status = 404

    def __init__(self, entity: str, identifier: str) -> None:
        super().__init__(f"{entity} '{identifier}' was not found.")
        self.entity = entity
        self.identifier = identifier


class InvalidStateTransition(RevivePayError):
    """A recovery case was asked to make a transition that is not permitted.

    The message names both the source and the requested target state
    (Requirement 16.8).
    """

    code = "INVALID_STATE_TRANSITION"
    http_status = 409

    def __init__(self, source: CaseState, target: CaseState) -> None:
        super().__init__(
            f"Transition from {source.value} to {target.value} is not permitted."
        )
        self.source = source
        self.target = target


class CaseAlreadyTerminal(RevivePayError):
    """A run was requested for a case that has already reached a terminal state.

    Surfaces as HTTP 409 with the current state (Requirement 17.5, 24.9).
    """

    code = "CASE_TERMINAL"
    http_status = 409

    def __init__(self, case_id: str, state: CaseState) -> None:
        super().__init__(
            f"Recovery case '{case_id}' is in terminal state {state.value}; "
            "no further runs are permitted."
        )
        self.case_id = case_id
        self.state = state


class ActionNotDue(RevivePayError):
    """A scheduled action is not yet due at the current simulation time.

    Not an error condition for callers: the workflow reports this as a waiting
    run rather than raising to the API layer (Requirement 18.5).
    """

    code = "ACTION_NOT_DUE"
    http_status = 200

    def __init__(self, action: ActionType, scheduled_at: str, now: str) -> None:
        super().__init__(
            f"{action.value} is scheduled for {scheduled_at}; simulation time is {now}."
        )
        self.action = action
        self.scheduled_at = scheduled_at
        self.now = now


class UnsupportedAction(RevivePayError):
    """The configured executor cannot perform the requested action."""

    code = "UNSUPPORTED_ACTION"
    http_status = 400

    def __init__(self, action: ActionType) -> None:
        super().__init__(f"Action {action.value} is not supported by the configured executor.")
        self.action = action


__all__ = [
    "ActionNotDue",
    "CaseAlreadyTerminal",
    "InvalidStateTransition",
    "RecordNotFound",
    "RevivePayError",
    "UnsupportedAction",
]
