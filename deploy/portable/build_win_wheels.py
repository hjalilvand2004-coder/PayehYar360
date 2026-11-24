"""حل کامل زنجیره وابستگی‌های runtime برای ویندوز و دانلود ویل‌های win_amd64.

روش: BFS روی importlib.metadata از ریشه‌های requirements.txt با ارزیابی
environment markerها برای win_amd64/CPython3.12 (نه لیست دستی — درسِ خطای
annotated_doc). سپس هر dist با نسخه محیطِ آزم‌شده دانلود می‌شود (--no-deps).
"""
from __future__ import annotations

import importlib.metadata as md
import subprocess
import sys
from pathlib import Path

from packaging.markers import Marker
from packaging.requirements import Requirement

WHEELS = Path("/tmp/portable/wheels")
REQ = Path("/home/z/my-project/download/student360-shared-core/backend/requirements.txt")

WIN_ENV = {
    "os_name": "nt",
    "sys_platform": "win32",
    "platform_system": "Windows",
    "platform_machine": "AMD64",
    "platform_python_implementation": "CPython",
    "implementation_name": "cpython",
    "python_version": "3.12",
    "python_full_version": "3.12.10",
    "implementation_version": "3.12.10",
}

def canon(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def resolve_roots() -> list[Requirement]:
    roots = []
    for line in REQ.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = line.split("#")[0].strip()
        if line:
            roots.append(Requirement(line))
    return roots


def req_active(req: Requirement, extras: frozenset[str]) -> bool:
    if req.marker is None:
        return True
    for extra in extras | {""}:
        env = dict(WIN_ENV, extra=extra)
        if req.marker.evaluate(env):
            return True
    return False


def resolve_closure() -> dict[str, str]:
    """نام یکتای کانونی → نسخه نصب‌شده در محیط آزم‌شده."""
    seen: dict[str, frozenset[str]] = {}
    queue: list[Requirement] = resolve_roots()
    result: dict[str, str] = {}
    skipped: list[str] = []
    while queue:
        req = queue.pop()
        cname = canon(req.name)
        extras = frozenset(e for e in (req.extras or set()))
        if cname in seen:
            if extras - seen[cname]:
                new_ex = seen[cname] | extras
                seen[cname] = new_ex
                _push_deps(req.name, new_ex, queue, result, skipped)
            continue
        try:
            version = md.version(cname)
        except md.PackageNotFoundError:
            skipped.append(f"{req.name} (محیط نصب ندارد)")
            continue
        seen[cname] = extras
        result[cname] = version
        _push_deps(req.name, extras, queue, result, skipped)
    if skipped:
        print("skipped:", skipped)
    return result


def _push_deps(name: str, extras: frozenset[str], queue: list, result: dict, skipped: list) -> None:
    try:
        dist = md.distribution(canon(name))
    except md.PackageNotFoundError:
        return
    for raw in dist.requires or []:
        try:
            req = Requirement(raw)
        except Exception:
            continue
        if not req_active(req, extras):
            continue
        queue.append(req)


def download(pins: dict[str, str]) -> int:
    # ایمنی win-only: colorama در محیط لینوکس نصب نیست ولی مسیرهای win32 یوویکورن از آن استفاده می‌کنند
    pins = dict(pins, **{"colorama": "0.4.6"})
    if WHEELS.exists():
        for f in WHEELS.iterdir():
            f.unlink()
    else:
        WHEELS.mkdir(parents=True)
    failed: list[str] = []
    for cname, version in sorted(pins.items()):
        pin = f"{cname}=={version}"
        r = subprocess.run(
            [sys.executable, "-m", "pip", "download", "-q", "--platform", "win_amd64",
             "--only-binary=:all:", "--no-deps", "-d", str(WHEELS), pin],
            capture_output=True, text=True)
        if r.returncode != 0:
            failed.append(pin)
            print(f"FAIL {pin}: {r.stderr.strip()[-150:]}")
    seen: dict[str, str] = {}
    dupes: list[str] = []
    whls = sorted(WHEELS.glob("*.whl"))
    for whl in whls:
        c = canon(whl.name.split("-")[0])
        if c in seen:
            dupes.append(f"{seen[c]} + {whl.name}")
        seen[c] = whl.name
    print(f"\nwheels: {len(whls)} | closure: {len(pins)} | dupes: {dupes or 'none'}")
    for c in sorted(seen):
        print(" ", c)
    if dupes or failed:
        return 1
    # هر عضو closure باید ویل داشته باشد (به‌جز linux-only ها که در failed می‌آیند)
    missing = set(pins) - set(seen)
    if missing:
        print("MISSING wheels for closure members:", missing)
        return 1
    print("OK — closure complete")
    return 0


if __name__ == "__main__":
    closure = resolve_closure()
    print(f"closure size: {len(closure)}")
    sys.exit(download(closure))
