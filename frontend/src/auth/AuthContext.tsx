import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, loadAuth, saveAuth, type AuthState } from '../api/client'
import type { Me, Meta } from '../api/types'

interface AuthContextValue {
  meta: Meta | null
  me: Me | null
  auth: AuthState | null
  ready: boolean
  setDevIdentity: (v: { user: string; name: string; roles: string[]; tenant: string; scopes?: string; service?: string }) => void
  setOidcToken: (token: string) => void
  setTenant: (tenant: string) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue>(null as unknown as AuthContextValue)

export function useAuth() {
  return useContext(AuthContext)
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const payload = token.split('.')[1]
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(decodeURIComponent(escape(json)))
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [me, setMe] = useState<Me | null>(null)
  const [auth, setAuth] = useState<AuthState | null>(() => loadAuth())
  const [ready, setReady] = useState(false)

  useEffect(() => {
    api<Meta>('/api/v1/meta')
      .then((m) => setMeta(m))
      .catch(() => setMeta(null))
  }, [])

  useEffect(() => {
    if (meta === null) return
    const current = loadAuth()
    if (!current) {
      // در حالت OIDC بدون client پیکربندی‌شده کاربر باید از SSO وارد شود
      setReady(true)
      return
    }
    api<Me>('/api/v1/identity/me')
      .then(setMe)
      .catch(() => {
        saveAuth(null)
        setAuth(null)
        setMe(null)
      })
      .finally(() => setReady(true))
  }, [meta, auth])

  const value = useMemo<AuthContextValue>(
    () => ({
      meta,
      me,
      auth,
      ready,
      setDevIdentity: ({ user, name, roles, tenant, scopes, service }) => {
        const headers: Record<string, string> = {
          'X-Dev-User': user,
          'X-Dev-Name': name || user,
          'X-Dev-Roles': roles.join(','),
          'X-Dev-Tenants': tenant,
        }
        if (scopes) headers['X-Dev-Scopes'] = scopes
        if (service) headers['X-Dev-Service'] = service
        const next: AuthState = { mode: 'dev', token: 'dev', devHeaders: headers, tenant }
        saveAuth(next)
        setAuth(next)
      },
      setOidcToken: (token: string) => {
        const claims = decodeJwtPayload(token)
        const tenantClaim = claims?.tenant
        const tenants = (claims?.tenants as string[]) || (typeof tenantClaim === 'string' && tenantClaim ? [tenantClaim] : [])
        const next: AuthState = {
          mode: 'oidc',
          token,
          tenant: tenants[0],
        }
        saveAuth(next)
        setAuth(next)
      },
      setTenant: (tenant: string) => {
        const current = loadAuth()
        if (!current) return
        const next = { ...current, tenant }
        saveAuth(next)
        setAuth(next)
      },
      logout: () => {
        saveAuth(null)
        setAuth(null)
        setMe(null)
      },
    }),
    [meta, me, auth, ready],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export { decodeJwtPayload }
