import { useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { HELP, helpTopicForPath } from '../shared/helpContent'

export function PageHead({ title, actions, subtitle }: { title: string; actions?: ReactNode; subtitle?: string }) {
  // دکمه «؟ راهنما» در سربرگ همه صفحات — محتوای جامع همان بخش در مودال باز می‌شود
  const topic = helpTopicForPath(useLocation().pathname)
  const [helpOpen, setHelpOpen] = useState(false)
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <div className="muted small">{subtitle}</div>}
      </div>
      <div className="actions">
        {topic && (
          <button className="btn ghost sm" onClick={() => setHelpOpen(true)} title={`راهنمای ${HELP[topic].title}`}>
            ؟ راهنما
          </button>
        )}
        {actions}
      </div>
      {topic && helpOpen && (
        <Modal title={`راهنما — ${HELP[topic].title}`} wide onClose={() => setHelpOpen(false)}>
          <div style={{ maxHeight: '65vh', overflowY: 'auto', lineHeight: 1.9 }}>
            <p style={{ marginTop: 0 }}>{HELP[topic].intro}</p>
            {HELP[topic].sections.map((sec) => (
              <div key={sec.h}>
                <h3 style={{ margin: '14px 0 6px' }}>{sec.h}</h3>
                <ul style={{ margin: 0, paddingInlineStart: 22 }}>
                  {sec.items.map((it, idx) => <li key={idx} style={{ marginBottom: 4 }}>{it}</li>)}
                </ul>
              </div>
            ))}
            {HELP[topic].tips && HELP[topic].tips.length > 0 && (
              <div className="alert info" style={{ marginTop: 14 }}>
                <b>نکات:</b>
                <ul style={{ margin: '6px 0 0', paddingInlineStart: 20 }}>
                  {HELP[topic].tips.map((t, idx) => <li key={idx}>{t}</li>)}
                </ul>
              </div>
            )}
          </div>
        </Modal>
      )}
    </div>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; label: string }> = {
    active: { cls: 'ok', label: 'فعال' },
    inactive: { cls: 'warn', label: 'غیرفعال' },
    merged: { cls: 'warn', label: 'ادغام‌شده' },
    open: { cls: '', label: 'در جریان' },
    approved: { cls: 'ok', label: 'تأییدشده' },
    rejected: { cls: 'danger', label: 'ردشده' },
    cancelled: { cls: 'warn', label: 'لغوشده' },
    decided: { cls: 'ok', label: 'تصمیم‌گیری‌شده' },
    done: { cls: 'ok', label: 'انجام‌شده' },
    queued: { cls: '', label: 'در صف' },
    running: { cls: 'warn', label: 'در حال اجرا' },
    failed: { cls: 'danger', label: 'ناموفق' },
    expired: { cls: 'danger', label: 'منقضی' },
    revoked: { cls: 'danger', label: 'قطع‌شده' },
    verified: { cls: 'ok', label: 'تأییدشده' },
    unverified: { cls: 'warn', label: 'تأییدنشده' },
    rejected_v: { cls: 'danger', label: 'ردشده' },
    applied: { cls: 'ok', label: 'اعمال‌شده' },
    reversed: { cls: 'warn', label: 'بازگردانی‌شده' },
    retired: { cls: 'warn', label: 'بازنشسته' },
    integrated: { cls: 'ok', label: 'یکپارچه' },
    local: { cls: '', label: 'مستقل' },
  }
  const item = map[status] || { cls: '', label: status }
  return <span className={`chip ${item.cls}`}>{item.label}</span>
}

export function Modal({
  title, children, onClose, wide,
}: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  return (
    <div className="modal-back" onClick={onClose}>
      <div className={`modal ${wide ? 'wide' : ''}`} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="btn ghost sm" onClick={onClose}>✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function Empty({ text = 'موردی برای نمایش نیست' }: { text?: string }) {
  return <div className="empty">{text}</div>
}

export function Loading({ text = 'در حال بارگذاری …' }: { text?: string }) {
  return <div className="skeleton">{text}</div>
}

export function ErrorBox({ error }: { error: unknown }) {
  const e = error as { message?: string; code?: string }
  return <div className="alert error">خطا {e?.code ? `(${e.code})` : ''}: {e?.message || 'نامشخص'}</div>
}

export function ConfirmInline({
  message, onConfirm, onCancel, busy,
}: { message: string; onConfirm: () => void; onCancel: () => void; busy?: boolean }) {
  return (
    <div className="alert warn">
      <div style={{ marginBottom: 8 }}>{message}</div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="btn danger sm" onClick={onConfirm} disabled={busy}>تأیید نهایی</button>
        <button className="btn sm" onClick={onCancel} disabled={busy}>انصراف</button>
      </div>
    </div>
  )
}
