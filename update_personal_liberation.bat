@echo off
setlocal EnableExtensions

set "DEV_DIR=%~dp0"
if "%DEV_DIR:~-1%"=="\" set "DEV_DIR=%DEV_DIR:~0,-1%"

set "PERSONAL_DIR=C:\Users\aleja\Saved Games\DCS-Liberation-Personal"
set "STAGING_DIR=C:\Users\aleja\Saved Games\DCS-Liberation-Personal.new"
set "PY311=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

echo ============================================================
echo Updating personal DCS Liberation build
echo Development repo: "%DEV_DIR%"
echo Playable install: "%PERSONAL_DIR%"
echo ============================================================
echo.

cd /d "%DEV_DIR%" || goto fail_unmodified

for /f "delims=" %%B in ('git branch --show-current') do set "CURRENT_BRANCH=%%B"
if /I not "%CURRENT_BRANCH%"=="alex-liberation" (
    echo Switching to alex-liberation...
    git switch alex-liberation || goto fail_unmodified
)

echo Checking for uncommitted tracked changes...
git diff --quiet
if errorlevel 1 (
    echo.
    echo UPDATE FAILED - CURRENT PLAYABLE VERSION WAS NOT MODIFIED
    echo Tracked working-tree changes are present. Commit or stash them first.
    goto end_fail
)

git diff --cached --quiet
if errorlevel 1 (
    echo.
    echo UPDATE FAILED - CURRENT PLAYABLE VERSION WAS NOT MODIFIED
    echo Staged changes are present. Commit or unstage them first.
    goto end_fail
)

echo Fetching official upstream changes...
git fetch upstream || goto fail_unmodified

echo Integrating upstream/develop into alex-liberation...
git merge --no-edit upstream/develop
if errorlevel 1 (
    echo.
    echo UPDATE FAILED - CURRENT PLAYABLE VERSION WAS NOT MODIFIED
    echo Git merge conflicts or another merge error occurred.
    echo Resolve the conflicts in "%DEV_DIR%", then rerun this script.
    goto end_fail
)

if exist "client\package.json" (
    where npm >nul 2>nul
    if not errorlevel 1 (
        echo Building web client with npm...
        pushd client || goto fail_unmodified
        call npm run build
        if errorlevel 1 (
            popd
            goto fail_unmodified
        )
        popd
    ) else (
        echo npm was not found. Reusing existing client\build.
        if not exist "client\build\index.html" (
            echo.
            echo UPDATE FAILED - CURRENT PLAYABLE VERSION WAS NOT MODIFIED
            echo client\build is missing and npm is not available to rebuild it.
            goto end_fail
        )
    )
)

if not exist "%PY311%" (
    echo.
    echo UPDATE FAILED - CURRENT PLAYABLE VERSION WAS NOT MODIFIED
    echo Python 3.11 was not found at "%PY311%".
    goto end_fail
)

echo Packaging Windows build with Liberation's PyInstaller release script...
set "PATH=%DEV_DIR%\.venv311\Scripts;%PATH%"
"%PY311%" resources\tools\mkrelease.py
if errorlevel 1 goto fail_unmodified

if not exist "dist\dcs_liberation\liberation_main.exe" (
    echo.
    echo UPDATE FAILED - CURRENT PLAYABLE VERSION WAS NOT MODIFIED
    echo Build completed but dist\dcs_liberation\liberation_main.exe was not found.
    goto end_fail
)

echo Deploying build through temporary staging folder...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$src = Join-Path $env:DEV_DIR 'dist\dcs_liberation';" ^
  "$dst = $env:PERSONAL_DIR;" ^
  "$staging = $env:STAGING_DIR;" ^
  "$backup = $dst + '.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss');" ^
  "if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }" ^
  "Copy-Item -LiteralPath $src -Destination $staging -Recurse;" ^
  "if (-not (Test-Path -LiteralPath (Join-Path $staging 'liberation_main.exe'))) { throw 'Staged executable was not found.' }" ^
  "try {" ^
  "  if (Test-Path -LiteralPath $dst) { Move-Item -LiteralPath $dst -Destination $backup }" ^
  "  Move-Item -LiteralPath $staging -Destination $dst" ^
  "} catch {" ^
  "  if ((-not (Test-Path -LiteralPath $dst)) -and (Test-Path -LiteralPath $backup)) { Move-Item -LiteralPath $backup -Destination $dst }" ^
  "  throw" ^
  "}"
if errorlevel 1 goto fail_unmodified

echo.
echo PERSONAL LIBERATION UPDATED SUCCESSFULLY
echo Executable: "%PERSONAL_DIR%\liberation_main.exe"
goto end_ok

:fail_unmodified
echo.
echo UPDATE FAILED - CURRENT PLAYABLE VERSION WAS NOT MODIFIED

:end_fail
exit /b 1

:end_ok
exit /b 0
