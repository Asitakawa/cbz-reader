"""一键打包：图标 → PyInstaller 冻结 → 组装安装负载 → IExpress 单文件安装包 + 便携版 zip。

用法：
    python packaging/build.py                # 全流程
    python packaging/build.py --no-installer # 只出 dist/CBZReader/ 与 zip
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
PAYLOAD = ROOT / "packaging" / "out" / "payload"
APP_NAME = "CBZReader"
VERSION = "2.4.0"
SETUP_NAME = f"CBZReader_Setup_{VERSION}.exe"

EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtWebSockets", "PySide6.QtWebChannel",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSvgWidgets",
    "tkinter", "unittest", "pydoc", "doctest", "pdb", "lib2to3", "distutils",
]

# ps1 脚本必须带 UTF-8 BOM，PowerShell 5.1 才能正确读取其中的中文
BOM_FILES = ["install.ps1", "uninstall.ps1"]


def run(cmd: list[str], **kw) -> int:
    print("$", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.call(cmd, **kw)


def step(msg: str):
    print(f"\n=== {msg} ===", flush=True)


def ensure_bom() -> None:
    for name in BOM_FILES:
        p = ROOT / "packaging" / name
        raw = p.read_bytes()
        if not raw.startswith(b"\xef\xbb\xbf"):
            p.write_bytes(b"\xef\xbb\xbf" + raw)
            print(f"  已为 {name} 添加 UTF-8 BOM")


def make_icon() -> None:
    step("1/6 生成图标")
    sys.path.insert(0, str(ROOT / "tools"))
    from make_icon import main as icon_main  # type: ignore
    icon_main()


def pyinstaller() -> Path:
    step("2/6 PyInstaller 打包")
    target = DIST / APP_NAME
    if target.exists():
        # 不直接删除旧产物（避免大批量删除），先挪到 build/ 下留底
        stale = BUILD / f"prev_app_{int(time.time())}"
        stale.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(target), str(stale))
            print(f"  旧产物已挪至 {stale}")
        except Exception as e:
            print(f"  挪动旧产物失败：{e!r}")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--windowed", "--name", APP_NAME,
           "--icon", str(ASSETS / "icon.ico"),
           "--distpath", str(DIST), "--workpath", str(BUILD / "work"),
           "--specpath", str(BUILD)]
    for m in EXCLUDES:
        cmd += ["--exclude-module", m]
    cmd.append(str(ROOT / "main.py"))
    if run(cmd) != 0:
        raise SystemExit("PyInstaller 打包失败")
    out = DIST / APP_NAME
    exe = out / f"{APP_NAME}.exe"
    if not exe.exists():
        raise SystemExit(f"未找到产物：{exe}")
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1024 / 1024
    print(f"  产物：{out}  ({size:.1f} MB)")
    return out


def verify_frozen(app_dir: Path) -> bool:
    """在冻结产物上跑 --selftest，确认 PIL/webp/路径等依赖完整。"""
    step("3/6 冻结产物自检")
    exe = app_dir / f"{APP_NAME}.exe"
    # 自检需要书库数据才能验证解码链路，这里带上当前书库索引
    data_src = ROOT / "data"
    (app_dir / "data").mkdir(exist_ok=True)
    for name in ("books.json", "history.json", "config.json"):
        p = data_src / name
        if p.exists():
            shutil.copy2(p, app_dir / "data" / name)
    try:
        subprocess.run([str(exe), "--selftest"], timeout=120,
                       cwd=str(app_dir), check=False)
    except Exception as e:
        print(f"  自检进程异常：{e!r}")
    report = app_dir / "data" / "selftest_report.txt"
    if not report.exists():
        print("  自检未生成报告，视为失败")
        return False
    text = report.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        print("  " + line)
    ok = "result      : PASS" in text
    print("  自检结论：" + ("PASS" if ok else "FAIL"))
    for junk in ("data", "cache", "library"):     # 不外带本机数据与缓存
        shutil.rmtree(app_dir / junk, ignore_errors=True)
    return ok


def assemble_payload(app_dir: Path) -> None:
    step("4/6 组装安装负载")
    PAYLOAD.mkdir(parents=True, exist_ok=True)
    dest_app = PAYLOAD / APP_NAME
    dest_app.mkdir(parents=True, exist_ok=True)
    shutil.copytree(app_dir, dest_app, dirs_exist_ok=True)
    for name in ("install.cmd", "install.ps1", "uninstall.ps1"):
        shutil.copy2(ROOT / "packaging" / name, PAYLOAD / name)
    shutil.copy2(ROOT / "README.md", PAYLOAD / "README.md")
    print(f"  负载目录：{PAYLOAD}")


def make_zip() -> Path:
    step("5/6 便携版 zip")
    zip_path = DIST / f"{APP_NAME}_{VERSION}_portable.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted((DIST / APP_NAME).rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(DIST))
    print(f"  便携版：{zip_path}  ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return zip_path


def make_selfinstaller() -> Path | None:
    """用 PyInstaller onefile 打出「内置完整负载」的单文件安装程序。

    说明：本机没有 Inno Setup / NSIS，7-Zip 也未安装；Windows 自带的 IExpress
    在无头调用下会挂起，因此改用自解包方式，行为等价且完全可测。
    """
    step("6/6 生成单文件安装包（自解包）")
    name = f"{APP_NAME}_Setup_{VERSION}"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
           "--console", "--name", name, "--icon", str(ASSETS / "icon.ico"),
           "--distpath", str(DIST), "--workpath", str(BUILD / "work_setup"),
           "--specpath", str(BUILD),
           "--add-data", f"{PAYLOAD};payload",
           str(ROOT / "packaging" / "selfinstall.py")]
    if run(cmd) != 0:
        print("  单文件安装包构建失败")
        return None
    exe = DIST / f"{name}.exe"
    if not exe.exists():
        print("  未找到安装包产物")
        return None
    size = exe.stat().st_size / 1024 / 1024
    print(f"  安装包：{exe}  ({size:.1f} MB)")

    print("  校验安装包内部负载…")
    try:
        rc = subprocess.call([str(exe), "--dry-run"], timeout=300, cwd=str(DIST))
    except Exception as e:
        print(f"  校验异常：{e!r}")
        rc = -1
    if rc != 0:
        print(f"  安装包自校验失败（返回码 {rc}）")
        return None
    print("  安装包自校验通过")
    return exe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-installer", action="store_true", help="跳过 IExpress 安装包")
    args = ap.parse_args()

    ensure_bom()
    make_icon()
    app_dir = pyinstaller()
    ok = verify_frozen(app_dir)
    assemble_payload(app_dir)
    zip_path = make_zip()
    setup = None if args.no_installer else make_selfinstaller()

    step("完成")
    print(f"  程序目录：{app_dir}")
    print(f"  便携版  ：{zip_path}")
    if setup:
        print(f"  安装包  ：{setup}")
    print(f"  冻结自检：{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
