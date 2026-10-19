# Windows 一键开发：API(8787) + Vite(5173)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Write-Host "== RPG Framework P0 dev ==" -ForegroundColor Cyan

Push-Location $root
$api = Start-Process -PassThru -NoNewWindow -FilePath "python" `
  -ArgumentList @("-m", "uvicorn", "main:app", "--app-dir", "api", "--port", "8787", "--reload")

Push-Location (Join-Path $root "ui")
$ui = Start-Process -PassThru -NoNewWindow -FilePath "npm.cmd" -ArgumentList @("run", "dev")
Pop-Location

Write-Host "API  http://127.0.0.1:8787/api/health"
Write-Host "UI   http://127.0.0.1:5173"
Write-Host "Ctrl+C 结束" -ForegroundColor DarkGray

try {
  Wait-Process -Id $api.Id
} finally {
  if ($ui -and -not $ui.HasExited) { Stop-Process -Id $ui.Id -Force -ErrorAction SilentlyContinue }
  if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
  Pop-Location
}
