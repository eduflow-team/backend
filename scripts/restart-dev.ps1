# EduFlow local dev: restart API container (bind-mount + uvicorn --reload).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

docker compose run --rm backend alembic upgrade heads
docker compose restart backend
docker compose ps backend

Write-Host "Backend: http://localhost:8000/docs"
