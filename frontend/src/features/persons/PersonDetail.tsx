import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { HistoryEntry, PersonDetail } from '../../api/types'
import { ConfirmInline, Empty, ErrorBox, Loading, Modal, PageHead, StatusBadge } from '../../components/ui'
import { fmtDateTime } from '../../shared/format'
import { useAuth } from '../../auth/AuthContext'

const TABS = [
  { key: 'identifiers', label: 'شناسه‌ها' },
  { key: 'contacts', label: 'تماس‌ها' },
  { key: 'links', label: 'حساب SSO' },
  { key: 'mappings', label: 'نگاشت‌ها' },
  { key: 'history', label: 'سابقه تغییر' },
]

export default function PersonDetail() {
  const { id } = useParams()
  const qc = useQueryClient()
  const { me } = useAuth()
  const [tab, setTab] = useState('identifiers')
  const [modal, setModal] = useState<string>('')
  const [confirming, setConfirming] = useState<string>('')
  const [error, setError] = useState('')

  const isSteward = (me?.roles || []).includes('steward') || (me?.roles || []).includes('tenant_admin')
  const isEditor = (me?.roles || []).includes('master_data_editor') || isSteward

  const person = useQuery({
    queryKey: ['person', id],
    queryFn: () => api<PersonDetail>(`/api/v1/persons/${id}`),
  })
  const history = useQuery({
    queryKey: ['person-history', id],
    queryFn: () => api<{ items: HistoryEntry[] }>(`/api/v1/persons/${id}/history`),
    enabled: tab === 'history',
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['person', id] })
  const run = (fn: () => Promise<unknown>, after?: () => void) =>
    fn()
      .then(() => { setError(''); setModal(''); setConfirming(''); invalidate(); after?.() })
      .catch((e) => setError((e as ApiError).message))

  const deactivate = useMutation({
    mutationFn: (version: number) =>
      api(`/api/v1/persons/${id}/deactivation`, { method: 'POST', body: { version }, extraHeaders: { 'If-Match': `"${version}"` } }),
    onSuccess: () => { setConfirming(''); invalidate() },
    onError: (e) => setError((e as ApiError).message),
  })

  if (person.isLoading) return <Loading />
  if (person.error) return <ErrorBox error={person.error} />
  const p = person.data!

  return (
    <>
      <PageHead
        title={p.display_name}
        subtitle={`شناسه مشترک: ${p.id}`}
        actions={
          <>
            <span className="chip">نسخه {p.version}</span>
            <StatusBadge status={p.status} />
            {isSteward && p.status === 'active' && (
              <button className="btn danger" onClick={() => setConfirming('deactivate')}>غیرفعال‌سازی</button>
            )}
          </>
        }
      />
      {error && <div className="alert error">{error}</div>}
      {confirming === 'deactivate' && (
        <ConfirmInline
          message={`غیرفعال‌سازی «${p.display_name}» — این عمل با کنترل نسخه ${p.version} انجام و رویداد PersonDeactivated منتشر می‌شود. مطمئن هستید؟`}
          busy={deactivate.isPending}
          onConfirm={() => deactivate.mutate(p.version)}
          onCancel={() => setConfirming('')}
        />
      )}

      <div className="card">
        <div className="kv">
          <div className="k">نام</div><div>{p.given_name}</div>
          <div className="k">نام خانوادگی</div><div>{p.family_name}</div>
          <div className="k">نام نمایشی</div><div>{p.display_name}</div>
          <div className="k">وضعیت</div><div><StatusBadge status={p.status} /> {p.merged_into_id && <span className="muted small">→ {p.merged_into_id}</span>}</div>
          <div className="k">ایجاد</div><div>{fmtDateTime(p.created_at)}</div>
          <div className="k">آخرین تغییر</div><div>{fmtDateTime(p.updated_at)}</div>
        </div>
      </div>

      <div className="card">
        <div className="tabs">
          {TABS.map((t) => (
            <div key={t.key} className={`tab ${tab === t.key ? 'active' : ''}`} onClick={() => setTab(t.key)}>
              {t.label}
            </div>
          ))}
        </div>

        {tab === 'identifiers' && (
          <>
            <div className="table-wrap">
              <table className="tbl">
                <thead><tr><th>نوع</th><th>صادرکننده</th><th>مقدار (ماسک‌شده)</th><th>وضعیت تأیید</th><th>وضعیت</th><th></th></tr></thead>
                <tbody>
                  {p.identifiers.map((i) => (
                    <tr key={i.id}>
                      <td>{i.type}</td><td>{i.issuer}</td><td className="num">{i.value_masked}</td>
                      <td><StatusBadge status={i.verification_status} /></td>
                      <td><StatusBadge status={i.status} /></td>
                      <td>
                        {isSteward && i.status === 'active' && i.verification_status !== 'verified' && (
                          <button className="btn sm" onClick={() => run(() =>
                            api(`/api/v1/persons/${id}/identifiers/${i.id}`, { method: 'PATCH', body: { verification_status: 'verified' } }))}>
                            تأیید
                          </button>
                        )}
                        {isSteward && i.status === 'active' && (
                          <button className="btn sm ghost" onClick={() => run(() =>
                            api(`/api/v1/persons/${id}/identifiers/${i.id}`, { method: 'PATCH', body: { status: 'revoked' } }))}>
                            ابطال
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {p.identifiers.length === 0 && <Empty text="شناسه‌ای ثبت نشده است" />}
            </div>
            {isSteward && <button className="btn" onClick={() => setModal('identifier')}>افزودن شناسه</button>}
          </>
        )}

        {tab === 'contacts' && (
          <>
            <div className="table-wrap">
              <table className="tbl">
                <thead><tr><th>نوع</th><th>مقدار</th><th>تأیید</th><th>وضعیت</th><th></th></tr></thead>
                <tbody>
                  {p.contacts.map((c) => (
                    <tr key={c.id}>
                      <td>{c.type}</td><td>{c.value}</td>
                      <td>{c.verified_at ? fmtDateTime(c.verified_at) : '—'}</td>
                      <td><StatusBadge status={c.status} /></td>
                      <td>
                        {isEditor && c.status === 'active' && !c.verified_at && (
                          <button className="btn sm" onClick={() => run(() =>
                            api(`/api/v1/persons/${id}/contacts/${c.id}`, { method: 'PATCH', body: { verified: true } }))}>
                            تأیید تماس
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {p.contacts.length === 0 && <Empty text="تماسی ثبت نشده است" />}
            </div>
            {isEditor && <button className="btn" onClick={() => setModal('contact')}>افزودن تماس</button>}
          </>
        )}

        {tab === 'links' && (
          <>
            <div className="table-wrap">
              <table className="tbl">
                <thead><tr><th>Issuer</th><th>Subject</th><th>برچسب</th><th>وضعیت</th><th>زمان اتصال</th><th></th></tr></thead>
                <tbody>
                  {p.account_links.map((l) => (
                    <tr key={l.id}>
                      <td className="small">{l.issuer}</td><td className="num">{l.subject}</td><td>{l.account_label || '—'}</td>
                      <td><StatusBadge status={l.status} /></td><td>{fmtDateTime(l.linked_at)}</td>
                      <td>
                        {isSteward && l.status === 'active' && (
                          <button className="btn sm ghost" onClick={() => run(() =>
                            api(`/api/v1/identity-account-links/${l.id}/revoke`, { method: 'POST', body: { note: 'قطع از پنل' } }))}>
                            قطع اتصال
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {p.account_links.length === 0 && <Empty text="حسابی متصل نشده است" />}
            </div>
            {isSteward && <button className="btn" onClick={() => setModal('link')}>اتصال حساب SSO</button>}
            <p className="muted small">اتصال صرفاً بر اساس issuer + subject انجام می‌شود؛ استفاده از ایمیل برای اتصال ممنوع است.</p>
          </>
        )}

        {tab === 'mappings' && (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>نصب</th><th>نوع موجودیت</th><th>شناسه محلی</th><th>وضعیت</th></tr></thead>
              <tbody>
                {p.mappings.map((m) => (
                  <tr key={m.id}>
                    <td>{m.installation_code}</td><td>{m.entity_type}</td>
                    <td className="num">{m.local_id}</td><td><StatusBadge status={m.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {p.mappings.length === 0 && <Empty text="نگاهتی ثبت نشده است" />}
          </div>
        )}

        {tab === 'history' && (
          history.isLoading ? <Loading /> : (
            <div className="table-wrap">
              <table className="tbl">
                <thead><tr><th>شماره</th><th>عملیات</th><th>نسخه</th><th>فیلدها</th><th>عامل</th><th>زمان</th></tr></thead>
                <tbody>
                  {(history.data?.items || []).map((h) => (
                    <tr key={h.seq}>
                      <td className="num">{h.seq}</td>
                      <td>{h.operation}</td>
                      <td className="num">{h.version}</td>
                      <td className="small">{(h.changed_fields || []).join('، ') || '—'}</td>
                      <td className="small">{h.actor_id}</td>
                      <td>{fmtDateTime(h.occurred_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(history.data?.items || []).length === 0 && <Empty />}
            </div>
          )
        )}
      </div>

      {modal === 'identifier' && <IdentifierModal personId={id!} onClose={() => setModal('')} onDone={invalidate} />}
      {modal === 'contact' && <ContactModal personId={id!} onClose={() => setModal('')} onDone={invalidate} />}
      {modal === 'link' && <LinkModal personId={id!} onClose={() => setModal('')} onDone={invalidate} />}
    </>
  )
}

function IdentifierModal({ personId, onClose, onDone }: { personId: string; onClose: () => void; onDone: () => void }) {
  const [type, setType] = useState('national_id')
  const [issuer, setIssuer] = useState('civil_registry')
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  return (
    <Modal title="افزودن شناسه" onClose={onClose}>
      {error && <div className="alert error">{error}</div>}
      <label>نوع شناسه</label>
      <select value={type} onChange={(e) => setType(e.target.value)}>
        <option value="national_id">کد ملی</option>
        <option value="student_number">شماره دانشجویی</option>
        <option value="personnel_number">شماره پرسنلی</option>
        <option value="passport">گذرنامه</option>
      </select>
      <label>حوزه صادرکننده</label>
      <input value={issuer} onChange={(e) => setIssuer(e.target.value)} />
      <label>مقدار</label>
      <input value={value} onChange={(e) => setValue(e.target.value)} dir="ltr" />
      <div className="modal-foot">
        <button className="btn primary" onClick={() =>
          api(`/api/v1/persons/${personId}/identifiers`, { method: 'POST', body: { type, issuer, value } })
            .then(onDone).then(onClose).catch((e) => setError((e as ApiError).message))
        }>ثبت</button>
        <button className="btn" onClick={onClose}>انصراف</button>
      </div>
    </Modal>
  )
}

function ContactModal({ personId, onClose, onDone }: { personId: string; onClose: () => void; onDone: () => void }) {
  const [type, setType] = useState('email')
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  return (
    <Modal title="افزودن تماس" onClose={onClose}>
      {error && <div className="alert error">{error}</div>}
      <label>نوع</label>
      <select value={type} onChange={(e) => setType(e.target.value)}>
        <option value="email">ایمیل</option>
        <option value="mobile">تلفن همراه</option>
        <option value="phone">تلفن ثابت</option>
      </select>
      <label>مقدار</label>
      <input value={value} onChange={(e) => setValue(e.target.value)} dir="ltr" />
      <div className="modal-foot">
        <button className="btn primary" onClick={() =>
          api(`/api/v1/persons/${personId}/contacts`, { method: 'POST', body: { type, value } })
            .then(onDone).then(onClose).catch((e) => setError((e as ApiError).message))
        }>ثبت</button>
        <button className="btn" onClick={onClose}>انصراف</button>
      </div>
    </Modal>
  )
}

function LinkModal({ personId, onClose, onDone }: { personId: string; onClose: () => void; onDone: () => void }) {
  const [subject, setSubject] = useState('')
  const [label, setLabel] = useState('')
  const [error, setError] = useState('')
  return (
    <Modal title="اتصال حساب SSO (کنترل‌شده)" onClose={onClose}>
      {error && <div className="alert error">{error}</div>}
      <label>Subject کاربر در SSO</label>
      <input value={subject} onChange={(e) => setSubject(e.target.value)} dir="ltr" />
      <label>برچسب نمایشی (اختیاری)</label>
      <input value={label} onChange={(e) => setLabel(e.target.value)} />
      <div className="modal-foot">
        <button className="btn primary" disabled={subject.length < 2} onClick={() =>
          api('/api/v1/identity-account-links', {
            method: 'POST',
            body: { person_id: personId, subject, account_label: label || null },
          }).then(onDone).then(onClose).catch((e) => setError((e as ApiError).message))
        }>اتصال</button>
        <button className="btn" onClick={onClose}>انصراف</button>
      </div>
    </Modal>
  )
}
