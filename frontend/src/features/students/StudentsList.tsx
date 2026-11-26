import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { api, ApiError } from '../../api/client'
import type { Student, StudentDetail, StudentStats, SyncReport } from '../../api/types'
import { Empty, ErrorBox, Loading, Modal, PageHead, StatusBadge } from '../../components/ui'
import { fmtDateTime } from '../../shared/format'
import { useAuth } from '../../auth/AuthContext'

/** مقاطع تحصیلی — کد کانونی بک‌اند با برچسب فارسی (مشترک ثبت دستی و نمایش) */
const DEGREES: Array<{ code: string; label: string }> = [
  { code: 'kardani', label: 'کاردانی' },
  { code: 'karshenasi', label: 'کارشناسی' },
  { code: 'karshenasi_arshad', label: 'کارشناسی ارشد' },
  { code: 'doktori_herfei', label: 'دکتری حرفه‌ای' },
  { code: 'doktori_takhassosi', label: 'دکتری تخصصی' },
  { code: 'post_doktori', label: 'پسادکتری' },
]
const degreeLabel = (code: string) => DEGREES.find((d) => d.code === code)?.label || code

const STATUSES: Array<{ code: string; label: string }> = [
  { code: 'active', label: 'فعال' },
  { code: 'graduated', label: 'فارغ‌التحصیل' },
  { code: 'withdrawn', label: 'انصراف‌داده' },
  { code: 'suspended', label: 'تعلیق‌شده' },
  { code: 'inactive', label: 'غیرفعال' },
]

const EDITABLE_ROLES = ['master_data_editor', 'steward', 'tenant_admin']
const SYNC_ROLES = ['steward', 'integration_admin', 'tenant_admin']

const studentSchema = z.object({
  student_number: z.string().min(1, 'شماره دانشجویی لازم است').max(40),
  national_id: z.string().regex(/^\d{10}$/, 'کد ملی باید 10 رقم باشد').or(z.literal('')),
  first_name: z.string().min(1, 'نام لازم است').max(120),
  last_name: z.string().min(1, 'نام خانوادگی لازم است').max(120),
  father_name: z.string().max(120).optional().or(z.literal('')),
  gender: z.string().optional().or(z.literal('')),
  mobile: z.string().regex(/^09\d{9}$/, 'شماره همراه باید 09xxxxxxxxx باشد'),
  phone: z.string().max(20).optional().or(z.literal('')),
  email: z.string().max(120).optional().or(z.literal('')),
  city: z.string().min(1, 'شهر محل سکونت لازم است').max(80),
  province: z.string().max(80).optional().or(z.literal('')),
  address: z.string().max(500).optional().or(z.literal('')),
  university_code: z.string().max(40).optional().or(z.literal('')),
  university_name: z.string().min(1, 'دانشگاه لازم است').max(160),
  major_code: z.string().max(40).optional().or(z.literal('')),
  major_name: z.string().min(1, 'رشته تحصیلی لازم است').max(160),
  degree_level: z.enum(['kardani', 'karshenasi', 'karshenasi_arshad', 'doktori_herfei', 'doktori_takhassosi', 'post_doktori']),
  entrance_year: z.coerce.number().int().min(1350).max(1500).optional().or(z.literal('').transform(() => undefined)),
  notes: z.string().max(500).optional().or(z.literal('')),
})
type StudentForm = z.infer<typeof studentSchema>

const EMPTY_FORM: StudentForm = {
  student_number: '', national_id: '', first_name: '', last_name: '', father_name: '', gender: '',
  mobile: '', phone: '', email: '', city: '', province: '', address: '',
  university_code: '', university_name: '', major_code: '', major_name: '',
  degree_level: 'karshenasi', entrance_year: undefined, notes: '',
}

export default function StudentsList() {
  const { me } = useAuth()
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [degree, setDegree] = useState('')
  const [university, setUniversity] = useState('')
  const [city, setCity] = useState('')
  const [status, setStatus] = useState('')
  const [source, setSource] = useState('')
  const [page, setPage] = useState(0)
  const [showCreate, setShowCreate] = useState(false)
  const [editing, setEditing] = useState<Student | null>(null)
  const [detail, setDetail] = useState<StudentDetail | null>(null)
  const [syncReport, setSyncReport] = useState<SyncReport | null>(null)
  const [formError, setFormError] = useState('')

  const canEdit = (me?.roles || []).some((r) => EDITABLE_ROLES.includes(r))
  const canSync = (me?.roles || []).some((r) => SYNC_ROLES.includes(r))
  const limit = 25

  const qs = (extra: Record<string, string> = {}) => {
    const p = new URLSearchParams({ q, degree_level: degree, university_code: university, city, status, source, ...extra })
    for (const [k, v] of [...p.entries()]) if (!v) p.delete(k)
    return p.toString()
  }

  const students = useQuery({
    queryKey: ['students', q, degree, university, city, status, source, page],
    queryFn: () =>
      api<{ items: Student[]; total: number }>(`/api/v1/students?${qs({ limit: String(limit), offset: String(page * limit) })}`),
  })

  const stats = useQuery({
    queryKey: ['students-stats'],
    queryFn: () => api<StudentStats>('/api/v1/students/stats'),
    refetchInterval: 30_000,
  })

  const create = useMutation({
    mutationFn: (body: StudentForm) => api<Student>('/api/v1/students', { method: 'POST', body }),
    onSuccess: () => {
      setShowCreate(false)
      setFormError('')
      qc.invalidateQueries({ queryKey: ['students'] })
      qc.invalidateQueries({ queryKey: ['students-stats'] })
    },
    onError: (e) => setFormError((e as ApiError).message),
  })

  const patch = useMutation({
    mutationFn: ({ id, version, body }: { id: string; version: number; body: Partial<StudentForm> }) =>
      api<Student>(`/api/v1/students/${id}`, { method: 'PATCH', body, extraHeaders: { 'If-Match': `"${version}"` } }),
    onSuccess: () => {
      setEditing(null)
      setFormError('')
      qc.invalidateQueries({ queryKey: ['students'] })
      qc.invalidateQueries({ queryKey: ['students-stats'] })
    },
    onError: (e) => {
      const err = e as ApiError
      setFormError(
        err.code === 'VERSION_CONFLICT'
          ? 'تعارض نسخه: این دانشجو در فاصله باز و ارسال شما اصلاح شده است؛ فهرست را بارگیری کنید.'
          : err.message,
      )
    },
  })

  const sync = useMutation({
    mutationFn: () => api<SyncReport>('/api/v1/students/sync', { method: 'POST' }),
    onSuccess: (rep) => {
      setSyncReport(rep)
      qc.invalidateQueries({ queryKey: ['students'] })
      qc.invalidateQueries({ queryKey: ['students-stats'] })
    },
  })

  const createForm = useForm<StudentForm>({ resolver: zodResolver(studentSchema), defaultValues: EMPTY_FORM })
  const editForm = useForm<StudentForm>({ resolver: zodResolver(studentSchema) })

  const openEdit = (s: Student) => {
    setFormError('')
    setEditing(s)
    editForm.reset({
      ...EMPTY_FORM,
      student_number: s.student_number, national_id: s.national_id,
      first_name: s.first_name, last_name: s.last_name, mobile: s.mobile, city: s.city,
      university_code: '', university_name: s.university_name,
      major_code: '', major_name: s.major_name,
      degree_level: (DEGREES.some((d) => d.code === s.degree_level) ? s.degree_level : 'karshenasi') as StudentForm['degree_level'],
    })
  }

  const openDetail = async (s: Student) => {
    try {
      setDetail(await api<StudentDetail>(`/api/v1/students/${s.id}`))
    } catch (e) {
      setFormError((e as ApiError).message)
    }
  }

  const formFields = (f: ReturnType<typeof useForm<StudentForm>>) => {
    const reg = f.register as (name: keyof StudentForm) => Record<string, unknown>
    const err = f.formState.errors as Record<string, { message?: string }>
    return (
      <>
        <div className="grid cols-2">
          <div>
            <label>شماره دانشجویی *</label>
            <input {...reg('student_number')} />
            {err.student_number && <div className="alert error">{err.student_number.message}</div>}
          </div>
          <div>
            <label>کد ملی</label>
            <input {...reg('national_id')} placeholder="10 رقم" />
            {err.national_id && <div className="alert error">{err.national_id.message}</div>}
          </div>
          <div>
            <label>نام *</label>
            <input {...reg('first_name')} />
            {err.first_name && <div className="alert error">{err.first_name.message}</div>}
          </div>
          <div>
            <label>نام خانوادگی *</label>
            <input {...reg('last_name')} />
            {err.last_name && <div className="alert error">{err.last_name.message}</div>}
          </div>
          <div>
            <label>نام پدر</label>
            <input {...reg('father_name')} />
          </div>
          <div>
            <label>جنسیت</label>
            <select {...reg('gender')}>
              <option value="">—</option>
              <option value="female">خانم</option>
              <option value="male">آقا</option>
            </select>
          </div>
          <div>
            <label>شماره تلفن همراه *</label>
            <input {...reg('mobile')} placeholder="09xxxxxxxxx" />
            {err.mobile && <div className="alert error">{err.mobile.message}</div>}
          </div>
          <div>
            <label>تلفن ثابت</label>
            <input {...reg('phone')} />
          </div>
          <div>
            <label>شهر محل سکونت *</label>
            <input {...reg('city')} />
            {err.city && <div className="alert error">{err.city.message}</div>}
          </div>
          <div>
            <label>استان</label>
            <input {...reg('province')} />
          </div>
          <div>
            <label>دانشگاه *</label>
            <input {...reg('university_name')} />
            {err.university_name && <div className="alert error">{err.university_name.message}</div>}
          </div>
          <div>
            <label>کد دانشگاه</label>
            <input {...reg('university_code')} />
          </div>
          <div>
            <label>رشته تحصیلی *</label>
            <input {...reg('major_name')} />
            {err.major_name && <div className="alert error">{err.major_name.message}</div>}
          </div>
          <div>
            <label>کد رشته</label>
            <input {...reg('major_code')} />
          </div>
          <div>
            <label>مقطع تحصیلی *</label>
            <select {...reg('degree_level')}>
              {DEGREES.map((d) => <option key={d.code} value={d.code}>{d.label}</option>)}
            </select>
            {err.degree_level && <div className="alert error">{err.degree_level.message}</div>}
          </div>
          <div>
            <label>سال ورود</label>
            <input {...reg('entrance_year')} placeholder="1402" />
            {err.entrance_year && <div className="alert error">{err.entrance_year.message}</div>}
          </div>
        </div>
        <label>نشانی</label>
        <input {...reg('address')} />
        <label>یادداشت</label>
        <input {...reg('notes')} />
      </>
    )
  }

  const st = stats.data
  return (
    <>
      <PageHead
        title="دانشجویان"
        subtitle="بخش ویژه ثبت دانشجویان — مقطع، دانشگاه، رشته، همراه و شهر؛ هماهنگ کامل با سامانه دانشگاه هوشمند (فضایار۳۶۰)"
        actions={
          <>
            {canSync && (
              <button className="btn" onClick={() => sync.mutate()} disabled={sync.isPending}>
                {sync.isPending ? 'در حال همگام‌سازی…' : '⟳ همگام‌سازی از دانشگاه هوشمند'}
              </button>
            )}
            {canEdit && (
              <button className="btn primary" onClick={() => { setFormError(''); setShowCreate(true) }}>
                ثبت دانشجو
              </button>
            )}
          </>
        }
      />

      {syncReport && (
        <div className={`alert ${syncReport.created || syncReport.updated ? 'success' : 'warn'}`}>
          <b>گزارش همگام‌سازی ({syncReport.mode === 'pull' ? 'واکشی از دانشگاه هوشمند' : 'دریافت push'}):</b>{' '}
          {syncReport.total_remote} رکورد از مبدأ — {syncReport.created} ایجاد، {syncReport.updated} به‌روزرسانی، {syncReport.skipped.length} نادیده.
          {syncReport.message && <div className="muted small">{syncReport.message}</div>}
          {syncReport.skipped.length > 0 && (
            <div className="muted small">نادیده‌شده‌ها: {syncReport.skipped.map((s) => `${s.ref} (${s.reason})`).join('؛ ')}</div>
          )}
        </div>
      )}
      {formError && !showCreate && !editing && <div className="alert error">{formError}</div>}

      <div className="grid cols-4">
        <div className="stat"><div className="num">{st?.total ?? '—'}</div><div className="lbl">کل دانشجویان</div></div>
        <div className="stat"><div className="num">{st?.by_status?.active ?? 0}</div><div className="lbl">فعال</div></div>
        <div className="stat"><div className="num">{st?.by_status?.graduated ?? 0}</div><div className="lbl">فارغ‌التحصیل</div></div>
        <div className="stat"><div className="num">{st?.by_source?.smart_university ?? 0}</div><div className="lbl">واردشده از دانشگاه هوشمند</div></div>
      </div>

      <div className="card">
        <div className="filters">
          <input placeholder="جست‌وجو (نام/شماره دانشجویی/کد ملی/همراه/رشته/شهر…)" value={q}
                 onChange={(e) => { setQ(e.target.value); setPage(0) }} />
          <select value={degree} onChange={(e) => { setDegree(e.target.value); setPage(0) }}>
            <option value="">همه مقاطع</option>
            {DEGREES.map((d) => <option key={d.code} value={d.code}>{d.label}</option>)}
          </select>
          <input placeholder="کد دانشگاه" value={university}
                 onChange={(e) => { setUniversity(e.target.value); setPage(0) }} />
          <input placeholder="شهر" value={city} onChange={(e) => { setCity(e.target.value); setPage(0) }} />
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(0) }}>
            <option value="">همه وضعیت‌ها</option>
            {STATUSES.map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}
          </select>
          <select value={source} onChange={(e) => { setSource(e.target.value); setPage(0) }}>
            <option value="">همه منشأها</option>
            <option value="manual">ثبت دستی</option>
            <option value="smart_university">دانشگاه هوشمند</option>
          </select>
        </div>
        {students.isLoading ? <Loading /> : students.error ? <ErrorBox error={students.error} /> : (
          students.data?.items.length === 0 ? <Empty /> : (
            <div className="table-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>شماره دانشجویی</th><th>نام و نام خانوادگی</th><th>کد ملی</th><th>همراه</th>
                    <th>شهر</th><th>دانشگاه</th><th>رشته</th><th>مقطع</th><th>وضعیت</th><th>منشأ</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {students.data?.items?.map((s) => (
                    <tr key={s.id} className="clickable" onClick={() => openDetail(s)}>
                      <td className="num">{s.student_number}</td>
                      <td>{s.first_name} {s.last_name}</td>
                      <td className="num">{s.national_id || '—'}</td>
                      <td className="num" style={{ direction: 'ltr' }}>{s.mobile || '—'}</td>
                      <td>{s.city || '—'}</td>
                      <td>{s.university_name}</td>
                      <td>{s.major_name}</td>
                      <td><span className="chip">{degreeLabel(s.degree_level)}</span></td>
                      <td><StatusBadge status={s.status} /></td>
                      <td>{s.source === 'smart_university' ? <span className="chip info">فضایار</span> : <span className="muted small">دستی</span>}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        {canEdit && s.status === 'active' && <button className="btn sm" onClick={() => openEdit(s)}>اصلاح</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
        {students.data && students.data.total > limit && (
          <div className="pager">
            <button className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>قبلی</button>
            <span className="muted small">صفحه {page + 1} از {Math.ceil(students.data.total / limit)}</span>
            <button className="btn sm" disabled={(page + 1) * limit >= students.data.total} onClick={() => setPage(page + 1)}>بعدی</button>
          </div>
        )}
      </div>

      {showCreate && (
        <Modal title="ثبت دانشجو" wide onClose={() => setShowCreate(false)}>
          {formError && <div className="alert error">{formError}</div>}
          <form onSubmit={createForm.handleSubmit((v) => create.mutate(v))}>
            {formFields(createForm)}
            <div className="modal-foot">
              <button className="btn primary" type="submit" disabled={create.isPending}>ثبت</button>
              <button className="btn" type="button" onClick={() => setShowCreate(false)}>انصراف</button>
            </div>
          </form>
        </Modal>
      )}

      {editing && (
        <Modal title={`اصلاح دانشجو — ${editing.student_number} (نسخه ${editing.version})`} wide onClose={() => setEditing(null)}>
          {formError && <div className="alert error">{formError}</div>}
          <form
            onSubmit={editForm.handleSubmit((v) =>
              patch.mutate({ id: editing.id, version: editing.version, body: v }),
            )}
          >
            {formFields(editForm)}
            <div className="modal-foot">
              <button className="btn primary" type="submit" disabled={patch.isPending}>ذخیره (با کنترل نسخه)</button>
              <button className="btn" type="button" onClick={() => setEditing(null)}>انصراف</button>
            </div>
          </form>
        </Modal>
      )}

      {detail && (
        <Modal title={`پرونده دانشجو — ${detail.student_number}`} wide onClose={() => setDetail(null)}>
          <div className="kv">
            <span className="k">نام و نام خانوادگی</span><span>{detail.first_name} {detail.last_name}</span>
            <span className="k">کد ملی</span><span>{detail.national_id || '—'}</span>
            <span className="k">نام پدر</span><span>{detail.father_name || '—'}</span>
            <span className="k">جنسیت</span><span>{detail.gender === 'female' ? 'خانم' : detail.gender === 'male' ? 'آقا' : '—'}</span>
            <span className="k">تاریخ تولد</span><span>{detail.birth_date || '—'}</span>
            <span className="k">تلفن همراه</span><span style={{ direction: 'ltr' }}>{detail.mobile || '—'}</span>
            <span className="k">تلفن ثابت</span><span>{detail.phone || '—'}</span>
            <span className="k">ایمیل</span><span>{detail.email || '—'}</span>
            <span className="k">شهر / استان</span><span>{detail.city || '—'} / {detail.province || '—'}</span>
            <span className="k">نشانی</span><span>{detail.address || '—'}</span>
            <span className="k">دانشگاه</span><span>{detail.university_name} {detail.university_code ? `(${detail.university_code})` : ''}</span>
            <span className="k">رشته تحصیلی</span><span>{detail.major_name} {detail.major_code ? `(${detail.major_code})` : ''}</span>
            <span className="k">مقطع تحصیلی</span><span>{degreeLabel(detail.degree_level)}</span>
            <span className="k">سال ورود</span><span>{detail.entrance_year ?? '—'}</span>
            <span className="k">وضعیت</span><span><StatusBadge status={detail.status} /></span>
            <span className="k">منشأ داده</span><span>{detail.source === 'smart_university' ? 'دانشگاه هوشمند (فضایار۳۶۰)' : 'ثبت دستی'}</span>
            {detail.ext_ref && <><span className="k">شناسه مبدأ</span><span>{detail.ext_ref}</span></>}
            {detail.synced_at && <><span className="k">آخرین همگام‌سازی</span><span>{fmtDateTime(detail.synced_at)}</span></>}
            {detail.notes && <><span className="k">یادداشت</span><span>{detail.notes}</span></>}
          </div>
          <div className="modal-foot">
            <span className="muted small">نسخه {detail.version} — ثبت {fmtDateTime(detail.created_at)}</span>
          </div>
        </Modal>
      )}
    </>
  )
}
