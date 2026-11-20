import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import type { Installation, Mapping, Person } from '../../api/types'
import { Empty, ErrorBox, Loading, PageHead, StatusBadge } from '../../components/ui'
import { useAuth } from '../../auth/AuthContext'

interface ResolveResult {
  entity_id: string
  entity?: { display_name?: string; status?: string; version?: number }
  merged_from?: string
}

export default function Mappings() {
  const qc = useQueryClient()
  const { me } = useAuth()
  const canEdit = (me?.roles || []).some((r) =>
    ['master_data_editor', 'steward', 'tenant_admin', 'integration_admin'].includes(r))
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  // فرم ثبت نگاشت
  const [instCode, setInstCode] = useState('')
  const [entityType, setEntityType] = useState('person')
  const [localId, setLocalId] = useState('')
  const [personQ, setPersonQ] = useState('')
  const [entityId, setEntityId] = useState('')

  // پنل resolve
  const [rInst, setRInst] = useState('')
  const [rLocal, setRLocal] = useState('')
  const [rResult, setRResult] = useState<ResolveResult | null>(null)

  const installations = useQuery({
    queryKey: ['installations'],
    queryFn: () => api<{ items: Installation[] }>('/api/v1/installations'),
  })
  const mappings = useQuery({
    queryKey: ['mappings'],
    queryFn: () => api<{ items: Mapping[] }>('/api/v1/id-mappings?limit=100'),
  })
  const personSearch = useQuery({
    queryKey: ['person-search', personQ],
    queryFn: () => api<{ items: Person[] }>(`/api/v1/persons?q=${encodeURIComponent(personQ)}&limit=8`),
    enabled: personQ.length >= 2,
  })

  const register = useMutation({
    mutationFn: (body: Record<string, unknown>) => api('/api/v1/id-mappings', { method: 'POST', body }),
    onSuccess: () => {
      setError(''); setNotice('نگاشت ثبت شد.')
      setLocalId(''); setEntityId(''); setPersonQ('')
      qc.invalidateQueries({ queryKey: ['mappings'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const resolve = () => {
    setNotice(''); setError('')
    api<ResolveResult>('/api/v1/id-mappings/resolve', {
      method: 'POST',
      body: { installation_code: rInst, entity_type: 'person', local_id: rLocal },
    })
      .then((r) => setRResult(r))
      .catch((e) => { setRResult(null); setError((e as ApiError).message) })
  }

  return (
    <>
      <PageHead
        title="نگاشت شناسه"
        subtitle="تبدیل شناسه محلی زیرسامانه‌ها به شناسه مشترک هسته (FR-03)"
      />
      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert info">{notice}</div>}

      <div className="grid cols-2">
        <div className="card">
          <h2>ثبت نگاشت جدید</h2>
          {canEdit ? (
            <>
              <label>نصب سامانه</label>
              <select value={instCode} onChange={(e) => setInstCode(e.target.value)}>
                <option value="">— انتخاب کنید —</option>
                {(installations.data?.items || []).map((i) => (
                  <option key={i.id} value={i.installation_code}>{i.title} ({i.installation_code})</option>
                ))}
              </select>
              <label>نوع موجودیت</label>
              <select value={entityType} onChange={(e) => setEntityType(e.target.value)}>
                <option value="person">شخص</option>
                <option value="organization">سازمان</option>
              </select>
              <label>شناسه محلی (مثلاً شماره دانشجویی)</label>
              <input value={localId} onChange={(e) => setLocalId(e.target.value)} dir="ltr" />
              <label>جست‌وجوی شخص هدف</label>
              <input value={personQ} onChange={(e) => setPersonQ(e.target.value)} placeholder="نام شخص (حداقل ۲ حرف)" />
              {personSearch.data?.items.length ? (
                <div className="table-wrap" style={{ marginTop: 6 }}>
                  <table className="tbl">
                    <tbody>
                      {personSearch.data.items.map((p) => (
                        <tr key={p.id} className="clickable" onClick={() => { setEntityId(p.id); setPersonQ(p.display_name) }}
                            style={{ background: p.id === entityId ? 'var(--ok-soft)' : undefined }}>
                          <td>{p.display_name}</td>
                          <td className="muted small num">{p.id.slice(0, 8)}…</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
              <div className="modal-foot">
                <button className="btn primary" disabled={!instCode || !localId || !entityId}
                        onClick={() => register.mutate({ installation_code: instCode, entity_type: entityType, local_id: localId, entity_id: entityId })}>
                  ثبت نگاشت
                </button>
              </div>
            </>
          ) : <div className="muted">برای ثبت نگاشت نقش لازم را ندارید.</div>}
        </div>

        <div className="card">
          <h2>تبدیل شناسه محلی (Resolve)</h2>
          <label>نصب</label>
          <select value={rInst} onChange={(e) => setRInst(e.target.value)}>
            <option value="">— انتخاب کنید —</option>
            {(installations.data?.items || []).map((i) => (
              <option key={i.id} value={i.installation_code}>{i.installation_code}</option>
            ))}
          </select>
          <label>شناسه محلی</label>
          <input value={rLocal} onChange={(e) => setRLocal(e.target.value)} dir="ltr" />
          <div className="modal-foot">
            <button className="btn primary" disabled={!rInst || !rLocal} onClick={resolve}>دریافت شناسه مشترک</button>
          </div>
          {rResult && (
            <div className="alert info">
              <div className="kv">
                <div className="k">شناسه مشترک</div><div className="num">{rResult.entity_id}</div>
                {rResult.entity && (
                  <>
                    <div className="k">نام نمایشی</div><div>{rResult.entity.display_name}</div>
                    <div className="k">وضعیت</div><div>{rResult.entity.status}</div>
                    <div className="k">نسخه</div><div>{rResult.entity.version}</div>
                  </>
                )}
                {rResult.merged_from && <><div className="k">ادغام‌شده از</div><div className="num">{rResult.merged_from}</div></>}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <h2>نگاشت‌های ثبت‌شده</h2>
        {mappings.isLoading ? <Loading /> : mappings.error ? <ErrorBox error={mappings.error} /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>نصب</th><th>نوع</th><th>شناسه محلی</th><th>شناسه مشترک</th><th>وضعیت</th></tr></thead>
              <tbody>
                {(mappings.data?.items || []).map((m) => (
                  <tr key={m.id}>
                    <td>{m.installation_code}</td>
                    <td>{m.entity_type}</td>
                    <td className="num">{m.local_id}</td>
                    <td className="num small">{m.entity_id}</td>
                    <td><StatusBadge status={m.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(mappings.data?.items || []).length === 0 && <Empty />}
          </div>
        )}
      </div>
    </>
  )
}
