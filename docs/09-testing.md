# سند ۰۹ — آزمون و پذیرش

## ۱. لایه‌های آزمون (بند ۱۵.۱)

| لایه | ابزار | وضعیت |
|---|---|---|
| Unit — مالکیت، قواعد ادغام، اعتبارسنجی | pytest | ✅ درون سناریوهای یکپارچه پوشش داده شده |
| Integration — PostgreSQL واقعی و RabbitMQ | pytest + docker | ✅ با SQLite در CI/سندباکس؛ با PG فقط `DATABASE_URL` عوض می‌شود؛ RabbitMQ با خالی‌بودن URL شبیه‌سازی قطعی |
| Contract — API و schema رویداد | OpenAPI + قرارداد پیام | ✅ Pydantic v2 در دو سر API و رویداد |
| E2E — گردش‌کار React و SSO آزمایشی | Playwright (فایل‌های سناریو فاز بعد) | ⬜ بررسی دستی با مرورگر انجام شد |
| Security — جداسازی مشتری و مجوز فیلد | pytest | ✅ test_cross_tenant_access_forbidden، غیرمالک، scope سرویس |
| Load — API/Snapshot/Outbox | k6/Locust | ⬜ پیش‌تولید |
| Recovery — قطعی Broker/Worker/DB و بازیابی Backup | pytest + عملیات | ✅ قطع Broker؛ بازیابی Backup مستند |

## ۲. نگاشت سناریوهای الزامی ۱۵.۲ → آزمون‌ها

| سناریو | آزمون (backend/tests/test_scenarios.py) | نتیجه |
|---|---|---|
| اصلاح هم‌زمان یک شخص | test_concurrent_edit_person_version_conflict | یکی موفق؛ دیگری 412 |
| ثبت مجدد با همان کلید | test_idempotency_same_key_no_duplicate_effect | اثر جدید ایجاد نمی‌شود |
| کلید یکسان با ورودی متفاوت | test_idempotency_same_key_different_input_rejected | 409 رد |
| دسترسی مشتری دیگر | test_cross_tenant_access_forbidden | منع دسترسی |
| ویرایش توسط غیرمالک | test_non_owner_edit_rejected_then_change_request_applied | رد → درخواست اصلاح → اعمال پس از تأیید |
| تکرار پیام | test_consumer_dedupes_and_gap_detection | بدون اثر تکراری |
| رویداد قدیمی | test_consumer_dedupes_and_gap_detection | عدم بازنویسی نسخه جدید |
| شکاف نسخه | test_consumer_dedupes_and_gap_detection | بازیابی از مرجع |
| قطعی RabbitMQ | test_rabbitmq_outage_keeps_changes_in_outbox | تغییر در Outbox می‌ماند |
| قطع Worker پس از انتشار | test_outbox_replay_safe_and_worker_marks_pending | تکرار امن |
| Snapshot همراه تغییر هم‌زمان | test_snapshot_no_gap_and_boundary | هیچ تغییر Commit‌شده‌ای از دست نمی‌رود |
| cursor منقضی | test_cursor_flow_and_expiry | 410 + الزام Snapshot مجدد |
| ادغام شخص | test_merge_preserves_alias_history_and_mappings | حفظ alias، سابقه و انتقال نگاشت |
| بازگردانی ادغام | test_merge_reverse_restores_source | فرآیند اصلاحی مستقل |
| غیرفعال‌سازی با نسخه | test_person_deactivation_flow | 412 با نسخه غلط، موفق با نسخه درست |
| قیود شناسه (حوزه صادرکننده) | test_identifier_duplicate_rules | یکتایی فقط در حوزه نوع+صادرکننده |
| قواعد اتصال حساب SSO | test_account_link_rules | یکتایی اتصال فعال + Idempotency |
| منع چرخه سازمانی | test_organizations_cycle_forbidden | 409 ORG_CYCLE |
| سلامت و قرارداد خطا | test_health_and_meta, test_unauthenticated_rejected | 401 با قرارداد |

**نتیجه اجرا: 18 passed**

```bash
cd backend && python -m pytest tests/ -v
```

آزمون Snapshot شامل تراکنش‌هایی است که ترتیب شروع و Commit متفاوت دارند (مرز با قفل شمارنده در همان تراکنش خوانده می‌شود).

## ۳. ردیابی FR

| FR | عنوان | وضعیت |
|---|---|---|
| FR-01..FR-12 | اشخاص تا همگام‌سازی | ✅ MVP کامل |
| FR-13 | تشخیص تکرار و ادغام | ✅ پایه در MVP؛ تکمیل (نمره‌دهی شباهت پیشرفته) بعدی |
| FR-14 | مهاجرت نصب مستقل | ⚙️ ابزار/گزارش پایه (تطبیق)؛ فرآیند کامل مرحله بعد |
| FR-15..FR-17 | مشتری/نصب، ممیزی، پایش | ✅ MVP پایه |

## ۴. معیار اتمام نسخه عملیاتی (بخش ۱۷)

جداسازی مشتری ✅ / کنترل مالکیت و نسخه ✅ / انتشار قابل اعتماد ✅ (Outbox+Confirm+Retry) / Snapshot بدون شکاف ✅ / بازیابی تغییرات ✅ / آزمون Restore — فرآیند مستند؛ اجرای دوره‌ای در تولید نیازمند عملیات.
