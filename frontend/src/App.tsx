import { NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import DevLogin from './auth/DevLogin'
import OidcCallback from './auth/OidcCallback'
import Dashboard from './features/dashboard/Dashboard'
import PersonsList from './features/persons/PersonsList'
import PersonDetail from './features/persons/PersonDetail'
import Organizations from './features/organizations/Organizations'
import References from './features/references/References'
import Mappings from './features/mappings/Mappings'
import Ownership from './features/ownership/Ownership'
import Quality from './features/quality/Quality'
import ChangeRequests from './features/changeRequests/ChangeRequests'
import Integrations from './features/integrations/Integrations'
import Audit from './features/audit/Audit'

const NAV = [
  { to: '/', label: 'داشبورد', icon: '▦', end: true },
  { to: '/persons', label: 'اشخاص', icon: '👤' },
  { to: '/organizations', label: 'سازمان‌ها', icon: '🏛' },
  { to: '/references', label: 'اطلاعات پایه', icon: '📚' },
  { to: '/mappings', label: 'نگاشت شناسه', icon: '🔗' },
  { to: '/ownership', label: 'مالکیت داده', icon: '🔐' },
  { to: '/quality', label: 'کیفیت داده', icon: '♻️' },
  { to: '/change-requests', label: 'درخواست اصلاح', icon: '✏️' },
  { to: '/integrations', label: 'اتصال‌ها', icon: '🛰' },
  { to: '/audit', label: 'ممیزی', icon: '🗂' },
]

export default function App() {
  const { meta, me, auth, ready, logout } = useAuth()
  const navigate = useNavigate()

  if (!ready || (meta === null && !ready)) {
    return <div className="page-loading">در حال اتصال به هسته …</div>
  }

  if (meta?.dev_mode && !auth) {
    return <DevLogin />
  }

  if (!meta?.dev_mode && !auth && meta?.oidc.available) {
    return (
      <div className="login-wrap">
        <div className="login-card">
          <div className="login-logo">۳۶۰</div>
          <h1>هسته مشترک دانشجو۳۶۰</h1>
          <p className="muted">ورود از طریق پرتال یکپارچه SSO سازمان انجام می‌شود.</p>
          <button
            className="btn primary block"
            onClick={() =>
              import('./auth/OidcCallback').then((m) =>
                m.startOidcLogin(meta.oidc.authorization_endpoint!, meta.oidc.client_id!),
              )
            }
          >
            ورود با SSO سازمانی
          </button>
          {meta.oidc.client_id === null && (
            <p className="alert error">OIDC_CLIENT_ID روی بک‌اند تنظیم نشده است؛ با مدیر یکپارچگی هماهنگ کنید.</p>
          )}
        </div>
      </div>
    )
  }

  if (!auth) {
    return <DevLogin />
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-badge">۳۶۰</span>
          <div>
            <div className="brand-title">هسته مشترک</div>
            <div className="brand-sub muted">Shared Core</div>
          </div>
        </div>
        <nav>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <span className="nav-icon">{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot muted small">
          نسخه ۱.۰.۰ — ماه‌افزار هوشمند رسا
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="muted small">
            {meta?.dev_mode ? 'حالت توسعه (هویت آزمایشی)' : `SSO: ${meta?.oidc.issuer}`}
          </div>
          <div className="topbar-user">
            {auth.tenant && <span className="chip">{auth.tenant}</span>}
            {me?.person && <span className="chip ok">شخص متصل: {me.person.display_name}</span>}
            {me?.roles?.length ? <span className="chip">{me.roles.length} نقش</span> : null}
            <button className="btn ghost sm" onClick={logout}>
              خروج
            </button>
          </div>
        </header>
        <main className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/persons" element={<PersonsList />} />
            <Route path="/persons/:id" element={<PersonDetail />} />
            <Route path="/organizations" element={<Organizations />} />
            <Route path="/references" element={<References />} />
            <Route path="/mappings" element={<Mappings />} />
            <Route path="/ownership" element={<Ownership />} />
            <Route path="/quality" element={<Quality />} />
            <Route path="/change-requests" element={<ChangeRequests />} />
            <Route path="/integrations" element={<Integrations />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/login/callback" element={<OidcCallback />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
