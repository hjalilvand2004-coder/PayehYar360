"""تبدیل تاریخ میلادی به شمسی (جلالی) — الگوریتم استاندارد بدون وابستگی خارجی.

در همه تاریخ‌های نمایشی کاربر (تاریخچه واکشی، همگام‌سازی، لاگ‌ها) استفاده می‌شود.
"""
from __future__ import annotations

from datetime import date, datetime

_G_D_M = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """تبدیل تاریخ میلادی به (سال، ماه، روز) شمسی."""
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) - 80 + gd + _G_D_M[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """تبدیل معکوس — برای اعتبارسنجی و پیمایش بازه‌های شمسی."""
    if jy > 979:
        gy = 1600
        jy -= 979
    else:
        gy = 621
    days = (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + (78 + jd) + ((jm < 7 and (jm - 1) * 31) or ((jm - 7) * 30 + 186))
    gy += 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    if (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0):
        leap = 1
    else:
        leap = 0
    sal_a = [0, 31, 59 + leap, 90 + leap, 120 + leap, 151 + leap, 181 + leap,
             212 + leap, 243 + leap, 273 + leap, 304 + leap, 334 + leap]
    gm = 0
    for i in range(12):
        if sal_a[i] < gd:
            gm = i + 1
    gd -= sal_a[gm - 1]
    return gy, gm, gd


def _parse(value: str | datetime | date) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    s = str(value).strip()
    # فرمت‌های رایج: "2026-11-21T08:30:00" / "2026-11-21 08:30:00" / "2026-11-21"
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:26] if ".%f" in fmt else s[:19] if "%H" in fmt else s[:10], fmt)
        except ValueError:
            continue
    return datetime.strptime(s[:10], "%Y-%m-%d")


def jalali_str(value: str | datetime | date, with_time: bool = False,
               fa_digits: bool = True) -> str:
    """رشته تاریخ شمسی: «۱۴۰۵/۰۹/۰۱» یا با ساعت «۱۴۰۵/۰۹/۰۱ ۱۲:۳۴»."""
    dt = _parse(value)
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    out = f"{jy}/{jm:02d}/{jd:02d}"
    if with_time:
        out += f" {dt.hour:02d}:{dt.minute:02d}"
    return out.translate(FA_DIGITS) if fa_digits else out
