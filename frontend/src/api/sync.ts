import { requestJson } from './client'

export type SyncSummary = {
  scanned: number
  new: number
  updated: number
  skipped: number
  skipped_already_seen: number
  skipped_groq_failed: number
  skipped_low_confidence: number
  skipped_missing_company: number
  skipped_unknown_status: number
  skipped_duplicate_same_status: number
}

type SyncJobStarted = {
  job_id: string
  status: string
}

type SyncJobStatus =
  | { status: 'running' }
  | { status: 'done'; summary: SyncSummary }
  | { status: 'error'; error: string }

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export async function syncGmail(): Promise<SyncSummary> {
  const started = await requestJson<SyncJobStarted>('/api/sync', { method: 'POST' })
  const jobId = started.job_id
  const maxPolls = 60

  for (let i = 0; i < maxPolls; i++) {
    await sleep(3000)
    const state = await requestJson<SyncJobStatus>(`/api/sync/status/${jobId}`)
    if (state.status === 'done') {
      if (!state.summary) {
        throw new Error('Sync completed without summary')
      }
      return state.summary
    }
    if (state.status === 'error') {
      throw new Error(state.error || 'Sync failed')
    }
  }

  throw new Error('Sync timed out')
}
