import { useCallback, useEffect, useState } from 'react'
import * as applicationsApi from '../api/applications'
import * as settingsApi from '../api/settings'
import * as syncApi from '../api/sync'
import { StatusBadge } from '../components/StatusBadge'
import type { Application } from '../types/application'

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}

export function ApplicationsPage() {
  const [rows, setRows] = useState<Application[]>([])
  const [error, setError] = useState<string | null>(null)
  const [syncBusy, setSyncBusy] = useState(false)
  const [lastSync, setLastSync] = useState<syncApi.SyncSummary | null>(null)
  const [lookbackDays, setLookbackDays] = useState<number | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await applicationsApi.listApplications()
      setRows(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
      setRows([])
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    void settingsApi
      .getSettings()
      .then((s) => setLookbackDays(s.gmail_sync_lookback_days))
      .catch(() => setLookbackDays(null))
  }, [])

  const onSync = async () => {
    setSyncBusy(true)
    setLastSync(null)
    setError(null)
    try {
      const summary = await syncApi.syncGmail()
      setLastSync(summary)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sync failed')
    } finally {
      setSyncBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Applications</h1>
          <p className="mt-1 text-sm text-slate-500">
            Sync Gmail to extract applications and update your Google Sheet.
            {lookbackDays != null ? (
              <span className="block text-xs text-slate-400">
                Only threads from about the last {lookbackDays} days that match job-related keywords are scanned; older
                mail or different wording may be skipped.
              </span>
            ) : null}
          </p>
        </div>
        <button
          type="button"
          disabled={syncBusy}
          onClick={() => void onSync()}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {syncBusy ? 'Syncing…' : 'Sync Gmail'}
        </button>
      </div>

      {lastSync ? (
        <div className="space-y-2 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-800">
          <p>
            <span className="font-medium text-slate-600">Scanned {lastSync.scanned}</span>
            <span className="mx-2 text-slate-300">·</span>
            {lastSync.new} new · {lastSync.updated} updated · {lastSync.skipped} skipped
          </p>
          {lastSync.skipped > 0 ? (
            <ul className="list-inside list-disc text-xs text-slate-600">
              {lastSync.skipped_already_seen > 0 ? (
                <li>Already processed before: {lastSync.skipped_already_seen}</li>
              ) : null}
              {lastSync.skipped_gemini_failed > 0 ? (
                <li>
                  Gemini failed (missing key, API error, or blocked response): {lastSync.skipped_gemini_failed}
                </li>
              ) : null}
              {lastSync.skipped_low_confidence > 0 ? (
                <li>Low confidence (&lt;60): {lastSync.skipped_low_confidence}</li>
              ) : null}
              {lastSync.skipped_missing_company > 0 ? (
                <li>Missing company: {lastSync.skipped_missing_company}</li>
              ) : null}
              {lastSync.skipped_unknown_status > 0 ? (
                <li>Unknown status from AI: {lastSync.skipped_unknown_status}</li>
              ) : null}
              {lastSync.skipped_duplicate_same_status > 0 ? (
                <li>Duplicate (same status): {lastSync.skipped_duplicate_same_status}</li>
              ) : null}
            </ul>
          ) : null}
        </div>
      ) : null}

      {error ? <p className="text-sm text-rose-600">{error}</p> : null}

      {rows.length === 0 && !error ? (
        <p className="rounded-lg border border-dashed border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-600">
          No applications yet. Click Sync Gmail to start.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Company</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50/80">
                  <td className="whitespace-nowrap px-4 py-3 text-slate-700">{formatDate(r.date)}</td>
                  <td className="px-4 py-3 text-slate-900">{r.company}</td>
                  <td className="px-4 py-3 text-slate-700">{r.role}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={r.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
