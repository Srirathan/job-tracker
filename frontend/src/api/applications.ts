import type { Application } from '../types/application'
import { requestJson } from './client'

export async function listApplications(): Promise<Application[]> {
  return requestJson<Application[]>('/api/applications')
}
