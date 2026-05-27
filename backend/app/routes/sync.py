import secrets
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.config import settings
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.sync import SyncJobStarted
from app.services.sync_service import _jobs, get_job_state, run_gmail_sync_background

router = APIRouter(prefix="/api/sync", tags=["Sync"])


@router.post("", response_model=SyncJobStarted)
def sync_gmail(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    if not current_user.google_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gmail not connected. Connect Gmail in Settings first.",
        )
    job_id = secrets.token_hex(16)
    started_at = datetime.now(timezone.utc).isoformat()
    _jobs[job_id] = {
        "status": "running",
        "summary": None,
        "error": None,
        "started_at": started_at,
        "finished_at": None,
    }
    background_tasks.add_task(
        run_gmail_sync_background,
        job_id,
        settings.database_url,
        current_user.id,
    )
    return SyncJobStarted(job_id=job_id, status="running")


@router.get("/status/{job_id}")
def sync_status(
    job_id: str,
    _current_user: User = Depends(get_current_user),
):
    job = get_job_state(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job["status"] == "running":
        return {"status": "running"}
    if job["status"] == "done":
        summary = job["summary"]
        return {"status": "done", "summary": asdict(summary) if summary is not None else None}
    return {"status": "error", "error": job.get("error")}
