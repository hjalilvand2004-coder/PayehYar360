"""چکر بستار وابستگی‌های بسته پرتیبل ویندوز — از METADATA خود ویل‌ها.

گراف وابستگی از ویل‌های /tmp/portable/wheels ساخته و برای محیط ویندوز/پایتون 3.12
ارزیابی می‌شود؛ هر وابستگیِ لازمِ بدون ویل یا با نسخه ناسازگار → خطا.
(باگ واقعی: annotated-doc جا افتاده بود → ModuleNotFoundError هنگام استارت روی دستگاه کاربر)
"""
from __future__ import annotations

import email.parser
import sys
from pathlib import Path

from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

WHEELS = Path("/tmp/portable/wheels")

# اکستراسی که واقعاً نصب/پین شده‌اند (其余 اکستراس‌ها نصب نمی‌شوند)
INSTALLED_EXTRAS: dict[str, set[str]] = {
    "uvicorn": {"standard"},       # httptools/watchfiles/websockets/python-dotenv/PyYAML/colorama پین شده‌اند
    "pyjwt": {"crypto"},           # cryptography پین شده
    "psycopg": {"binary"},         # psycopg-binary پین شده
}

# ریشه‌ها: pinهای download_win_wheels + ماژول‌های لیست پیش‌بررسی start.bat
sys.path.insert(0, str(Path(__file__).parent))
from download_win_wheels import PINS  # noqa: E402

ROOTS = list(PINS)

WIN_ENV = {
    "python_version": "3.12",
    "python_full_version": "3.12.10",
    "sys_platform": "win32",
    "platform_system": "Windows",
    "platform_machine": "AMD64",
    "platform_python_implementation": "CPython",
    "implementation_name": "cpython",
    "os_name": "nt",
    "implementation_version": "3.12.10",
    "platform_release": "10",
    "platform_version": "10.0.19045",
}


def canonical(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def load_wheels() -> dict[str, dict]:
    """نام کانونی → {version, requires:[(req, extras_of_this_dist)], provides}"""
    out: dict[str, dict] = {}
    for whl in sorted(WHEELS.glob("*.whl")):
        name, version = whl.name.split("-")[0], whl.name.split("-")[1]
        meta_name = f"{name}-{version}.dist-info/METADATA"
        with __import__("zipfile").ZipFile(whl) as z:
            raw = z.read(meta_name).decode("utf-8", "replace")
        msg = email.parser.Parser().parsestr(raw)
        dist = canonical(msg["Name"] or name)
        out[dist] = {
            "version": msg["Version"] or version,
            "provides_extras": {canonical(e) for e in (msg.get_all("Provides-Extra") or [])},
            "requires": [str(r) for r in msg.get_all("Requires-Dist") or []],
        }
    return out


def main() -> int:
    wheels = load_wheels()
    print(f"wheels present: {len(wheels)}")
    seen: set[str] = set()
    missing: list[tuple[str, str]] = []       # (نیاز از، نام بسته)
    conflicts: list[str] = []

    def visit(dist: str, via: str) -> None:
        if dist in seen:
            return
        seen.add(dist)
        info = wheels.get(dist)
        if info is None:
            missing.append((via, dist))
            return
        for line in info["requires"]:
            req = Requirement(line)
            extras_declared = info["provides_extras"]
            ok = False
            if req.marker is None:
                ok = True
            else:
                # پایه بدون extra یا با اکستراس‌هایی که واقعاً نصب شده‌اند
                envs = [dict(WIN_ENV, extra="")] + [
                    dict(WIN_ENV, extra=e) for e in INSTALLED_EXTRAS.get(dist, set())
                ]
                ok = any(req.marker.evaluate(e) for e in envs)
                # اکستراس اعلام‌شده ولی نصب‌نشده → صرف‌نظر (اختیاری است)
                if not ok and req.marker and "extra" in str(req.marker):
                    pass
            if not ok:
                continue
            target = canonical(req.name)
            found = wheels.get(target)
            if found is None:
                missing.append((f"{dist} {info['version']}", target))
                continue
            if req.specifier and not SpecifierSet(str(req.specifier)).contains(
                    Version(found["version"]), prereleases=True):
                conflicts.append(
                    f"{dist} {info['version']} → {target}: لازم {req.specifier}، موجود {found['version']}")
            visit(target, dist)

    for root in ROOTS:
        visit(canonical(root.split("==")[0]), "ROOT")

    if missing:
        print("\nMISSING (required, no wheel):")
        for via, pkg in sorted(set(missing)):
            print(f"  - {pkg}  (نیازِ {via})")
    if conflicts:
        print("\nVERSION CONFLICTS:")
        for c in sorted(set(conflicts)):
            print(f"  - {c}")
    if not missing and not conflicts:
        print("OK — بستار وابستگی‌ها کامل است؛ هیچ ماژولِ لازمِ بدون ویل وجود ندارد.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
