@echo off
setlocal

set "PATH=C:\Program Files\nodejs;%PATH%"

echo ======================================
echo  Installing with China mirror...
echo ======================================

cd /d "e:\电商客服V1.1\electron-client"

echo [1/3] Installing npm packages...
call npm install 2>&1

if errorlevel 1 (
    echo Install failed!
    exit /b 1
)

echo.
echo [2/3] Install complete!
echo [3/3] Starting Electron...
call npm start
