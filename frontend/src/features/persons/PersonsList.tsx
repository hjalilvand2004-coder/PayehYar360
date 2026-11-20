import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { Person } from '../../api/types'
import { Empty, ErrorBox, Loading, Modal, PageHead, StatusBadge } from '../../components/ui'
import { fmtDateTime } from '../../shared/format'
import { useAuth } from '../../auth/AuthContext'

const personSchema = z.object({
  given_name: z.string().min(1, 'نام لازم است').max(120),
  family_name: z.string().min(1, 'نام خانوادگی لازم است').max(120),
  display_name: z.string().max(240).optional().or(z.literal('')),
})
type PersonForm = z.infer<typeof personSchema>

const EDITABLE_ROLES = ['master_data_editor', 'steward', 'tenant_admin']

export default function PersonsList() {
  const { me } = useAuth()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(0)
  const [showCreate, setShowCreate] = useState(false)
  const [editing, setEditing] = useState<Person | null>(null)
  const [formError, setFormError] = useState('')

  const canEdit = (me?.roles || []).some((r) => EDITABLE_ROLES.includes(r))
  const limit = 25

  const persons = useQuery({
    queryKey: ['persons', q, status, page],
    queryFn: () =>
      api<{ items: Person[]; total: number }>(
        `/api/v1/persons?q=${encodeURIComponent(q)}&status=${status}&limit=${limit}&offset=${page * limit}`,
      ),
  })

  const create = useMutation({
    mutationFn: (body: PersonForm) => api<Person>('/api/v1/persons', { method: 'POST', body }),
    onSuccess: () => {
      setShowCreate(false)
      qc.invalidateQueries({ queryKey: ['persons'] })
    },
    onError: (e) => setFormError((e as ApiError).message),
  })

  const patch = useMutation({
    mutationFn: ({ id, version, body }: { id: string; version: number; body: Partial<PersonForm> }) =>
      api<Person>(`/api/v1/persons/${id}`, {
        method: 'PATCH',
        body,
        extraHeaders: { 'If-Match': `"${version}"` },
      }),
    onSuccess: () => {
      setEditing(null)
      setFormError('')
      qc.invalidateQueries({ queryKey: ['persons'] })
    },
    onError: (e) => {
      const err = e as ApiError
      setFormError(
        err.code === 'VERSION_CONFLICT'
          ? 'تعارض نسخه: این شخص در فاصله باز و ارسال شما توسط دیگری اصلاح شده است؛ نسخه جدید را بارگیری کنید.'
          : err.message,
      )
    },
  })

  const createForm = useForm<PersonForm>({ resolver: zodResolver(personSchema), defaultValues: { given_name: '', family_name: '', display_name: '' } })
  const editForm = useForm<PersonForm>({ resolver: zodResolver(personSchema) })

  const openEdit = (p: Person) => {
    setFormError('')
    setEditing(p)
    editForm.reset({ given_name: p.given_name, family_name: p.family_name, display_name: p.display_name })
  }

  return (
    <>
      <PageHead
        title="اشخاص"
        subtitle="مرجع هویت عمومی — UUID شناسه اصلی است؛ وضعیت تحصیلی/استخدامی در این هسته مدیریت نمی‌شود"
        actions={canEdit && <button className="btn primary" onClick={() => { setFormError(''); setShowCreate(true) }}>ایجاد شخص</button>}
      />

      <div className="card">
        <div className="filters">
          <input placeholder="جست‌وجو در نام…" value={q} onChange={(e) => { setQ(e.target.value); setPage(0) }} />
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(0) }}>
            <option value="">همه وضعیت‌ها</option>
            <option value="active">فعال</option>
            <option value="inactive">غیرفعال</option>
            <option value="merged">ادغام‌شده</option>
          </select>
        </div>
        {persons.isLoading ? <Loading /> : persons.error ? <ErrorBox error={persons.error} /> : (
          persons.data?.items.length === 0 ? <Empty /> : (
            <div className="table-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>نام</th><th>نام نمایشی</th><th>وضعیت</th><th>نسخه</th><th>آخرین تغییر</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {persons.data?.items?.map((p) => (
                    <tr key={p.id} className="clickable" onClick={() => navigate(`/persons/${p.id}`)}>
                      <td>{p.given_name} {p.family_name}</td>
                      <td>{p.display_name}</td>
                      <td><StatusBadge status={p.status} /></td>
                      <td className="num">{p.version}</td>
                      <td>{fmtDateTime(p.updated_at)}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        {canEdit && p.status === 'active' && (
                          <button className="btn sm" onClick={() => openEdit(p)}>اصلاح</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
        {persons.data && persons.data.total > limit && (
          <div className="pager">
            <button className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>قبلی</button>
            <span className="muted small">
              صفحه {page + 1} از {Math.ceil(persons.data.total / limit)}
            </span>
            <button className="btn sm" disabled={(page + 1) * limit >= persons.data.total} onClick={() => setPage(page + 1)}>بعدی</button>
          </div>
        )}
      </div>

      {showCreate && (
        <Modal title="ایجاد شخص" onClose={() => setShowCreate(false)}>
          {formError && <div className="alert error">{formError}</div>}
          <form onSubmit={createForm.handleSubmit((v) => create.mutate(v))}>
            <label>نام</label>
            <input {...createForm.register('given_name')} />
            {createForm.formState.errors.given_name && <div className="alert error">{createForm.formState.errors.given_name.message}</div>}
            <label>نام خانوادگی</label>
            <input {...createForm.register('family_name')} />
            {createForm.formState.errors.family_name && <div className="alert error">{createForm.formState.errors.family_name.message}</div>}
            <label>نام نمایشی (اختیاری)</label>
            <input {...createForm.register('display_name')} placeholder="خالی = نام و نام خانوادگی" />
            <div className="modal-foot">
              <button className="btn primary" type="submit" disabled={create.isPending}>ثبت</button>
              <button className="btn" type="button" onClick={() => setShowCreate(false)}>انصراف</button>
            </div>
          </form>
        </Modal>
      )}

      {editing && (
        <Modal title={`اصلاح شخص — نسخه ${editing.version}`} onClose={() => setEditing(null)}>
          {formError && <div className="alert error">{formError}</div>}
          <form
            onSubmit={editForm.handleSubmit((v) =>
              patch.mutate({
                id: editing.id,
                version: editing.version,
                body: {
                  given_name: v.given_name,
                  family_name: v.family_name,
                  display_name: v.display_name || undefined,
                },
              }),
            )}
          >
            <label>نام</label>
            <input {...editForm.register('given_name')} />
            <label>نام خانوادگی</label>
            <input {...editForm.register('family_name')} />
            <label>نام نمایشی</label>
            <input {...editForm.register('display_name')} />
            <div className="modal-foot">
              <button className="btn primary" type="submit" disabled={patch.isPending}>ذخیره (با کنترل نسخه)</button>
              <button className="btn" type="button" onClick={() => setEditing(null)}>انصراف</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  )
}
