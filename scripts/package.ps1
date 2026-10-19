# 打包 P4 发布物：构建前端 → PyInstaller onefile sidecar → dist\rpg-sidecar.exe
# 用法：pwsh -File scripts\package.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    Write-Host "== 1/3 构建前端 ==" -ForegroundColor Cyan
    Push-Location (Join-Path $root "ui")
    if (-not (Test-Path "node_modules")) { npm install }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
    Pop-Location

    Write-Host "== 2/3 PyInstaller 打包 sidecar ==" -ForegroundColor Cyan
    python -m PyInstaller scripts/rpg-sidecar.spec --noconfirm `
        --distpath dist --workpath build/pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }

    $exe = Join-Path $root "dist\rpg-sidecar.exe"
    if (-not (Test-Path $exe)) { throw "没有生成 $exe" }

    Write-Host "== 3/3 完成 ==" -ForegroundColor Green
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "产物：$exe （$size MB）"
    Write-Host "启动：pwsh -File scripts\play.ps1" -ForegroundColor DarkGray
} finally {
    Pop-Location
}
