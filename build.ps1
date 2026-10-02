param([string]$OutputDirectory = "dist")

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $bundledPython) { $pythonPath = $bundledPython }
    else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if (-not $pythonCommand) { throw "Python was not found. Install project dependencies and PyInstaller." }
        $pythonPath = $pythonCommand.Source
    }
}
$localPackages = Join-Path $projectRoot ".packages"
$sourceRoot = Join-Path $projectRoot "src"
$env:PYTHONPATH = "$localPackages;$sourceRoot"
# The spec embeds the correct runtime DLLs and notices before producing the EXE.
# Nothing is copied alongside or patched into the output after this step.
& $pythonPath -m PyInstaller --noconfirm --clean --distpath $OutputDirectory `
    --workpath "build/onefile" "$projectRoot/packaging/DeltaHarmonica.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }
Write-Host "Build complete: $OutputDirectory/DeltaHarmonica.exe"
