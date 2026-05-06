from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.application import Application
from app.models.user import User
from app.schemas.application import ApplicationOut

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
