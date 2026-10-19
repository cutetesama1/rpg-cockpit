# 桌面版冒烟测试：验证「窗口 → sidecar 启动 → 健康检查 → 关窗 → 进程树回收」。
# 用法：pwsh -File scripts\smoke-desktop.ps1            （或 powershell -ExecutionPolicy Bypass -File ...）
#       pwsh -File scripts\smoke-desktop.ps1 -Keep      （保留临时目录与 stderr 日志）
# 说明：会把 rpg-cockpit.exe + dist\rpg-sidecar.exe 复制到 %TEMP% 下的普通目录再运行，
#       因为本仓库所在目录可能带低完整性/拒绝 ACE，PyInstaller onefile 在那里会被系统拒绝。
param([switch]$Keep)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root "src-tauri\target\release\rpg-cockpit.exe"
$sidecar = Join-Path $root "dist\rpg-sidecar.exe"

foreach ($path in @($exe, $sidecar)) {
    if (-not (Test-Path $path)) { throw "缺少 $path：先运行 scripts\package-desktop.ps1" }
}

$dir = Join-Path $env:TEMP ("rpg-cockpit-smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $dir | Out-Null
Copy-Item $exe (Join-Path $dir "rpg-cockpit.exe")
Copy-Item $sidecar (Join-Path $dir "rpg-sidecar.exe")

$started = Get-Date
$app = Start-Process -PassThru -FilePath (Join-Path $dir "rpg-cockpit.exe") -WorkingDirectory $dir `
    -RedirectStandardOutput (Join-Path $dir "stdout.log") -RedirectStandardError (Join-Path $dir "stderr.log")
Write-Host "启动 rpg-cockpit.exe（pid $($app.Id)），工作目录 $dir"

$failed = $false
try {
    $port = $null
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        $app.Refresh()
        if ($app.HasExited) { break }
        $sidecarIds = @(Get-Process rpg-sidecar -ErrorAction SilentlyContinue |
            Where-Object { $_.StartTime -ge $started } | Select-Object -ExpandProperty Id)
        if ($sidecarIds.Count -gt 0) {
            $listen = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
                Where-Object { $sidecarIds -contains $_.OwningProcess -and $_.LocalAddress -eq "127.0.0.1" } |
                Select-Object -First 1
            if ($listen) { $port = $listen.LocalPort; break }
        }
        Start-Sleep -Milliseconds 300
    }
    if (-not $port) {
        $err = Get-Content (Join-Path $dir "stderr.log") -Encoding UTF8 -ErrorAction SilentlyContinue
        throw ("60 秒内没等到 sidecar API 端口。stderr:`n" + ($err -join "`n"))
    }

    # PowerShell 5.1 的 Invoke-RestMethod 按 ANSI 解码 UTF-8 会乱码，这里手动按 UTF-8 解。
    $resp = Invoke-WebRequest "http://127.0.0.1:$port/api/health" -UseBasicParsing -TimeoutSec 10
    $stream = $resp.RawContentStream
    $stream.Position = 0
    $health = [Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
    Write-Host ("健康检查 OK：port=$port version=$($health.version) pack=$($health.pack_title) resumed=$($health.resumed)")

    $index = Invoke-WebRequest "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 10
    Write-Host ("首页 OK：HTTP $($index.StatusCode)，$($index.Content.Length) 字节")

    $saves = Invoke-WebRequest "http://127.0.0.1:$port/api/saves" -UseBasicParsing -TimeoutSec 10
    Write-Host ("存档接口 OK：HTTP $($saves.StatusCode)")
}
catch {
    Write-Host ("FAIL：" + $_.Exception.Message) -ForegroundColor Red
    $failed = $true
}
finally {
    $app.Refresh()
    if (-not $app.HasExited) {
        # 关闭主窗口 = 用户点右上角 ×，走 RunEvent::Exit → 杀 sidecar 进程树。
        $null = $app.CloseMainWindow()
        if (-not $app.WaitForExit(20000)) {
            Write-Host "窗口 20 秒内没有退出，强制结束。" -ForegroundColor Yellow
            Stop-Process -Id $app.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Milliseconds 1500
    $left = @(Get-Process rpg-sidecar -ErrorAction SilentlyContinue |
        Where-Object { $_.StartTime -ge $started })
    if ($left.Count -gt 0) {
        Write-Host ("FAIL：关窗后仍有 sidecar 残留进程 " + ($left | ForEach-Object { $_.Id } -join ",")) -ForegroundColor Red
        $left | Stop-Process -Force -ErrorAction SilentlyContinue
        $failed = $true
    }
    else {
        Write-Host "退出清理 OK：窗口关闭后没有残留 sidecar 进程" -ForegroundColor Green
    }
    if ($Keep) { Write-Host "保留目录：$dir" }
    else { Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue }
}

if ($failed) { exit 1 }
Write-Host "桌面版冒烟测试通过" -ForegroundColor Green
exit 0
