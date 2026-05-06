import type { User } from '../types/user'
import { requestJson } from './client'

export type TokenResponse = {
  access_token: string
  token_type: string
  user: User
}

export async function register(email: string, password: string): Promise<TokenResponse> {
  return requestJson<TokenResponse>('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  return requestJson<TokenResponse>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export async function me(): Promise<User> {
  return requestJson<User>('/api/auth/me')
}
