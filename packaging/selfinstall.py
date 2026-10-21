"""单文件安装程序：内置完整应用负载，运行后调用 install.ps1 完成安装。

用法（用户双击即为普通安装）：
    CBZReader_Setup_1.0.0.exe              安装并启动
    CBZReader_Setup_1.0.0.exe --no-launch  安装但不自动启动
    CBZReader_Setup_1.0.0.exe --dry-run    只校验内部负载完整性，不做任何安装
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

VERSION = "1.3.0"


def bundle_root() -> Path:
    """PyInstaller 解包目录（开发态回退到本文件所在目录）。"""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def main() -> int:
    dry = "--dry-run" in sys.argv
    no_launch = "--no-launch" in sys.argv
    payload = bundle_root() / "payload"
    script = payload / "install.ps1"
    app_exe = payload / "CBZReader" / "CBZReader.exe"

    print("=" * 50)
    print(f"      CBZ 阅读器  安装程序   v{VERSION}")
    print("=" * 50)

    if dry:
        files = [p for p in payload.rglob("*") if p.is_file()]
        size = sum(p.stat().st_size for p in files) / 1024 / 1024
        print(f"[dry-run] 负载目录：{payload}")
        print(f"[dry-run] 文件数 {len(files)}，总大小 {size:.1f} MB")
        print(f"[dry-run] 主程序存在：{app_exe.exists()}")
        print(f"[dry-run] 安装脚本存在：{script.exists()}")
        print(f"[dry-run] 卸载脚本存在：{(payload / 'uninstall.ps1').exists()}")
        print("[dry-run] 结论：" + ("PASS" if app_exe.exists() and script.exists() else "FAIL"))
        return 0 if app_exe.exists() and script.exists() else 1

    if not script.exists():
        print(f"[错误] 安装负载缺失：{script}")
        return 1

    ps = Path(os.environ.get("SystemRoot", r"C:\Windows")) / \
        "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not ps.exists():
        ps = Path("powershell.exe")

    env = dict(os.environ)
    if no_launch:
        env["CBZ_NO_LAUNCH"] = "1"
    cmd = [str(ps), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    rc = subprocess.call(cmd, env=env)
    if rc != 0:
        print(f"\n[错误] 安装脚本返回码 {rc}")
        try:
            input("按回车键退出…")
        except Exception:
            pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
