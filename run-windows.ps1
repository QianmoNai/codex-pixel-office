$ErrorActionPreference = "Stop"
$RootDir = Split-Path -LiteralPath $MyInvocation.MyCommand.Path -Parent

function Test-PythonCandidate {
    param([string]$Path, [string[]]$Prefix)
    try {
        & $Path @Prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Resolve-PythonLauncher {
    $candidates = @()
    if ($env:VIRTUAL_ENV) {
        $venvPython = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
        if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
            $candidates += @{ Path = $venvPython; Prefix = @() }
        }
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $launcher) {
        $candidates += @{ Path = $launcher.Source; Prefix = @("-3") }
    }
    foreach ($name in @("python.exe", "python3.exe")) {
        $launcher = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $launcher) {
            $candidates += @{ Path = $launcher.Source; Prefix = @() }
        }
    }
    foreach ($candidate in $candidates) {
        if (Test-PythonCandidate -Path $candidate.Path -Prefix $candidate.Prefix) {
            return $candidate
        }
    }
    throw "Python 3.11 or newer was not found. Install Python and enable the py launcher or add python.exe to PATH."
}

$Python = Resolve-PythonLauncher
$PythonPath = $Python.Path
$PythonPrefix = @($Python.Prefix)

$ApplicationArgs = @((Join-Path $RootDir "windows_app.py")) + @($args)
& $PythonPath @PythonPrefix @ApplicationArgs
exit $LASTEXITCODE
