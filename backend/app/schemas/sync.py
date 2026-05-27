from pydantic import BaseModel


class SyncJobStarted(BaseModel):
    job_id: str
    status: str


class SyncSummaryOut(BaseModel):
    scanned: int
    new: int
    updated: int
    skipped: int
    skipped_already_seen: int = 0
    skipped_groq_failed: int = 0
    skipped_low_confidence: int = 0
    skipped_missing_company: int = 0
    skipped_unknown_status: int = 0
    skipped_duplicate_same_status: int = 0
