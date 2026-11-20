import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import type { ChangeRequest } from '../../api/types'
import { Empty, ErrorBox, Loading, Modal, PageHead, StatusBadge } from '../../components/ui'
import { fmtDateTime } from '../../shared/format'
import { useAuth } from '../../auth/AuthContext'

export default function ChangeRequests() {
  const qc = useQueryClient()
  const { me } = useAuth()
  const isSteward = (me?.roles || []).some((r) => ['steward', 'tenant_admin'].includes(r))
  const [statusFilter, setStatusFilter] = useState('open')
  const [detail, setDetail] = useState<ChangeRequest | null>(null)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const requests = useQuery({
    queryKey: ['change-requests', statusFilter],
    queryFn: () => api<{ items: ChangeRequest[] }>(`/api/v1/change-requests?status=${statusFilter}`),
  })

  const decide = useMutation({
    mutationFn: ({ id, action, note }: { id: string; action: string; note: string }) =>
      api(`/api/v1/change-requests/${id}/decision`, { method: 'POST', body: { action, note: note || null } }),
    onSuccess: (_d, v) => {
      setNotice(v.action === 'approve' ? 'درخواست تأیید و تغییر اعمال شد.' : 'درخواست رد شد.')
      setError(''); setDetail(null); setNote('')
      qc.invalidateQueries({ queryKey: ['change-requests'] })
    },
    onError: (e) => setError((e as ApiError).message),
  })

  return (
    <>
      <PageHead
        title="درخواست اصلاح"
        subtitle="درخواست اصلاح داده غیرمالک به مرجع مسئول هدایت می‌شود؛ هسته وضعیت را مدیریت و پس از تأیید اعمال می‌کند (FR-09)"
      />
      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert info">{notice}</div>}
      <div className="card">
        <div className="filters">
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">همه</option>
            <option value="open">در جریان</option>
            <option value="approved">تأییدشده</option>
            <option value="rejected">ردشده</option>
            <option value="cancelled">لغوشده</option>
          </select>
        </div>
        {requests.isLoading ? <Loading /> : requests.error ? <ErrorBox error={requests.error} /> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>هدف</th><th>درخواست‌کننده</th><th>دلیل</th><th>وضعیت</th><th>ایجاد</th><th></th></tr></thead>
              <tbody>
                {(requests.data?.items || []).map((r) => (
                  <tr key={r.id}>
                    <td className="num small">{r.entity_type} — {r.entity_id.slice(0, 8)}…</td>
                    <td>{r.requested_by_name || r.requested_by}</td>
                    <td className="small">{r.reason.slice(0, 40)}{r.reason.length > 40 ? '…' : ''}</td>
                    <td><StatusBadge status={r.status} /></td>
                    <td className="small">{fmtDateTime(r.created_at)}</td>
                    <td><button className="btn sm" onClick={() => setDetail(r)}>جزئیات</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(requests.data?.items || []).length === 0 && <Empty />}
          </div>
        )}
      </div>

      {detail && (
        <Modal title={`درخواست اصلاح ${detail.id.slice(0, 8)}…`} onClose={() => setDetail(null)}>
          <div className="kv">
            <div className="k">هدف</div><div className="num small">{detail.entity_id}</div>
            <div className="k">درخواست‌کننده</div><div>{detail.requested_by_name || detail.requested_by}</div>
            <div className="k">دلیل</div><div>{detail.reason}</div>
            <div className="k">وضعیت</div><div><StatusBadge status={detail.status} /></div>
          </div>
          <h3>تغییر پیشنهادی</h3>
          <table className="tbl">
            <thead><tr><th>فیلد</th><th>مقدار پیشنهادی</th></tr></thead>
            <tbody>
              {Object.entries(detail.proposed_changes).map(([k, v]) => (
                <tr key={k}><td>{k}</td><td><span className="diff-add">{v}</span></td></tr>
              ))}
            </tbody>
          </table>
          {detail.decided_by && (
            <div className="alert info">
              تصمیم‌گیر: {detail.decided_by} — {fmtDateTime(detail.decided_at)} {detail.decision_note && <>— یادداشت: {detail.decision_note}</>}
            </div>
          )}
          {detail.status === 'open' && isSteward && (
            <>
              <label>یادداشت تصمیم</label>
              <input value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="modal-foot">
                <button className="btn primary" disabled={decide.isPending}
                        onClick={() => decide.mutate({ id: detail.id, action: 'approve', note })}>
                  تأیید و اعمال
                </button>
                <button className="btn danger" disabled={decide.isPending}
                        onClick={() => decide.mutate({ id: detail.id, action: 'reject', note })}>
                  رد
                </button>
              </div>
            </>
          )}
        </Modal>
      )}
    </>
  )
}
