param(
    [switch]$SkipDependencies,
    [string]$ProgramsDirectory = ""
)

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

$RuntimeCheck = @'
import sys
sys.path.insert(0, sys.argv[1])
from windows_app import require_webview2
try:
    require_webview2()
except Exception as error:
    print(error, file=sys.stderr)
    raise SystemExit(1)
'@
& $PythonPath @PythonPrefix -c $RuntimeCheck $RootDir
if ($LASTEXITCODE -ne 0) {
    throw "Microsoft Edge WebView2 is not ready. Install or update it from https://developer.microsoft.com/microsoft-edge/webview2/"
}

if (-not $SkipDependencies) {
    $PipArgs = @("-m", "pip", "install")
    $VirtualCheck = (& $PythonPath @PythonPrefix -c "import sys; print('1' if sys.prefix != sys.base_prefix else '0')" | Select-Object -Last 1).Trim()
    if ($VirtualCheck -ne "1") {
        $PipArgs += "--user"
    }
    $PipArgs += @("-r", (Join-Path $RootDir "requirements-windows.txt"))
    & $PythonPath @PythonPrefix @PipArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install the Windows desktop dependency."
    }
}

$PythonExecutable = (& $PythonPath @PythonPrefix -c "import sys; print(sys.executable)" | Select-Object -Last 1).Trim()
$PythonwExecutable = Join-Path (Split-Path -LiteralPath $PythonExecutable -Parent) "pythonw.exe"
if (-not (Test-Path -LiteralPath $PythonwExecutable -PathType Leaf)) {
    $PythonwExecutable = $PythonExecutable
}

if (-not $ProgramsDirectory) {
    $ProgramsDirectory = [Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
}
$ApplicationDirectory = Join-Path $ProgramsDirectory "Codex Pixel Office"
$ShortcutPath = Join-Path $ApplicationDirectory "Codex Pixel Office.lnk"
New-Item -ItemType Directory -Path $ApplicationDirectory -Force | Out-Null

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PythonwExecutable
$Shortcut.Arguments = '"' + (Join-Path $RootDir "windows_app.pyw") + '"'
$Shortcut.WorkingDirectory = $RootDir
$Shortcut.Description = "Watch active Codex sessions work as pixel characters"
$IconPath = Join-Path $RootDir "static\assets\app-icon.ico"
if (Test-Path -LiteralPath $IconPath -PathType Leaf) {
    $Shortcut.IconLocation = "$IconPath,0"
}
$Shortcut.Save()

Write-Host "Installed Codex Pixel Office in the current user's Start menu."
Write-Host "Shortcut: $ShortcutPath"
Write-Host "The source directory must stay at: $RootDir"
Write-Host "Microsoft Edge WebView2 Runtime is required: https://developer.microsoft.com/microsoft-edge/webview2/"
