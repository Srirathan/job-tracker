import { requestJson } from './client'

export type SyncSummary = {
  scanned: number
  new: number
  updated: number
  skipped: number
  skipped_already_seen: number
  skipped_gemini_failed: number
  skipped_low_confidence: number
  skipped_missing_company: number
  skipped_unknown_status: number
  skipped_duplicate_same_status: number
}

export async function syncGmail(): Promise<SyncSummary> {
  return requestJson<SyncSummary>('/api/sync', { method: 'POST' })
}
