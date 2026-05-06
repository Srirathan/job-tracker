import { useContext } from 'react'
import { type AuthContextValue, AuthContext } from './auth-context-core'

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return ctx
}
