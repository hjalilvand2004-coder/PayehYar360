import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { IntegrationsStatus, Stats } from '../../api/types'
import { ErrorBox, Loading, PageHead, StatusBadge } from '../../components/ui'
import { fmtNumber, fmtSeconds } from '../../shared/format'
import { useAuth } from '../../auth/AuthContext'

export default function Dashboard() {
  const { auth } = useAuth()
  const stats = useQuery({ queryKey: ['stats'], queryFn: () => api<Stats>('/api/v1/stats') })
  const status = useQuery({
    queryKey: ['int-status'],
    queryFn: () => api<IntegrationsStatus>('/api/v1/integrations/status'),
    refetchInterval: 15000,
  })
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api<{ status: string; checks: Record<string, { ok: boolean; detail: string }> }>('/health/ready'),
    refetchInterval: 20000,
  })

  return (
    <>
      <PageHead
        title="داشبورد"
        subtitle={`سلامت هسته، اتصال‌ها و درخواست‌های معوق — مشتری: ${auth?.tenant ?? '—'}`}
      />
      <div className="grid cols-4">
        <div className="card stat">
          <div className="num">{stats.data ? fmtNumber(stats.data.persons_active) : '…'}</div>
          <div className="lbl">شخص فعال</div>
        </div>
        <div className="card stat">
          <div className="num">{stats.data ? fmtNumber(stats.data.persons_merged) : '…'}</div>
          <div className="lbl">شخص ادغام‌شده</div>
        </div>
        <div className="card stat">
          <div className="num">{stats.data ? fmtNumber(stats.data.open_change_requests) : '…'}</div>
          <div className="lbl">درخواست اصلاح معوق</div>
        </div>
        <div className="card stat">
          <div className="num">{stats.data ? fmtNumber(stats.data.open_quality_cases) : '…'}</div>
          <div className="lbl">پرونده کیفیت معوق</div>
        </div>
      </div>

      <div className="card">
        <h2>سلامت اجزا</h2>
        {health.isLoading ? <Loading /> : health.error ? <ErrorBox error={health.error} /> : (
          <div className="grid cols-3">
            <div>
              <div className="muted small">دیتابیس</div>
              <StatusBadge status={health.data?.checks.database?.ok ? 'active' : 'failed'} />
              <div className="muted small">{health.data?.checks.database?.detail}</div>
            </div>
            <div>
              <div className="muted small">RabbitMQ</div>
              <StatusBadge status={health.data?.checks.rabbitmq?.ok ? 'active' : 'inactive'} />
              <div className="muted small">{status.data?.rabbitmq.detail}</div>
            </div>
            <div>
              <div className="muted small">وضعیت کلی</div>
              <StatusBadge status={health.data?.status === 'ok' ? 'active' : 'failed'} />
            </div>
          </div>
        )}
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h2>Outbox</h2>
          <div className="kv">
            <div className="k">رویداد در انتظار انتشار</div>
            <div>{status.data ? fmtNumber(status.data.outbox.pending) : '…'}</div>
            <div className="k">قدیمی‌ترین رویداد</div>
            <div>{status.data ? fmtSeconds(status.data.outbox.oldest_pending_age_seconds) : '…'}</div>
            <div className="k">ناموفق</div>
            <div>{status.data ? fmtNumber(status.data.outbox.failed) : '…'}</div>
            <div className="k">مرز تغییر (max_seq)</div>
            <div className="num">{status.data ? fmtNumber(status.data.max_seq) : '…'}</div>
          </div>
          <p className="muted small">
            قطع RabbitMQ داده را از دست نمی‌دهد؛ رویدادها در Outbox باقی می‌مانند و با بازگشت Broker منتشر می‌شوند.
          </p>
        </div>
        <div className="card">
          <h2>فاصله مصرف‌کننده‌ها</h2>
          {status.isLoading ? <Loading /> : (
            <div className="table-wrap">
              <table className="tbl">
                <thead>
                  <tr><th>نصب</th><th>حالت</th><th>checkpoint</th><th>فاصله</th></tr>
                </thead>
                <tbody>
                  {(status.data?.installations || []).map((i) => (
                    <tr key={i.installation_code}>
                      <td>{i.title} <span className="muted small">({i.installation_code})</span></td>
                      <td><StatusBadge status={i.mode} /></td>
                      <td className="num">{fmtNumber(i.checkpoint_cursor)}</td>
                      <td>{i.lag === null ? '—' : <span className={`chip ${i.lag > 100 ? 'warn' : 'ok'}`}>{fmtNumber(i.lag)}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
