import { requestJson } from './client'

export type Settings = {
  gmail_connected: boolean
  sheet_id: string
  sheet_id_from_env: boolean
  last_synced_at: string | null
  gmail_sync_lookback_days: number
}

export async function getSettings(): Promise<Settings> {
  return requestJson<Settings>('/api/settings')
}

export async function updateSheetId(google_sheet_id: string): Promise<Settings> {
  return requestJson<Settings>('/api/settings/sheet-id', {
    method: 'PUT',
    body: JSON.stringify({ google_sheet_id }),
  })
}

export type RebuildResult = { ok: boolean; rows_written: number }

export async function rebuildSheet(): Promise<RebuildResult> {
  return requestJson<RebuildResult>('/api/settings/rebuild-sheet', { method: 'POST' })
}

export async function startGmailOAuth(): Promise<{ authorization_url: string }> {
  return requestJson<{ authorization_url: string }>('/api/gmail/oauth/start', { method: 'POST' })
}

export async function disconnectGmail(): Promise<void> {
  await requestJson<void>('/api/gmail/disconnect', { method: 'POST' })
}

export async function clearProcessedEmails(): Promise<void> {
  await requestJson<void>('/api/settings/clear-processed-emails', { method: 'POST' })
}
