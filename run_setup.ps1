$nssmPath = "C:\nssm\nssm.exe"
$python = "C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe"
$appDir = "D:\Projects\yt-title-generator"
$ngrok = "C:\ngrok\ngrok.exe"
$config = "$appDir\ngrok_config\ngrok.yml"
$logsDir = "$appDir\logs"
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
& $nssmPath stop YTTool-Web confirm 2>$null
& $nssmPath stop YTTool-Ngrok confirm 2>$null
& $nssmPath remove YTTool-Web confirm 2>$null
& $nssmPath remove YTTool-Ngrok confirm 2>$null
Start-Sleep -Seconds 2
& $nssmPath install YTTool-Web $python "app.py"
& $nssmPath set YTTool-Web AppDirectory $appDir
& $nssmPath set YTTool-Web AppEnvironmentExtra "PYTHONIOENCODING=utf-8" "PORT=5055"
& $nssmPath set YTTool-Web Start SERVICE_AUTO_START
& $nssmPath set YTTool-Web AppExit Default Restart
& $nssmPath set YTTool-Web AppRestartDelay 5000
$ngrokArgs = "http 5055 --config=" + $config + " --log=stdout"
& $nssmPath install YTTool-Ngrok $ngrok $ngrokArgs
& $nssmPath set YTTool-Ngrok AppDirectory "C:\ngrok"
& $nssmPath set YTTool-Ngrok Start SERVICE_AUTO_START
& $nssmPath set YTTool-Ngrok AppExit Default Restart
& $nssmPath set YTTool-Ngrok AppRestartDelay 5000
& $nssmPath set YTTool-Ngrok DependOnService YTTool-Web
& $nssmPath start YTTool-Web
Start-Sleep -Seconds 8
& $nssmPath start YTTool-Ngrok
Start-Sleep -Seconds 8
Write-Host "DONE - Services installed!" -ForegroundColor Green
& $nssmPath status YTTool-Web
& $nssmPath status YTTool-Ngrok
