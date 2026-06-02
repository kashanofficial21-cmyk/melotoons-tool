@echo off
echo.
echo  Checking YT Tool link...
echo.
curl -s http://localhost:4040/api/tunnels 2>nul | python -c "import sys,json; data=json.load(sys.stdin); [print('  LINK: '+t['public_url'].replace('http://','https://')) for t in data.get('tunnels',[]) if '5055' in t.get('config',{}).get('addr','')]" 2>nul
echo.
echo  (Agar link nahi dikh raha to services.msc mein YTTool-Ngrok check karo)
echo.
pause
