const TOKEN_KEY = 'job_tracker_access_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

/** API origin. In dev with no env var, use '' so requests stay same-origin and Vite proxies `/api` to FastAPI. */
function resolveApiBase(): string {
  const raw = import.meta.env.VITE_API_URL as string | undefined
  const trimmed = typeof raw === 'string' ? raw.trim() : ''
  if (trimmed.length > 0) {
    return trimmed.replace(/\/$/, '')
  }
  if (import.meta.env.DEV) {
    return ''
  }
  return 'http://127.0.0.1:8000'
}

export const API_BASE = resolveApiBase()

function handleSessionExpiredIfNeeded(status: number, hadToken: boolean): void {
  if (status !== 401 || !hadToken) return
  clearToken()
  const pathOnly = window.location.pathname
  if (pathOnly !== '/login' && pathOnly !== '/register') {
    window.location.assign('/login')
  }
}

function buildHeaders(init?: RequestInit, jsonBody?: boolean): Headers {
  const headers = new Headers(init?.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (jsonBody && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  return headers
}

async function parseErrorMessage(res: Response): Promise<string> {
  try {
    const j: unknown = await res.json()
    if (typeof j === 'object' && j !== null && 'detail' in j) {
      const d = (j as { detail: unknown }).detail
      if (typeof d === 'string') return d
      if (Array.isArray(d)) return d.map((x) => JSON.stringify(x)).join('; ')
    }
  } catch {
    /* ignore */
  }
  return res.statusText || 'Request failed'
}

async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = `${API_BASE}${path}`
  try {
    return await fetch(url, init)
  } catch (e) {
    if (e instanceof TypeError) {
      throw new Error(
        'Cannot reach the API. Start the backend: `cd backend` then `uvicorn app.main:app --reload`. ' +
          'In dev, remove `VITE_API_URL` from `frontend/.env` so Vite can proxy `/api` to port 8000, or set it to the exact URL your browser can open.',
        { cause: e },
      )
    }
    throw e
  }
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const isJsonBody = typeof init?.body === 'string'
  const hadToken = Boolean(getToken())
  const res = await apiFetch(path, {
    ...init,
    headers: buildHeaders(init, isJsonBody),
  })
  handleSessionExpiredIfNeeded(res.status, hadToken)
  if (!res.ok) {
    throw new Error(await parseErrorMessage(res))
  }
  if (res.status === 204) {
    return undefined as T
  }
  return res.json() as Promise<T>
}

export async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  const hadToken = Boolean(getToken())
  const res = await apiFetch(path, {
    ...init,
    headers: buildHeaders(init, false),
  })
  handleSessionExpiredIfNeeded(res.status, hadToken)
  if (!res.ok) {
    throw new Error(await parseErrorMessage(res))
  }
  return res.blob()
}

export function buildQuery(params: Record<string, string | undefined | null>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') {
      sp.set(k, v)
    }
  }
  const q = sp.toString()
  return q ? `?${q}` : ''
}
