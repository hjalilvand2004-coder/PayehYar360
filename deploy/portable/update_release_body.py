"""افزودن یادداشت اصلاح بسته پرتیبل ویندوز به بدنه ریلیز v1.0.13 (بدون تغییر بقیه متن)."""
import json
import os
import sys
import urllib.request

REPO = "hjalilvand2004-coder/PayehYar360"
REL_ID = "456520723"
TOKEN = os.environ["GH_TOKEN"]

NOTE = """
---

## به‌روزرسانی بسته‌های پرتیبل (۲۴ نوامبر ۲۰۲۶ — اصلاح بسته ویندوز)

بسته‌های پرتیبل این ریلیز با ویل‌های کامل بازسازی شدند: `annotated-doc==0.0.4`
(وابستگی اجباری FastAPI 0.128) و `tzdata==2026.1` به بسته اضافه شدند. در بسته ویندوزِ
اولیه، جا افتادن `annotated-doc` هنگام استارت خطای
`ModuleNotFoundError: No module named 'annotated_doc'` می‌داد. اگر بسته ویندوز را
قبل از این تاریخ دانلود کرده‌اید، آن را با نسخه فعلی جایگزین کنید.

- SHA256 ویندوز: `ce774c35d39b3b8637a5dcbdeca5a0f59a63db4f9f8b3fe8894baca529c18ae2`
- SHA256 لینوکس: `0407b9a9dcc8c062df26fa6fd329aec2fb58df516a600db18963f8e2ba60c73c`
"""

req = urllib.request.Request(
    f"https://api.github.com/repos/{REPO}/releases/{REL_ID}",
    headers={"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github+json"},
)
with urllib.request.urlopen(req) as r:
    rel = json.load(r)
body = rel.get("body") or ""
if "به‌روزرسانی بسته‌های پرتیبل" in body:
    print("note already present — skip")
    sys.exit(0)

patch = json.dumps({"body": body + NOTE}).encode()
req = urllib.request.Request(
    f"https://api.github.com/repos/{REPO}/releases/{REL_ID}",
    data=patch, method="PATCH",
    headers={"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github+json",
             "Content-Type": "application/json"},
)
with urllib.request.urlopen(req) as r:
    out = json.load(r)
print("body updated | assets:", [(a["name"], a["state"]) for a in out["assets"]])
