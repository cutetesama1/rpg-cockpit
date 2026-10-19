# 打包桌面版：构建前端 + Python sidecar → Tauri 外壳 → NSIS 安装包
# 用法：pwsh -File scripts\package-desktop.ps1
# 产物：src-tauri\target\release\bundle\nsis\*.exe（安装包）
#       src-tauri\target\release\rpg-cockpit.exe（免安装，需同目录有 rpg-sidecar.exe 资源）
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

# rushup 默认装到 %USERPROFILE%\.cargo\bin；新开的 shell 可能还没刷新 PATH。
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if ((Test-Path $cargoBin) -and ($env:PATH -notlike "*$cargoBin*")) {
    $env:PATH = "$cargoBin;$env:PATH"
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "找不到 cargo：先安装 rustup（https://rustup.rs），或把 $cargoBin 加进 PATH"
}

Push-Location $root
try {
    Write-Host "== 1/3 构建前端 + sidecar ==" -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "package.ps1")
    if ($LASTEXITCODE -ne 0) { throw "package.ps1 失败" }

    Write-Host "== 2/3 安装 Tauri CLI 依赖 ==" -ForegroundColor Cyan
    if (-not (Test-Path "node_modules\@tauri-apps\cli")) {
        npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install 失败" }
    }

    Write-Host "== 3/3 Tauri 打包（NSIS）==" -ForegroundColor Cyan
    & node ".\node_modules\@tauri-apps\cli\tauri.js" build
    if ($LASTEXITCODE -ne 0) { throw "Tauri 打包失败" }

    Write-Host "== 完成 ==" -ForegroundColor Green
    Get-ChildItem "src-tauri\target\release\bundle\nsis" -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Host ("安装包：" + $_.FullName + "（" + [math]::Round($_.Length / 1MB, 1) + " MB）") }
    $exe = "src-tauri\target\release\rpg-cockpit.exe"
    if (Test-Path $exe) {
        Write-Host ("主程序：" + (Resolve-Path $exe) + "（" + [math]::Round((Get-Item $exe).Length / 1MB, 1) + " MB）")
    }
} finally {
    Pop-Location
}
