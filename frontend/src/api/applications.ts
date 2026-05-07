import type { Application, ApplicationStatus } from '../types/application'
import { requestJson } from './client'

export type ApplicationUpsertBody = {
  company: string
  role: string
  status: ApplicationStatus
  /** YYYY-MM-DD (date input) or ISO string; backend accepts both */
  date: string
}

export async function listApplications(): Promise<Application[]> {
  return requestJson<Application[]>('/api/applications')
}

export async function createApplication(body: ApplicationUpsertBody): Promise<Application> {
  return requestJson<Application>('/api/applications', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function updateApplication(id: number, body: ApplicationUpsertBody): Promise<Application> {
  return requestJson<Application>(`/api/applications/${id}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export async function deleteApplication(id: number): Promise<void> {
  await requestJson<void>(`/api/applications/${id}`, { method: 'DELETE' })
}
