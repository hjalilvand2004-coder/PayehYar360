import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import type { OwnershipPolicy } from '../../api/types'
import { ErrorBox, Loading, PageHead } from '../../components/ui'
import { fmtDateTime } from '../../shared/format'
import { useAuth } from '../../auth/AuthContext'

const ROLE_OPTIONS = [
  { value: 'master_data_editor', label: 'کارشناس اطلاعات پایه' },
  { value: 'steward', label: 'متولی داده' },
  { value: 'tenant_admin', label: 'مدیر مشتری' },
  { value: 'integration_admin', label: 'مدیر یکپارچگی' },
]

export default function Ownership() {
  const qc = useQueryClient()
  const { me } = useAuth()
  const canEdit = (me?.roles || []).some((r) => ['steward', 'tenant_admin', 'integration_admin'].includes(r))
  const [error, setError] = useState('')

  const policies = useQuery({
    queryKey: ['ownership'],
    queryFn: () => api<{ items: OwnershipPolicy[] }>('/api/v1/ownership-policies'),
  })

  const upsert = useMutation({
    mutationFn: (body: Record<string, unknown>) => api('/api/v1/ownership-policies', { method: 'PUT', body }),
    onSuccess: () => { setError(''); qc.invalidateQueries({ queryKey: ['ownership'] }) },
    onError: (e) => setError((e as ApiError).message),
  })

  return (
    <>
      <PageHead
        title="مالکیت داده"
        subtitle="ماتریس مالکیت در سطح (موجودیت، گروه ویژه) — ویرایش فقط توسط مرجع مالک مجاز است (FR-07/FR-08)"
      />
      {error && <div className="alert error">{error}</div>}
      <div className="card">
        {policies.isLoading ? <Loading /> : policies.error ? <ErrorBox error={policies.error} /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead>
                <tr><th>موجودیت</th><th>گروه ویژه</th><th>مالک فعلی</th><th>نسخه</th><th>آخرین تغییر</th><th>تغییر مالک</th></tr>
              </thead>
              <tbody>
                {policies.data?.items?.map((p) => (
                  <tr key={p.id}>
                    <td>{p.entity_type}</td>
                    <td>{p.field_group}</td>
                    <td><span className="chip">{p.owner_type === 'role' ? roleLabel(p.owner_code) : `${p.owner_type}: ${p.owner_code}`}</span></td>
                    <td className="num">{p.version}</td>
                    <td className="small">{p.updated_by || '—'} <br />{fmtDateTime(p.updated_at)}</td>
                    <td>
                      {canEdit && p.owner_type === 'role' ? (
                        <select
                          value={p.owner_code}
                          onChange={(e) =>
                            upsert.mutate({ entity_type: p.entity_type, field_group: p.field_group, owner_type: 'role', owner_code: e.target.value })
                          }
                          style={{ minWidth: 160 }}
                        >
                          {ROLE_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                        </select>
                      ) : <span className="muted small">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted small">
          تغییر مالکیت، عملیات مدیریتی حساس است و در ممیزی ثبت می‌شود. سرویس‌های مرجع با scope مالکیت (owner:…) نیز می‌توانند ویرایش کنند.
        </p>
      </div>
    </>
  )
}

function roleLabel(code: string): string {
  return ROLE_OPTIONS.find((r) => r.value === code)?.label || code
}
