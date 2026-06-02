# =====================================================================
# MeloToons YT Title Generator — One-Time Always-On Setup
# RIGHT-CLICK this file, "Run with PowerShell" select karein
# (UAC prompt aaye to YES dabayein — admin rights chahiyein)
# =====================================================================

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File",$PSCommandPath
    exit
}

$ErrorActionPreference = "Continue"

Write-Host "`n=====================================================" -ForegroundColor Cyan
Write-Host " MeloToons YT Tool — One-Time Always-On Setup" -ForegroundColor Cyan
Write-Host "=====================================================`n" -ForegroundColor Cyan

# ---------- STEP 1: nssm ----------
Write-Host "[1/5] nssm check..." -ForegroundColor Green
$nssmPath = $null
$existingNssm = Get-Command nssm -ErrorAction SilentlyContinue
if ($existingNssm) {
    $nssmPath = $existingNssm.Source
    Write-Host "  nssm found: $nssmPath" -ForegroundColor Gray
} else {
    $nssmPath = "C:\nssm\nssm.exe"
    if (-not (Test-Path $nssmPath)) {
        Write-Host "  Downloading nssm..." -ForegroundColor Gray
        $nssmZip = "$env:TEMP\nssm.zip"
        New-Item -ItemType Directory -Path "C:\nssm" -Force | Out-Null
        Invoke-WebRequest "https://nssm.cc/release/nssm-2.24.zip" -OutFile $nssmZip -UseBasicParsing
        Expand-Archive -Path $nssmZip -DestinationPath "$env:TEMP\nssm-extract" -Force
        Copy-Item "$env:TEMP\nssm-extract\nssm-2.24\win64\nssm.exe" "C:\nssm" -Force
        $env:Path = "C:\nssm;$env:Path"
    }
}
Write-Host "  nssm ready" -ForegroundColor Gray

# ---------- STEP 2: Stop old ----------
Write-Host "`n[2/5] Old processes band kar raha hoon..." -ForegroundColor Green
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*yt-title*' } | Stop-Process -Force -ErrorAction SilentlyContinue
& $nssmPath stop YTTool-Web confirm 2>$null | Out-Null
& $nssmPath stop YTTool-Ngrok confirm 2>$null | Out-Null
& $nssmPath remove YTTool-Web confirm 2>$null | Out-Null
& $nssmPath remove YTTool-Ngrok confirm 2>$null | Out-Null
Start-Sleep -Seconds 2
Write-Host "  Done" -ForegroundColor Gray

# ---------- STEP 3: Logs ----------
Write-Host "`n[3/5] Logs folder..." -ForegroundColor Green
New-Item -ItemType Directory -Path "D:\Projects\yt-title-generator\logs" -Force | Out-Null
Write-Host "  Ready" -ForegroundColor Gray

# ---------- STEP 4: YTTool-Web service ----------
Write-Host "`n[4/5] YTTool-Web service install..." -ForegroundColor Green
$pythonPath = (Get-Command python).Source
$appDir = "D:\Projects\yt-title-generator"

& $nssmPath install YTTool-Web $pythonPath "app.py"
& $nssmPath set YTTool-Web AppDirectory $appDir
& $nssmPath set YTTool-Web AppStdout "$appDir\logs\web-stdout.log"
& $nssmPath set YTTool-Web AppStderr "$appDir\logs\web-stderr.log"
& $nssmPath set YTTool-Web AppEnvironmentExtra "PYTHONIOENCODING=utf-8" "PORT=5055"
& $nssmPath set YTTool-Web Start SERVICE_AUTO_START
& $nssmPath set YTTool-Web AppExit Default Restart
& $nssmPath set YTTool-Web AppRestartDelay 5000
& $nssmPath set YTTool-Web Description "MeloToons YT Title Generator Flask server"
Write-Host "  YTTool-Web installed" -ForegroundColor Gray

# ---------- STEP 5: YTTool-Ngrok service ----------
Write-Host "`n[5/5] YTTool-Ngrok service install..." -ForegroundColor Green
$ngrokExe = "C:\ngrok\ngrok.exe"
if (-not (Test-Path $ngrokExe)) {
    # ngrok is at Program Files
    $ngrokSearch = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($ngrokSearch) { $ngrokExe = $ngrokSearch.Source }
}

if (Test-Path $ngrokExe) {
    # Second tunnel - random URL (permanent domain already used by Factory ERP)
    & $nssmPath install YTTool-Ngrok $ngrokExe "http 5055 --log=stdout"
    & $nssmPath set YTTool-Ngrok AppDirectory (Split-Path $ngrokExe)
    & $nssmPath set YTTool-Ngrok AppStdout "$appDir\logs\ngrok-stdout.log"
    & $nssmPath set YTTool-Ngrok AppStderr "$appDir\logs\ngrok-stderr.log"
    & $nssmPath set YTTool-Ngrok Start SERVICE_AUTO_START
    & $nssmPath set YTTool-Ngrok AppExit Default Restart
    & $nssmPath set YTTool-Ngrok AppRestartDelay 5000
    & $nssmPath set YTTool-Ngrok DependOnService YTTool-Web
    & $nssmPath set YTTool-Ngrok Description "MeloToons YT Tool ngrok tunnel"
    Write-Host "  YTTool-Ngrok installed" -ForegroundColor Gray
} else {
    Write-Host "  ngrok nahi mila — service skip" -ForegroundColor Yellow
}

# ---------- Start services ----------
Write-Host "`n  Starting services..." -ForegroundColor Green
& $nssmPath start YTTool-Web
Start-Sleep -Seconds 8
if (Test-Path $ngrokExe) { & $nssmPath start YTTool-Ngrok }
Start-Sleep -Seconds 8

# ---------- Get ngrok URL ----------
Write-Host "`n=====================================================" -ForegroundColor Cyan
Write-Host " URL NIKAALNA" -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

$url = $null
try {
    $tunnels = Invoke-RestMethod "http://localhost:4040/api/tunnels" -ErrorAction Stop
    foreach ($t in $tunnels.tunnels) {
        if ($t.config.addr -like "*5055*") {
            $url = $t.public_url
            if ($url -like "http://*") { $url = $url.Replace("http://","https://") }
        }
    }
} catch { }

if ($url) {
    $url | Out-File "$appDir\CURRENT_LINK.txt" -Encoding utf8
    Write-Host "`n  ✅ TUMHARA LINK:" -ForegroundColor Green
    Write-Host "  $url" -ForegroundColor White
    Write-Host "`n  Yeh link CURRENT_LINK.txt mein bhi save hai" -ForegroundColor Gray
} else {
    Write-Host "`n  Link abhi aa raha hai — 30 sec baad CHECK_LINK.bat chalao" -ForegroundColor Yellow
}

Write-Host "`n=====================================================" -ForegroundColor Cyan
Write-Host " SETUP COMPLETE — PC restart hone pe auto-start hoga" -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Services:" -ForegroundColor White
Write-Host "    YTTool-Web  : Flask app (always on)" -ForegroundColor Gray
Write-Host "    YTTool-Ngrok: ngrok tunnel (always on)" -ForegroundColor Gray
Write-Host ""

Read-Host "Press Enter to close"
