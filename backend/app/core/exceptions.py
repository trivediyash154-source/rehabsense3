"""Structured application errors.

Every failure the client can legitimately act on gets a stable machine code;
unexpected exceptions are caught at the boundary and reported as an opaque
INTERNAL_ERROR so internals never leak.
"""

from __future__ import annotations

from fastapi import HTTPException, status


class AppError(HTTPException):
    code = "INTERNAL_ERROR"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, detail: str | None = None, **context):
        super().__init__(
            status_code=self.status_code,
            detail={"code": self.code, "message": detail or self.default_message, **context},
        )

    default_message = "Something went wrong."


class NotFound(AppError):
    code = "NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    default_message = "Resource not found."


class PatientNotFound(NotFound):
    code = "PATIENT_NOT_FOUND"
    default_message = "Patient not found."


class SessionNotFound(NotFound):
    code = "SESSION_NOT_FOUND"
    default_message = "Session not found."


class ReportNotFound(NotFound):
    code = "REPORT_NOT_FOUND"
    default_message = "Report not found."


class DeviceNotFound(NotFound):
    code = "DEVICE_NOT_FOUND"
    default_message = "Device not found."


class Unauthorized(AppError):
    code = "UNAUTHORIZED"
    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "Authentication required."


class Forbidden(AppError):
    code = "FORBIDDEN"
    status_code = status.HTTP_403_FORBIDDEN
    default_message = "You do not have access to this resource."


class Conflict(AppError):
    code = "CONFLICT"
    status_code = status.HTTP_409_CONFLICT
    default_message = "The request conflicts with the current state."


class SessionAlreadyCompleted(Conflict):
    code = "SESSION_ALREADY_COMPLETED"
    default_message = "This session has already been completed."


class EmailAlreadyRegistered(Conflict):
    code = "EMAIL_ALREADY_REGISTERED"
    default_message = "An account with this email already exists."


class LastSignInMethod(Conflict):
    code = "LAST_SIGN_IN_METHOD"
    default_message = ("This is the only way to sign in to this account. Connect another "
                       "sign-in method first.")


class InvalidSensorPacket(AppError):
    code = "INVALID_SENSOR_PACKET"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    default_message = "Sensor packet failed validation."


class InsufficientData(AppError):
    code = "INSUFFICIENT_DATA"
    status_code = status.HTTP_409_CONFLICT
    default_message = "Not enough recorded data to complete this operation."


class ReportNotReady(AppError):
    code = "REPORT_NOT_READY"
    status_code = status.HTTP_409_CONFLICT
    default_message = "This report has not been generated yet."


class BadRequest(AppError):
    code = "BAD_REQUEST"
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "The request is invalid."


class ConfirmationRequired(BadRequest):
    code = "CONFIRMATION_REQUIRED"
    default_message = "Type DELETE to confirm."


class ActiveAssignments(Conflict):
    code = "ACTIVE_ASSIGNMENTS"
    default_message = ("This account still has active patient assignments. End or hand them "
                       "over before deleting the account.")
