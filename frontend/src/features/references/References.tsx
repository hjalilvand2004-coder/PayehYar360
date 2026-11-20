import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import type { RefItem, RefSet } from '../../api/types'
import { Empty, ErrorBox, Loading, Modal, PageHead, StatusBadge } from '../../components/ui'
import { useAuth } from '../../auth/AuthContext'

export default function References() {
  const qc = useQueryClient()
  const { me } = useAuth()
  const canEdit = (me?.roles || []).some((r) => ['master_data_editor', 'steward', 'tenant_admin'].includes(r))
  const [selected, setSelected] = useState<string>('')
  const [groupFilter, setGroupFilter] = useState('')
  const [modal, setModal] = useState<{ kind: 'set' | 'item' | 'editItem'; item?: RefItem } | null>(null)
  const [error, setError] = useState('')

  const sets = useQuery({ queryKey: ['ref-sets'], queryFn: () => api<{ items: RefSet[] }>('/api/v1/reference-sets') })
  const items = useQuery({
    queryKey: ['ref-items', selected],
    queryFn: () => api<{ items: RefItem[] }>(`/api/v1/reference-sets/${selected}/items`),
    enabled: !!selected,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['ref-sets'] })
    qc.invalidateQueries({ queryKey: ['ref-items'] })
  }
  const run = (fn: () => Promise<unknown>) =>
    fn().then(() => { setError(''); setModal(null); invalidate() }).catch((e) => setError((e as ApiError).message))

  const activeSet = sets.data?.items.find((s) => s.code === selected)

  // نمای اختصاصی «درس‌های یکتا»: سرگروه‌های SEC-* ستون «گروه» می‌شوند و جدول ۷ ستونه دارد
  const isCourses = selected === 'unique_courses'
  const allItems = items.data?.items || []
  const groupRows = allItems.filter((i) => i.code.startsWith('SEC-'))
  const groupRank = new Map(groupRows.map((g, idx) => [g.title, idx]))
  const courseRows = allItems
    .filter((i) => !i.code.startsWith('SEC-'))
    .filter((i) => !groupFilter || ((i.attrs || {}) as Record<string, any>).group === groupFilter)
    .sort((x, y) => {
      const ax = (x.attrs || {}) as Record<string, any>
      const ay = (y.attrs || {}) as Record<string, any>
      const gx = groupRank.get(ax.group) ?? 99
      const gy = groupRank.get(ay.group) ?? 99
      return gx - gy || (ax.group_order ?? 0) - (ay.group_order ?? 0)
    })

  return (
    <>
      <PageHead
        title="اطلاعات پایه"
        subtitle="فهرست‌های مرجع مصوب با نسخه‌بندی — هر تغییر آیتم، نسخه مجموعه را افزایش می‌دهد"
        actions={canEdit && <button className="btn primary" onClick={() => setModal({ kind: 'set' })}>مجموعه جدید</button>}
      />
      {error && <div className="alert error">{error}</div>}

      <div className="grid cols-2" style={{ gridTemplateColumns: '300px 1fr' }}>
        <div className="card">
          <h2>مجموعه‌ها</h2>
          {sets.isLoading ? <Loading /> : sets.error ? <ErrorBox error={sets.error} /> : (
            <div className="table-wrap">
              <table className="tbl">
                <tbody>
                  {sets.data?.items?.map((s) => (
                    <tr key={s.code} className="clickable" onClick={() => setSelected(s.code)}
                        style={{ background: s.code === selected ? 'var(--primary-soft)' : undefined }}>
                      <td><b>{s.title}</b><div className="muted small">{s.code}</div></td>
                      <td><span className="chip">نسخه {s.version}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {sets.data?.items.length === 0 && <Empty />}
            </div>
          )}
        </div>

        <div className="card">
          <h2>
            {activeSet ? `آیتم‌های «${activeSet.title}»` : 'یک مجموعه انتخاب کنید'}
          </h2>
          {!selected ? <Empty text="برای مشاهده آیتم‌ها یک مجموعه انتخاب کنید" /> : (
            <>
              {items.isLoading ? <Loading /> : isCourses ? (
                <>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
                    <select value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)}>
                      <option value="">همه گروه‌ها</option>
                      {groupRows.map((g) => <option key={g.id} value={g.title}>{g.title}</option>)}
                    </select>
                    <span className="muted small">{courseRows.length} درس از {allItems.length - groupRows.length}</span>
                  </div>
                  <div className="table-wrap">
                    <table className="tbl">
                      <thead>
                        <tr>
                          <th>کد یکتا</th><th>عنوان درس</th><th>گروه</th><th>ظرفیت برآوردی</th>
                          <th>تعداد واحد نظری</th><th>تعداد واحد عملی</th><th>وضعیت</th><th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {courseRows.map((i) => {
                          const a = (i.attrs || {}) as Record<string, any>
                          return (
                            <tr key={i.id}>
                              <td className="num">{a.unique_code || i.code}</td>
                              <td>{i.title}</td>
                              <td>{a.group || '—'}</td>
                              <td className="num">{a.estimated_capacity ?? '—'}</td>
                              <td className="num">{a.credits_theory ?? '—'}</td>
                              <td className="num">{a.credits_practical ?? '—'}</td>
                              <td><span className="chip">{a.status || i.status}</span></td>
                              <td>{canEdit && <button className="btn sm ghost" onClick={() => setModal({ kind: 'editItem', item: i })}>اصلاح</button>}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                    {courseRows.length === 0 && <Empty />}
                  </div>
                </>
              ) : (
                <div className="table-wrap">
                  <table className="tbl">
                    <thead><tr><th>کد</th><th>عنوان</th><th>ترتیب</th><th>اعتبار</th><th>وضعیت</th><th></th></tr></thead>
                    <tbody>
                      {(items.data?.items || []).map((i) => (
                        <tr key={i.id}>
                          <td className="num">{i.code}</td><td>{i.title}</td><td className="num">{i.sort_order}</td>
                          <td className="small">{i.valid_from || '…'} تا {i.valid_to || '∞'}</td>
                          <td><StatusBadge status={i.status} /></td>
                          <td>{canEdit && <button className="btn sm ghost" onClick={() => setModal({ kind: 'editItem', item: i })}>اصلاح</button>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {(items.data?.items || []).length === 0 && <Empty />}
                </div>
              )}
              {canEdit && <button className="btn" onClick={() => setModal({ kind: 'item' })}>افزودن آیتم</button>}
            </>
          )}
        </div>
      </div>

      {modal?.kind === 'set' && (
        <SimpleModal title="مجموعه مرجع جدید" onClose={() => setModal(null)}
          onSubmit={(v) => run(() => api('/api/v1/reference-sets', { method: 'POST', body: v }))}
          fields={[
            { name: 'code', label: 'کد (لاتین، مثلاً gender)', dir: 'ltr' },
            { name: 'title', label: 'عنوان فارسی' },
            { name: 'description', label: 'توضیح (اختیاری)' },
          ]} />
      )}
      {modal?.kind === 'item' && (
        <SimpleModal title={`آیتم جدید در «${selected}»`} onClose={() => setModal(null)}
          onSubmit={(v) => run(() => api(`/api/v1/reference-sets/${selected}/items`, { method: 'POST', body: v }))}
          fields={[
            { name: 'code', label: 'کد', dir: 'ltr' },
            { name: 'title', label: 'عنوان' },
            { name: 'sort_order', label: 'ترتیب', type: 'number' },
          ]} />
      )}
      {modal?.kind === 'editItem' && modal.item && (
        <SimpleModal title={`اصلاح آیتم «${modal.item.code}»`} onClose={() => setModal(null)}
          onSubmit={(v) => {
            // در درس‌های یکتا، ظرفیت برآوردی داخل attrs ذخیره می‌شود (PATCH کل attrs را جایگزین می‌کند)
            let body: Record<string, unknown> = v
            if (isCourses) {
              const { estimated_capacity: cap, ...rest } = v as Record<string, unknown>
              body = {
                ...rest,
                attrs: {
                  ...(modal.item!.attrs || {}),
                  estimated_capacity: cap === undefined || cap === '' ? null : Number(cap),
                },
              }
            }
            return run(() => api(`/api/v1/reference-sets/${selected}/items/${modal.item!.id}`, { method: 'PATCH', body }))
          }}
          fields={[
            { name: 'title', label: 'عنوان', initial: modal.item.title },
            { name: 'valid_to', label: 'اعتبار تا (YYYY-MM-DD، خالی = بدون پایان)', dir: 'ltr' },
            ...(isCourses ? [{
              name: 'estimated_capacity', label: 'ظرفیت برآوردی (خالی = نامشخص)', type: 'number',
              initial: String(((modal.item.attrs || {}) as Record<string, any>).estimated_capacity ?? ''),
            }] : []),
          ]}
          extraStatusSelect={(v) => run(() => api(`/api/v1/reference-sets/${selected}/items/${modal.item!.id}`, { method: 'PATCH', body: { status: v } }))} />
      )}
    </>
  )
}

function SimpleModal({
  title, fields, onSubmit, onClose, extraStatusSelect,
}: {
  title: string
  fields: Array<{ name: string; label: string; dir?: string; type?: string; initial?: string }>
  onSubmit: (v: Record<string, unknown>) => void
  onClose: () => void
  extraStatusSelect?: (status: string) => void
}) {
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(fields.map((f) => [f.name, f.initial || ''])),
  )
  return (
    <Modal title={title} onClose={onClose}>
      {fields.map((f) => (
        <div key={f.name}>
          <label>{f.label}</label>
          <input
            dir={f.dir}
            type={f.type || 'text'}
            value={values[f.name]}
            onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
          />
        </div>
      ))}
      {extraStatusSelect && (
        <>
          <label>تغییر وضعیت</label>
          <select onChange={(e) => e.target.value && extraStatusSelect(e.target.value)}>
            <option value="">— انتخاب کنید —</option>
            <option value="active">فعال</option>
            <option value="retired">بازنشسته</option>
          </select>
        </>
      )}
      <div className="modal-foot">
        <button className="btn primary" onClick={() => {
          const payload: Record<string, unknown> = {}
          for (const [k, v] of Object.entries(values)) {
            if (v === '') continue
            payload[k] = k === 'sort_order' ? Number(v) : v
          }
          onSubmit(payload)
        }}>ذخیره</button>
        <button className="btn" onClick={onClose}>انصراف</button>
      </div>
    </Modal>
  )
}
