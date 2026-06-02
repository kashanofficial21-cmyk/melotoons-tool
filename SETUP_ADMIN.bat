@echo off
:: Auto-elevate
net session >nul 2>&1
if %errorLevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit
)

set NSSM=C:\nssm\nssm.exe
set PYTHON=C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe
set APPDIR=d:\Projects\yt-title-generator
set NGROK=C:\Program Files (x86)\cloudflared\..\..\..\ngrok\ngrok.exe

:: Find ngrok
if not exist "%NGROK%" set NGROK=C:\ngrok\ngrok.exe

echo Stopping old services...
%NSSM% stop YTTool-Web confirm >nul 2>&1
%NSSM% stop YTTool-Ngrok confirm >nul 2>&1
%NSSM% remove YTTool-Web confirm >nul 2>&1
%NSSM% remove YTTool-Ngrok confirm >nul 2>&1
timeout /t 2 /nobreak >nul

echo Installing YTTool-Web...
%NSSM% install YTTool-Web "%PYTHON%" "app.py"
%NSSM% set YTTool-Web AppDirectory "%APPDIR%"
%NSSM% set YTTool-Web AppEnvironmentExtra "PYTHONIOENCODING=utf-8" "PORT=5055"
%NSSM% set YTTool-Web Start SERVICE_AUTO_START
%NSSM% set YTTool-Web AppExit Default Restart
%NSSM% set YTTool-Web AppRestartDelay 5000

echo Installing YTTool-Ngrok...
%NSSM% install YTTool-Ngrok "%NGROK%" "http 5055 --log=stdout"
%NSSM% set YTTool-Ngrok Start SERVICE_AUTO_START
%NSSM% set YTTool-Ngrok AppExit Default Restart
%NSSM% set YTTool-Ngrok DependOnService YTTool-Web

echo Starting services...
%NSSM% start YTTool-Web
timeout /t 8 /nobreak >nul
%NSSM% start YTTool-Ngrok
timeout /t 8 /nobreak >nul

echo Getting link...
curl -s http://localhost:4040/api/tunnels 2>nul | python -c "import sys,json; data=json.load(sys.stdin); [print('YOUR LINK: '+t['public_url'].replace('http://','https://')) for t in data.get('tunnels',[]) if '5055' in t.get('config',{}).get('addr','')]" 2>nul

echo.
echo Setup complete! PC restart hone pe auto-start hoga.
pause
