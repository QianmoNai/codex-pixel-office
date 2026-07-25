param(
    [string]$ProgramsDirectory = ""
)

$ErrorActionPreference = "Stop"
if (-not $ProgramsDirectory) {
    $ProgramsDirectory = [Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
}
$ApplicationDirectory = Join-Path $ProgramsDirectory "Codex Pixel Office"
$ShortcutPath = Join-Path $ApplicationDirectory "Codex Pixel Office.lnk"

if (Test-Path -LiteralPath $ShortcutPath -PathType Leaf) {
    Remove-Item -LiteralPath $ShortcutPath -Force
}
if ((Test-Path -LiteralPath $ApplicationDirectory -PathType Container) -and
    -not (Get-ChildItem -LiteralPath $ApplicationDirectory -Force | Select-Object -First 1)) {
    Remove-Item -LiteralPath $ApplicationDirectory
}

Write-Host "Uninstalled the Codex Pixel Office Start menu shortcut."
Write-Host "Python packages and source files were not removed."
