# BytePlus Voice Chat - Start Script (Windows PowerShell)
# Usage: .\start.ps1

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  BytePlus Voice Chat v2.0 - Starting..." -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# Cek .env
if (-not (Test-Path .env)) {
    Write-Host "[ERROR] File .env tidak ditemukan!" -ForegroundColor Red
    Write-Host "        Jalankan: copy .env.example .env"
    Write-Host "        Lalu isi API keys Anda."
    exit 1
}

# Cek Python
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $pythonCmd) {
    Write-Host "[ERROR] Python tidak ditemukan. Install: https://python.org" -ForegroundColor Red
    exit 1
}

# Install dependencies
Write-Host "[1/2] Install dependencies..." -ForegroundColor Yellow
& python -m pip install -q -r requirements.txt

# Tentukan port
$port = if ($env:PORT) { $env:PORT } else { "8000" }
$host_ = if ($env:HOST) { $env:HOST } else { "0.0.0.0" }

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Server: http://localhost:$port" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""

# Start server
& python -m uvicorn server:app --host $host_ --port $port
