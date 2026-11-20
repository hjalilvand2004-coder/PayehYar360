import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { AuditLog } from '../../api/types'
import { Empty, ErrorBox, Loading, PageHead } from '../../components/ui'
import { fmtDateTime } from '../../shared/format'
import { useAuth } from '../../auth/AuthContext'

export default function Audit() {
  const { me } = useAuth()
  const allowed = (me?.roles || []).some((r) => ['auditor', 'tenant_admin', 'steward', 'integration_admin'].includes(r))
  const [entityType, setEntityType] = useState('')
  const [operation, setOperation] = useState('')
  const [actorId, setActorId] = useState('')

  const logs = useQuery({
    queryKey: ['audit', entityType, operation, actorId],
    queryFn: () =>
      api<{ total: number; items: AuditLog[] }>(
        `/api/v1/audit-logs?entity_type=${entityType}&operation=${encodeURIComponent(operation)}&actor_id=${encodeURIComponent(actorId)}&limit=100`,
      ),
    enabled: allowed,
  })

  return (
    <>
      <PageHead
        title="ممیزی"
        subtitle="سوابق عملیات — فقط خواندن؛ ثبت ممیزی غیرقابل تغییر توسط کاربران عادی است (FR-16)"
      />
      {!allowed ? (
        <div className="alert warn">مشاهده ممیزی نیازمند نقش ممیز/مدیر است.</div>
      ) : (
        <>
          <div className="card">
            <div className="filters">
              <select value={entityType} onChange={(e) => setEntityType(e.target.value)}>
                <option value="">همه موجودیت‌ها</option>
                <option value="person">شخص</option>
                <option value="organization">سازمان</option>
                <option value="identity_link">اتصال حساب</option>
                <option value="external_id_mapping">نگاشت</option>
                <option value="reference_item">آیتم مرجع</option>
                <option value="ownership_policy">سیاست مالکیت</option>
                <option value="tenant">مشتری</option>
                <option value="system_installation">نصب</option>
              </select>
              <input placeholder="عملیات (مثلاً person.update)" value={operation} onChange={(e) => setOperation(e.target.value)} dir="ltr" />
              <input placeholder="عامل (user:...)" value={actorId} onChange={(e) => setActorId(e.target.value)} dir="ltr" />
            </div>
            {logs.isLoading ? <Loading /> : logs.error ? <ErrorBox error={logs.error} /> : (
              <div className="table-wrap">
                <table className="tbl">
                  <thead><tr><th>زمان</th><th>عامل</th><th>عملیات</th><th>موجودیت</th><th>قبل</th><th>بعد</th><th>Correlation</th></tr></thead>
                  <tbody>
                    {logs.data?.items?.map((l) => (
                      <tr key={l.id}>
                        <td className="small">{fmtDateTime(l.created_at)}</td>
                        <td className="small">{l.actor_name || l.actor_id}</td>
                        <td className="num small" dir="ltr">{l.operation}</td>
                        <td className="small">{l.entity_type}{l.entity_id ? ` — ${l.entity_id.slice(0, 8)}…` : ''}</td>
                        <td className="small" dir="ltr">{clip(l.before)}</td>
                        <td className="small" dir="ltr">{clip(l.after)}</td>
                        <td className="small num" dir="ltr">{l.correlation_id?.slice(0, 8)}…</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {logs.data?.items.length === 0 && <Empty />}
              </div>
            )}
          </div>
        </>
      )}
    </>
  )
}

function clip(s: string | null): string {
  if (!s) return '—'
  return s.length > 60 ? s.slice(0, 60) + '…' : s
}
