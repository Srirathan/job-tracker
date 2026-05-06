import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import * as authApi from '../api/auth'
import { clearToken, getToken, setToken } from '../api/client'
import type { User } from '../types/user'
import { AuthContext } from './auth-context-core'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)

  const refreshUser = useCallback(async () => {
    const u = await authApi.me()
    setUser(u)
  }, [])

  useEffect(() => {
    const run = async () => {
      if (!getToken()) {
        setReady(true)
        return
      }
      try {
        await refreshUser()
      } catch {
        clearToken()
        setUser(null)
      } finally {
        setReady(true)
      }
    }
    void run()
  }, [refreshUser])

  const login = useCallback(async (email: string, password: string) => {
    const res = await authApi.login(email, password)
    setToken(res.access_token)
    setUser(res.user)
  }, [])

  const register = useCallback(async (email: string, password: string) => {
    const res = await authApi.register(email, password)
    setToken(res.access_token)
    setUser(res.user)
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, ready, login, register, logout, refreshUser }),
    [user, ready, login, register, logout, refreshUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
