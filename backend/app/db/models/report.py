"""Reports: immutable snapshots of the data used to produce them.

A finalised report stores its own payload so the dashboard, the receipt and
the exported file can never disagree — even after the analytics formulas
change, because the analytics version is recorded alongside.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.base import TimestampMixin


class ReportKind(str, enum.Enum):
    SESSION_SUMMARY = "SESSION_SUMMARY"
    PROGRESS_COMPARISON = "PROGRESS_COMPARISON"
    PATIENT_SUMMARY = "PATIENT_SUMMARY"
    CLINICIAN_REPORT = "CLINICIAN_REPORT"


class ReportStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    GENERATING = "GENERATING"
    READY = "READY"
    FAILED = "FAILED"


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))
    baseline_session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))
    kind: Mapped[ReportKind] = mapped_column(Enum(ReportKind), nullable=False)
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus), default=ReportStatus.DRAFT, nullable=False
    )

    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    # Versioning so historical reports stay interpretable.
    analytics_version: Mapped[str | None] = mapped_column(String(32))
    report_version: Mapped[str] = mapped_column(String(32), default="1.0", nullable=False)

    # The frozen payload. Two sections: everything a patient may see, and the
    # clinician-only additions. The API serves them separately by role.
    payload_patient: Mapped[dict | None] = mapped_column(JSON)
    payload_clinician: Mapped[dict | None] = mapped_column(JSON)

    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)

    shares: Mapped[list["ReportShare"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class ReportShare(Base, TimestampMixin):
    """Tokenised, expiring, revocable share link.

    The token is stored only as a hash, so a database read cannot be replayed
    as a working link.
    """

    __tablename__ = "report_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    view_count: Mapped[int] = mapped_column(default=0, nullable=False)
    # Shares are patient-visible content only, never clinician-only sections.
    include_clinician_sections: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    report: Mapped["Report"] = relationship(back_populates="shares")
