@echo off
set "PATH=C:\Program Files\nodejs;%PATH%"
set "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/"

cd /d "e:\电商客服V1.1\electron-client"

echo Removing broken electron...
rmdir /s /q node_modules\electron 2>nul

echo Installing electron...
call npm install electron --registry https://registry.npmmirror.com

echo.
echo Done! Starting app...
call npm start
