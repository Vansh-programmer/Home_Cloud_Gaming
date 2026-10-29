@echo off
:: ==============================================================================
:: RYOKU CLOUD GAMING // 1-CLICK WINDOWS NATIVE CLIENT
:: ==============================================================================
title RYOKU CLOUD GAMING
echo +----------------------------------------------------------------------------+
echo ^| RYOKU CLOUD GAMING // NATIVE MOONLIGHT CLIENT                              ^|
echo +----------------------------------------------------------------------------+

set SERVER_URL=%1
if "%SERVER_URL%"=="" set SERVER_URL=https://play.vanshdev.online

set TARGET_HOST=%2
if "%TARGET_HOST%"=="" set TARGET_HOST=play.vanshdev.online

echo [RYOKU] Connecting to %SERVER_URL%...
python client\ryoku_client.py --server %SERVER_URL% --host %TARGET_HOST%

if %ERRORLEVEL% NEQ 0 (
    echo [NOTE] Python GTK not found. Opening Ryoku Web Console directly in your default browser...
    start "" "%SERVER_URL%"
)
