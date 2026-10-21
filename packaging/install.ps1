# CBZ 阅读器 —— 安装脚本（由安装包调用，也可在解压目录里直接右键运行）
# 说明：本文件为 UTF-8 (BOM) 编码，PowerShell 5.1 可正确读取中文。

$ErrorActionPreference = 'Stop'

$payload = Join-Path $PSScriptRoot 'CBZReader'
$dest    = Join-Path $env:LOCALAPPDATA 'CBZReader'
$exe     = Join-Path $dest 'CBZReader.exe'
$version = '1.2.1'

Write-Host ''
Write-Host '  ====================================' -ForegroundColor Cyan
Write-Host "     CBZ 阅读器 安装程序  v$version" -ForegroundColor Cyan
Write-Host '  ====================================' -ForegroundColor Cyan
Write-Host ''

if (-not (Test-Path (Join-Path $payload 'CBZReader.exe'))) {
    Write-Host "  [错误] 找不到程序文件：$payload" -ForegroundColor Red
    Write-Host '  请确认安装包解压完整后重试。' -ForegroundColor Red
    exit 1
}

# 1) 结束正在运行的实例
Get-Process -Name 'CBZReader' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 400

# 2) 复制程序文件（保留已有的 data / cache 用户数据）
Write-Host "  安装目录：$dest"
if (Test-Path $dest) {
    Get-ChildItem -Path $dest -Force |
        Where-Object { $_.Name -notin @('data', 'cache') } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
} else {
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
}
Copy-Item -Path (Join-Path $payload '*') -Destination $dest -Recurse -Force
Copy-Item -Path (Join-Path $PSScriptRoot 'uninstall.ps1') -Destination $dest -Force
Write-Host '  程序文件复制完成' -ForegroundColor Green

# 3) 快捷方式
$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = $ws.CreateShortcut((Join-Path $desktop 'CBZ 阅读器.lnk'))
$lnk.TargetPath       = $exe
$lnk.WorkingDirectory = $dest
$lnk.IconLocation     = "$exe,0"
$lnk.Description      = 'CBZ 漫画阅读器'
$lnk.Save()

$startDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\CBZ 阅读器'
New-Item -ItemType Directory -Path $startDir -Force | Out-Null
$a = $ws.CreateShortcut((Join-Path $startDir 'CBZ 阅读器.lnk'))
$a.TargetPath = $exe; $a.WorkingDirectory = $dest; $a.IconLocation = "$exe,0"; $a.Save()
$b = $ws.CreateShortcut((Join-Path $startDir '卸载 CBZ 阅读器.lnk'))
$b.TargetPath   = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$b.Arguments    = "-NoProfile -ExecutionPolicy Bypass -File `"$dest\uninstall.ps1`""
$b.IconLocation = "$env:SystemRoot\System32\shell32.dll,131"
$b.Save()
Write-Host '  已创建桌面与开始菜单快捷方式' -ForegroundColor Green

# 4) 注册到「应用和功能」
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CBZReader'
New-Item -Path $key -Force | Out-Null
Set-ItemProperty -Path $key -Name 'DisplayName'     -Value 'CBZ 阅读器'
Set-ItemProperty -Path $key -Name 'DisplayVersion'  -Value $version
Set-ItemProperty -Path $key -Name 'Publisher'       -Value 'Asitakawa'
Set-ItemProperty -Path $key -Name 'InstallLocation' -Value $dest
Set-ItemProperty -Path $key -Name 'DisplayIcon'     -Value "$exe,0"
Set-ItemProperty -Path $key -Name 'UninstallString' -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$dest\uninstall.ps1`""
Set-ItemProperty -Path $key -Name 'NoModify' -Value 1 -Type DWord
Set-ItemProperty -Path $key -Name 'NoRepair' -Value 1 -Type DWord
try {
    $mb = [math]::Round(((Get-ChildItem $dest -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum) / 1MB, 1)
    Set-ItemProperty -Path $key -Name 'EstimatedSize' -Value ([int]($mb * 1024)) -Type DWord
} catch { $mb = 0 }
Write-Host '  已注册卸载信息（可在「设置 → 应用」中卸载）' -ForegroundColor Green

Write-Host ''
Write-Host "  安装完成！程序大小约 $mb MB" -ForegroundColor Green
if ($env:CBZ_NO_LAUNCH -eq '1') {
    Write-Host '  已跳过自动启动（--no-launch）' -ForegroundColor Yellow
} else {
    Write-Host '  正在启动 CBZ 阅读器…' -ForegroundColor Green
    Start-Sleep -Milliseconds 800
    Start-Process -FilePath $exe
}
Write-Host ''
exit 0
