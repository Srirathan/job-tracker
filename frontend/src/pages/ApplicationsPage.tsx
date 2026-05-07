import { useCallback, useEffect, useMemo, useState } from 'react'
import * as applicationsApi from '../api/applications'
import type { ApplicationUpsertBody } from '../api/applications'
import * as authApi from '../api/auth'
import * as settingsApi from '../api/settings'
import * as syncApi from '../api/sync'
import { StatusBadge } from '../components/StatusBadge'
import type { Application, ApplicationStatus } from '../types/application'
import { APPLICATION_STATUSES } from '../types/application'

const MODAL_STATUS_ORDER: ApplicationStatus[] = ['Applied', 'Interview', 'OA', 'Rejected', 'Offer']

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}

function toInputDate(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  } catch {
    return iso.slice(0, 10)
  }
}

function todayInputDate(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

const emptyForm = (): { company: string; role: string; status: ApplicationStatus; date: string } => ({
  company: '',
  role: '',
  status: 'Applied',
  date: todayInputDate(),
})

type StatusFilter = 'All' | ApplicationStatus

function formatRelativeSyncedAt(iso: string | null | undefined): string {
  if (iso == null || iso === '') return 'Never'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return 'Unknown'
  const sec = Math.floor((Date.now() - t) / 1000)
  if (sec < 10) return 'just now'
  if (sec < 60) return `${sec} second${sec === 1 ? '' : 's'} ago`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min} minute${min === 1 ? '' : 's'} ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} hour${hr === 1 ? '' : 's'} ago`
  const day = Math.floor(hr / 24)
  if (day < 7) return `${day} day${day === 1 ? '' : 's'} ago`
  return formatDate(iso)
}

export function ApplicationsPage() {
  const [rows, setRows] = useState<Application[]>([])
  const [error, setError] = useState<string | null>(null)
  const [syncBusy, setSyncBusy] = useState(false)
  const [lastSync, setLastSync] = useState<syncApi.SyncSummary | null>(null)
  const [lookbackDays, setLookbackDays] = useState<number | null>(null)
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('All')

  const [modalMode, setModalMode] = useState<'add' | 'edit' | null>(null)
  const [editId, setEditId] = useState<number | null>(null)
  const [form, setForm] = useState(() => emptyForm())
  const [modalBusy, setModalBusy] = useState(false)
  const [modalError, setModalError] = useState<string | null>(null)

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

  const refreshMe = useCallback(() => {
    void authApi.me().then((u) => setLastSyncedAt(u.last_synced_at ?? null))
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void load()
        refreshMe()
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [load, refreshMe])

  useEffect(() => {
    void settingsApi
      .getSettings()
      .then((s) => setLookbackDays(s.gmail_sync_lookback_days))
      .catch(() => setLookbackDays(null))
  }, [])

  useEffect(() => {
    refreshMe()
  }, [refreshMe])

  const filteredRows = useMemo(() => {
    if (statusFilter === 'All') return rows
    return rows.filter((r) => r.status === statusFilter)
  }, [rows, statusFilter])

  const summaryLine = useMemo(() => {
    const total = rows.length
    const interview = rows.filter((r) => r.status === 'Interview').length
    const rejected = rows.filter((r) => r.status === 'Rejected').length
    const offer = rows.filter((r) => r.status === 'Offer').length
    return `${total} applications — ${interview} interviews · ${rejected} rejected · ${offer} offers`
  }, [rows])

  const filterButtons: { label: string; value: StatusFilter }[] = [
    { label: 'All', value: 'All' },
    { label: 'Applied', value: 'Applied' },
    { label: 'Interview', value: 'Interview' },
    { label: 'OA', value: 'OA' },
    { label: 'Rejected', value: 'Rejected' },
    { label: 'Offer', value: 'Offer' },
  ]

  const openAdd = () => {
    setModalMode('add')
    setEditId(null)
    setForm(emptyForm())
    setModalError(null)
  }

  const openEdit = (r: Application) => {
    setModalMode('edit')
    setEditId(r.id)
    setForm({
      company: r.company,
      role: r.role,
      status: APPLICATION_STATUSES.includes(r.status) ? r.status : 'Applied',
      date: toInputDate(r.date),
    })
    setModalError(null)
  }

  const closeModal = () => {
    setModalMode(null)
    setEditId(null)
    setModalError(null)
    setModalBusy(false)
  }

  const buildPayload = (): ApplicationUpsertBody => ({
    company: form.company.trim(),
    role: form.role.trim(),
    status: form.status,
    date: form.date,
  })

  const saveModal = async () => {
    setModalBusy(true)
    setModalError(null)
    try {
      const body = buildPayload()
      if (!body.company || !body.role) {
        setModalError('Company and role are required.')
        setModalBusy(false)
        return
      }
      if (modalMode === 'add') {
        await applicationsApi.createApplication(body)
      } else if (modalMode === 'edit' && editId != null) {
        await applicationsApi.updateApplication(editId, body)
      }
      await load()
      refreshMe()
      closeModal()
    } catch (e) {
      setModalError(e instanceof Error ? e.message : 'Save failed')
      setModalBusy(false)
    }
  }

  const onDelete = async (id: number) => {
    try {
      await applicationsApi.deleteApplication(id)
      await load()
      refreshMe()
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  const onSync = async () => {
    setSyncBusy(true)
    setLastSync(null)
    setError(null)
    try {
      const summary = await syncApi.syncGmail()
      setLastSync(summary)
      await load()
      refreshMe()
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
        <div className="flex flex-col items-end gap-1">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => openAdd()}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-900 hover:bg-slate-50"
            >
              Add application
            </button>
            <button
              type="button"
              disabled={syncBusy}
              onClick={() => void onSync()}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {syncBusy ? 'Syncing…' : 'Sync Gmail'}
            </button>
          </div>
          <p className="text-xs text-slate-500">Last synced: {formatRelativeSyncedAt(lastSyncedAt)}</p>
        </div>
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
              {lastSync.skipped_groq_failed > 0 ? (
                <li>
                  Groq extraction failed (API error or bad response): {lastSync.skipped_groq_failed}
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

      {rows.length > 0 ? (
        <p className="text-sm text-slate-700">{summaryLine}</p>
      ) : null}

      {rows.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {filterButtons.map((b) => (
            <button
              key={b.label}
              type="button"
              onClick={() => setStatusFilter(b.value)}
              className={
                statusFilter === b.value
                  ? 'rounded-full bg-slate-900 px-3 py-1 text-xs font-medium text-white'
                  : 'rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50'
              }
            >
              {b.label}
            </button>
          ))}
        </div>
      ) : null}

      {rows.length === 0 && !error ? (
        <p className="rounded-lg border border-dashed border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-600">
          No applications yet. Click Sync Gmail or Add application to start.
        </p>
      ) : filteredRows.length === 0 && rows.length > 0 ? (
        <p className="rounded-lg border border-dashed border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-600">
          No applications match this filter.
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
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filteredRows.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50/80">
                  <td className="whitespace-nowrap px-4 py-3 text-slate-700">{formatDate(r.date)}</td>
                  <td className="px-4 py-3 text-slate-900">{r.company}</td>
                  <td className="px-4 py-3 text-slate-700">{r.role}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => openEdit(r)}
                      className="mr-3 text-slate-700 underline decoration-slate-300 underline-offset-2 hover:text-slate-900"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => void onDelete(r.id)}
                      className="text-rose-700 underline decoration-rose-200 underline-offset-2 hover:text-rose-900"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalMode ? (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/35 p-4"
          role="presentation"
          onMouseDown={(ev) => {
            if (ev.target === ev.currentTarget) closeModal()
          }}
        >
          <div
            className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-5 shadow-lg"
            role="dialog"
            aria-modal="true"
          >
            <h2 className="text-lg font-semibold text-slate-900">
              {modalMode === 'add' ? 'Add application' : 'Edit application'}
            </h2>
            <div className="mt-4 space-y-3">
              <label className="block text-xs font-medium uppercase tracking-wide text-slate-600">
                Company
                <input
                  type="text"
                  value={form.company}
                  onChange={(e) => setForm((f) => ({ ...f, company: e.target.value }))}
                  className="mt-1 block w-full rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
                />
              </label>
              <label className="block text-xs font-medium uppercase tracking-wide text-slate-600">
                Role
                <input
                  type="text"
                  value={form.role}
                  onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
                  className="mt-1 block w-full rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
                />
              </label>
              <label className="block text-xs font-medium uppercase tracking-wide text-slate-600">
                Status
                <select
                  value={form.status}
                  onChange={(e) => setForm((f) => ({ ...f, status: e.target.value as ApplicationStatus }))}
                  className="mt-1 block w-full rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
                >
                  {MODAL_STATUS_ORDER.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs font-medium uppercase tracking-wide text-slate-600">
                Date
                <input
                  type="date"
                  value={form.date}
                  onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
                  className="mt-1 block w-full rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
                />
              </label>
            </div>
            {modalError ? <p className="mt-3 text-sm text-rose-600">{modalError}</p> : null}
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => closeModal()}
                className="rounded-md border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={modalBusy}
                onClick={() => void saveModal()}
                className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {modalBusy ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
