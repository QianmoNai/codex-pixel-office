@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-windows.ps1" %*
set "codex_pixel_exit=%ERRORLEVEL%"
if not "%codex_pixel_exit%"=="0" if not defined CI (
  echo.
  echo Installation failed. Press any key to close this window.
  pause >nul
)
exit /b %codex_pixel_exit%
