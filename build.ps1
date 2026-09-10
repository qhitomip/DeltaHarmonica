$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $bundledPython) {
        $pythonPath = $bundledPython
    }
    else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if (-not $pythonCommand) {
            throw "Python was not found. Create .venv and install the project plus PyInstaller."
        }
        $pythonPath = $pythonCommand.Source
    }
}

$sourceRoot = Join-Path $projectRoot "src"
$localPackages = Join-Path $projectRoot ".packages"
if (-not (Test-Path -LiteralPath (Join-Path $localPackages "mido"))) {
    throw "Mido was not found. Install the project dependencies first."
}
$env:PYTHONPATH = "$localPackages;$sourceRoot"

& $pythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name "DeltaHarmonica" `
    --paths $sourceRoot `
    --paths $localPackages `
    "$projectRoot\launcher.py"

# PyInstaller may collect the runtime that ships with Python even when Qt was
# built against a newer compatible MSVC runtime. Keep the app-local runtime
# set consistent with the current Windows VC++ installation.
$internalDir = Join-Path $projectRoot "dist\DeltaHarmonica\_internal"
$runtimeFiles = @(
    "MSVCP140.dll",
    "MSVCP140_1.dll",
    "MSVCP140_2.dll",
    "VCRUNTIME140.dll",
    "VCRUNTIME140_1.dll",
    "concrt140.dll",
    "msvcp140_codecvt_ids.dll"
)
foreach ($runtimeFile in $runtimeFiles) {
    $source = Join-Path "$env:WINDIR\System32" $runtimeFile
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $internalDir -Force
    }
}

# Qt 6 on Windows uses the ICU compatibility library from System32. A build
# environment may expose Poppler's versioned ICU DLLs on PATH; PyInstaller can
# accidentally collect those under the same generic name. They export different
# symbols and make QtCore fail with ERROR_PROC_NOT_FOUND.
$incompatibleIcuFiles = @("icuuc.dll", "icudt78.dll")
foreach ($icuFile in $incompatibleIcuFiles) {
    $collected = Join-Path $internalDir $icuFile
    if (Test-Path -LiteralPath $collected) {
        Remove-Item -LiteralPath $collected -Force
    }
}

Copy-Item -LiteralPath (Join-Path $projectRoot "README.md") -Destination (Join-Path $projectRoot "dist\DeltaHarmonica") -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "THIRD_PARTY_NOTICES.md") -Destination (Join-Path $projectRoot "dist\DeltaHarmonica") -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "licenses") -Destination (Join-Path $projectRoot "dist\DeltaHarmonica") -Recurse -Force

Write-Host "Build complete: $projectRoot\dist\DeltaHarmonica\DeltaHarmonica.exe"
