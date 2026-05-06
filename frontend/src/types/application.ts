export const APPLICATION_STATUSES = ['Applied', 'Rejected', 'Interview', 'OA', 'Offer'] as const

export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number]

export type Application = {
  id: number
  user_id: number
  gmail_message_id: string | null
  date: string
  company: string
  role: string
  status: ApplicationStatus
  created_at: string
  updated_at: string
}
