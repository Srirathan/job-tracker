import type { ApplicationStatus } from '../types/application'

const tones: Record<string, string> = {
  Applied: 'bg-blue-100 text-blue-900',
  Rejected: 'bg-rose-100 text-rose-800',
  Interview: 'bg-yellow-100 text-yellow-900',
  OA: 'bg-violet-100 text-violet-900',
  Offer: 'bg-emerald-100 text-emerald-900',
}

export function StatusBadge({ status }: { status: ApplicationStatus | string }) {
  const cls = tones[status] ?? 'bg-slate-100 text-slate-800'
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>{status}</span>
  )
}
