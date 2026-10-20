$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv sync --frozen
} else {
    & python -m uv sync --frozen
}
if ($LASTEXITCODE -ne 0) { throw "Install Python 3.14 and uv, then run this script again. See README.md." }
& .\.venv\Scripts\canvas-bridge.exe init-demo
if ($LASTEXITCODE -ne 0) { throw "Demo initialization failed; existing configuration was preserved." }
Write-Host "Open http://127.0.0.1:8000/settings for fictional connection settings."
Write-Host "Keep this window open. Press Ctrl+C to stop the local server."
& .\.venv\Scripts\canvas-bridge.exe serve
