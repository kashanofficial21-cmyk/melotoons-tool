@echo off
cd /d "d:\Projects\yt-title-generator"
set PYTHONIOENCODING=utf-8
start /B "C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe" app.py > "d:\Projects\yt-title-generator\logs\web.log" 2>&1
timeout /t 4 /nobreak > nul
start /B "C:\ngrok\ngrok.exe" http 5055 --config="d:\Projects\yt-title-generator\ngrok_config\ngrok.yml" --log="d:\Projects\yt-title-generator\ngrok_config\ngrok.log"
