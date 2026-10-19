# 一键启动打包版：dist\rpg-sidecar.exe（无需 Python / Node）
param([int]$Port = 8787)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root "dist\rpg-sidecar.exe"
if (-not (Test-Path $exe)) {
    throw "未找到 dist\rpg-sidecar.exe。先运行 scripts\package.ps1 打包。"
}

$env:RPG_PORT = "$Port"
Write-Host "== RPG Framework · 叙事驾驶舱 ==" -ForegroundColor Cyan
Write-Host "启动 $exe （端口 $Port，Ctrl+C 结束）" -ForegroundColor DarkGray
$proc = Start-Process -PassThru -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe)

$url = "http://127.0.0.1:$Port/"
$health = "${url}api/health"
$ok = $false
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { throw "sidecar 提前退出（exit $($proc.ExitCode)），端口 $Port 可能被占用。" }
    try {
        $response = Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) { $ok = $true; break }
    } catch {
        # 还没起来，继续等
    }
}
if (-not $ok) { throw "sidecar 在 60 秒内没有就绪：$health" }

Write-Host "就绪：$url" -ForegroundColor Green
Start-Process $url

try {
    Wait-Process -Id $proc.Id
} finally {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
}
