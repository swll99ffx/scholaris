# Start Scholaris: the backend (FastAPI) and frontend (Vite) in two windows.
# Run from the repository root:  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
$root = Split-Path -Parent $PSScriptRoot

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root\backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
)

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root\frontend'; npm run dev"
)

Write-Host "Backend API : http://localhost:8000/docs" -ForegroundColor Green
Write-Host "Web app     : http://localhost:5173" -ForegroundColor Green
Write-Host "On your phone (same Wi-Fi): http://<your-PC-IP>:5173" -ForegroundColor Yellow
