$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceRoot = Join-Path $projectRoot "src"
$localPackages = Join-Path $projectRoot ".packages"
$pythonPaths = @($localPackages, $sourceRoot) | Where-Object { Test-Path -LiteralPath $_ }
$env:PYTHONPATH = $pythonPaths -join ";"

$pythonCandidates = @(
    (Join-Path $projectRoot ".venv\Scripts\python.exe"),
    "py",
    "python"
)

foreach ($candidate in $pythonCandidates) {
    if ($candidate -eq "py") {
        $command = Get-Command py -ErrorAction SilentlyContinue
        if ($command) {
            & py -3.11 -m delta_harmonica
            exit $LASTEXITCODE
        }
    }
    elseif ($candidate -eq "python") {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command) {
            & python -m delta_harmonica
            exit $LASTEXITCODE
        }
    }
    elseif (Test-Path -LiteralPath $candidate) {
        & $candidate -m delta_harmonica
        exit $LASTEXITCODE
    }
}

throw "未找到 Python 3.11。请先创建 .venv 并安装项目依赖。"
