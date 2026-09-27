<#
.SYNOPSIS
  Start llama.cpp for VLM mode on Windows. One engine for all 5 models:
  llama-server in router mode, at most one model loaded at a time.

  NB: kept ASCII-only on purpose. Windows PowerShell 5.1 reads a BOM-less .ps1
  as the system ANSI code page, so Cyrillic here would corrupt the parse.

.EXAMPLE
  .\scripts\vlm\setup.ps1 -Cpu        # docker compose --profile vlm-cpu (default)
  .\scripts\vlm\setup.ps1 -Gpu        # docker compose --profile vlm-gpu
  .\scripts\vlm\setup.ps1 -Native     # no docker: download GGUF to .vlm\ and run llama-server.exe
  .\scripts\vlm\setup.ps1 -Cpu -BackendUrl http://localhost:8756

  $env:VLM_MODELS = "glm-ocr,dots-ocr"  # download only some models (names from scripts\vlm\models.ini)

  Docker modes write nothing: compose already points the backend container at
  http://llama-vlm:8080, and a localhost VLM_ENDPOINT in .env would break it.
  -Native writes .env.vlm with VLM_ENDPOINT for a backend run natively on the host.
  Then calls GET {backend}/models/status.
#>
[CmdletBinding()]
param(
  [switch]$Cpu,
  [switch]$Gpu,
  [switch]$Native,
  [string]$BackendUrl = "http://localhost:8756"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot

if (-not ($Cpu -or $Gpu -or $Native)) { $Cpu = $true }

function Invoke-SelfCheck {
  Write-Host "`n== GET $BackendUrl/models/status =="
  try {
    Invoke-RestMethod -Uri "$BackendUrl/models/status" -TimeoutSec 5 | ConvertTo-Json -Depth 5
  } catch {
    Write-Host "(backend not reachable at $BackendUrl - start it and re-check)"
  }
}

if ($Native) {
  if (-not (Get-Command llama-server -ErrorAction SilentlyContinue)) {
    throw "llama-server.exe not found - install llama.cpp (build b11206 or newer)"
  }
  & python -c "import huggingface_hub, gguf"
  if ($LASTEXITCODE -ne 0) { throw "missing packages: pip install huggingface_hub==2.0.0 gguf==0.19.0" }
  $VlmDir = Join-Path $RepoRoot ".vlm"
  $ModelsDir = Join-Path $VlmDir "models"
  New-Item -ItemType Directory -Force $ModelsDir | Out-Null
  & python scripts\vlm\fetch_models.py $ModelsDir
  if ($LASTEXITCODE -ne 0) { throw "model download failed" }
  # models.ini points at /models (container path) - substitute the local folder.
  $ModelsPrefix = ($ModelsDir -replace '\\', '/') + "/"
  $Preset = Join-Path $VlmDir "models.ini"
  (Get-Content scripts\vlm\models.ini) -replace '= /models/', "= $ModelsPrefix" | Set-Content -Path $Preset -Encoding ascii
  $ModelsMax = if ($env:VLM_MODELS_MAX) { $env:VLM_MODELS_MAX } else { "1" }
  Write-Host "Starting llama-server (router) on :8080..."
  Start-Process -NoNewWindow llama-server -ArgumentList "--models-preset `"$Preset`" --models-max $ModelsMax --host 127.0.0.1 --port 8080"
  Set-Content -Path (Join-Path $RepoRoot ".env.vlm") -Value "VLM_ENDPOINT=http://localhost:8080" -Encoding utf8
  Write-Host "Wrote .env.vlm (VLM_ENDPOINT=http://localhost:8080) for a native backend"
  Invoke-SelfCheck
  return
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "docker not found (Docker Desktop required)"
}

$ComposeProfile = "vlm-cpu"
if ($Gpu) {
  if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    Write-Host "WARNING: nvidia-smi not found - the GPU profile likely will not start"
  }
  $ComposeProfile = "vlm-gpu"
}

& docker compose --profile $ComposeProfile up -d --force-recreate
Write-Host "Waiting for model downloads (init container vlm-models, slow on first run)..."
& docker compose logs -f vlm-models

Write-Host "`nBackend in docker compose already targets llama-vlm by name (http://llama-vlm:8080)."
Write-Host "Do not put VLM_ENDPOINT into .env - a localhost endpoint would break VLM mode."
Invoke-SelfCheck
