import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { api } from '../api/client'

function base64url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

async function sha256(input: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input)))
}

export async function startOidcLogin(authorizationEndpoint: string, clientId: string) {
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)))
  const challenge = base64url(await sha256(verifier))
  const state = base64url(crypto.getRandomValues(new Uint8Array(16)))
  sessionStorage.setItem('oidc.verifier', verifier)
  sessionStorage.setItem('oidc.state', state)
  const redirectUri = `${location.origin}/login/callback`
  const url = new URL(authorizationEndpoint)
  url.searchParams.set('response_type', 'code')
  url.searchParams.set('client_id', clientId)
  url.searchParams.set('redirect_uri', redirectUri)
  url.searchParams.set('scope', 'openid profile email')
  url.searchParams.set('state', state)
  url.searchParams.set('code_challenge', challenge)
  url.searchParams.set('code_challenge_method', 'S256')
  location.assign(url.toString())
}

/** بازگشت از SSO: تبادل کد با PKCE از طریق بک‌اند (اجتناب از CORS). */
export default function OidcCallback() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { setOidcToken, meta } = useAuth()
  const [error, setError] = useState('')
  const done = useRef(false)

  useEffect(() => {
    if (done.current) return
    done.current = true
    const code = params.get('code')
    const state = params.get('state')
    const verifier = sessionStorage.getItem('oidc.verifier')
    const expectedState = sessionStorage.getItem('oidc.state')
    if (!code || !verifier) {
      setError('پارامترهای بازگشت از SSO ناقص است.')
      return
    }
    if (state !== expectedState) {
      setError('مقدار state مطابقت ندارد؛ احتمال CSRF.')
      return
    }
    api<{ access_token: string }>('/api/v1/auth/token', {
      method: 'POST',
      body: { code, code_verifier: verifier, redirect_uri: `${location.origin}/login/callback` },
    })
      .then((r) => {
        sessionStorage.removeItem('oidc.verifier')
        sessionStorage.removeItem('oidc.state')
        setOidcToken(r.access_token)
        navigate('/', { replace: true })
      })
      .catch((e) => setError(e.message || 'تبادل توکن ناموفق بود.'))
  }, [params, navigate, setOidcToken, meta])

  return (
    <div className="login-wrap">
      <div className="login-card">
        <h2>بازگشت از SSO</h2>
        {error ? <div className="alert error">{error}</div> : <p className="muted">در حال تبادل توکن …</p>}
      </div>
    </div>
  )
}
