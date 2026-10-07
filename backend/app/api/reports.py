"""Report lifecycle: create, generate, read, export, share."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbDep
from app.core.exceptions import Forbidden, NotFound, ReportNotFound, ReportNotReady
from app.core.security import generate_share_token, hash_share_token
from app.db.models.audit import AuditAction
from app.db.models.base import as_utc, utc_iso
from app.db.models.patient import PatientProfile
from app.db.models.report import Report, ReportKind, ReportShare, ReportStatus
from app.db.models.session import Session as SessionModel
from app.services import audit_service, authz, progress_service, report_service

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportCreate(BaseModel):
    patient_id: int
    kind: ReportKind = ReportKind.SESSION_SUMMARY
    session_id: int | None = None
    baseline_session_id: int | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)


class ShareCreate(BaseModel):
    expires_in_hours: int = Field(default=72, ge=1, le=24 * 30)


def _owned(db, user, report: Report):
    patient = authz.get_patient_or_403(db, user, report.patient_id)
    return patient


@router.post("", status_code=status.HTTP_201_CREATED)
def create_report(payload: ReportCreate, user: CurrentUser, db: DbDep):
    patient = authz.get_patient_or_403(db, user, payload.patient_id)

    if payload.idempotency_key:
        existing = db.execute(
            select(Report).where(Report.idempotency_key == payload.idempotency_key)
        ).scalar_one_or_none()
        if existing:
            return {"id": existing.id, "status": existing.status.value}

    report = Report(
        patient_id=patient.id, kind=payload.kind, session_id=payload.session_id,
        baseline_session_id=payload.baseline_session_id, status=ReportStatus.DRAFT,
        idempotency_key=payload.idempotency_key,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return {"id": report.id, "status": report.status.value}


@router.post("/{report_id}/generate")
def generate_report(report_id: int, user: CurrentUser, db: DbDep):
    """Freeze the report payload from persisted session data."""
    report = db.get(Report, report_id)
    if report is None:
        raise ReportNotFound()
    patient = _owned(db, user, report)

    report.status = ReportStatus.GENERATING
    db.flush()

    if report.kind is ReportKind.MOVEMENT_PROGRESS:
        report_service.generate_movement_report(db, report, patient, actor_id=user.id)
        audit_service.record(
            db, action=AuditAction.REPORT_GENERATED, entity_type="report",
            entity_id=report.id, actor_id=user.id, patient_id=patient.id, kind=report.kind.value,
        )
        db.commit()
        db.refresh(report)
        return {"id": report.id, "status": report.status.value,
                "generated_at": utc_iso(report.generated_at)}

    if report.kind is ReportKind.SESSION_SUMMARY and report.session_id:
        session = db.get(SessionModel, report.session_id)
        if session is None or session.patient_id != patient.id:
            raise NotFound("The referenced session does not belong to this patient.")
        patient_payload = report_service.build_session_report(db, session, include_clinical=False)
        clinical_payload = report_service.build_session_report(db, session, include_clinical=True)
        report.analytics_version = session.analytics_version
    else:
        patient_payload = progress_service.compare(
            db, patient,
            baseline_session_id=report.baseline_session_id,
            current_session_id=report.session_id,
        )
        clinical_payload = dict(patient_payload)
        clinical_payload["clinical"] = progress_service.build_progress(db, patient)

    # Both sections stored; the API chooses which to serve, per role.
    report.payload_patient = patient_payload
    report.payload_clinician = clinical_payload
    report.status = ReportStatus.READY
    report.generated_at = datetime.now(timezone.utc)
    report.generated_by = user.id

    audit_service.record(
        db, action=AuditAction.REPORT_GENERATED, entity_type="report",
        entity_id=report.id, actor_id=user.id, patient_id=patient.id, kind=report.kind.value,
    )
    db.commit()
    db.refresh(report)
    return {"id": report.id, "status": report.status.value,
            "generated_at": utc_iso(report.generated_at)}


@router.get("")
def list_reports(
    user: CurrentUser, db: DbDep,
    patient_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    allowed = authz.visible_patient_ids(db, user)
    stmt = select(Report)
    if allowed is not None:
        if not allowed:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        stmt = stmt.where(Report.patient_id.in_(allowed))
    if patient_id is not None:
        authz.get_patient_or_403(db, user, patient_id)
        stmt = stmt.where(Report.patient_id == patient_id)

    rows = db.execute(stmt.order_by(Report.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    patients = {p.id: p for p in db.execute(select(PatientProfile).where(
        PatientProfile.id.in_({r.patient_id for r in rows} or {-1}))).scalars()}
    items = []
    for r in rows:
        payload = r.payload_patient or {}
        summary = payload.get("summary") or {}
        p = patients.get(r.patient_id)
        items.append({
            "id": r.id, "patient_id": r.patient_id, "session_id": r.session_id,
            "kind": r.kind.value, "status": r.status.value,
            "generated_at": utc_iso(r.generated_at),
            "analytics_version": r.analytics_version, "report_version": r.report_version,
            "patient_name": p.name if p else None,
            "provenance": payload.get("provenance") or (p.provenance if p else None),
            "title": payload.get("title"),
            "sessions": summary.get("sessions_completed"),
            "period_days": (payload.get("period") or {}).get("days"),
            "status_label": summary.get("status"),
            "pdf": r.kind is ReportKind.MOVEMENT_PROGRESS and r.status is ReportStatus.READY,
        })
    return {"items": items, "total": len(rows), "limit": limit, "offset": offset}


@router.get("/{report_id}")
def get_report(report_id: int, user: CurrentUser, db: DbDep):
    report = db.get(Report, report_id)
    if report is None:
        raise ReportNotFound()
    patient = _owned(db, user, report)
    if report.status is not ReportStatus.READY:
        raise ReportNotReady()

    # Field visibility is enforced here, at the server.
    if authz.can_view_clinical_detail(db, user, patient):
        payload = report.payload_clinician
    else:
        payload = report.payload_patient
    return {
        "id": report.id, "kind": report.kind.value, "status": report.status.value,
        "generated_at": utc_iso(report.generated_at),
        "analytics_version": report.analytics_version,
        "report_version": report.report_version,
        "payload": payload,
    }


@router.get("/{report_id}/pdf")
def report_pdf(report_id: int, user: CurrentUser, db: DbDep):
    """The report as a PDF, rendered from its frozen payload (role-aware)."""
    from app.services.pdf_report import render_movement_report

    report = db.get(Report, report_id)
    if report is None:
        raise ReportNotFound()
    patient = _owned(db, user, report)
    if report.status is not ReportStatus.READY:
        raise ReportNotReady()
    if report.kind is not ReportKind.MOVEMENT_PROGRESS:
        raise NotFound("Only movement progress reports have a PDF rendering.")
    payload = (report.payload_clinician if authz.can_view_clinical_detail(db, user, patient)
               else report.payload_patient)
    pdf = render_movement_report(payload, report_id=report.id)
    slug = "".join(ch if ch.isalnum() else "-" for ch in (patient.name or "record").lower()).strip("-")
    filename = f"rehabsense-movement-report-{report.id}-{slug[:40] or 'record'}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "private, no-store",
    })


@router.post("/{report_id}/share", status_code=status.HTTP_201_CREATED)
def share_report(report_id: int, payload: ShareCreate, user: CurrentUser, db: DbDep):
    """Create a tokenised, expiring link. Patient-visible sections only."""
    report = db.get(Report, report_id)
    if report is None:
        raise ReportNotFound()
    patient = _owned(db, user, report)
    if not authz.can_edit_patient(db, user, patient):
        raise Forbidden("Only an assigned clinician may share this report.")
    if report.status is not ReportStatus.READY:
        raise ReportNotReady()

    token, digest = generate_share_token()
    share = ReportShare(
        report_id=report.id, token_hash=digest, created_by=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours),
        include_clinician_sections=False,
    )
    db.add(share)
    audit_service.record(
        db, action=AuditAction.REPORT_SHARED, entity_type="report",
        entity_id=report.id, actor_id=user.id, expires_in_hours=payload.expires_in_hours,
    )
    db.commit()
    # The plaintext token is returned exactly once and never stored.
    return {"token": token, "expires_at": utc_iso(share.expires_at)}


@router.delete("/{report_id}/share/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share(report_id: int, share_id: int, user: CurrentUser, db: DbDep) -> None:
    share = db.get(ReportShare, share_id)
    if share is None or share.report_id != report_id:
        raise NotFound("Share link not found.")
    report = db.get(Report, report_id)
    _owned(db, user, report)
    share.revoked = True
    audit_service.record(
        db, action=AuditAction.REPORT_SHARE_REVOKED, entity_type="report_share",
        entity_id=share_id, actor_id=user.id,
    )
    db.commit()


@router.get("/shared/{token}")
def read_shared(token: str, db: DbDep):
    """Public read of a shared report. No authentication, but token-gated.

    Only the patient-visible payload is ever returned here, regardless of who
    created the link.
    """
    share = db.execute(
        select(ReportShare).where(ReportShare.token_hash == hash_share_token(token))
    ).scalar_one_or_none()
    if share is None or share.revoked:
        raise NotFound("This link is not valid.")
    if as_utc(share.expires_at) < datetime.now(timezone.utc):
        raise NotFound("This link has expired.")

    report = db.get(Report, share.report_id)
    if report is None or report.status is not ReportStatus.READY:
        raise ReportNotFound()

    share.view_count += 1
    db.commit()
    return {
        "id": report.id, "kind": report.kind.value,
        "generated_at": utc_iso(report.generated_at),
        "payload": report.payload_patient,
        "shared": True,
    }
