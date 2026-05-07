from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.application import Application, ApplicationStatus
from app.models.user import User
from app.schemas.application import ApplicationOut, ApplicationUpsertIn, SheetWebhookUpdateIn
from app.services.normalize import normalize_label
from app.services import sheets_sync
from app.services.sheets_sync import delete_application_row, upsert_application_row

router = APIRouter(prefix="/api/applications", tags=["Applications"])
_log = logging.getLogger(__name__)


def _timing_safe_match(expected: str, provided: str) -> bool:
    e = expected.strip().encode()
    p = provided.strip().encode()
    if not e or not p or len(e) != len(p):
        return False
    return secrets.compare_digest(e, p)


def _parse_sheet_status(raw: str) -> ApplicationStatus:
    s = raw.strip()
    if not s:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status is empty")
    for st in ApplicationStatus:
        if st.value.lower() == s.lower():
            return st
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Invalid status ({s}); use Applied, Interview, OA, Rejected, or Offer.",
    )


@router.get("", response_model=list[ApplicationOut])
def list_applications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Application)
        .where(Application.user_id == current_user.id)
        .order_by(Application.email_date.desc(), Application.id.desc())
    )
    return list(db.scalars(stmt).all())


@router.put("/sheet-update")
def sheet_update_from_apps_script(
    body: SheetWebhookUpdateIn,
    db: Session = Depends(get_db),
    x_sheet_token: Annotated[str | None, Header(alias="X-Sheet-Token")] = None,
):
    expected = (settings.sheet_sync_token or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sheet sync is not configured",
        )

    hdr = x_sheet_token or ""
    if not _timing_safe_match(expected, hdr):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid sheet sync token")

    company_s = body.company.strip()
    role_s = body.role.strip()
    status_trim = body.status.strip()
    if not status_trim:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status is empty")
    want_c = normalize_label(company_s)
    want_r = normalize_label(role_s)
    if not want_c or not want_r:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="company and role resolve to empty after normalization",
        )

    new_status = _parse_sheet_status(status_trim)
    sid_filter = (body.spreadsheet_id or "").strip() or None

    matches: list[Application] = []
    for app in db.scalars(select(Application).options(joinedload(Application.user))).all():
        if normalize_label(app.company) != want_c or normalize_label(app.role) != want_r:
            continue
        if sid_filter:
            eff = sheets_sync.effective_sheet_id(app.user)
            if eff != sid_filter:
                continue
        matches.append(app)

    if not matches:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    owners = {a.user_id for a in matches}
    if len(owners) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Multiple accounts match these fields; send spreadsheet_id in the request body.",
        )

    chosen = max(matches, key=lambda a: (a.updated_at, a.id))
    chosen.status = new_status
    db.add(chosen)
    db.commit()

    disp_company = chosen.company if chosen.company else company_s
    disp_role = chosen.role if chosen.role else role_s
    _log.info("Sheet update: %s - %s - %s", disp_company, disp_role, new_status.value)
    return {"ok": True}


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def create_application(
    body: ApplicationUpsertIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    app = Application(
        user_id=current_user.id,
        gmail_message_id=None,
        email_date=body.date,
        company=body.company.strip(),
        role=body.role.strip(),
        status=body.status,
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    upsert_application_row(current_user, app)
    return app


@router.put("/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: int,
    body: ApplicationUpsertIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    app = db.get(Application, application_id)
    if app is None or app.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    old_company, old_role = app.company, app.role
    app.company = body.company.strip()
    app.role = body.role.strip()
    app.status = body.status
    app.email_date = body.date

    db.add(app)
    db.commit()
    db.refresh(app)

    if normalize_label(old_company) != normalize_label(app.company) or normalize_label(old_role) != normalize_label(
        app.role
    ):
        delete_application_row(current_user, old_company, old_role)

    upsert_application_row(current_user, app)
    return app


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    app = db.get(Application, application_id)
    if app is None or app.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    company, role = app.company, app.role
    db.delete(app)
    db.commit()
    delete_application_row(current_user, company, role)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
