// نمایش تاریخ محلی (تهران) — تبادل زمان با بک‌اند در UTC انجام می‌شود
const dtf = new Intl.DateTimeFormat('fa-IR', {
  dateStyle: 'short',
  timeStyle: 'short',
  timeZone: 'Asia/Tehran',
})

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return dtf.format(new Date(iso))
  } catch {
    return iso
  }
}

export function fmtNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return new Intl.NumberFormat('fa-IR').format(n)
}

export function fmtSeconds(s: number | null | undefined): string {
  if (s === null || s === undefined) return '—'
  if (s < 60) return `${fmtNumber(Math.round(s))} ثانیه`
  if (s < 3600) return `${fmtNumber(Math.round(s / 60))} دقیقه`
  return `${fmtNumber(Math.round(s / 3600))} ساعت`
}
