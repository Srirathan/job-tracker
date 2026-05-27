import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import * as settingsApi from '../api/settings'

function formatTs(iso: string | null): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString()
  } catch {
    return iso
  }
}

export function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [settings, setSettings] = useState<settingsApi.Settings | null>(null)
  const [sheetInput, setSheetInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const s = await settingsApi.getSettings()
      setSettings(s)
      setSheetInput(s.sheet_id)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load settings')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (searchParams.get('gmail') === 'connected') {
      void load()
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams, load])

  const onConnectGmail = async () => {
    setError(null)
    try {
      const { authorization_url: url } = await settingsApi.startGmailOAuth()
      window.location.assign(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start Gmail connection')
    }
  }

  const onDisconnectGmail = async () => {
    setBusy(true)
    setError(null)
    try {
      await settingsApi.disconnectGmail()
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Disconnect failed')
    } finally {
      setBusy(false)
    }
  }

  const onSaveSheet = async () => {
    setBusy(true)
    setError(null)
    try {
      const s = await settingsApi.updateSheetId(sheetInput.trim())
      setSettings(s)
      setSheetInput(s.sheet_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  const onRebuild = async () => {
    if (!window.confirm('Clear all data rows in the Sheet (below row 5) and rewrite from the database?')) return
    setBusy(true)
    setError(null)
    try {
      const r = await settingsApi.rebuildSheet()
      window.alert(`Rebuilt sheet: ${r.rows_written} row(s) written.`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Rebuild failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Settings</h1>
        <p className="mt-1 text-sm text-slate-500">Gmail, Google Sheet, and sync status.</p>
      </div>

      {error ? <p className="text-sm text-rose-600">{error}</p> : null}

      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-semibold text-slate-900">Gmail</h2>
        <p className="text-xs text-slate-500">
          Sync searches roughly the last{' '}
          <span className="font-medium text-slate-700">{settings?.gmail_sync_lookback_days ?? '—'}</span> days of mail
          (job-related keywords). Change <code className="rounded bg-slate-100 px-1">GMAIL_SYNC_NEWER_THAN_DAYS</code> in
          backend <code className="rounded bg-slate-100 px-1">.env</code> (1–120), then restart the API.
        </p>
        <p className="text-sm text-slate-600">
          Status:{' '}
          <span className="font-medium text-slate-900">
            {settings?.gmail_connected ? 'Connected' : 'Disconnected'}
          </span>
        </p>
        {settings?.gmail_connected ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => void onDisconnectGmail()}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-50"
          >
            Disconnect Gmail
          </button>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={() => void onConnectGmail()}
            className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Connect Gmail
          </button>
        )}
      </section>

      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-semibold text-slate-900">Google Sheet</h2>
        <p className="text-xs text-slate-500">
          Tab must be named <code className="rounded bg-slate-100 px-1">Applications</code>. You can set an ID here or
          use <code className="rounded bg-slate-100 px-1">GOOGLE_SHEET_ID</code> in the backend{' '}
          <code className="rounded bg-slate-100 px-1">.env</code>.
          {settings?.sheet_id_from_env ? (
            <span className="mt-1 block">Currently using the Sheet ID from the server environment.</span>
          ) : null}
        </p>
        <label className="block text-sm">
          <span className="text-slate-600">Sheet ID</span>
          <input
            type="text"
            className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
            value={sheetInput}
            onChange={(e) => setSheetInput(e.target.value)}
            placeholder="Spreadsheet ID"
          />
        </label>
        <button
          type="button"
          disabled={busy}
          onClick={() => void onSaveSheet()}
          className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          Save
        </button>
      </section>

      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-semibold text-slate-900">Sync</h2>
        <p className="text-sm text-slate-600">
          Last synced: <span className="font-medium text-slate-900">{formatTs(settings?.last_synced_at ?? null)}</span>
        </p>
        <p className="text-xs text-slate-500">
          If every message shows as skipped or &quot;already processed&quot; after a bad run, clear the processed list
          once, then sync again.
        </p>
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            if (!window.confirm('Clear the list of processed Gmail messages for your account? The next sync will re-try recent messages.')) return
            setBusy(true)
            setError(null)
            try {
              await settingsApi.clearProcessedEmails()
              window.alert('Processed list cleared. Run Sync Gmail on the Applications page.')
            } catch (e) {
              setError(e instanceof Error ? e.message : 'Clear failed')
            } finally {
              setBusy(false)
            }
          }}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-50"
        >
          Clear processed Gmail messages
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void onRebuild()}
          className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-950 hover:bg-amber-100 disabled:opacity-50"
        >
          Rebuild Sheet
        </button>
      </section>
    </div>
  )
}
