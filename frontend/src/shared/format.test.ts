import { describe, expect, it } from 'vitest'
import { fmtDateTime, fmtNumber, fmtSeconds } from './format'

describe('نمایش تاریخ محلی', () => {
  it('تبادل UTC → نمایش تهران', () => {
    const out = fmtDateTime('2026-11-20T09:00:00Z')
    expect(out).toContain('۱۴۰۵') // سال شمسی درست
  })
  it('مقدار خالی', () => {
    expect(fmtDateTime(null)).toBe('—')
  })
})

describe('اعداد فارسی', () => {
  it('اعداد با جداکننده', () => {
    expect(fmtNumber(12345)).toBe('۱۲٬۳۴۵')
    expect(fmtNumber(null)).toBe('—')
  })
  it('بازه‌های زمانی', () => {
    expect(fmtSeconds(30)).toContain('ثانیه')
    expect(fmtSeconds(90)).toContain('دقیقه')
    expect(fmtSeconds(7200)).toContain('ساعت')
  })
})
