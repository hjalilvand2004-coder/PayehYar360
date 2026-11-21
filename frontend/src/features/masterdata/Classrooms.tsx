import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import { Empty, ErrorBox, Loading, Modal, PageHead } from '../../components/ui'
import { fmtNumber } from '../../shared/format'

interface Classroom {
  id: string
  source_code: string
  name: string
  kind: string | null
  building: string | null
  capacity: number | null
  status: string
  source: string
  updated_at_jalali: string
}

/** صفحه کلاس‌ها و سالن‌ها — واکشی دقیق همان سرویس از سامانه برنامه‌ریزی درسی (8083) یا درج دستی */
export default function Classrooms() {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [rawJson, setRawJson] = useState('')

  const items = useQuery({
    queryKey: ['classrooms', search],
    queryFn: () => api<{ items: Classroom[] }>(`/api/v1/masterdata/classrooms?search=${encodeURIComponent(search)}`),
  })

  const sync = useMutation({
    mutationFn: () => api<{ created: number; updated: number; source: string }>('/api/v1/masterdata/sync/classrooms', { method: 'POST' }),
    onSuccess: (d) => {
      setNotice(`همگام‌سازی از سامانه برنامه‌ریزی درسی انجام شد: ${d.created} ایجاد، ${d.updated} بروزرسانی.`)
      setError(''); qc.invalidateQueries({ queryKey: ['classrooms'] }); qc.invalidateQueries({ queryKey: ['md-catalog'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const importItems = useMutation({
    mutationFn: (payload: unknown[]) =>
      api<{ created: number; updated: number; skipped: number }>('/api/v1/masterdata/import/classrooms', { method: 'POST', body: { items: payload } }),
    onSuccess: (d) => {
      setImportOpen(false); setRawJson('')
      setNotice(`درج انجام شد: ${d.created} ایجاد، ${d.updated} بروزرسانی${d.skipped ? `، ${d.skipped} ردیف نادیده` : ''}.`)
      setError(''); qc.invalidateQueries({ queryKey: ['classrooms'] }); qc.invalidateQueries({ queryKey: ['md-catalog'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  return (
    <>
      <PageHead
        title="کلاس‌ها و سالن‌ها"
        subtitle="فضاهای آموزشی مشترک — واکشی دقیق از فرم «کلاس‌ها و سالن‌ها» سامانه برنامه‌ریزی درسی (188.212.96.235:8083)"
        actions={
          <>
            <button className="btn sm" onClick={() => setImportOpen(true)}>درج دستی</button>
            <button className="btn primary sm" onClick={() => sync.mutate()} disabled={sync.isPending}>
              {sync.isPending ? 'در حال واکشی…' : 'همگام‌سازی از منبع'}
            </button>
          </>
        }
      />
      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert info">{notice}</div>}

      <div className="card">
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
          <input placeholder="جست‌وجو در نام، کد یا ساختمان…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
          {items.data && <span className="chip">{fmtNumber(items.data.items.length)} فضا</span>}
        </div>
        {items.isLoading ? <Loading /> : items.error ? <ErrorBox error={items.error} /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>کد منبع</th><th>نام</th><th>نوع</th><th>ساختمان/محل</th><th>ظرفیت</th><th>منبع</th><th>بروزرسانی (شمسی)</th></tr></thead>
              <tbody>
                {(items.data?.items || []).map((c) => (
                  <tr key={c.id}>
                    <td className="num">{c.source_code}</td>
                    <td><b>{c.name}</b></td>
                    <td>{c.kind || '—'}</td>
                    <td>{c.building || '—'}</td>
                    <td className="num">{c.capacity === null ? '—' : fmtNumber(c.capacity)}</td>
                    <td><span className="chip">{c.source === 'scheduler8083' ? 'برنامه‌ریزی درسی' : c.source}</span></td>
                    <td className="small">{c.updated_at_jalali}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(items.data?.items || []).length === 0 && <Empty text="فضایی ثبت نشده — با «همگام‌سازی از منبع» یا «درج دستی» شروع کنید" />}
          </div>
        )}
      </div>

      {importOpen && (
        <Modal title="درج دستی کلاس‌ها و سالن‌ها (JSON)" wide onClose={() => setImportOpen(false)}>
          <p className="muted small">
            داده‌های صفحه «کلاس‌ها و سالن‌ها» سامانه برنامه‌ریزی درسی را به‌صورت JSON بچسبانید.
            کلیدهای پذیرفته: <code dir="ltr">id/code</code>، <code dir="ltr">name/room_name</code>،
            <code dir="ltr">room_type</code>، <code dir="ltr">building</code>، <code dir="ltr">capacity</code>.
          </p>
          <textarea
            dir="ltr" rows={10} style={{ width: '100%', fontFamily: 'monospace' }}
            placeholder={'[{"id": 1, "name": "کلاس ۲۰۱", "room_type": "کلاس", "capacity": 40, "building": "…"}]'}
            value={rawJson} onChange={(e) => setRawJson(e.target.value)}
          />
          <div className="modal-foot">
            <button className="btn primary" disabled={importItems.isPending}
                    onClick={() => { try { importItems.mutate(JSON.parse(rawJson)) } catch { setError('JSON نامعتبر است.') } }}>
              {importItems.isPending ? 'در حال ثبت…' : 'ثبت'}
            </button>
            <button className="btn" onClick={() => setImportOpen(false)}>انصراف</button>
          </div>
        </Modal>
      )}
    </>
  )
}
