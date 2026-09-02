<#
.SYNOPSIS
  Provision the VLM-mode companion services on Windows.

  NB: kept ASCII-only on purpose. Windows PowerShell 5.1 reads a BOM-less .ps1
  as the system ANSI code page, so Cyrillic here would corrupt the parse.

.EXAMPLE
  .\scripts\vlm\setup.ps1 -Cpu        # Ollama + llama-server via docker compose
  .\scripts\vlm\setup.ps1 -Gpu        # + vLLM for dots.ocr / Unlimited-OCR
  .\scripts\vlm\setup.ps1 -Native     # no docker: ollama pull + llama-server.exe
  .\scripts\vlm\setup.ps1 -Cpu -BackendUrl http://localhost:8756

  Writes .env.vlm with the *_ENDPOINT lines and calls GET {backend}/models/status.
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

function Write-EnvFile {
  param([bool]$IncludeGpu)
  $lines = @(
    "GLM_OCR_ENDPOINT=http://localhost:11434",
    "PADDLEOCR_VL_ENDPOINT=http://localhost:11434",
    "HUNYUAN_OCR_ENDPOINT=http://localhost:8081"
  )
  if ($IncludeGpu) {
    $lines += "DOTS_OCR_ENDPOINT=http://localhost:8082"
    $lines += "UNLIMITED_OCR_ENDPOINT=http://localhost:8083"
  }
  $path = Join-Path $RepoRoot ".env.vlm"
  Set-Content -Path $path -Value $lines -Encoding utf8
  Write-Host "Wrote $path"
  Get-Content $path | ForEach-Object { Write-Host "  $_" }
}

function Invoke-SelfCheck {
  Write-Host "`n== GET $BackendUrl/models/status =="
  try {
    Invoke-RestMethod -Uri "$BackendUrl/models/status" -TimeoutSec 5 | ConvertTo-Json -Depth 5
  } catch {
    Write-Host "(backend not reachable at $BackendUrl - start it and re-check)"
  }
}

if ($Native) {
  if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "ollama not found - install from https://ollama.com/download/windows"
  }
  ollama pull glm-ocr
  ollama pull MedAIBase/PaddleOCR-VL:0.9b
  if (Get-Command llama-server -ErrorAction SilentlyContinue) {
    Write-Host "Starting llama-server (HunyuanOCR) on :8081..."
    Start-Process -NoNewWindow llama-server -ArgumentList "-hf ggml-org/HunyuanOCR-GGUF --host 0.0.0.0 --port 8081 -c 16384"
  } else {
    Write-Host "llama-server.exe not found - install llama.cpp and run manually:"
    Write-Host "  llama-server -hf ggml-org/HunyuanOCR-GGUF --port 8081 -c 16384"
  }
  Write-EnvFile -IncludeGpu:$false
  Invoke-SelfCheck
  return
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "docker not found (Docker Desktop required)"
}

$composeProfiles = @("--profile", "vlm-cpu")
if ($Gpu) {
  if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    Write-Host "WARNING: nvidia-smi not found - the GPU profile likely will not start"
  }
  $composeProfiles += @("--profile", "vlm-gpu")
}

& docker compose @composeProfiles up -d --force-recreate
Write-Host "Waiting for Ollama model downloads (slow on first run)..."
& docker compose logs -f ollama-pull

Write-EnvFile -IncludeGpu:$Gpu
Invoke-SelfCheck
