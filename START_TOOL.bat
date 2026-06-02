@echo off
title MeloToons Title Generator
color 0A

echo.
echo  ==========================================
echo   MeloToons Title Generator - Starting...
echo  ==========================================
echo.

:: Kill any old instances
taskkill /F /IM cloudflared.exe >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":5055"') do taskkill /F /PID %%a >nul 2>&1
timeout /t 1 /nobreak >nul

:: Start Flask app in background
cd /d "%~dp0"
start /B python app.py > app_log.txt 2>&1

:: Wait for Flask to start
echo  Waiting for app to start...
timeout /t 3 /nobreak >nul

:: Start Cloudflare tunnel and capture URL
echo  Creating shareable link...
cloudflared tunnel --url http://localhost:5055 --logfile tunnel_log.txt 2>&1 | find /v "" > tunnel_output.txt &

:: Wait for URL to appear
timeout /t 8 /nobreak >nul

:: Extract URL from log
set URL=
for /f "tokens=*" %%i in ('findstr "trycloudflare.com" tunnel_log.txt 2^>nul') do (
    for %%j in (%%i) do (
        echo %%j | findstr "https://" >nul 2>&1
        if not errorlevel 1 set URL=%%j
    )
)

:: Save URL to file
if defined URL (
    echo %URL% > SHAREABLE_LINK.txt
    echo.
    echo  ==========================================
    echo   YOUR SHAREABLE LINK IS READY!
    echo  ==========================================
    echo.
    echo   %URL%
    echo.
    echo   ^ This link has been saved to: SHAREABLE_LINK.txt
    echo   ^ Share this link with anyone - works worldwide
    echo   ^ Link works as long as this window is OPEN
    echo  ==========================================
    echo.
    :: Open browser with the URL
    start "" "%URL%"
) else (
    echo  Getting URL... check SHAREABLE_LINK.txt in a moment
    echo  Or open: http://localhost:5055
    start "" "http://localhost:5055"
)

echo.
echo  Press any key to STOP the tool...
pause >nul

:: Cleanup on exit
taskkill /F /IM cloudflared.exe >nul 2>&1
echo Tool stopped.
