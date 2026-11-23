import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import { Empty, ErrorBox, Loading, Modal, PageHead, ConfirmInline } from '../../components/ui'
import { fmtNumber } from '../../shared/format'
import { useAuth } from '../../auth/AuthContext'

interface UniqueCourseRow {
  id: string
  code: string
  title_fa: string
  title_en: string | null
  section: string | null
  unit_theory: number | null
  unit_practice: number | null
  capacity: number | null
  prerequisite: string | null
  status: string
  source: string
  split_count: number
  syllabi_count: number
  chain_ok: boolean
  updated_at_jalali: string
}

interface SplitRow {
  id: string
  code: string | null
  title: string
  year_label: string | null
  cohort_set: string | null
  unit_theory: number | null
  unit_practice: number | null
  capacity: number | null
  status: string
  syllabi_count: number
  updated_at_jalali: string
}

interface UniqueCourseDetail extends UniqueCourseRow {
  extra: Record<string, unknown>
  split_courses: SplitRow[]
  syllabi_total: number
}

interface ListOut { total: number; items: UniqueCourseRow[] }

const EMPTY_FORM = { code: '', title_fa: '', title_en: '', section: '', unit_theory: '', unit_practice: '', capacity: '', prerequisite: '', status: 'active' }

/** صفحه درس‌های یکتا — رأس زنجیره درس؛ هر درس یکتا ۱ تا ۳ درس تفکیکی دارد و هر تفکیکی سرفصل مصوب خودش را. */
export default function UniqueCourses() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { me } = useAuth()
  const canEdit = (me?.roles || []).some((r) => ['master_data_editor', 'steward', 'tenant_admin'].includes(r))
  const canDelete = (me?.roles || []).some((r) => ['steward', 'tenant_admin'].includes(r))
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [section, setSection] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState({ ...EMPTY_FORM })
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [rawJson, setRawJson] = useState('')

  const items = useQuery({
    queryKey: ['unique-courses', search, section],
    queryFn: () => api<ListOut>(
      `/api/v1/masterdata/unique-courses?search=${encodeURIComponent(search)}&section=${encodeURIComponent(section)}`),
  })

  const detail = useQuery({
    queryKey: ['unique-course', openId],
    queryFn: () => api<UniqueCourseDetail>(`/api/v1/masterdata/unique-courses/${openId}`),
    enabled: !!openId,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['unique-courses'] })
    qc.invalidateQueries({ queryKey: ['unique-course'] })
    qc.invalidateQueries({ queryKey: ['split-courses'] })
    qc.invalidateQueries({ queryKey: ['md-catalog'] })
    qc.invalidateQueries({ queryKey: ['quality'] })
  }

  const save = useMutation({
    mutationFn: () => api<UniqueCourseRow>(editId ? `/api/v1/masterdata/unique-courses/${editId}` : '/api/v1/masterdata/unique-courses', {
      method: editId ? 'PATCH' : 'POST',
      body: {
        code: form.code.trim(), title_fa: form.title_fa.trim(),
        title_en: form.title_en.trim() || null, section: form.section.trim() || null,
        unit_theory: form.unit_theory.trim() ? Number(form.unit_theory) : null,
        unit_practice: form.unit_practice.trim() ? Number(form.unit_practice) : null,
        capacity: form.capacity.trim() ? Number(form.capacity) : null,
        prerequisite: form.prerequisite.trim() || null, status: form.status,
      },
    }),
    onSuccess: () => {
      setFormOpen(false); setEditId(null)
      setNotice(editId ? 'درس یکتا ویرایش شد.' : 'درس یکتا ثبت شد — حالا درس‌های تفکیکی آن را با سال/مجموعه اضافه کنید.')
      setError(''); invalidate()
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api<{ deleted: boolean }>(`/api/v1/masterdata/unique-courses/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      setDeleteId(null); setOpenId(null)
      setNotice('درس یکتا حذف شد.'); setError(''); invalidate()
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const importRows = useMutation({
    mutationFn: (rows: unknown[]) =>
      api<{ created_unique: number; created_split: number; updated_unique: number; updated_split: number; skipped: number; linked_syllabi: number }>(
        '/api/v1/masterdata/import/darsyar-courses', { method: 'POST', body: { rows } }),
    onSuccess: (d) => {
      setImportOpen(false); setRawJson('')
      setNotice(`ایمپورت درس‌یار۳۶۰ انجام شد: ${d.created_unique} درس یکتا و ${d.created_split} درس تفکیکی جدید` +
        (d.updated_unique || d.updated_split ? `؛ ${d.updated_unique + d.updated_split} رکورد بروزرسانی شد` : '') +
        (d.skipped ? `؛ ${d.skipped} ردیف نادیده` : '') +
        (d.linked_syllabi ? `؛ ${d.linked_syllabi} سرفصل متصل شد` : '') + '.')
      setError(''); invalidate()
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const openCreate = () => { setEditId(null); setForm({ ...EMPTY_FORM }); setFormOpen(true) }
  const openEdit = (r: UniqueCourseRow) => {
    setEditId(r.id)
    setForm({
      code: r.code, title_fa: r.title_fa, title_en: r.title_en || '', section: r.section || '',
      unit_theory: r.unit_theory === null ? '' : String(r.unit_theory),
      unit_practice: r.unit_practice === null ? '' : String(r.unit_practice),
      capacity: r.capacity === null ? '' : String(r.capacity),
      prerequisite: r.prerequisite || '', status: r.status,
    })
    setOpenId(null); setFormOpen(true)
  }

  const sectionChips = ['پایه', 'اصلی', 'تخصصی', 'اختیاری', 'نرم‌افزار', 'هوش']

  return (
    <>
      <PageHead
        title="درس‌های یکتا"
        subtitle="رأس زنجیره درس — کد یکتا از درس‌یار۳۶۰؛ هر درس یکتا ۱ تا ۳ درس تفکیکی دارد (سال/مجموعه) و هر تفکیکی سرفصل‌های مصوب خودش را"
        actions={
          <>
            <button className="btn sm" onClick={() => setImportOpen(true)}>ایمپورت از درس‌یار۳۶۰</button>
            {canEdit && <button className="btn primary sm" onClick={openCreate}>درس یکتای جدید</button>}
          </>
        }
      />
      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert info">{notice}</div>}

      {items.isLoading ? <Loading /> : items.error ? <ErrorBox error={items.error} /> : (
        <div className="card">
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
            <input placeholder="جست‌وجو در کد یا عنوان درس…" value={search}
                   onChange={(e) => setSearch(e.target.value)} style={{ flex: 1, minWidth: 220 }} />
            <button className={`btn sm${section === '' ? ' primary' : ''}`} onClick={() => setSection('')}>همه بخش‌ها</button>
            {sectionChips.map((s) => (
              <button key={s} className={`btn sm${section === s ? ' primary' : ''}`} onClick={() => setSection(s)}>{s}</button>
            ))}
          </div>
          <div className="muted small" style={{ marginBottom: 8 }}>
            {fmtNumber(items.data?.total || 0)} درس یکتا — قاعده زنجیره: تعداد تفکیکی هر درس باید ۱ یا ۳ باشد.
          </div>
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr>
                <th>کد یکتا</th><th>عنوان درس</th><th>بخش</th><th>واحد</th>
                <th>تفکیکی‌ها</th><th>سرفصل‌ها</th><th>زنجیره</th><th>بروزرسانی</th>
              </tr></thead>
              <tbody>
                {(items.data?.items || []).map((r) => (
                  <tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => setOpenId(r.id)}>
                    <td className="num"><b>{r.code}</b></td>
                    <td><b>{r.title_fa}</b>{r.title_en && <span className="small muted" dir="ltr"> — {r.title_en}</span>}</td>
                    <td className="small">{r.section || '—'}</td>
                    <td className="small">
                      {[r.unit_theory !== null ? `نظری ${fmtNumber(r.unit_theory)}` : '',
                        r.unit_practice ? `عملی ${fmtNumber(r.unit_practice)}` : ''].filter(Boolean).join(' + ') || '—'}
                    </td>
                    <td className="num">{fmtNumber(r.split_count)}</td>
                    <td className="num">{fmtNumber(r.syllabi_count)}</td>
                    <td>{r.chain_ok ? <span className="chip ok">سالم</span> : <span className="chip warn">{r.split_count === 0 ? 'بدون تفکیکی' : 'خارج از قاعده'}</span>}</td>
                    <td className="small">{r.updated_at_jalali}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(items.data?.items || []).length === 0 && <Empty text="درس یکتایی ثبت نشده — با «ایمپورت از درس‌یار۳۶۰» یا فرم ثبت دستی شروع کنید" />}
          </div>
        </div>
      )}

      {openId && (
        <Modal title={detail.data ? `درس یکتا: ${detail.data.title_fa} (${detail.data.code})` : 'جزئیات درس یکتا'} wide
               onClose={() => setOpenId(null)}>
          {detail.isLoading ? <Loading /> : detail.error ? <ErrorBox error={detail.error} /> : detail.data && (
            <>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                <span className="chip num">کد {detail.data.code}</span>
                {detail.data.section && <span className="chip">{detail.data.section}</span>}
                <span className="chip">واحد: {[detail.data.unit_theory !== null ? `نظری ${fmtNumber(detail.data.unit_theory)}` : '',
                  detail.data.unit_practice ? `عملی ${fmtNumber(detail.data.unit_practice)}` : ''].filter(Boolean).join(' + ') || '—'}</span>
                {detail.data.capacity !== null && <span className="chip">ظرفیت: {fmtNumber(detail.data.capacity)}</span>}
                <span className="chip">{detail.data.chain_ok ? 'زنجیره سالم' : 'خارج از قاعده ۱/۳'}</span>
                <span className="chip small">{detail.data.source === 'darsyar360' ? 'منبع: درس‌یار۳۶۰' : 'درج دستی'}</span>
                {canEdit && (
                  <button className="btn primary sm" style={{ marginInlineStart: 'auto' }}
                          onClick={() => openEdit(detail.data)}>ویرایش</button>
                )}
                {canDelete && (
                  <button className="btn danger sm" onClick={() => setDeleteId(detail.data.id)}>حذف</button>
                )}
              </div>
              {detail.data.prerequisite && <p className="small"><b>پیش‌نیاز (از منبع):</b> {detail.data.prerequisite}</p>}
              <h4 style={{ margin: '12px 0 6px' }}>
                درس‌های تفکیکی ({fmtNumber(detail.data.split_courses.length)}) — مجموع سرفصل‌ها: {fmtNumber(detail.data.syllabi_total)}
              </h4>
              {detail.data.split_courses.length === 0 ? (
                <Empty text="هنوز درس تفکیکی ندارد — در صفحه «درس‌های تفکیکی» با سال/مجموعه اضافه کنید" />
              ) : (
                <div className="table-wrap">
                  <table className="tbl">
                    <thead><tr>
                      <th>عنوان در منبع</th><th>سال</th><th>مجموعه</th><th>واحد نظری/عملی</th>
                      <th>ظرفیت</th><th>سرفصل‌ها</th><th></th>
                    </tr></thead>
                    <tbody>
                      {detail.data.split_courses.map((s) => (
                        <tr key={s.id}>
                          <td>{s.title}{s.code && <span className="small muted" dir="ltr"> ({s.code})</span>}</td>
                          <td className="num">{s.year_label ? fmtNumber(Number(s.year_label)) : '—'}</td>
                          <td className="small">{s.cohort_set || '—'}</td>
                          <td className="small">{s.unit_theory ?? '—'} / {s.unit_practice ?? '—'}</td>
                          <td className="num">{s.capacity !== null ? fmtNumber(s.capacity) : '—'}</td>
                          <td className="num">{fmtNumber(s.syllabi_count)}</td>
                          <td>
                            <button className="btn sm" onClick={() => navigate(`/syllabi?split=${s.id}`)}>سرفصل‌ها</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </Modal>
      )}

      {deleteId && (
        <ConfirmInline
          message="حذف درس یکتا فقط وقتی ممکن است که هیچ درس تفکیکی نداشته باشد؛ ترتیب زنجیره درس محفوظ می‌ماند. ادامه؟"
          busy={remove.isPending}
          onConfirm={() => remove.mutate(deleteId)}
          onCancel={() => setDeleteId(null)}
        />
      )}

      {formOpen && (
        <Modal title={editId ? 'ویرایش درس یکتا' : 'درج درس یکتای جدید'} wide onClose={() => setFormOpen(false)}>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 150px' }}>
              <label>کد یکتا (بدون پیشوند، مثل 1044)</label>
              <input dir="ltr" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 300px' }}>
              <label>عنوان فارسی درس</label>
              <input value={form.title_fa} onChange={(e) => setForm({ ...form, title_fa: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 250px' }}>
              <label>عنوان انگلیسی (اختیاری)</label>
              <input dir="ltr" value={form.title_en} onChange={(e) => setForm({ ...form, title_en: e.target.value })} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 10 }}>
            <div style={{ flex: '1 1 160px' }}>
              <label>بخش</label>
              <input value={form.section} onChange={(e) => setForm({ ...form, section: e.target.value })}
                     placeholder="پایه / اصلی / تخصصی / اختیاری…" />
            </div>
            <div style={{ flex: '1 1 110px' }}>
              <label>واحد نظری</label>
              <input type="number" min={0} value={form.unit_theory}
                     onChange={(e) => setForm({ ...form, unit_theory: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 110px' }}>
              <label>واحد عملی</label>
              <input type="number" min={0} value={form.unit_practice}
                     onChange={(e) => setForm({ ...form, unit_practice: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 110px' }}>
              <label>ظرفیت برآوردی</label>
              <input type="number" min={0} value={form.capacity}
                     onChange={(e) => setForm({ ...form, capacity: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 110px' }}>
              <label>وضعیت</label>
              <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                <option value="active">فعال</option>
                <option value="inactive">غیرفعال</option>
              </select>
            </div>
          </div>
          <div style={{ marginTop: 10 }}>
            <label>پیش‌نیاز (خام از منبع)</label>
            <input value={form.prerequisite} onChange={(e) => setForm({ ...form, prerequisite: e.target.value })} />
          </div>
          <div className="modal-foot">
            <button className="btn primary" disabled={!form.code.trim() || !form.title_fa.trim() || save.isPending}
                    onClick={() => save.mutate()}>
              {save.isPending ? 'در حال ذخیره…' : 'ذخیره'}
            </button>
            <button className="btn" onClick={() => setFormOpen(false)}>انصراف</button>
          </div>
          <p className="muted small">
            کد یکتا کلید اتصال سایر سامانه‌هاست — پس از ثبت، درس تفکیکی‌ها (سال/مجموعه) را اضافه کنید تا زنجیره کامل شود.
          </p>
        </Modal>
      )}

      {importOpen && (
        <Modal title="ایمپورت درس‌های تفکیکی از درس‌یار۳۶۰" wide onClose={() => setImportOpen(false)}>
          <p className="muted small">
            ردیف‌های جدول <code dir="ltr">darsyar360.ir/admin/courses</code> را (خروجی JSON هر ردیف) وارد کنید.
            هر ردیف یک «درس تفکیکی» است: کلیدها <code dir="ltr">unique_code</code>، <code dir="ltr">title</code>،
            <code dir="ltr"> section</code>، <code dir="ltr">year</code>، <code dir="ltr">type</code>،
            <code dir="ltr"> unit_theory/unit_practice</code>، <code dir="ltr">prereq</code>، <code dir="ltr">capacity</code>.
            ایمپورت idempotent است — رکورد تکراری بروزرسانی می‌شود و سرفصل‌های هم‌عنوان خودکار متصل می‌شوند.
          </p>
          <textarea
            dir="ltr" rows={10} style={{ width: '100%', fontFamily: 'monospace' }}
            placeholder={'[{"unique_code": "1044", "title": "ریاضی عمومی 1", "section": "پایه", "year": "1403", "type": "پیوسته", "unit_theory": "3", "capacity": "30"}]'}
            value={rawJson} onChange={(e) => setRawJson(e.target.value)}
          />
          <div className="modal-foot">
            <button className="btn primary" disabled={importRows.isPending}
                    onClick={() => { try { importRows.mutate(JSON.parse(rawJson)) } catch { setError('JSON نامعتبر است.') } }}>
              {importRows.isPending ? 'در حال ایمپورت…' : 'ایمپورت'}
            </button>
            <button className="btn" onClick={() => setImportOpen(false)}>انصراف</button>
          </div>
        </Modal>
      )}
    </>
  )
}
