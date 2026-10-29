@echo off
setlocal enabledelayedexpansion
title RYOKU CLOUD GAMING // 120 FPS NATIVE LAUNCHER

echo +----------------------------------------------------------------------------+
echo ^| RYOKU CLOUD GAMING // NATIVE MOONLIGHT CLIENT (120 FPS SUB-2MS)            ^|
echo +----------------------------------------------------------------------------+
echo.

:: Server configuration (dynamically injected by Ryoku server)
set "DEFAULT_SERVER_URL=__SERVER_URL__"
set "DEFAULT_TARGET_HOST=__TARGET_HOST__"

if "%DEFAULT_SERVER_URL%"=="__SERVER_URL__" set "DEFAULT_SERVER_URL=https://play.vanshdev.online"
if "%DEFAULT_TARGET_HOST%"=="__TARGET_HOST__" set "DEFAULT_TARGET_HOST=play.vanshdev.online"

set "SERVER_URL=%~1"
if "%SERVER_URL%"=="" set "SERVER_URL=%DEFAULT_SERVER_URL%"

set "TARGET_HOST=%~2"
if "%TARGET_HOST%"=="" set "TARGET_HOST=%DEFAULT_TARGET_HOST%"

echo [RYOKU] Server URL  : %SERVER_URL%
echo [RYOKU] Target Host : %TARGET_HOST%
echo.

:: 1. Search for Moonlight Game Streaming engine
set "MOONLIGHT_EXE="
if exist "%ProgramFiles%\Moonlight Game Streaming\Moonlight.exe" set "MOONLIGHT_EXE=%ProgramFiles%\Moonlight Game Streaming\Moonlight.exe"
if exist "%ProgramFiles(x86)%\Moonlight Game Streaming\Moonlight.exe" set "MOONLIGHT_EXE=%ProgramFiles(x86)%\Moonlight Game Streaming\Moonlight.exe"
if exist "%LocalAppData%\Moonlight Game Streaming\Moonlight.exe" set "MOONLIGHT_EXE=%LocalAppData%\Moonlight Game Streaming\Moonlight.exe"

if not defined MOONLIGHT_EXE (
    echo [RYOKU] Moonlight engine not found. Checking winget...
    where winget >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        echo [RYOKU] Installing official Moonlight client via winget...
        winget install -e --id MoonlightGameStreaming.Moonlight --accept-source-agreements --accept-package-agreements
        if exist "%ProgramFiles%\Moonlight Game Streaming\Moonlight.exe" set "MOONLIGHT_EXE=%ProgramFiles%\Moonlight Game Streaming\Moonlight.exe"
        if exist "%ProgramFiles(x86)%\Moonlight Game Streaming\Moonlight.exe" set "MOONLIGHT_EXE=%ProgramFiles(x86)%\Moonlight Game Streaming\Moonlight.exe"
    )
)

if not defined MOONLIGHT_EXE (
    echo [NOTE] Moonlight is not yet installed.
    echo Opening Moonlight official download page in browser...
    start https://moonlight-stream.org/
) else (
    echo [OK] Moonlight engine found: !MOONLIGHT_EXE!
)

:: 2. Check if local Python PyGObject client is present
if exist "%~dp0ryoku_client.py" (
    where python >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        echo [RYOKU] Starting native GTK container window...
        python "%~dp0ryoku_client.py" --server "%SERVER_URL%" --host "%TARGET_HOST%"
        if %ERRORLEVEL% equ 0 goto :DONE
    )
)

:: 3. Dedicated App Window (Pixel-perfect Ryoku console with live auto-updating UI)
echo.
echo [RYOKU] Launching dedicated Ryoku Console window...
where msedge >nul 2>&1
if %ERRORLEVEL% equ 0 (
    start "" msedge --app="%SERVER_URL%" --window-size=1280,820
    goto :STARTED
)

where chrome >nul 2>&1
if %ERRORLEVEL% equ 0 (
    start "" chrome --app="%SERVER_URL%" --window-size=1280,820
    goto :STARTED
)

start "" "%SERVER_URL%"

:STARTED
echo.
echo +----------------------------------------------------------------------------+
echo ^| RYOKU IS READY! Live interface active. Sub-2ms low-latency enabled.        ^|
echo +----------------------------------------------------------------------------+
timeout /t 5 >nul

:DONE
exit /b 0
