import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.sync import SyncSummaryOut
from app.services.gmail_client import GmailDisconnectedError
from app.services.sync_service import run_gmail_sync

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["Sync"])


@router.post("", response_model=SyncSummaryOut)
def sync_gmail(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.google_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gmail not connected. Connect Gmail in Settings first.",
        )
    user_id = current_user.id
    try:
        summary = run_gmail_sync(db, current_user)
    except GmailDisconnectedError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Gmail disconnected, please reconnect in Settings",
        ) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        _log.exception("Sync failed for user %s", user_id)
        raise HTTPException(status_code=500, detail="Sync failed") from None

    return SyncSummaryOut(
        scanned=summary.scanned,
        new=summary.new,
        updated=summary.updated,
        skipped=summary.skipped,
        skipped_already_seen=summary.skipped_already_seen,
        skipped_groq_failed=summary.skipped_groq_failed,
        skipped_low_confidence=summary.skipped_low_confidence,
        skipped_missing_company=summary.skipped_missing_company,
        skipped_unknown_status=summary.skipped_unknown_status,
        skipped_duplicate_same_status=summary.skipped_duplicate_same_status,
    )
