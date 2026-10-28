$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskTemp = Join-Path $PSScriptRoot '.tmp'
New-Item -ItemType Directory -Path $taskTemp -Force | Out-Null
$env:TEMP = $taskTemp
$env:TMP = $taskTemp
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    $runtimePython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        & $pythonCommand.Source -3 -m venv .venv
    } elseif (Test-Path -LiteralPath $runtimePython) {
        & $runtimePython -m venv .venv
    } else {
        python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Python environment setup failed. Install Python 3.11 or newer.' }
}
$ErrorActionPreference = 'Continue'
& $projectPython -c 'import streamlit, google.genai, pydantic, jieba, fontTools' 2>$null
$dependenciesReady = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = 'Stop'
if (-not $dependenciesReady) {
    & $projectPython -m ensurepip --upgrade
    & $projectPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the network connection.' }
}
& $projectPython -m streamlit run app.py --server.address 127.0.0.1
