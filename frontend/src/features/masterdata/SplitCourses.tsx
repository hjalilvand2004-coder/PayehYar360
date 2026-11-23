import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import { Empty, ErrorBox, Loading, Modal, PageHead, ConfirmInline } from '../../components/ui'
import { fmtNumber } from '../../shared/format'
import { useAuth } from '../../auth/AuthContext'

interface SplitRow {
  id: string
  unique_course_id: string
  code: string | null
  title: string
  year_label: string | null
  cohort_set: string | null
  unit_theory: number | null
  unit_practice: number | null
  capacity: number | null
  status: string
  source: string
  syllabi_count: number
  unique_course: { id: string; code: string; title_fa: string; section: string | null } | null
}

interface ListOut { total: number; items: SplitRow[] }

interface UcListOut { total: number; items: Array<{ id: string; code: string; title_fa: string; section: string | null; status: string }> }

const YEARS = ['1394', '1403']
const COHORTS = ['پیوسته', 'ناپیوسته']

/** صفحه درس‌های تفکیکی — حلقه واسط زنجیره: هر تفکیکی به یک درس یکتا (سال/مجموعه) و سرفصل‌هایش متصل است. */
export default function SplitCourses() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { me } = useAuth()
  const canEdit = (me?.roles || []).some((r) => ['master_data_editor', 'steward', 'tenant_admin'].includes(r))
  const canDelete = (me?.roles || []).some((r) => ['steward', 'tenant_admin'].includes(r))
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [year, setYear] = useState('')
  const [cohort, setCohort] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState({ unique_course_id: '', title: '', year_label: '', cohort_set: '', unit_theory: '', unit_practice: '', capacity: '', status: 'active' })
  const [deleteId, setDeleteId] = useState<string | null>(null)

  const items = useQuery({
    queryKey: ['split-courses', search, year, cohort],
    queryFn: () => api<ListOut>(
      `/api/v1/masterdata/split-courses?search=${encodeURIComponent(search)}&year=${encodeURIComponent(year)}&cohort=${encodeURIComponent(cohort)}`),
  })

  // فهرست درس‌های یکتا برای انتخاب در فرم (همه — تا سقف ۱۰۰۰)
  const ucs = useQuery({
    queryKey: ['unique-courses', 'all'],
    queryFn: () => api<UcListOut>('/api/v1/masterdata/unique-courses?limit=1000'),
    enabled: formOpen,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['split-courses'] })
    qc.invalidateQueries({ queryKey: ['unique-courses'] })
    qc.invalidateQueries({ queryKey: ['unique-course'] })
    qc.invalidateQueries({ queryKey: ['md-catalog'] })
    qc.invalidateQueries({ queryKey: ['quality'] })
  }

  const save = useMutation({
    mutationFn: () => api<SplitRow>(editId ? `/api/v1/masterdata/split-courses/${editId}` : '/api/v1/masterdata/split-courses', {
      method: editId ? 'PATCH' : 'POST',
      body: {
        unique_course_id: form.unique_course_id,
        title: form.title.trim() || null,
        year_label: form.year_label || null, cohort_set: form.cohort_set || null,
        unit_theory: form.unit_theory.trim() ? Number(form.unit_theory) : null,
        unit_practice: form.unit_practice.trim() ? Number(form.unit_practice) : null,
        capacity: form.capacity.trim() ? Number(form.capacity) : null, status: form.status,
      },
    }),
    onSuccess: () => {
      setFormOpen(false); setEditId(null)
      setNotice(editId ? 'درس تفکیکی ویرایش شد.' : 'درس تفکیکی ثبت شد — سرفصل‌های مصوبش را از ستون «سرفصل‌ها» متصل کنید.')
      setError(''); invalidate()
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api<{ unlinked_syllabi: number }>(`/api/v1/masterdata/split-courses/${id}`, { method: 'DELETE' }),
    onSuccess: (d) => {
      setDeleteId(null)
      setNotice(`درس تفکیکی حذف شد${d.unlinked_syllabi ? ` — ${d.unlinked_syllabi} سرفصل از پیوند خارج شد (حذف نشد)` : ''}.`)
      setError(''); invalidate()
    },
    onError: (e) => setError((e as ApiError).message),
  })

  const openCreate = () => {
    setEditId(null)
    setForm({ unique_course_id: '', title: '', year_label: '', cohort_set: '', unit_theory: '', unit_practice: '', capacity: '', status: 'active' })
    setFormOpen(true)
  }
  const openEdit = (r: SplitRow) => {
    setEditId(r.id)
    setForm({
      unique_course_id: r.unique_course_id, title: r.title,
      year_label: r.year_label || '', cohort_set: r.cohort_set || '',
      unit_theory: r.unit_theory === null ? '' : String(r.unit_theory),
      unit_practice: r.unit_practice === null ? '' : String(r.unit_practice),
      capacity: r.capacity === null ? '' : String(r.capacity), status: r.status,
    })
    setFormOpen(true)
  }

  return (
    <>
      <PageHead
        title="درس‌های تفکیکی"
        subtitle="نمونه‌های اجرایی هر درس یکتا — تفکیک با سال یا مجموعه (پیوسته/ناپیوسته)؛ هر تفکیکی سرفصل‌های مصوب خودش را دارد"
        actions={canEdit && <button className="btn primary sm" onClick={openCreate}>درس تفکیکی جدید</button>}
      />
      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert info">{notice}</div>}

      <div className="card">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
          <input placeholder="جست‌وجو در عنوان درس تفکیکی یا درس یکتا…" value={search}
                 onChange={(e) => setSearch(e.target.value)} style={{ flex: 1, minWidth: 220 }} />
          <button className={`btn sm${year === '' ? ' primary' : ''}`} onClick={() => setYear('')}>همه سال‌ها</button>
          {YEARS.map((y) => (
            <button key={y} className={`btn sm${year === y ? ' primary' : ''}`} onClick={() => setYear(y)}>{fmtNumber(Number(y))}</button>
          ))}
          <button className={`btn sm${cohort === '' ? ' primary' : ''}`} onClick={() => setCohort('')}>همه مجموعه‌ها</button>
          {COHORTS.map((c) => (
            <button key={c} className={`btn sm${cohort === c ? ' primary' : ''}`} onClick={() => setCohort(c)}>{c}</button>
          ))}
        </div>
        <div className="muted small" style={{ marginBottom: 8 }}>
          {fmtNumber(items.data?.total || 0)} درس تفکیکی
        </div>
        {items.isLoading ? <Loading /> : items.error ? <ErrorBox error={items.error} /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr>
                <th>درس یکتا</th><th>عنوان در منبع</th><th>سال</th><th>مجموعه</th>
                <th>واحد نظری/عملی</th><th>ظرفیت</th><th>سرفصل‌ها</th><th>منبع</th><th></th>
              </tr></thead>
              <tbody>
                {(items.data?.items || []).map((r) => (
                  <tr key={r.id}>
                    <td>
                      <b>{r.unique_course?.title_fa || '—'}</b>
                      {r.unique_course && <span className="small muted"> <span className="num">{r.unique_course.code}</span></span>}
                    </td>
                    <td>{r.title}{r.title !== r.unique_course?.title_fa && r.unique_course ? <span className="small muted"> (متفاوت با درس یکتا)</span> : null}</td>
                    <td className="num">{r.year_label ? fmtNumber(Number(r.year_label)) : '—'}</td>
                    <td className="small">{r.cohort_set || '—'}</td>
                    <td className="small">{r.unit_theory ?? '—'} / {r.unit_practice ?? '—'}</td>
                    <td className="num">{r.capacity !== null ? fmtNumber(r.capacity) : '—'}</td>
                    <td className="num">
                      {r.syllabi_count > 0 ? (
                        <button className="btn sm" onClick={() => navigate(`/syllabi?split=${r.id}`)}>
                          {fmtNumber(r.syllabi_count)} سرفصل
                        </button>
                      ) : <span className="chip warn">بدون سرفصل</span>}
                    </td>
                    <td className="small">{r.source === 'darsyar360' ? 'درس‌یار۳۶۰' : 'دستی'}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {canEdit && <button className="btn sm" onClick={() => openEdit(r)}>ویرایش</button>}
                      {' '}
                      {canDelete && <button className="btn danger sm" onClick={() => setDeleteId(r.id)}>حذف</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(items.data?.items || []).length === 0 && <Empty text="درس تفکیکی‌ای یافت نشد — از ایمپورت درس‌یار۳۶۰ یا فرم ثبت دستی شروع کنید" />}
          </div>
        )}
      </div>

      {deleteId && (
        <ConfirmInline
          message="حذف درس تفکیکی سرفصل‌های متصلش را حذف نمی‌کند؛ فقط پیوندشان باز می‌شود و در «کیفیت داده» به‌عنوان سرفصل بی‌پیوند گزارش می‌شوند. ادامه؟"
          busy={remove.isPending}
          onConfirm={() => remove.mutate(deleteId)}
          onCancel={() => setDeleteId(null)}
        />
      )}

      {formOpen && (
        <Modal title={editId ? 'ویرایش درس تفکیکی' : 'درج درس تفکیکی جدید'} wide onClose={() => setFormOpen(false)}>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 320px' }}>
              <label>درس یکتا (رأس زنجیره)</label>
              <select value={form.unique_course_id} onChange={(e) => setForm({ ...form, unique_course_id: e.target.value })}>
                <option value="">— انتخاب کنید —</option>
                {(ucs.data?.items || []).map((u) => (
                  <option key={u.id} value={u.id}>{u.code} — {u.title_fa}{u.section ? ` (${u.section})` : ''}</option>
                ))}
              </select>
            </div>
            <div style={{ flex: '1 1 280px' }}>
              <label>عنوان در منبع (خالی = عنوان درس یکتا)</label>
              <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
                     placeholder="مثلاً «ریاضی گسسته» برای ناپیوسته" />
            </div>
            <div style={{ flex: '1 1 140px' }}>
              <label>سال (عامل تفکیک)</label>
              <select value={form.year_label} onChange={(e) => setForm({ ...form, year_label: e.target.value })}>
                <option value="">— بدون سال (ناپیوسته) —</option>
                {YEARS.map((y) => <option key={y} value={y}>{fmtNumber(Number(y))}</option>)}
              </select>
            </div>
            <div style={{ flex: '1 1 140px' }}>
              <label>مجموعه</label>
              <select value={form.cohort_set} onChange={(e) => setForm({ ...form, cohort_set: e.target.value })}>
                <option value="">— بدون مجموعه —</option>
                {COHORTS.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 10 }}>
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
              <label>ظرفیت</label>
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
          <div className="modal-foot">
            <button className="btn primary" disabled={!form.unique_course_id || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? 'در حال ذخیره…' : 'ذخیره'}
            </button>
            <button className="btn" onClick={() => setFormOpen(false)}>انصراف</button>
          </div>
          <p className="muted small">
            ترکیب (درس یکتا + سال + مجموعه) یکتاست؛ قاعده کسب‌وکار: هر درس یکتا ۱ یا ۳ درس تفکیکی دارد و تعداد خارج از این بازه در «کیفیت داده» گزارش می‌شود.
          </p>
        </Modal>
      )}
    </>
  )
}
