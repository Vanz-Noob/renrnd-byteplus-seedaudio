# BytePlus Voice Chat - Stop Script (Windows PowerShell)
# Usage: .\stop.ps1

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  BytePlus Voice Chat - Stopping..." -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# Cari dan kill proses uvicorn
$processes = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -eq "python" -and $_.CommandLine -match "uvicorn"
}

if (-not $processes) {
    # Fallback: cari berdasarkan command line
    $processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match "uvicorn.*server:app"
    } | ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
}

if (-not $processes) {
    Write-Host "Server tidak berjalan." -ForegroundColor Yellow
    exit 0
}

foreach ($proc in $processes) {
    Write-Host "Menghentikan proses PID $($proc.Id)..." -ForegroundColor Yellow
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 2
Write-Host "Server berhenti." -ForegroundColor Green
