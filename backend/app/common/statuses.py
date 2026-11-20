"""کلاس‌های وضعیت مشترک (به‌صورت رشته — سازگار بین دیتابیس‌ها)."""
PERSON_ACTIVE = "active"
PERSON_INACTIVE = "inactive"
PERSON_MERGED = "merged"

LINK_ACTIVE = "active"
LINK_REVOKED = "revoked"

POLICY_OPEN = "open"
POLICY_APPROVED = "approved"
POLICY_REJECTED = "rejected"
POLICY_CANCELLED = "cancelled"

CASE_OPEN = "open"
CASE_DECIDED = "decided"
CASE_CANCELLED = "cancelled"

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"
JOB_EXPIRED = "expired"

OUTBOX_PENDING = "pending"
OUTBOX_PUBLISHED = "published"
OUTBOX_FAILED = "failed"
