import { useState } from 'react'
import { useAuth } from './AuthContext'
import { ThemeToggle } from '../components/ui'

const ROLE_OPTIONS = [
  { value: 'viewer', label: 'مشاهده‌گر اطلاعات پایه' },
  { value: 'master_data_editor', label: 'کارشناس اطلاعات پایه' },
  { value: 'steward', label: 'متولی داده' },
  { value: 'integration_admin', label: 'مدیر یکپارچگی' },
  { value: 'auditor', label: 'ممیز' },
  { value: 'tenant_admin', label: 'مدیر مشتری' },
]

/** فقط در حالت توسعه (DEV_AUTH=true بک‌اند) — ورود واقعی از SSO سازمان انجام می‌شود. */
export default function DevLogin() {
  const { setDevIdentity, meta } = useAuth()
  const [user, setUser] = useState('steward1')
  const [name, setName] = useState('متولی داده نمونه')
  const [tenant, setTenant] = useState('demo')
  const [roles, setRoles] = useState<string[]>(['steward', 'tenant_admin'])
  const [error, setError] = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user || !tenant || roles.length === 0) {
      setError('کاربر، مشتری و حداقل یک نقش لازم است.')
      return
    }
    // بررسی اعتبار هویت با یک فراخوانی واقعی — مقدار فارسی نام به‌صورت هدر ارسال نمی‌شود
    const headers: Record<string, string> = {
      'X-Dev-User': user, 'X-Dev-Roles': roles.join(','), 'X-Dev-Tenants': tenant,
    }
    try {
      const resp = await fetch(`/api/v1/identity/me`, {
        headers: { ...headers, Authorization: 'Bearer dev' },
      })
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        setError(body.message || 'هویت آزمایشی پذیرفته نشد (آیا مشتری وجود دارد؟)')
        return
      }
      setDevIdentity({ user, name, roles, tenant })
    } catch {
      setError('ارتباط با سرور برقرار نشد.')
    }
  }

  if (!meta?.dev_mode) return null

  return (
    <div className="login-wrap">
      <div className="login-theme-toggle"><ThemeToggle /></div>
      <form className="login-card" onSubmit={submit}>
        <div className="login-logo">۳۶۰</div>
        <h1>پایه‌یار۳۶۰ — هسته مشترک</h1>
        <p className="muted">ورود آزمایشی — فقط در محیط توسعه؛ در محیط واقعی ورود از پرتال یکپارچه (دانشجویار۳۶۰) انجام می‌شود.</p>
        {error && <div className="alert error">{error}</div>}
        <label>شناسه کاربر</label>
        <input value={user} onChange={(e) => setUser(e.target.value)} placeholder="steward1" />
        <label>نام نمایشی</label>
        <input value={name} onChange={(e) => setName(e.target.value)} />
        <label>مشتری (X-Tenant-Code)</label>
        <input value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="demo" />
        <label>نقش‌ها</label>
        <div className="role-grid">
          {ROLE_OPTIONS.map((r) => (
            <label key={r.value} className={`role-chip ${roles.includes(r.value) ? 'on' : ''}`}>
              <input
                type="checkbox"
                checked={roles.includes(r.value)}
                onChange={(e) =>
                  setRoles((prev) => (e.target.checked ? [...prev, r.value] : prev.filter((x) => x !== r.value)))
                }
              />
              {r.label}
            </label>
          ))}
        </div>
        <button className="btn primary block" type="submit">
          ورود
        </button>
        <p className="muted small">نقش‌ها به claimهای SSO نگاشت می‌شوند؛ این فرم صرفاً هویت آزمایشی می‌سازد.</p>
      </form>
    </div>
  )
}
