import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import { ConfirmInline, Empty, ErrorBox, Loading, Modal, PageHead, StatusBadge } from '../../components/ui'
import { fmtNumber } from '../../shared/format'

interface CatalogItem {
  domain: string
  title: string
  endpoint: string
  count: number
  source_configured: boolean
  last_sync: { at: string; at_jalali: string; source: string | null; status: string; count: number } | null
  last_fetch: { at: string; at_jalali: string; client: string | null; status: string; count: number } | null
}

interface ServiceClient {
  id: string
  code: string
  title: string
  api_key_masked: string
  scopes: string[]
  status: string
  last_seen_at_jalali: string | null
  note: string | null
}

interface FetchLog {
  id: string
  direction: string
  domain: string
  client_code: string | null
  source: string | null
  record_count: number
  status: string
  http_status: number | null
  duration_ms: number | null
  error: string | null
  occurred_at_jalali: string
}

/** صفحه سرویس‌های داده — نقطه مشخص بروزرسانی سایر سامانه‌ها و دریافت سرویس، با تاریخچه شمسی */
export default function MasterServices() {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [clientOpen, setClientOpen] = useState(false)
  const [newCode, setNewCode] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [newScopes, setNewScopes] = useState('')
  const [newKey, setNewKey] = useState('')
  const [revokeId, setRevokeId] = useState<string | null>(null)
  const [dirFilter, setDirFilter] = useState('')

  const catalog = useQuery({
    queryKey: ['md-catalog'],
    queryFn: () => api<{ items: CatalogItem[] }>('/api/v1/masterdata/catalog'),
  })
  const clients = useQuery({
    queryKey: ['md-clients'],
    queryFn: () => api<{ items: ServiceClient[] }>('/api/v1/masterdata/service-clients'),
  })
  const logs = useQuery({
    queryKey: ['md-logs', dirFilter],
    queryFn: () => api<{ items: FetchLog[] }>(`/api/v1/masterdata/fetch-logs?limit=100${dirFilter ? `&direction=${dirFilter}` : ''}`),
  })

  const createClient = useMutation({
    mutationFn: () =>
      api<ServiceClient & { api_key: string }>('/api/v1/masterdata/service-clients', {
        method: 'POST',
        body: { code: newCode.trim(), title: newTitle.trim() || newCode.trim(),
                scopes: newScopes.split(/[,،\s]+/).map((s) => s.trim()).filter(Boolean) },
      }),
    onSuccess: (d) => {
      setNewKey(d.api_key); setNewCode(''); setNewTitle(''); setNewScopes('')
      qc.invalidateQueries({ queryKey: ['md-clients'] }); qc.invalidateQueries({ queryKey: ['md-catalog'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const revoke = useMutation({
    mutationFn: (id: string) => api(`/api/v1/masterdata/service-clients/${id}/revoke`, { method: 'POST' }),
    onSuccess: () => {
      setRevokeId(null); setNotice('دسترسی سامانه قطع شد.')
      qc.invalidateQueries({ queryKey: ['md-clients'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ['md-catalog'] }); qc.invalidateQueries({ queryKey: ['md-logs'] })
    qc.invalidateQueries({ queryKey: ['md-clients'] })
  }

  return (
    <>
      <PageHead
        title="سرویس‌های داده"
        subtitle="نقطه مشخص بروزرسانی سایر سامانه‌ها و دریافت سرویس اطلاعات پایه — با کلید API و تاریخچه شمسی"
        actions={<button className="btn ghost sm" onClick={refreshAll}>بروزرسانی نمایش</button>}
      />
      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert info">{notice}</div>}

      {/* کاتالوگ سرویس‌ها */}
      <div className="card">
        <h2>کاتالوگ سرویس‌ها برای سامانه‌های اکوسیستم</h2>
        <p className="muted small">
          هر سامانه با هدر <code dir="ltr">X-API-Key</code> به آدرس زیر وصل می‌شود؛ هر واکشی در تاریخچه ثبت می‌شود.
          نمونه: <code dir="ltr" className="num">curl -H "X-API-Key: …" http://…:8094/api/v1/services/masterdata/instructors</code>
        </p>
        {catalog.isLoading ? <Loading /> : catalog.error ? <ErrorBox error={catalog.error} /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>سرویس</th><th>آدرس</th><th>رکورد</th><th>آخرین بروزرسانی از منبع</th><th>آخرین واکشی سامانه‌ها</th><th>پیکربندی منبع</th></tr></thead>
              <tbody>
                {(catalog.data?.items || []).map((d) => (
                  <tr key={d.domain}>
                    <td><b>{d.title}</b></td>
                    <td dir="ltr" className="num small">{d.endpoint}</td>
                    <td className="num">{fmtNumber(d.count)}</td>
                    <td className="small">
                      {d.last_sync ? `${d.last_sync.at_jalali} — ${d.last_sync.status === 'success' ? 'موفق' : 'ناموفق'} (${d.last_sync.source || '—'})` : '—'}
                    </td>
                    <td className="small">
                      {d.last_fetch ? `${d.last_fetch.at_jalali} — ${d.last_fetch.client || '—'}` : '—'}
                    </td>
                    <td>{['instructors', 'classrooms'].includes(d.domain)
                      ? <span className={`chip ${d.source_configured ? 'ok' : 'warn'}`}>{d.source_configured ? 'تنظیم‌شده' : 'نیازمند پیکربندی'}</span>
                      : <span className="chip ok">داخلی</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* کلاینت‌ها */}
      <div className="card">
        <h2>سامانه‌های مصرف‌کننده (کلید API)</h2>
        <button className="btn primary sm" style={{ marginBottom: 8 }} onClick={() => { setClientOpen(true); setNewKey('') }}>ایجاد کلید جدید</button>
        {clients.isLoading ? <Loading /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>کد</th><th>عنوان</th><th>کلید</th><th>دامنه‌های مجاز</th><th>وضعیت</th><th>آخرین استفاده</th><th></th></tr></thead>
              <tbody>
                {(clients.data?.items || []).map((c) => (
                  <tr key={c.id}>
                    <td className="num">{c.code}</td>
                    <td>{c.title}</td>
                    <td dir="ltr" className="num small">{c.api_key_masked}</td>
                    <td className="small">{c.scopes.length ? c.scopes.join('، ') : 'همه دامنه‌ها'}</td>
                    <td><StatusBadge status={c.status} /></td>
                    <td className="small">{c.last_seen_at_jalali || '—'}</td>
                    <td>{c.status === 'active' && (
                      <button className="btn sm ghost" onClick={() => setRevokeId(c.id)}>قطع دسترسی</button>
                    )}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(clients.data?.items || []).length === 0 && <Empty text="سامانه مصرف‌کننده‌ای ثبت نشده" />}
          </div>
        )}
        <p className="muted small">کلید کامل فقط هنگام ایجاد نمایش داده می‌شود و بعداً قابل بازیابی نیست؛ فقط hash آن ذخیره می‌شود.</p>
      </div>

      {/* تاریخچه */}
      <div className="card">
        <h2>تاریخچه واکشی و بروزرسانی</h2>
        <div style={{ display: 'flex', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
          <select value={dirFilter} onChange={(e) => setDirFilter(e.target.value)}>
            <option value="">همه رخدادها</option>
            <option value="out">واکشی سایر سامانه‌ها</option>
            <option value="in">بروزرسانی از منبع</option>
          </select>
          <span className="chip">{logs.data?.items.length ? fmtNumber(logs.data.items.length) + ' رخداد اخیر' : '—'}</span>
        </div>
        {logs.isLoading ? <Loading /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>زمان (شمسی)</th><th>نوع</th><th>سرویس</th><th>سامانه/منبع</th><th>تعداد</th><th>وضعیت</th><th>مدت</th><th>خطا</th></tr></thead>
              <tbody>
                {(logs.data?.items || []).map((l) => (
                  <tr key={l.id}>
                    <td className="small">{l.occurred_at_jalali}</td>
                    <td>{l.direction === 'out' ? 'واکشی ← ما' : 'بروزرسانی ← از منبع'}</td>
                    <td>{l.domain}</td>
                    <td className="small">{l.direction === 'out' ? l.client_code : (l.source || '—')}</td>
                    <td className="num">{fmtNumber(l.record_count)}</td>
                    <td><span className={`chip ${l.status === 'success' ? 'ok' : 'danger'}`}>{l.status === 'success' ? 'موفق' : 'ناموفق'}</span></td>
                    <td className="num small">{l.duration_ms === null ? '—' : `${l.duration_ms}ms`}</td>
                    <td className="small" title={l.error || ''}>{l.error ? l.error.slice(0, 60) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(logs.data?.items || []).length === 0 && <Empty text="رخدادی ثبت نشده" />}
          </div>
        )}
        <p className="muted small">زمان‌ها به‌وقت تهران و به‌صورت شمسی ذخیره و نمایش داده می‌شوند؛ در پاسخ API هم میلادی (UTC) و هم شمسی ارسال می‌شود.</p>
      </div>

      {/* مودال ایجاد کلید */}
      {clientOpen && (
        <Modal title="ایجاد کلید API برای سامانه جدید" onClose={() => setClientOpen(false)}>
          {newKey ? (
            <>
              <div className="alert info">
                کلید فقط همین یک بار نمایش داده می‌شود — همین حالا در سامانه مصرف‌کننده ذخیره کنید:
              </div>
              <input dir="ltr" readOnly value={newKey} style={{ fontFamily: 'monospace' }} onFocus={(e) => e.currentTarget.select()} />
              <div className="modal-foot">
                <button className="btn primary" onClick={() => { setClientOpen(false); setNotice('کلید ایجاد شد.') }}>ذخیره شد</button>
              </div>
            </>
          ) : (
            <>
              <label>کد سامانه (لاتین، مثل edu یا scheduler)</label>
              <input dir="ltr" value={newCode} onChange={(e) => setNewCode(e.target.value)} />
              <label>عنوان</label>
              <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="مثلاً سامانه آموزش" />
              <label>دامنه‌های مجاز (اختیاری — با کاما؛ خالی = همه)</label>
              <input dir="ltr" value={newScopes} onChange={(e) => setNewScopes(e.target.value)}
                     placeholder="instructors, classrooms, organizations, unique-courses, reference-items" />
              <div className="modal-foot">
                <button className="btn primary" disabled={!newCode.trim() || createClient.isPending} onClick={() => createClient.mutate()}>
                  {createClient.isPending ? 'در حال ایجاد…' : 'ایجاد کلید'}
                </button>
                <button className="btn" onClick={() => setClientOpen(false)}>انصراف</button>
              </div>
            </>
          )}
        </Modal>
      )}

      {revokeId && (
        <Modal title="قطع دسترسی سامانه" onClose={() => setRevokeId(null)}>
          <ConfirmInline
            message="با قطع دسترسی، واکشی‌های این سامانه با کلید فعلی بلافاصله 401 می‌گیرد و در تاریخچه ثبت می‌شود."
            busy={revoke.isPending}
            onConfirm={() => revoke.mutate(revokeId)}
            onCancel={() => setRevokeId(null)}
          />
        </Modal>
      )}
    </>
  )
}
