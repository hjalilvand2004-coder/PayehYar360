import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import type { Organization } from '../../api/types'
import { ErrorBox, Loading, Modal, PageHead, StatusBadge } from '../../components/ui'
import { useAuth } from '../../auth/AuthContext'

const TYPE_LABELS: Record<string, string> = {
  university: 'دانشگاه', campus: 'پردیس', faculty: 'دانشکده', department: 'گروه آموزشی', unit: 'واحد اداری',
}

export default function Organizations() {
  const qc = useQueryClient()
  const { me } = useAuth()
  const canEdit = (me?.roles || []).some((r) => ['master_data_editor', 'steward', 'tenant_admin'].includes(r))
  const [modal, setModal] = useState<{ mode: 'create' | 'edit'; parent?: string; org?: Organization } | null>(null)
  const [error, setError] = useState('')

  const orgs = useQuery({
    queryKey: ['organizations'],
    queryFn: () => api<{ items: Organization[] }>('/api/v1/organizations'),
  })

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api('/api/v1/organizations', { method: 'POST', body }),
    onSuccess: () => { setModal(null); setError(''); qc.invalidateQueries({ queryKey: ['organizations'] }) },
    onError: (e) => setError((e as ApiError).message),
  })
  const patch = useMutation({
    mutationFn: ({ id, version, body }: { id: string; version: number; body: Record<string, unknown> }) =>
      api(`/api/v1/organizations/${id}`, { method: 'PATCH', body, extraHeaders: { 'If-Match': `"${version}"` } }),
    onSuccess: () => { setModal(null); setError(''); qc.invalidateQueries({ queryKey: ['organizations'] }) },
    onError: (e) => {
      const err = e as ApiError
      setError(err.code === 'VERSION_CONFLICT' ? 'تعارض نسخه — داده جدید را بارگیری کنید.' : err.message)
    },
  })

  if (orgs.isLoading) return <Loading />
  if (orgs.error) return <ErrorBox error={orgs.error} />
  const items = orgs.data!.items

  const buildTree = (parentId: string | null): JSX.Element[] =>
    items
      .filter((o) => o.parent_id === parentId)
      .map((o) => (
        <li key={o.id}>
          <div className="node">
            <span onClick={() => setModal({ mode: 'edit', org: o })}>
              {TYPE_LABELS[o.type] || o.type} — <b>{o.name}</b> <span className="code">({o.code})</span>
            </span>
            <StatusBadge status={o.status} />
            {canEdit && (
              <>
                <button className="btn sm ghost" onClick={() => setModal({ mode: 'create', parent: o.id })}>+ زیرمجموعه</button>
                <button className="btn sm ghost" onClick={() => setModal({ mode: 'edit', org: o })}>اصلاح</button>
              </>
            )}
          </div>
          <ul>{buildTree(o.id)}</ul>
        </li>
      ))

  return (
    <>
      <PageHead
        title="سازمان‌ها"
        subtitle="ساختار سازمانی مشترک — چرخه در ساختار ممنوع است؛ جابه‌جایی با کنترل نسخه انجام می‌شود"
        actions={canEdit && <button className="btn primary" onClick={() => setModal({ mode: 'create' })}>ایجاد واحد</button>}
      />
      {error && <div className="alert error">{error}</div>}
      <div className="card">
        {items.length === 0 ? <div className="empty">ساختار سازمانی خالی است</div> : <ul className="tree">{buildTree(null)}</ul>}
      </div>

      {modal?.mode === 'create' && (
        <OrgForm
          title="ایجاد واحد سازمانی"
          orgs={items}
          parentPreset={modal.parent}
          onSubmit={(v) => create.mutate(v)}
          onCancel={() => setModal(null)}
        />
      )}
      {modal?.mode === 'edit' && modal.org && (
        <OrgForm
          title={`اصلاح «${modal.org.name}» — نسخه ${modal.org.version}`}
          orgs={items.filter((o) => o.id !== modal.org!.id)}
          org={modal.org}
          onSubmit={(v) => patch.mutate({ id: modal.org!.id, version: modal.org!.version, body: v })}
          onCancel={() => setModal(null)}
        />
      )}
    </>
  )
}

function OrgForm({
  title, orgs, org, parentPreset, onSubmit, onCancel,
}: {
  title: string
  orgs: Organization[]
  org?: Organization
  parentPreset?: string
  onSubmit: (v: Record<string, unknown>) => void
  onCancel: () => void
}) {
  const [type, setType] = useState(org?.type || 'faculty')
  const [code, setCode] = useState(org?.code || '')
  const [name, setName] = useState(org?.name || '')
  const [parentId, setParentId] = useState<string>(org?.parent_id || parentPreset || '')
  return (
    <Modal title={title} onClose={onCancel}>
      <label>نوع واحد</label>
      <select value={type} onChange={(e) => setType(e.target.value)} disabled={!!org}>
        {Object.entries(TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      <label>کد</label>
      <input value={code} onChange={(e) => setCode(e.target.value)} disabled={!!org} dir="ltr" />
      <label>نام</label>
      <input value={name} onChange={(e) => setName(e.target.value)} />
      <label>والد</label>
      <select value={parentId} onChange={(e) => setParentId(e.target.value)}>
        <option value="">— بدون والد (ریشه) —</option>
        {orgs.map((o) => <option key={o.id} value={o.id}>{o.name} ({o.code})</option>)}
      </select>
      <div className="modal-foot">
        <button
          className="btn primary"
          onClick={() => onSubmit(org
            // قرارداد PATCH سازمان فقط name/parent_id/sort_order را می‌پذیرد — type/code تغییرناپذیرند
            // (ارسال فیلد اضافه با extra="forbid" به خطای 422 «ورودی ارسالی معتبر نیست» می‌رسید)
            ? { name, parent_id: parentId || null, sort_order: org.sort_order ?? 0 }
            : { type, code, name, parent_id: parentId || null, sort_order: 0 })}
        >ذخیره</button>
        <button className="btn" onClick={onCancel}>انصراف</button>
      </div>
    </Modal>
  )
}
