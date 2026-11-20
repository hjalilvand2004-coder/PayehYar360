import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import type { Installation, IntegrationsStatus } from '../../api/types'
import { Empty, ErrorBox, Loading, Modal, PageHead, StatusBadge } from '../../components/ui'
import { fmtDateTime, fmtNumber, fmtSeconds } from '../../shared/format'
import { useAuth } from '../../auth/AuthContext'

export default function Integrations() {
  const qc = useQueryClient()
  const { me } = useAuth()
  const isAdmin = (me?.roles || []).some((r) => ['integration_admin', 'tenant_admin'].includes(r))
  const canSync = (me?.roles || []).some((r) => ['integration_admin', 'tenant_admin', 'steward'].includes(r))
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [showCreate, setShowCreate] = useState(false)

  const status = useQuery({
    queryKey: ['int-status'],
    queryFn: () => api<IntegrationsStatus>('/api/v1/integrations/status'),
    refetchInterval: 10000,
  })
  const installations = useQuery({
    queryKey: ['installations'],
    queryFn: () => api<{ items: Installation[] }>('/api/v1/installations'),
  })

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api('/api/v1/installations', { method: 'POST', body }),
    onSuccess: () => {
      setShowCreate(false); setError(''); setNotice('نصب ثبت شد.')
      qc.invalidateQueries({ queryKey: ['installations'] }); qc.invalidateQueries({ queryKey: ['int-status'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const snapshot = useMutation({
    mutationFn: () => api<{ id: string; status: string }>('/api/v1/sync/snapshots', { method: 'POST', body: { entities: ['persons', 'organizations'] } }),
    onSuccess: (d) => {
      setNotice(`کار Snapshot با شناسه ${d.id.slice(0, 8)}… ایجاد شد (${d.status}).`)
      qc.invalidateQueries({ queryKey: ['int-status'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const reconcile = useMutation({
    mutationFn: (installation_code: string) =>
      api('/api/v1/sync/reconciliation/jobs', { method: 'POST', body: { installation_code, scope: 'persons' } }),
    onSuccess: () => {
      setNotice('تطبیق پایه انجام شد؛ گزارش در ممیزی ثبت شد.')
    },
    onError: (e) => setError((e as ApiError).message),
  })

  return (
    <>
      <PageHead
        title="اتصال‌ها"
        subtitle="نصب‌ها، وضعیت Sync و پایش (FR-15/FR-17)"
        actions={
          <>
            {canSync && <button className="btn" disabled={snapshot.isPending} onClick={() => snapshot.mutate()}>ایجاد Snapshot</button>}
            {isAdmin && <button className="btn primary" onClick={() => setShowCreate(true)}>ثبت نصب جدید</button>}
          </>
        }
      />
      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert info">{notice}</div>}

      <div className="grid cols-4">
        <div className="card stat">
          <div className="num">{status.data ? fmtNumber(status.data.outbox.pending) : '…'}</div>
          <div className="lbl">رویداد در Outbox</div>
        </div>
        <div className="card stat">
          <div className="num">{status.data ? fmtSeconds(status.data.outbox.oldest_pending_age_seconds) : '…'}</div>
          <div className="lbl">قدیمی‌ترین رویداد</div>
        </div>
        <div className="card stat">
          <div className="num"><StatusBadge status={status.data?.rabbitmq.connected ? 'active' : 'inactive'} /></div>
          <div className="lbl">RabbitMQ</div>
        </div>
        <div className="card stat">
          <div className="num">{status.data ? fmtNumber(status.data.max_seq) : '…'}</div>
          <div className="lbl">مرز تغییر (max_seq)</div>
        </div>
      </div>

      <div className="card">
        <h2>نصب‌ها و اشتراک‌ها</h2>
        {installations.isLoading ? <Loading /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead>
                <tr><th>کد نصب</th><th>عنوان</th><th>سامانه</th><th>حالت</th><th>وضعیت</th><th>آخرین activity</th><th>checkpoint</th><th>فاصله</th><th></th></tr>
              </thead>
              <tbody>
                {(installations.data?.items || []).map((i) => {
                  const st = status.data?.installations.find((s) => s.installation_code === i.installation_code)
                  return (
                    <tr key={i.id}>
                      <td className="num">{i.installation_code}</td>
                      <td>{i.title}</td>
                      <td>{i.system_code}</td>
                      <td><StatusBadge status={i.mode} /></td>
                      <td><StatusBadge status={i.status} /></td>
                      <td className="small">{fmtDateTime(i.last_seen_at)}</td>
                      <td className="num">{st ? fmtNumber(st.checkpoint_cursor) : '—'}</td>
                      <td>{st?.lag === null || st?.lag === undefined ? '—' : <span className={`chip ${st.lag > 100 ? 'warn' : 'ok'}`}>{fmtNumber(st.lag)}</span>}</td>
                      <td>
                        {canSync && (
                          <button className="btn sm ghost" disabled={reconcile.isPending}
                                  onClick={() => reconcile.mutate(i.installation_code)}>
                            تطبیق
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {(installations.data?.items || []).length === 0 && <Empty text="نصبی ثبت نشده است" />}
          </div>
        )}
      </div>

      <div className="card">
        <h2>آخرین Snapshotها</h2>
        <div className="table-wrap">
          <table className="tbl">
            <thead><tr><th>شناسه</th><th>وضعیت</th><th>مرز</th><th>ایجاد</th><th></th></tr></thead>
            <tbody>
              {(status.data?.recent_snapshots || []).map((s) => (
                <tr key={s.id}>
                  <td className="num small">{s.id.slice(0, 8)}…</td>
                  <td><StatusBadge status={s.status} /></td>
                  <td className="num">{fmtNumber(s.boundary_seq)}</td>
                  <td className="small">{fmtDateTime(s.created_at)}</td>
                  <td>
                    {s.status === 'done' && (
                      <a className="btn sm" href={`/api/v1/sync/snapshots/${s.id}/download`} target="_blank" rel="noreferrer">
                        دانلود
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {(status.data?.recent_snapshots || []).length === 0 && <Empty text="Snapshotای تولید نشده است" />}
        </div>
      </div>

      {showCreate && (
        <Modal title="ثبت نصب جدید" onClose={() => setShowCreate(false)}>
          <CreateInstForm onSubmit={(v) => create.mutate(v)} onCancel={() => setShowCreate(false)} />
        </Modal>
      )}
    </>
  )
}

function CreateInstForm({ onSubmit, onCancel }: { onSubmit: (v: Record<string, unknown>) => void; onCancel: () => void }) {
  const [systemCode, setSystemCode] = useState('edu')
  const [instCode, setInstCode] = useState('')
  const [title, setTitle] = useState('')
  const [mode, setMode] = useState('integrated')
  const [baseUrl, setBaseUrl] = useState('')
  const [scopes, setScopes] = useState('read:person,sync')
  return (
    <>
      <label>کد سامانه</label>
      <input value={systemCode} onChange={(e) => setSystemCode(e.target.value)} dir="ltr" />
      <label>کد نصب (یکتا در مشتری)</label>
      <input value={instCode} onChange={(e) => setInstCode(e.target.value)} dir="ltr" placeholder="edu-main" />
      <label>عنوان</label>
      <input value={title} onChange={(e) => setTitle(e.target.value)} />
      <label>حالت</label>
      <select value={mode} onChange={(e) => setMode(e.target.value)}>
        <option value="integrated">یکپارچه</option>
        <option value="local">مستقل</option>
      </select>
      <label>Base URL (اختیاری)</label>
      <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} dir="ltr" />
      <label>Scopeهای سرویس (اختیاری)</label>
      <input value={scopes} onChange={(e) => setScopes(e.target.value)} dir="ltr" />
      <div className="modal-foot">
        <button className="btn primary" disabled={!instCode || !title}
                onClick={() => onSubmit({ system_code: systemCode, installation_code: instCode, title, mode, base_url: baseUrl || null, owner_scopes: scopes || null })}>
          ثبت
        </button>
        <button className="btn" onClick={onCancel}>انصراف</button>
      </div>
    </>
  )
}
