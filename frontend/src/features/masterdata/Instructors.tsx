import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import { Empty, ErrorBox, Loading, Modal, PageHead } from '../../components/ui'
import { fmtNumber } from '../../shared/format'

interface Instructor {
  id: string
  source_code: string
  full_name: string
  rank: string | null
  department: string | null
  email: string | null
  phone: string | null
  status: string
  source: string
  updated_at_jalali: string
}

/** صفحه اطلاعات پایه اساتید — واکشی از darsyar360 یا درج دستی؛ کد منبع اصلی حفظ می‌شود */
export default function Instructors() {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [rawJson, setRawJson] = useState('')
  const [lastSync, setLastSync] = useState<{ created: number; updated: number } | null>(null)

  const items = useQuery({
    queryKey: ['instructors', search],
    queryFn: () => api<{ items: Instructor[] }>(`/api/v1/masterdata/instructors?search=${encodeURIComponent(search)}`),
  })

  const sync = useMutation({
    mutationFn: () => api<{ created: number; updated: number; source: string }>('/api/v1/masterdata/sync/instructors', { method: 'POST' }),
    onSuccess: (d) => {
      setLastSync({ created: d.created, updated: d.updated })
      setNotice(`همگام‌سازی از منبع انجام شد: ${d.created} ایجاد، ${d.updated} بروزرسانی.`)
      setError(''); qc.invalidateQueries({ queryKey: ['instructors'] }); qc.invalidateQueries({ queryKey: ['md-catalog'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const importItems = useMutation({
    mutationFn: (payload: unknown[]) =>
      api<{ created: number; updated: number; skipped: number }>('/api/v1/masterdata/import/instructors', { method: 'POST', body: { items: payload } }),
    onSuccess: (d) => {
      setImportOpen(false); setRawJson(''); setLastSync({ created: d.created, updated: d.updated })
      setNotice(`درج انجام شد: ${d.created} ایجاد، ${d.updated} بروزرسانی${d.skipped ? `، ${d.skipped} ردیف نادیده` : ''}.`)
      setError(''); qc.invalidateQueries({ queryKey: ['instructors'] }); qc.invalidateQueries({ queryKey: ['md-catalog'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  return (
    <>
      <PageHead
        title="اساتید"
        subtitle="اطلاعات پایه مشترک اساتید — واکشی از سامانه نظرسنجی دروس (darsyar360) با حفظ کد اصلی منبع"
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
          <input placeholder="جست‌وجو در نام، کد یا گروه…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
          {items.data && <span className="chip">{fmtNumber(items.data.items.length)} استاد</span>}
        </div>
        {items.isLoading ? <Loading /> : items.error ? <ErrorBox error={items.error} /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>کد منبع</th><th>نام کامل</th><th>مرتبه علمی</th><th>گروه/دانشکده</th><th>ایمیل</th><th>منبع</th><th>بروزرسانی (شمسی)</th></tr></thead>
              <tbody>
                {(items.data?.items || []).map((i) => (
                  <tr key={i.id}>
                    <td className="num">{i.source_code}</td>
                    <td><b>{i.full_name}</b></td>
                    <td>{i.rank || '—'}</td>
                    <td>{i.department || '—'}</td>
                    <td className="num">{i.email || '—'}</td>
                    <td><span className="chip">{i.source === 'darsyar360' ? 'darsyar360' : i.source}</span></td>
                    <td className="small">{i.updated_at_jalali}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(items.data?.items || []).length === 0 && <Empty text="استادی ثبت نشده — با «همگام‌سازی از منبع» یا «درج دستی» شروع کنید" />}
          </div>
        )}
      </div>

      {importOpen && (
        <Modal title="درج دستی اساتید (JSON از صفحه منبع)" wide onClose={() => setImportOpen(false)}>
          <p className="muted small">
            از صفحه اساتید سامانه منبع (داخل اکانت ادمین)، داده‌ها را کپی و به‌صورت JSON بچسبانید.
            کلیدهای پذیرفته: <code dir="ltr">id/code</code>، <code dir="ltr">name/instructor_name/full_name</code>،
            <code dir="ltr">academic_rank</code>، <code dir="ltr">department</code>، <code dir="ltr">email</code>.
            کد اصلی منبع حفظ می‌شود و رکوردهای تکراری بروزرسانی می‌شوند.
          </p>
          <textarea
            dir="ltr" rows={10} style={{ width: '100%', fontFamily: 'monospace' }}
            placeholder={'[{"id": 12, "name": "دکتر …", "academic_rank": "استاد", "department": "…"}]'}
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
