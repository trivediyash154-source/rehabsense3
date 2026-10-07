"""SQLAlchemy models.

Importing this package registers every table on `Base.metadata`, which is what
Alembic autogenerate and the test fixtures rely on.
"""

from app.db.models.audit import AuditLog  # noqa: F401
from app.db.models.device import Device, Sensor  # noqa: F401
from app.db.models.exercise import Exercise, ExercisePlan, ExercisePlanItem  # noqa: F401
from app.db.models.identity import OAuthStateUse, UserIdentity  # noqa: F401
from app.db.models.focus import (  # noqa: F401
    FocusEvent,
    FocusEventKind,
    FocusReminder,
    FocusSession,
    FocusStatus,
)
from app.db.models.notification import Notification  # noqa: F401
from app.db.models.patient import PatientAssignment, PatientProfile  # noqa: F401
from app.db.models.report import Report, ReportShare  # noqa: F401
from app.db.models.sensing import (  # noqa: F401
    ActivityResult,
    DataUseConsent,
    DeviceCalibration,
    ModelVersion,
    MovementAssessment,
    PatientBaseline,
    Recording,
    RecordingArtifact,
    RepetitionResult,
    SensorSampleChunk,
    SessionLabel,
    SessionMarker,
)
from app.db.models.session import (  # noqa: F401
    MetricSnapshot,
    RepEvent,
    RiskFlag,
    Session,
    SessionDeviceLink,
)
from app.db.models.user import User  # noqa: F401

__all__ = [
    "ActivityResult",
    "AuditLog",
    "DataUseConsent",
    "DeviceCalibration",
    "ModelVersion",
    "MovementAssessment",
    "PatientBaseline",
    "Recording",
    "RecordingArtifact",
    "RepetitionResult",
    "SensorSampleChunk",
    "SessionLabel",
    "SessionMarker",
    "Device",
    "FocusEvent",
    "FocusReminder",
    "FocusSession",
    "Sensor",
    "Exercise",
    "ExercisePlan",
    "ExercisePlanItem",
    "Notification",
    "PatientProfile",
    "PatientAssignment",
    "Report",
    "ReportShare",
    "Session",
    "SessionDeviceLink",
    "MetricSnapshot",
    "RepEvent",
    "RiskFlag",
    "User",
    "UserIdentity",
    "OAuthStateUse",
]
