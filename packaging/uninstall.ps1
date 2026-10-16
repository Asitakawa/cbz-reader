# CBZ 阅读器 —— 卸载脚本（UTF-8 BOM 编码）

$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms

$dest = Join-Path $env:LOCALAPPDATA 'CBZReader'

$ans = [System.Windows.Forms.MessageBox]::Show(
    "确定要卸载 CBZ 阅读器吗？`n`n【是】连书架索引与封面缓存一起删除`n【否】保留 data 与 cache 目录（书架记录保留，便于日后重装）",
    '卸载 CBZ 阅读器', 'YesNoCancel', 'Question')

if ($ans -eq 'Cancel') { exit }

Get-Process -Name 'CBZReader' | Stop-Process -Force
Start-Sleep -Milliseconds 500

if ($ans -eq 'Yes') {
    Remove-Item -Path $dest -Recurse -Force
} else {
    Get-ChildItem -Path $dest -Force |
        Where-Object { $_.Name -notin @('data', 'cache') } |
        Remove-Item -Recurse -Force
}

Remove-Item -Path (Join-Path ([Environment]::GetFolderPath('Desktop')) 'CBZ 阅读器.lnk') -Force
Remove-Item -Path (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\CBZ 阅读器') -Recurse -Force
Remove-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CBZReader' -Recurse -Force

[System.Windows.Forms.MessageBox]::Show('CBZ 阅读器 已卸载。', '卸载完成') | Out-Null
