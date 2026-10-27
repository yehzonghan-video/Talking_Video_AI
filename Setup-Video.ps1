$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Path '.tmp' -Force | Out-Null
$env:TEMP = Join-Path $PSScriptRoot '.tmp'
$env:TMP = $env:TEMP
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Run Start.ps1 once to create the Python environment, then stop it and run this setup.' }
& $projectPython -m pip install -r requirements-video.txt
if ($LASTEXITCODE -ne 0) { throw 'Video dependency installation failed.' }
& $projectPython tools/install_ffmpeg.py
if ($LASTEXITCODE -ne 0) { throw 'FFmpeg installation failed. See README for manual installation.' }
Write-Host 'Video tools ready. The speech model will be downloaded on first analysis.'
