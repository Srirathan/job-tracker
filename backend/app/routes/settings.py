import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.seen_message import SeenMessageId
from app.models.user import User
from app.schemas.settings import RebuildSheetOut, SettingsOut, SheetIdUpdate
from app.services.sheets_sync import effective_sheet_id, rebuild_sheet

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["Settings"])


def _gmail_lookback_days() -> int:
    try:
        return max(1, min(int(settings.gmail_sync_newer_than_days), 120))
    except (TypeError, ValueError):
        return 30


def _settings_out(user: User) -> SettingsOut:
    stored = (user.google_sheet_id or "").strip()
    env_id = (settings.google_sheet_id or "").strip()
    sheet_id = stored or env_id
    return SettingsOut(
        gmail_connected=bool(user.google_refresh_token),
        sheet_id=sheet_id,
        sheet_id_from_env=bool(sheet_id) and not bool(stored),
        last_synced_at=user.last_synced_at,
        gmail_sync_lookback_days=_gmail_lookback_days(),
    )


@router.get("", response_model=SettingsOut)
def get_settings(current_user: User = Depends(get_current_user)):
    return _settings_out(current_user)


@router.put("/sheet-id", response_model=SettingsOut)
def update_sheet_id(
    payload: SheetIdUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    raw = (payload.google_sheet_id or "").strip()
    current_user.google_sheet_id = raw or None
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return _settings_out(current_user)


@router.post("/rebuild-sheet", response_model=RebuildSheetOut)
def rebuild_sheet_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not effective_sheet_id(current_user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Configure a Google Sheet ID in Settings or GOOGLE_SHEET_ID in .env.",
        )
    if not current_user.google_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google account not connected.",
        )
    try:
        n = rebuild_sheet(db, current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        _log.exception("Rebuild sheet failed for user %s", current_user.id)
        raise HTTPException(status_code=500, detail="Rebuild failed") from None

    return RebuildSheetOut(ok=True, rows_written=n)


@router.post("/clear-processed-emails", status_code=status.HTTP_204_NO_CONTENT)
def clear_processed_gmail_messages(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Forget which Gmail messages were already processed so the next sync can try them again."""
    db.execute(delete(SeenMessageId).where(SeenMessageId.user_id == current_user.id))
    db.commit()
