# Screencast for the YouTube API Services audit (Missao em Cortes).
#
# BEFORE recording (local only, nothing goes to YouTube):
#   powershell -ExecutionPolicy Bypass -File scripts\demo_auditoria.ps1 -Preparar [-Stem <stem>] [-Bloco N] [-Segundos 15]
#
# WHILE recording (pauses before every step; the upload only happens after you press Enter):
#   powershell -ExecutionPolicy Bypass -File scripts\demo_auditoria.ps1 [-Agendar]
#
#   -Agendar  also sends status.publishAt in the test upload (default: private, no publishAt).
#
# The file is ASCII on purpose (Windows PowerShell 5.1 reads BOM-less scripts as ANSI).
param(
    [switch]$Preparar,
    [string]$Stem = "",
    [int]$Bloco = 0,
    [int]$Segundos = 15,
    [switch]$Agendar
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
Set-Location (Split-Path $PSScriptRoot -Parent)

$Canal = "Miss$([char]0x00E3)o em Cortes"
$Extra = @()
if ($Agendar) { $Extra += "--agendar" }

function Run09([string]$Etapa, [string[]]$Mais = @()) {
    & uv run py scripts/09_upload.py "--demo=$Etapa" --lang=en @Extra @Mais
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Step '$Etapa' failed (exit $LASTEXITCODE). Stopping the demo." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

function Step([string]$Titulo, [string[]]$Texto) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor Yellow
    Write-Host "  $Titulo" -ForegroundColor Yellow
    Write-Host ("=" * 72) -ForegroundColor Yellow
    foreach ($l in $Texto) { Write-Host "  $l" }
    Write-Host ""
}

function Pausa([string]$Msg = "Press Enter to continue") {
    Read-Host "  >> $Msg" | Out-Null
}

# ---------------------------------------------------------------- preparation
if ($Preparar) {
    $Mais = @("--segundos=$Segundos")
    if ($Stem) { $Mais = @($Stem) + $Mais }
    if ($Bloco -gt 0) { $Mais += "--bloco=$Bloco" }
    Run09 "preparar" $Mais
    Write-Host ""
    Write-Host "Ready. Nothing was sent to YouTube. Start recording, then run this script without -Preparar." -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------- recording
Clear-Host
Step "$Canal - YouTube Data API demo" @(
    "$Canal is a tool that turns long political livestreams into short clips",
    "and publishes them on our own YouTube channel.",
    "",
    "Google Cloud project: missao-em-cortes-publisher",
    "Scope requested:      https://www.googleapis.com/auth/youtube.upload",
    "",
    "This demo shows, step by step:",
    "  1. the upload plan (file, title, description, tags, thumbnail, publishAt)",
    "  2. the OAuth authorization (consent screen)",
    "  3. a real upload of a short TEST clip (private) with videos.insert",
    "  4. the thumbnail with thumbnails.set and the metadata",
    "  5. the confirmation (video ID and status)"
)
Pausa "Press Enter to start"

Step "1/5 - Upload plan" @(
    "The tool reads the finished clip, its title, description, tags and thumbnail,",
    "and computes the next publishing slot (publishAt) from our daily schedule.",
    "Nothing is sent to YouTube in this step."
)
Run09 "plano"
Pausa

Step "2/5 - OAuth authorization" @(
    "The previous token was revoked so the Google consent screen appears now.",
    "The channel owner signs in and grants only the youtube.upload scope.",
    "The token is stored locally and never leaves this computer."
)
Pausa "Press Enter to revoke the old token and open the consent screen"
Run09 "login"
Pausa

Step "3/5 - Upload (videos.insert)" @(
    "Uploading the short TEST clip as PRIVATE, with an English title and description.",
    "The title starts with [TEST] and the description says it will not be published."
)
Pausa "Press Enter to upload"
Run09 "upload"
Pausa

Step "4/5 - Thumbnail and metadata" @(
    "Setting the custom thumbnail with thumbnails.set.",
    "Then trying to update the description with videos.update (only if the scope allows it)."
)
Run09 "thumb"
Write-Host ""
Run09 "update"
Pausa

Step "5/5 - Confirmation" @(
    "Video ID and status returned by the API."
)
Run09 "status"

Step "Done" @(
    "Next: open YouTube Studio > Content to show the video, its thumbnail,",
    "and its visibility (Private)."
)
