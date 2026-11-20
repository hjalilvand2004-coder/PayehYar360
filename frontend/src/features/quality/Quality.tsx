import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import type { MergeRecord, ResolutionCase } from '../../api/types'
import { ConfirmInline, Empty, ErrorBox, Loading, Modal, PageHead, StatusBadge } from '../../components/ui'
import { fmtDateTime } from '../../shared/format'
import { useAuth } from '../../auth/AuthContext'

interface Suggestion {
  matched_by: string[]
  candidates: Array<{ person_id: string; display_name: string; version: number }>
  evidence: { note?: string }
}

export default function Quality() {
  const qc = useQueryClient()
  const { me } = useAuth()
  const isSteward = (me?.roles || []).some((r) => ['steward', 'tenant_admin'].includes(r))
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [caseDetail, setCaseDetail] = useState<ResolutionCase | null>(null)
  const [confirmMerge, setConfirmMerge] = useState<{ caseId: string; target: string } | null>(null)
  const [mergeNote, setMergeNote] = useState('')

  const scan = useQuery({
    queryKey: ['dup-scan'],
    queryFn: () => api<{ items: Suggestion[] }>('/api/v1/quality/duplicate-scan'),
  })
  const cases = useQuery({
    queryKey: ['quality-cases'],
    queryFn: () => api<{ items: ResolutionCase[] }>('/api/v1/resolution-cases'),
  })
  const merges = useQuery({
    queryKey: ['merges'],
    queryFn: () => api<{ items: MergeRecord[] }>('/api/v1/merges'),
  })

  const createCase = useMutation({
    mutationFn: (candidate_ids: string[]) =>
      api('/api/v1/quality/cases', { method: 'POST', body: { candidate_ids, evidence: {} } }),
    onSuccess: () => {
      setNotice('پرونده تکرار ایجاد شد.'); setError('')
      qc.invalidateQueries({ queryKey: ['quality-cases'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const decideMerge = useMutation({
    mutationFn: ({ caseId, target, note }: { caseId: string; target: string; note: string }) =>
      api(`/api/v1/resolution-cases/${caseId}/merge`, { method: 'POST', body: { target_person_id: target, note } }),
    onSuccess: () => {
      setConfirmMerge(null); setMergeNote(''); setNotice('ادغام با موفقیت انجام شد.')
      qc.invalidateQueries({ queryKey: ['quality-cases'] }); qc.invalidateQueries({ queryKey: ['merges'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const reverse = useMutation({
    mutationFn: ({ mergeId, note }: { mergeId: string; note: string }) =>
      api(`/api/v1/merges/${mergeId}/reverse`, { method: 'POST', body: { note } }),
    onSuccess: () => {
      setNotice('بازگردانی ادغام انجام شد.'); qc.invalidateQueries({ queryKey: ['merges'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  return (
    <>
      <PageHead
        title="کیفیت داده"
        subtitle="تشخیص تکرار، پرونده بررسی و ادغام کنترل‌شده با تصمیم انسانی (FR-13)"
      />
      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert info">{notice}</div>}

      <div className="card">
        <h2>نامزدهای تکرار (کشف خودکار)</h2>
        <p className="muted small">شباهت نام فقط نامزد ایجاد می‌کند؛ شواهد هویتی منشأ و وضعیت تأیید دارند و تصمیم نهایی انسانی است.</p>
        {scan.isLoading ? <Loading /> : scan.error ? <ErrorBox error={scan.error} /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>شواهد</th><th>نامزدها</th><th></th></tr></thead>
              <tbody>
                {scan.data?.items?.map((s, idx) => (
                  <tr key={idx}>
                    <td>{s.matched_by.map((m) => <span key={m} className="chip" style={{ marginInlineEnd: 4 }}>
                      {m === 'same_name' ? 'نام یکسان' : 'شناسه تأییدشده یکسان'}</span>)}</td>
                    <td>{s.candidates.map((c) => c.display_name).join(' ↔ ')}</td>
                    <td>{isSteward && (
                      <button className="btn sm" disabled={createCase.isPending}
                              onClick={() => createCase.mutate(s.candidates.map((c) => c.person_id))}>
                        ایجاد پرونده
                      </button>
                    )}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {scan.data?.items.length === 0 && <Empty text="نامزد تکراری یافت نشد" />}
          </div>
        )}
      </div>

      <div className="card">
        <h2>پرونده‌های بررسی</h2>
        {cases.isLoading ? <Loading /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>وضعیت</th><th>نامزدها</th><th>ایجاد</th><th>تصمیم</th><th></th></tr></thead>
              <tbody>
                {(cases.data?.items || []).map((c) => (
                  <tr key={c.id}>
                    <td><StatusBadge status={c.status} /></td>
                    <td>{c.candidate_ids.length} نامزد</td>
                    <td className="small">{fmtDateTime(c.created_at)}</td>
                    <td className="small">{c.decided_at ? fmtDateTime(c.decided_at) : '—'}</td>
                    <td>
                      <button className="btn sm" onClick={() => setCaseDetail(c)}>بررسی</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(cases.data?.items || []).length === 0 && <Empty text="پرونده‌ای وجود ندارد" />}
          </div>
        )}
      </div>

      <div className="card">
        <h2>سابقه ادغام‌ها</h2>
        {merges.isLoading ? <Loading /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>منبع (قبلی)</th><th>هدف (نهایی)</th><th>وضعیت</th><th>تصمیم‌گیر</th><th>زمان</th><th></th></tr></thead>
              <tbody>
                {(merges.data?.items || []).map((m) => (
                  <tr key={m.id}>
                    <td className="num small">{m.source_person_id.slice(0, 8)}…</td>
                    <td className="num small">{m.target_person_id.slice(0, 8)}…</td>
                    <td><StatusBadge status={m.status} /></td>
                    <td className="small">{m.decided_by}</td>
                    <td className="small">{fmtDateTime(m.created_at)}</td>
                    <td>
                      {isSteward && m.status === 'applied' && (
                        <button className="btn sm ghost" onClick={() => reverse.mutate({ mergeId: m.id, note: 'بازگردانی از پنل' })}>
                          بازگردانی
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(merges.data?.items || []).length === 0 && <Empty />}
          </div>
        )}
        <p className="muted small">بازگردانی ادغام، فرآیند اصلاحی مستقل است؛ ممکن است داده تخصصی جدیدی پس از ادغام ایجاد شده باشد.</p>
      </div>

      {caseDetail && (
        <Modal title={`پرونده ${caseDetail.id.slice(0, 8)}… — ${caseDetail.status === 'open' ? 'در جریان' : 'تصمیم‌گیری‌شده'}`} wide onClose={() => setCaseDetail(null)}>
          {caseDetail.evidence.persons?.map((per) => (
            <div key={per.person_id} className="card" style={{ marginBottom: 10 }}>
              <b>{per.display_name}</b> <span className="muted small num">{per.person_id}</span>
              <div className="small muted">نسخه {per.version} — وضعیت: {per.status}</div>
              <div className="small">
                {(per.identifiers || []).map((i) => (
                  <span key={`${i.type}-${i.value_masked}`} className="chip" style={{ marginInlineEnd: 4 }}>
                    {i.type}: {i.value_masked} ({i.verification_status === 'verified' ? 'تأییدشده' : 'تأییدنشده'})
                  </span>
                ))}
              </div>
            </div>
          ))}
          {caseDetail.status === 'open' && isSteward && (
            <>
              <label>انتخاب شناسه نهایی</label>
              <select onChange={(e) => setConfirmMerge(e.target.value ? { caseId: caseDetail.id, target: e.target.value } : null)}>
                <option value="">— انتخاب کنید —</option>
                {caseDetail.candidate_ids.map((cid) => (
                  <option key={cid} value={cid}>{cid.slice(0, 8)}… ({caseDetail.evidence.persons?.find((p) => p.person_id === cid)?.display_name})</option>
                ))}
              </select>
              <label>یادداشت تصمیم</label>
              <input value={mergeNote} onChange={(e) => setMergeNote(e.target.value)} />
              {confirmMerge && (
                <ConfirmInline
                  message={`ادغام به شناسه ${confirmMerge.target.slice(0, 8)}… — نگاشت‌ها منتقل، سابقه و alias حفظ و رویداد PersonMerged منتشر می‌شود. این عمل را دوباره تأیید کنید.`}
                  busy={decideMerge.isPending}
                  onConfirm={() => decideMerge.mutate({ caseId: confirmMerge.caseId, target: confirmMerge.target, note: mergeNote })}
                  onCancel={() => setConfirmMerge(null)}
                />
              )}
            </>
          )}
          {caseDetail.decision && (
            <div className="alert info">
              تصمیم: {JSON.stringify(caseDetail.decision, null, 2)}
            </div>
          )}
        </Modal>
      )}
    </>
  )
}
