# سند ۰۵ — رویدادها و همگام‌سازی

## ۱. رویدادها (بخش ۹.۱)

`PersonCreated`, `PersonUpdated`, `PersonDeactivated`, `PersonMerged`, `PersonMergeCorrected`, `OrganizationUpdated`, `ReferenceItemUpdated`, `IdentityAccountLinked`, `IdentifierMappingUpdated`

## ۲. قرارداد پیام (schemaVersion=1)

```json
{
  "eventId": "uuid",
  "eventType": "PersonUpdated",
  "schemaVersion": 1,
  "tenantId": "uuid",
  "sourceSystem": "shared-core",
  "entityType": "person",
  "entityId": "uuid",
  "entityVersion": 13,
  "occurredAt": "2026-11-20T09:00:00Z",
  "correlationId": "uuid",
  "payload": { "changedFields": ["display_name"], "display_name": "نام اصلاح‌شده" }
}
```

رویداد تغییر جزئی فقط با داشتن نسخه قبلی قابل اعمال است؛ در شکاف نسخه، مصرف‌کننده باید نمای معتبر را از API بگیرد (`GET /persons/{id}`).

## ۳. RabbitMQ (بند ۹.۳)

- Exchange: `shared-core.events` از نوع **topic**؛ routing key: `tenant.<tenantId>.<entity>.<event>`
- پیام **persistent**؛ Publisher Confirm فعال؛ پیام unroutable به‌صورت شکست ثبت و بعداً دوباره تلاش می‌شود
- صف durable مجزا برای هر نصب/گروه مصرف (سمت مصرف‌کننده)
- Retry با تأخیر نمایی (حداکثر ۳۰۰ ثانیه) و سقف تلاش → پس از سقف، وضعیت `failed` برای بررسی عملیاتی
- Publisher Confirm فقط دریافت توسط Broker را تضمین می‌کند، نه پردازش نهایی

## ۴. Outbox (بند ۹.۴)

```
BEGIN
  تغییر داده اصلی
  ثبت ChangeLog (seq با قفل ردیف شمارنده مشتری)
  ثبت Outbox
  ثبت ممیزی
COMMIT
Worker → انتشار → دریافت Confirm → ثبت published_at
```

تضمین طراحی: **تحویل حداقل یک‌بار + اثر تکرارناپذیر در مصرف‌کننده** (با eventId در Inbox) — نه Exactly-once سراسری. Worker با نشست و batch مستقل کار می‌کند؛ قطع RabbitMQ فقط انتشار را به تعویق می‌اندازد.

## ۵. تاریخچه تغییر بدون شکاف (بند ۹.۵)

- استفاده از MAX(id) یک Sequence برای cursor کافی نیست (Commit خارج از ترتیب تخصیص).
- **پیاده‌سازی:** شمارنده ترتیبی هر مشتری (`tenant_change_counters`) با `SELECT ... FOR UPDATE` در همان تراکنش تغییر تخصیص می‌یابد → شماره seq و ترتیب Commit هم‌راستا می‌مانند و داده + ChangeLog + مرز Snapshot هماهنگ می‌شوند.
- **Snapshot:** کار تولید ابتدا شمارنده را قفل می‌کند، مرز (`boundarySeq`) را می‌خواند و سپس در همان تراکنش داده را می‌خواند؛ هیچ تغییر Commit‌شده‌ای از قلم نمی‌افتد. خروجی در فایل JSON materialize می‌شود و همه صفحه‌ها از یک مرز می‌خوانند. در مقیاس بالاتر، مهاجرت به CDC با موقعیت Commit معتبر (ADR-08).

## ۶. فرآیند مصرف (بند ۹.۶)

```
دریافت Snapshot + cursor
→ ذخیره نسخه محلی
→ دریافت تغییرات پس از cursor (GET /sync/changes)
→ پردازش تراکنشی + خنثی‌سازی تکرار (Inbox/eventId)
→ ثبت checkpoint (POST /sync/checkpoints)
→ ادامه مصرف رویداد از صف
→ تطبیق دوره‌ای (POST /sync/reconciliation/jobs)
```

- Cursor با مشتری، نصب و دامنه مجوز مرتبط است؛ با تغییر دامنه اشتراک، Snapshot جدید لازم است.
- نگهداری ChangeLog: عمق `CHANGE_RETENTION_MIN` (پیش‌فرض ۵۰٬۰۰۰ تغییر)؛ درخواست cursor قدیمی‌تر → **410 CURSOR_EXPIRED** و الزام Snapshot مجدد.

## ۷. نمونه مصرف‌کننده

`examples/sample_consumer/consumer.py`: Inbox + نسخه محلی + قواعد (تکرار پیام → بی‌اثر؛ رویداد قدیمی → بی‌اثر؛ شکاف نسخه → fetch از مرجع؛ checkpoint). اجرا:

```bash
python examples/sample_consumer/consumer.py --core http://188.212.96.235:8094 \
  --tenant demo --installation edu-main --user consumer-svc --scopes sync
```
