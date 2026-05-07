from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.application import Application
from app.models.user import User
from app.schemas.application import ApplicationOut, ApplicationUpsertIn
from app.services.normalize import normalize_label
from app.services.sheets_sync import delete_application_row, upsert_application_row

router = APIRouter(prefix="/api/applications", tags=["Applications"])


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
