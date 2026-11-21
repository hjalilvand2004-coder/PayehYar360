import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import type { MergeRecord, ResolutionCase } from '../../api/types'
import { ConfirmInline, Empty, ErrorBox, Loading, Modal, PageHead, StatusBadge } from '../../components/ui'
import { fmtDateTime } from '../../shared/format'
import { useAuth } from '../../auth/AuthContext'

// ---------- انواع داشبورد کیفیت ----------
interface QRow { [k: string]: unknown }
interface QCheck {
  check_id: string
  dimension: string
  domain: string
  title: string
  severity: 'high' | 'medium' | 'low'
  status: 'ok' | 'warn' | 'fail'
  affected: number
  total: number
  pass_rate: number
  what: string
  root_cause: string
  fix_hint: string
  rows: QRow[]
}
interface QOverview {
  score: number
  counts: { checks: number; ok: number; warn: number; fail: number; affected: number }
  dimensions: Array<{ key: string; title: string; score: number; checks: number; affected: number }>
  domains: Array<{ key: string; title: string; score: number; checks: number; affected: number }>
  checks: QCheck[]
  ops: { open_cases: number; decided_cases: number; merges_applied: number; merges_reversed: number }
}

interface Suggestion {
  matched_by: string[]
  candidates: Array<{ person_id: string; display_name: string; version: number }>
  evidence: { note?: string }
}

const DIM_TITLES: Record<string, string> = {
  completeness: 'کامل‌بودن', uniqueness: 'یکتایی', integrity: 'انسجام و مرجعیت',
  validity: 'اعتبار', coverage: 'پوشش', freshness: 'به‌روزبودن',
}
const SEV: Record<string, { label: string; cls: string }> = {
  high: { label: 'بحرانی', cls: 'danger' },
  medium: { label: 'هشدار', cls: 'warn' },
  low: { label: 'اطلاع', cls: '' },
}
const STATUS: Record<string, { label: string; cls: string }> = {
  ok: { label: 'سالم', cls: 'ok' },
  warn: { label: 'نیاز به توجه', cls: 'warn' },
  fail: { label: 'بحرانی', cls: 'danger' },
}
const COL_LABELS: Record<string, string> = {
  person_id: 'شناسه شخص', org_id: 'شناسه واحد', item_id: 'شناسه آیتم', mapping_id: 'شناسه نگاشت',
  installation_id: 'شناسه نصب', merged_person_id: 'شناسه ادغام‌شده', missing_parent_id: 'شناسه والد ناموجود',
  display_name: 'نام نمایشی', name: 'نام', title: 'عنوان', code: 'کد', item_code: 'کد درس',
  given_name: 'نام', family_name: 'نام‌خانوادگی', name_key: 'کلید نام', group_size: 'اندازه گروه',
  identifier_type: 'نوع شناسه', issuer: 'صادرکننده', value_masked: 'شناسه (ماسک)',
  local_id: 'شناسه محلی', entity_type: 'نوع موجودیت', entity_id: 'شناسه مشترک',
  entity_status: 'وضعیت هدف', installation: 'نصب', installation_status: 'وضعیت نصب', mode: 'حالت',
  type: 'نوع', version: 'نسخه', prereq_code: 'کد پیش‌نیاز', prereq_title: 'عنوان پیش‌نیاز',
  estimated_capacity: 'ظرفیت برآوردی', valid_to: 'اعتبار تا', cycle_root: 'گره حلقه',
}

function scoreCls(score: number): string {
  return score >= 90 ? 'ok' : score >= 70 ? 'warn' : 'danger'
}

function ScoreBar({ score }: { score: number }) {
  return (
    <div style={{ background: 'var(--line, #e5e7eb)', borderRadius: 6, height: 8, minWidth: 70, overflow: 'hidden' }}>
      <div style={{ width: `${Math.max(0, Math.min(100, score))}%`, height: '100%', borderRadius: 6,
        background: score >= 90 ? 'var(--ok, #16a34a)' : score >= 70 ? 'var(--warn, #d97706)' : 'var(--danger, #dc2626)' }} />
    </div>
  )
}

function RowsTable({ rows }: { rows: QRow[] }) {
  if (!rows.length) return <Empty text="ردیفی برای نمایش نیست" />
  const cols: string[] = []
  for (const r of rows) for (const k of Object.keys(r)) if (!cols.includes(k)) cols.push(k)
  return (
    <div className="table-wrap">
      <table className="tbl">
        <thead><tr>{cols.map((c) => <th key={c}>{COL_LABELS[c] || c}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {cols.map((c) => {
                const v = r[c]
                const isId = /(_id|_key|_hash)$/.test(c) || c === 'code' || c === 'item_code' || c === 'value_masked' || c === 'local_id'
                return (
                  <td key={c} className={isId ? 'num small' : 'small'} dir={isId ? 'ltr' : undefined}>
                    {v === null || v === undefined || v === '' ? '—' : String(v)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
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
  const [drill, setDrill] = useState<QCheck | null>(null)
  // فیلترهای داشبورد
  const [dimFilter, setDimFilter] = useState('')
  const [sevFilter, setSevFilter] = useState('')
  const [query, setQuery] = useState('')

  const overview = useQuery({
    queryKey: ['quality-overview'],
    queryFn: () => api<QOverview>('/api/v1/quality/overview'),
  })
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
      qc.invalidateQueries({ queryKey: ['quality-cases'] }); qc.invalidateQueries({ queryKey: ['quality-overview'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const decideMerge = useMutation({
    mutationFn: ({ caseId, target, note }: { caseId: string; target: string; note: string }) =>
      api(`/api/v1/resolution-cases/${caseId}/merge`, { method: 'POST', body: { target_person_id: target, note } }),
    onSuccess: () => {
      setConfirmMerge(null); setMergeNote(''); setNotice('ادغام با موفقیت انجام شد.')
      qc.invalidateQueries({ queryKey: ['quality-cases'] }); qc.invalidateQueries({ queryKey: ['merges'] })
      qc.invalidateQueries({ queryKey: ['quality-overview'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const reverse = useMutation({
    mutationFn: ({ mergeId, note }: { mergeId: string; note: string }) =>
      api(`/api/v1/merges/${mergeId}/reverse`, { method: 'POST', body: { note } }),
    onSuccess: () => {
      setNotice('بازگردانی ادغام انجام شد.')
      qc.invalidateQueries({ queryKey: ['merges'] }); qc.invalidateQueries({ queryKey: ['quality-overview'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const filtered = useMemo(() => {
    const items = overview.data?.checks || []
    return items.filter((c) =>
      (!dimFilter || c.dimension === dimFilter) &&
      (!sevFilter || c.status === sevFilter) &&
      (!query || c.title.includes(query) || c.check_id.includes(query)))
      .sort((a, b) => {
        const rank = { fail: 0, warn: 1, ok: 2 }
        return rank[a.status] - rank[b.status] || b.affected - a.affected
      })
  }, [overview.data, dimFilter, sevFilter, query])

  const total = overview.data?.counts

  return (
    <>
      <PageHead
        title="کیفیت داده"
        subtitle="داشبورد هدفمند: ۱۷ بررسی خودکار در ۶ بُعد × ۴ حوزه — با ریشه‌یابی تا سطح رکورد (Drill-down)"
        actions={
          <button className="btn ghost sm" onClick={() => overview.refetch()} disabled={overview.isFetching}>
            {overview.isFetching ? 'در حال بررسی…' : 'بررسی مجدد'}
          </button>
        }
      />
      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert info">{notice}</div>}

      {overview.isLoading ? <Loading /> : overview.error ? <ErrorBox error={overview.error} /> : (
        <>
          {/* امتیاز کل */}
          <div className="card" style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'center' }}>
            <div style={{ textAlign: 'center', minWidth: 110 }}>
              <div style={{ fontSize: 'clamp(2.2rem, 6vw, 3.4rem)', fontWeight: 700, lineHeight: 1 }}>
                {overview.data!.score}
                <span className="muted small"> /100</span>
              </div>
              <span className={`chip ${scoreCls(overview.data!.score)}`}>امتیاز کل کیفیت</span>
            </div>
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', flex: 1 }}>
              {total && (
                <>
                  <span className={`chip ${STATUS.ok.cls}`}>{total.ok} بررسی سالم</span>
                  <span className={`chip ${STATUS.warn.cls}`}>{total.warn} نیاز به توجه</span>
                  <span className={`chip ${STATUS.fail.cls}`}>{total.fail} بحرانی</span>
                  <span className="chip">{total.affected} رکورد متأثر</span>
                  <span className="chip">{overview.data!.ops.open_cases} پرونده تکرار باز</span>
                </>
              )}
            </div>
          </div>

          {/* ابعاد شش‌گانه */}
          <div className="card">
            <h2>امتیاز به تفکیک بُعد</h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }}>
              {overview.data!.dimensions.map((d) => (
                <div key={d.key} className="card" style={{ margin: 0, padding: '10px 12px', cursor: 'pointer' }}
                     onClick={() => { setDimFilter(dimFilter === d.key ? '' : d.key); setSevFilter('') }}>
                  <div className="muted small">{d.title}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <b style={{ fontSize: '1.4rem' }}>{d.score}</b>
                    <ScoreBar score={d.score} />
                  </div>
                  <div className="muted small">{d.checks} بررسی — {d.affected} متأثر</div>
                </div>
              ))}
            </div>
          </div>

          {/* حوزه‌ها */}
          <div className="card">
            <h2>امتیاز به تفکیک حوزه</h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }}>
              {overview.data!.domains.map((d) => (
                <div key={d.key} className="card" style={{ margin: 0, padding: '10px 12px' }}>
                  <div className="muted small">{d.title}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <b style={{ fontSize: '1.4rem' }}>{d.score}</b>
                    <ScoreBar score={d.score} />
                  </div>
                  <div className="muted small">{d.checks} بررسی — {d.affected} متأثر</div>
                </div>
              ))}
            </div>
          </div>

          {/* جدول بررسی‌ها با فیلتر */}
          <div className="card">
            <h2>بررسی‌ها {dimFilter && `— بُعد «${DIM_TITLES[dimFilter] || dimFilter}»`}
              <button className="btn ghost sm" style={{ marginInlineStart: 8 }} onClick={() => { setDimFilter(''); setSevFilter(''); setQuery('') }}>
                حذف فیلترها
              </button>
            </h2>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
              <select value={dimFilter} onChange={(e) => setDimFilter(e.target.value)}>
                <option value="">همه ابعاد</option>
                {overview.data!.dimensions.map((d) => <option key={d.key} value={d.key}>{d.title}</option>)}
              </select>
              <select value={sevFilter} onChange={(e) => setSevFilter(e.target.value)}>
                <option value="">همه وضعیت‌ها</option>
                <option value="fail">بحرانی</option>
                <option value="warn">نیاز به توجه</option>
                <option value="ok">سالم</option>
              </select>
              <input placeholder="جست‌وجو در عنوان بررسی…" value={query} onChange={(e) => setQuery(e.target.value)} style={{ flex: 1, minWidth: 180 }} />
            </div>
            <div className="table-wrap">
              <table className="tbl">
                <thead>
                  <tr><th>بُعد</th><th>حوزه</th><th>بررسی</th><th>شدت</th><th>وضعیت</th><th>متأثر / کل</th><th>گذر</th><th></th></tr>
                </thead>
                <tbody>
                  {filtered.map((c) => (
                    <tr key={c.check_id}>
                      <td className="small">{DIM_TITLES[c.dimension] || c.dimension}</td>
                      <td className="small">{(overview.data!.domains.find((d) => d.key === c.domain) || {}).title || c.domain}</td>
                      <td><b>{c.title}</b></td>
                      <td><span className={`chip ${SEV[c.severity].cls}`}>{SEV[c.severity].label}</span></td>
                      <td><span className={`chip ${STATUS[c.status].cls}`}>{STATUS[c.status].label}</span></td>
                      <td className="num">{c.affected} / {c.total}</td>
                      <td style={{ minWidth: 90 }}><ScoreBar score={c.pass_rate} /></td>
                      <td>
                        {c.affected > 0 && (
                          <button className="btn sm ghost" onClick={() => setDrill(c)}>ریشه‌یابی</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {filtered.length === 0 && <Empty text="بررسی‌ای با این فیلترها نیست" />}
            </div>
          </div>
        </>
      )}

      {/* مودال ریشه‌یابی */}
      {drill && (
        <Modal title={`ریشه‌یابی — ${drill.title}`} wide onClose={() => setDrill(null)}>
          <div className="alert info"><b>معنا:</b> {drill.what}</div>
          <div className="alert warn"><b>ریشه رایج:</b> {drill.root_cause}</div>
          <div className="alert error" style={{ marginBottom: 12 }}><b>راه اصلاح:</b> {drill.fix_hint}</div>
          <RowsTable rows={drill.rows} />
          {drill.affected > drill.rows.length && (
            <p className="muted small" style={{ marginTop: 8 }}>
              نمایش {drill.rows.length} مورد اول از {drill.affected} — برای بقیه، فیلترهای صفحه اصلی همان موجودیت را ببینید.
            </p>
          )}
        </Modal>
      )}

      {/* ---------- جریان رفع تکرار (FR-13) ---------- */}
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
