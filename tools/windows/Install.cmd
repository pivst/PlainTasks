@echo off
setlocal DisableDelayedExpansion
echo PlainTasks - Windows offline installer
echo Close Sublime Text before installing.
echo Existing PlainTasks files will be backed up. Personal settings are retained.
echo.

if "%~1"=="" if not defined APPDATA (
    echo APPDATA is not set. Specify a portable Sublime Text directory instead.
    pause
    exit /b 1
)
if "%~1"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\Install-PlainTasks.ps1" -DataPath "%APPDATA%\Sublime Text" -BackupExisting
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\Install-PlainTasks.ps1" -PortablePath "%~1\." -BackupExisting
)
set "install_exit_code=%errorlevel%"
echo.
if "%install_exit_code%"=="0" (
    echo Installation complete. Start Sublime Text to use PlainTasks.
) else (
    echo Installation failed. Read the error above before retrying.
)
pause
exit /b %install_exit_code%
