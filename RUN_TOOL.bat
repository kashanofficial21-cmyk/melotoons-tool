@echo off
cd /d "d:\Projects\yt-title-generator"
set PYTHONIOENCODING=utf-8
start /B python app.py > service_log.txt 2>&1
