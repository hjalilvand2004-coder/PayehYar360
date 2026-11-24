#!/usr/bin/env bash
# آپلود بسته‌های پرتیبل v1.0.13 (اصلاح annotated-doc) روی ریلیز موجود GitHub
# توکن فقط از متغیر محیطی GH_TOKEN خوانده می‌شود؛ در هیچ فایلی ذخیره نمی‌شود.
set -euo pipefail
TOKEN="${GH_TOKEN:?GH_TOKEN is required}"
REPO="hjalilvand2004-coder/PayehYar360"
REL_ID="456520723"
DL="/home/z/my-project/download"

UP=$(curl -sS -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/$REPO/releases/$REL_ID" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['upload_url'].split('{')[0])")
echo "upload_url ok"

for f in "PayehYar360-Portable-Linux-v1.0.13.zip" "PayehYar360-Portable-Windows-v1.0.13.zip"; do
  echo "uploading $f ..."
  curl -sS -X POST \
    -H "Authorization: token $TOKEN" \
    -H "Content-Type: application/zip" \
    -H "Content-Length: $(stat -c%s "$DL/$f")" \
    --data-binary @"$DL/$f" \
    "$UP?name=$f" -o /tmp/upload_result.json
  python3 -c "
import json
d = json.load(open('/tmp/upload_result.json'))
print('  ->', d.get('name'), '| size:', d.get('size'), '| state:', d.get('state'))
assert d.get('state') == 'uploaded', d"
done
echo "ALL ASSETS UPLOADED"
