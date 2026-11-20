export class ApiError extends Error {
  code: string
  status: number
  details?: Record<string, unknown>
  constructor(code: string, message: string, status: number, details?: Record<string, unknown>) {
    super(message)
    this.code = code
    this.status = status
    this.details = details
  }
}

export interface AuthState {
  mode: 'dev' | 'oidc'
  token?: string      // در حالت oidc توکن واقعی؛ در dev مقدار "dev"
  devHeaders?: Record<string, string>
  tenant?: string
}

const AUTH_KEY = 'core.auth'

export function loadAuth(): AuthState | null {
  try {
    const raw = localStorage.getItem(AUTH_KEY)
    return raw ? (JSON.parse(raw) as AuthState) : null
  } catch {
    return null
  }
}

export function saveAuth(state: AuthState | null) {
  if (state === null) localStorage.removeItem(AUTH_KEY)
  else localStorage.setItem(AUTH_KEY, JSON.stringify(state))
}

export function getAuth(): AuthState | null {
  return loadAuth()
}

// هدرهای HTTP فقط ASCII می‌پذیرند؛ مقادیر غیر ASCII (مثل نام فارسی آزمایشی) حذف می‌شوند
function asciiHeaders(h: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(h)) {
    // eslint-disable-next-line no-control-regex
    if (/^[\x00-\x7F]*$/.test(v)) out[k] = v
  }
  return out
}

function headersFor(auth: AuthState, extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json', ...asciiHeaders(extra || {}) }
  if (auth.mode === 'oidc' && auth.token) {
    h['Authorization'] = `Bearer ${auth.token}`
  } else if (auth.mode === 'dev' && auth.devHeaders) {
    Object.assign(h, asciiHeaders(auth.devHeaders))
    h['Authorization'] = 'Bearer dev'
  }
  if (auth.tenant) h['X-Tenant-Code'] = auth.tenant
  return h
}

export async function api<T = unknown>(
  path: string,
  opts: { method?: string; body?: unknown; extraHeaders?: Record<string, string> } = {},
): Promise<T> {
  const auth = loadAuth()
  const resp = await fetch(path, {
    method: opts.method || 'GET',
    headers: headersFor(auth ?? { mode: 'dev' }, opts.extraHeaders),
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  })
  const text = await resp.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!resp.ok) {
    const err = (data as { code?: string; message?: string; details?: Record<string, unknown> }) || {}
    throw new ApiError(err.code || 'UNKNOWN', err.message || `خطای ${resp.status}`, resp.status, err.details)
  }
  return data as T
}

export function uuid(): string {
  return crypto.randomUUID()
}
