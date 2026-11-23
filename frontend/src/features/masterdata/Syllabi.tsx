import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import { Empty, ErrorBox, Loading, Modal, PageHead, ConfirmInline } from '../../components/ui'
import { fmtNumber } from '../../shared/format'
import { useAuth } from '../../auth/AuthContext'

interface SyllabusRow {
  id: string
  source_set: string
  source_file: string
  title_fa: string | null
  title_en: string
  course_code: string | null
  course_type: string | null
  unit_theory: number | null
  unit_practice: number | null
  hour_theory: number | null
  hour_practice: number | null
  has_text: boolean
  status: string
  topics_count: number
  updated_at_jalali: string
}

interface SyllabusDetail extends SyllabusRow {
  prerequisites: string | null
  corequisites: string | null
  general_goal: string | null
  evaluation: string | null
  references: string | null
  source: string
  topics: Array<{ seq: number; title: string; hours: number | null; hours_practice: number | null }>
}

interface Stats {
  total: number
  by_set: Record<string, number>
  topics_total: number
  scanned_without_text: number
  sets_labels: Record<string, string>
}

const SET_BADGE: Record<string, string> = { '1394': '۱۳۹۴', CE403: 'CE ۴۰۳', NP1400: 'NP ۱۴۰۰', MANUAL: 'دستی' }
const SETS = ['1394', 'CE403', 'NP1400']

/** صفحه سرفصل‌های مصوب دروس — اطلاعات پایه مشترک اکوسیستم؛ مصرف سایر سامانه‌ها از دامنه course-syllabi */
export default function Syllabi() {
  const qc = useQueryClient()
  const { me } = useAuth()
  const canEdit = (me?.roles || []).some((r) => ['master_data_editor', 'steward', 'tenant_admin'].includes(r))
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [setFilter, setSetFilter] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [rawJson, setRawJson] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)
  const [editOpen, setEditOpen] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<Record<string, string>>({})
  const [editTopics, setEditTopics] = useState<Array<{ title: string; hours: string; hours_practice: string }>>([])

  const stats = useQuery({
    queryKey: ['syllabi-stats'],
    queryFn: () => api<Stats>('/api/v1/masterdata/syllabi-stats'),
  })

  const items = useQuery({
    queryKey: ['syllabi', search, setFilter],
    queryFn: () => api<{ items: SyllabusRow[] }>(
      `/api/v1/masterdata/syllabi?search=${encodeURIComponent(search)}&source_set=${encodeURIComponent(setFilter)}`),
  })

  const detail = useQuery({
    queryKey: ['syllabus', openId],
    queryFn: () => api<SyllabusDetail>(`/api/v1/masterdata/syllabi/${openId}`),
    enabled: !!openId,
  })

  const importItems = useMutation({
    mutationFn: (payload: unknown[]) =>
      api<{ created: number; updated: number; skipped: number }>('/api/v1/masterdata/import/syllabi',
        { method: 'POST', body: { items: payload, source: 'manual' } }),
    onSuccess: (d) => {
      setImportOpen(false); setRawJson('')
      setNotice(`درج سرفصل‌ها انجام شد: ${d.created} ایجاد، ${d.updated} بروزرسانی${d.skipped ? `، ${d.skipped} ردیف نادیده` : ''}.`)
      setError(''); qc.invalidateQueries({ queryKey: ['syllabi'] }); qc.invalidateQueries({ queryKey: ['syllabi-stats'] })
      qc.invalidateQueries({ queryKey: ['md-catalog'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const [deleteOpen, setDeleteOpen] = useState(false)
  const deleteSet = useMutation({
    mutationFn: (sset: string) =>
      api<{ source_set: string; deleted_syllabi: number; deleted_topics: number }>(
        `/api/v1/masterdata/syllabi/set/${encodeURIComponent(sset)}`, { method: 'DELETE' }),
    onSuccess: (d) => {
      setDeleteOpen(false); setSetFilter('')
      setNotice(`مجموعه «${SET_BADGE[d.source_set] || d.source_set}» حذف شد: ${d.deleted_syllabi} سند و ${d.deleted_topics} سرفصل.`)
      setError(''); qc.invalidateQueries({ queryKey: ['syllabi'] }); qc.invalidateQueries({ queryKey: ['syllabi-stats'] })
      qc.invalidateQueries({ queryKey: ['md-catalog'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const editSyllabus = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api<SyllabusDetail>(`/api/v1/masterdata/syllabi/${id}`, { method: 'PATCH', body }),
    onSuccess: () => {
      setEditOpen(false); setEditId(null)
      setNotice('سرفصل ویرایش شد — سایر سامانه‌ها در همگام‌سازی دلتایی این تغییر را دریافت می‌کنند.')
      setError(''); qc.invalidateQueries({ queryKey: ['syllabi'] }); qc.invalidateQueries({ queryKey: ['syllabi-stats'] })
      qc.invalidateQueries({ queryKey: ['syllabus'] }); qc.invalidateQueries({ queryKey: ['md-catalog'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const openEdit = (d: SyllabusDetail) => {
    const s = (v: number | string | null | undefined) => (v === null || v === undefined ? '' : String(v))
    setEditId(d.id)
    setEditForm({
      title_fa: s(d.title_fa), title_en: s(d.title_en), course_code: s(d.course_code),
      course_type: s(d.course_type), unit_theory: s(d.unit_theory), unit_practice: s(d.unit_practice),
      hour_theory: s(d.hour_theory), hour_practice: s(d.hour_practice),
      prerequisites: s(d.prerequisites), corequisites: s(d.corequisites),
      general_goal: s(d.general_goal), evaluation: s(d.evaluation), references: s(d.references),
    })
    setEditTopics(d.topics.map((t) => ({
      title: t.title, hours: s(t.hours), hours_practice: s(t.hours_practice),
    })))
    setOpenId(null); setEditOpen(true)
  }

  const numOrNull = (s: string) => (s.trim() ? Number(s) : null)

  const saveEdit = () => {
    if (!editId) return
    if (!editForm.title_en.trim() && !editForm.title_fa.trim()) {
      setError('عنوان انگلیسی (یا فارسی به‌عنوان جایگزین) لازم است.')
      return
    }
    editSyllabus.mutate({
      id: editId,
      body: {
        title_fa: editForm.title_fa.trim() || null, title_en: editForm.title_en.trim(),
        course_code: editForm.course_code.trim() || null, course_type: editForm.course_type.trim() || null,
        unit_theory: numOrNull(editForm.unit_theory), unit_practice: numOrNull(editForm.unit_practice),
        hour_theory: numOrNull(editForm.hour_theory), hour_practice: numOrNull(editForm.hour_practice),
        prerequisites: editForm.prerequisites.trim() || null, corequisites: editForm.corequisites.trim() || null,
        general_goal: editForm.general_goal.trim() || null, evaluation: editForm.evaluation.trim() || null,
        references: editForm.references.trim() || null,
        topics: editTopics
          .filter((t) => t.title.trim())
          .map((t, i) => ({ seq: i + 1, title: t.title.trim(), hours: numOrNull(t.hours), hours_practice: numOrNull(t.hours_practice) })),
      },
    })
  }

  const moveTopic = (i: number, dir: -1 | 1) => {
    const j = i + dir
    if (j < 0 || j >= editTopics.length) return
    const next = [...editTopics]
    ;[next[i], next[j]] = [next[j], next[i]]
    setEditTopics(next)
  }

  const unitText = (r: SyllabusRow) => {
    const parts = []
    if (r.unit_theory) parts.push(`نظری ${fmtNumber(r.unit_theory)}`)
    if (r.unit_practice) parts.push(`عملی ${fmtNumber(r.unit_practice)}`)
    return parts.join(' + ') || '—'
  }
  const hourText = (r: SyllabusRow) => {
    const parts = []
    if (r.hour_theory) parts.push(`نظری ${fmtNumber(r.hour_theory)}`)
    if (r.hour_practice) parts.push(`عملی ${fmtNumber(r.hour_practice)}`)
    return parts.join(' + ') || '—'
  }

  return (
    <>
      <PageHead
        title="سرفصل دروس"
        subtitle="سرفصل‌های مصوب دروس (۱۳۹۴ / سری ۴۰۳ / ۱۴۰۰) به‌عنوان اطلاعات پایه مشترک — همه سامانه‌ها از دامنه course-syllabi مصرف می‌کنند"
        actions={<button className="btn sm" onClick={() => setImportOpen(true)}>درج دستی</button>}
      />
      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert info">{notice}</div>}

      {deleteOpen && setFilter && (
        <ConfirmInline
          message={`کل سندهای مجموعه «${SET_BADGE[setFilter] || setFilter}» به‌همراه همه سرفصل‌های آن‌ها حذف می‌شود (مثلاً برای ایمپورت مجدد نسخه کامل OCRشده). این عمل بازگشت‌ناپذیر است — ادامه؟`}
          busy={deleteSet.isPending}
          onConfirm={() => deleteSet.mutate(setFilter)}
          onCancel={() => setDeleteOpen(false)}
        />
      )}

      {stats.data && (
        <div className="card" style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <span className="chip">{fmtNumber(stats.data.total)} سند سرفصل</span>
          <span className="chip">{fmtNumber(stats.data.topics_total)} سرفصل/ریز محتوا</span>
          {SETS.map((s) => (
            <span className="chip" key={s}>
              {SET_BADGE[s]}: {fmtNumber(stats.data.by_set[s] || 0)}
            </span>
          ))}
          {stats.data.scanned_without_text > 0 && (
            <span className="chip" title="اسناد اسکن‌شده بدون لایه متنی — نیازمند OCR">
              {fmtNumber(stats.data.scanned_without_text)} اسکن (بدون متن)
            </span>
          )}
        </div>
      )}

      <div className="card">
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
          <input placeholder="جست‌وجو در عنوان فارسی، انگلیسی یا کد درس…" value={search}
                 onChange={(e) => setSearch(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
          <button className={`btn sm${setFilter === '' ? ' primary' : ''}`} onClick={() => setSetFilter('')}>همه</button>
          {SETS.map((s) => (
            <button key={s} className={`btn sm${setFilter === s ? ' primary' : ''}`} onClick={() => setSetFilter(s)}>
              {SET_BADGE[s]}
            </button>
          ))}
          {setFilter && (
            <button className="btn danger sm" title="حذف کل سندهای این مجموعه برای ایمپورت مجدد"
                    onClick={() => setDeleteOpen(true)}>حذف مجموعه</button>
          )}
        </div>
        {items.isLoading ? <Loading /> : items.error ? <ErrorBox error={items.error} /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr>
                <th>کد</th><th>عنوان فارسی</th><th>عنوان انگلیسی</th><th>مجموعه</th><th>نوع</th>
                <th>واحد</th><th>ساعت</th><th>سرفصل‌ها</th><th>متن</th><th>بروزرسانی</th>
              </tr></thead>
              <tbody>
                {(items.data?.items || []).map((r) => (
                  <tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => setOpenId(r.id)}>
                    <td className="num">{r.course_code || '—'}</td>
                    <td><b>{r.title_fa || '—'}</b></td>
                    <td dir="ltr" style={{ textAlign: 'right' }}>{r.title_en}</td>
                    <td><span className="chip">{SET_BADGE[r.source_set] || r.source_set}</span></td>
                    <td className="small">{r.course_type || '—'}</td>
                    <td className="small">{unitText(r)}</td>
                    <td className="small">{hourText(r)}</td>
                    <td className="num">{fmtNumber(r.topics_count)}</td>
                    <td className="small">{r.has_text ? '✓' : 'اسکن'}</td>
                    <td className="small">{r.updated_at_jalali}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(items.data?.items || []).length === 0 && <Empty text="سرفصلی ثبت نشده — با «درج دستی» یا ایمپورت فایل‌های سرفصل شروع کنید" />}
          </div>
        )}
      </div>

      {openId && (
        <Modal title={detail.data ? (detail.data.title_fa || detail.data.title_en) : 'جزئیات سرفصل'} wide onClose={() => setOpenId(null)}>
          {detail.isLoading ? <Loading /> : detail.error ? <ErrorBox error={detail.error} /> : detail.data && (
            <>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                <span className="chip">{SET_BADGE[detail.data.source_set] || detail.data.source_set}</span>
                {detail.data.course_code && <span className="chip num">{detail.data.course_code}</span>}
                {detail.data.course_type && <span className="chip">{detail.data.course_type}</span>}
                <span className="chip">واحد: {unitText(detail.data)}</span>
                <span className="chip">ساعت: {hourText(detail.data)}</span>
                <span className="chip small" dir="ltr">{detail.data.source_file}</span>
                {canEdit && (
                  <button className="btn primary sm" style={{ marginInlineStart: 'auto' }}
                          onClick={() => openEdit(detail.data)}>ویرایش</button>
                )}
              </div>
              {detail.data.general_goal && (
                <p><b>هدف کلی:</b> {detail.data.general_goal}</p>
              )}
              {(detail.data.prerequisites || detail.data.corequisites) && (
                <p className="small">
                  {detail.data.prerequisites && <><b>پیش‌نیاز:</b> {detail.data.prerequisites} </>}
                  {detail.data.corequisites && <><b>هم‌نیاز:</b> {detail.data.corequisites}</>}
                </p>
              )}
              <h4 style={{ margin: '12px 0 6px' }}>سرفصل‌ها ({fmtNumber(detail.data.topics.length)})</h4>
              <div className="table-wrap">
                <table className="tbl">
                  <thead><tr><th style={{ width: 40 }}>#</th><th>ریز محتوا</th><th>ساعت نظری</th><th>ساعت عملی</th></tr></thead>
                  <tbody>
                    {detail.data.topics.map((t) => (
                      <tr key={t.seq}>
                        <td className="num">{fmtNumber(t.seq)}</td>
                        <td>{t.title}</td>
                        <td className="num">{t.hours ? fmtNumber(t.hours) : '—'}</td>
                        <td className="num">{t.hours_practice ? fmtNumber(t.hours_practice) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {detail.data.evaluation && <p style={{ marginTop: 10 }}><b>روش ارزشیابی:</b> {detail.data.evaluation}</p>}
              {detail.data.references && <p className="small"><b>منابع:</b> <span dir="auto">{detail.data.references}</span></p>}
            </>
          )}
        </Modal>
      )}

      {editOpen && (
        <Modal title="ویرایش سرفصل مصوب" wide onClose={() => setEditOpen(false)}>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 220px' }}>
              <label>عنوان فارسی</label>
              <input value={editForm.title_fa} onChange={(e) => setEditForm({ ...editForm, title_fa: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 220px' }}>
              <label>عنوان انگلیسی (کلید تطبیق)</label>
              <input dir="ltr" value={editForm.title_en} onChange={(e) => setEditForm({ ...editForm, title_en: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 130px' }}>
              <label>کد درس</label>
              <input dir="ltr" value={editForm.course_code} onChange={(e) => setEditForm({ ...editForm, course_code: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 130px' }}>
              <label>نوع درس</label>
              <input value={editForm.course_type} onChange={(e) => setEditForm({ ...editForm, course_type: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 110px' }}>
              <label>واحد نظری</label>
              <input type="number" min={0} value={editForm.unit_theory} onChange={(e) => setEditForm({ ...editForm, unit_theory: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 110px' }}>
              <label>واحد عملی</label>
              <input type="number" min={0} value={editForm.unit_practice} onChange={(e) => setEditForm({ ...editForm, unit_practice: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 110px' }}>
              <label>ساعت نظری</label>
              <input type="number" min={0} value={editForm.hour_theory} onChange={(e) => setEditForm({ ...editForm, hour_theory: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 110px' }}>
              <label>ساعت عملی</label>
              <input type="number" min={0} value={editForm.hour_practice} onChange={(e) => setEditForm({ ...editForm, hour_practice: e.target.value })} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 10 }}>
            <div style={{ flex: '1 1 300px' }}>
              <label>پیش‌نیازها</label>
              <textarea rows={2} value={editForm.prerequisites} onChange={(e) => setEditForm({ ...editForm, prerequisites: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 300px' }}>
              <label>هم‌نیازها</label>
              <textarea rows={2} value={editForm.corequisites} onChange={(e) => setEditForm({ ...editForm, corequisites: e.target.value })} />
            </div>
          </div>
          <div style={{ marginTop: 10 }}>
            <label>هدف کلی درس</label>
            <textarea rows={4} value={editForm.general_goal} onChange={(e) => setEditForm({ ...editForm, general_goal: e.target.value })} />
          </div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 10 }}>
            <div style={{ flex: '1 1 300px' }}>
              <label>روش ارزشیابی</label>
              <textarea rows={2} value={editForm.evaluation} onChange={(e) => setEditForm({ ...editForm, evaluation: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 300px' }}>
              <label>منابع</label>
              <textarea rows={2} dir="auto" value={editForm.references} onChange={(e) => setEditForm({ ...editForm, references: e.target.value })} />
            </div>
          </div>

          <h4 style={{ margin: '14px 0 6px' }}>ریز محتوا / سرفصل‌ها ({fmtNumber(editTopics.length)})</h4>
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr>
                <th style={{ width: 44 }}>#</th><th>عنوان ریز محتوا</th>
                <th style={{ width: 110 }}>ساعت نظری</th><th style={{ width: 110 }}>ساعت عملی</th>
                <th style={{ width: 118 }}></th>
              </tr></thead>
              <tbody>
                {editTopics.map((t, i) => (
                  <tr key={i}>
                    <td className="num">{fmtNumber(i + 1)}</td>
                    <td><input value={t.title}
                               onChange={(e) => setEditTopics(editTopics.map((x, k) => k === i ? { ...x, title: e.target.value } : x))} /></td>
                    <td><input type="number" min={0} value={t.hours}
                               onChange={(e) => setEditTopics(editTopics.map((x, k) => k === i ? { ...x, hours: e.target.value } : x))} /></td>
                    <td><input type="number" min={0} value={t.hours_practice}
                               onChange={(e) => setEditTopics(editTopics.map((x, k) => k === i ? { ...x, hours_practice: e.target.value } : x))} /></td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <button className="btn sm" title="انتقال به بالا" onClick={() => moveTopic(i, -1)}>▲</button>{' '}
                      <button className="btn sm" title="انتقال به پایین" onClick={() => moveTopic(i, 1)}>▼</button>{' '}
                      <button className="btn danger sm" title="حذف ردیف" onClick={() => setEditTopics(editTopics.filter((_, k) => k !== i))}>✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button className="btn sm" style={{ marginTop: 8 }}
                  onClick={() => setEditTopics([...editTopics, { title: '', hours: '', hours_practice: '' }])}>
            افزودن سرفصل
          </button>

          <div className="modal-foot">
            <button className="btn primary" disabled={editSyllabus.isPending} onClick={saveEdit}>
              {editSyllabus.isPending ? 'در حال ذخیره…' : 'ذخیره تغییرات'}
            </button>
            <button className="btn" onClick={() => setEditOpen(false)}>انصراف</button>
          </div>
          <p className="muted small">
            ذخیره در سابقه ممیزی ثبت می‌شود و <code dir="ltr">updated_at</code> به‌روز می‌شود؛
            سامانه‌های مصرف‌کننده با همگام‌سازی دلتایی (<code dir="ltr">since</code>) تغییر را می‌گیرند.
          </p>
        </Modal>
      )}

      {importOpen && (
        <Modal title="درج دستی سرفصل‌ها (JSON)" wide onClose={() => setImportOpen(false)}>
          <p className="muted small">
            ساختار هر ردیف: <code dir="ltr">source_set</code>، <code dir="ltr">source_file</code>،
            <code dir="ltr"> title_fa/title_en</code>، <code dir="ltr">course_code</code>، <code dir="ltr">course_type</code>،
            <code dir="ltr"> unit_theory/unit_practice</code>، <code dir="ltr">hour_theory/hour_practice</code>،
            <code dir="ltr"> prerequisites</code>، <code dir="ltr">general_goal</code>، <code dir="ltr">evaluation</code>،
            <code dir="ltr"> references</code> و آرایه <code dir="ltr">topics</code> (هر آیتم: seq/title/hours/hours_practice).
            یکتایی بر (مجموعه + فایل منبع) است؛ ایمپورت مجدد بروزرسانی می‌کند.
          </p>
          <textarea
            dir="ltr" rows={10} style={{ width: '100%', fontFamily: 'monospace' }}
            placeholder={'[{"source_set": "CE403", "source_file": "x.pdf", "title_en": "…", "title_fa": "…", "topics": [{"seq": 1, "title": "…"}]}]'}
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
