# =====================================================================
# MeloToons YT Tool — One-Time Always-On Setup
# RIGHT-CLICK → "Run with PowerShell" (YES dabayein UAC pe)
# =====================================================================

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File",$PSCommandPath
    exit
}

$ErrorActionPreference = "Continue"
Write-Host "`n=====================================================" -ForegroundColor Cyan
Write-Host " MeloToons YT Tool — Always-On Setup" -ForegroundColor Cyan
Write-Host "=====================================================`n" -ForegroundColor Cyan

# ── NSSM ──
Write-Host "[1/6] nssm check..." -ForegroundColor Green
$nssmPath = "C:\nssm\nssm.exe"
if (-not (Test-Path $nssmPath)) {
    Write-Host "  Downloading nssm..." -ForegroundColor Gray
    New-Item -ItemType Directory -Path "C:\nssm" -Force | Out-Null
    Invoke-WebRequest "https://nssm.cc/release/nssm-2.24.zip" -OutFile "$env:TEMP\nssm.zip" -UseBasicParsing
    Expand-Archive "$env:TEMP\nssm.zip" "$env:TEMP\nssm-extract" -Force
    Copy-Item "$env:TEMP\nssm-extract\nssm-2.24\win64\nssm.exe" "C:\nssm" -Force
}
Write-Host "  nssm ready" -ForegroundColor Gray

# ── PATHS ──
$python   = "C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe"
$appDir   = "D:\Projects\yt-title-generator"
$ngrok    = "C:\ngrok\ngrok.exe"
$config   = "$appDir\ngrok_config\ngrok.yml"
$logsDir  = "$appDir\logs"
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

# ── STOP OLD ──
Write-Host "`n[2/6] Old services band kar raha hoon..." -ForegroundColor Green
& $nssmPath stop YTTool-Web confirm 2>$null | Out-Null
& $nssmPath stop YTTool-Ngrok confirm 2>$null | Out-Null
& $nssmPath remove YTTool-Web confirm 2>$null | Out-Null
& $nssmPath remove YTTool-Ngrok confirm 2>$null | Out-Null
Get-Process python,ngrok -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -notlike "*3000*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# ── YTTool-Web SERVICE ──
Write-Host "`n[3/6] YTTool-Web service install..." -ForegroundColor Green
& $nssmPath install YTTool-Web $python "app.py"
& $nssmPath set YTTool-Web AppDirectory $appDir
& $nssmPath set YTTool-Web AppStdout "$logsDir\web.log"
& $nssmPath set YTTool-Web AppStderr "$logsDir\web.log"
& $nssmPath set YTTool-Web AppEnvironmentExtra "PYTHONIOENCODING=utf-8" "PORT=5055"
& $nssmPath set YTTool-Web Start SERVICE_AUTO_START
& $nssmPath set YTTool-Web AppExit Default Restart
& $nssmPath set YTTool-Web AppRestartDelay 5000
& $nssmPath set YTTool-Web Description "MeloToons YT Title Generator"
Write-Host "  YTTool-Web installed" -ForegroundColor Gray

# ── YTTool-Ngrok SERVICE ──
Write-Host "`n[4/6] YTTool-Ngrok service install..." -ForegroundColor Green
& $nssmPath install YTTool-Ngrok $ngrok "http 5055 --config=`"$config`" --log=stdout"
& $nssmPath set YTTool-Ngrok AppDirectory "C:\ngrok"
& $nssmPath set YTTool-Ngrok AppStdout "$logsDir\ngrok.log"
& $nssmPath set YTTool-Ngrok AppStderr "$logsDir\ngrok.log"
& $nssmPath set YTTool-Ngrok Start SERVICE_AUTO_START
& $nssmPath set YTTool-Ngrok AppExit Default Restart
& $nssmPath set YTTool-Ngrok AppRestartDelay 5000
& $nssmPath set YTTool-Ngrok DependOnService YTTool-Web
& $nssmPath set YTTool-Ngrok Description "MeloToons YT Tool ngrok tunnel"
Write-Host "  YTTool-Ngrok installed" -ForegroundColor Gray

# ── START ──
Write-Host "`n[5/6] Services start kar raha hoon..." -ForegroundColor Green
& $nssmPath start YTTool-Web
Write-Host "  YTTool-Web started, waiting 8 seconds..." -ForegroundColor Gray
Start-Sleep -Seconds 8
& $nssmPath start YTTool-Ngrok
Start-Sleep -Seconds 8

# ── GET URL ──
Write-Host "`n[6/6] Link nikal raha hoon..." -ForegroundColor Green
$url = $null
foreach($port in @(4040,4041)){
    try {
        $r = Invoke-RestMethod "http://localhost:$port/api/tunnels" -ErrorAction Stop
        foreach($t in $r.tunnels){
            if($t.config.addr -like "*5055*"){
                $url = $t.public_url -replace "^http://","https://"
            }
        }
    } catch {}
}

Write-Host "`n=====================================================" -ForegroundColor Cyan
Write-Host " SETUP COMPLETE!" -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

if($url){
    $url | Out-File "$appDir\LINK.txt" -Encoding UTF8
    Write-Host ""
    Write-Host "  YT TOOL PERMANENT LINK:" -ForegroundColor White
    Write-Host "  $url" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "  Link file: $appDir\LINK.txt" -ForegroundColor Gray
    Write-Host "  Thori der baad check karo" -ForegroundColor Yellow
}

Write-Host "  PC restart hone pe dono services auto-start hongi" -ForegroundColor Gray
Write-Host "  Services: YTTool-Web + YTTool-Ngrok" -ForegroundColor Gray
Write-Host ""
Read-Host "Press Enter to close"
