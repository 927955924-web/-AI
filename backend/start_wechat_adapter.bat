@echo off
chcp 65001 >nul
title 微信PC客户端适配器服务

echo ============================================
echo   微信 PC 客户端适配器服务
echo ============================================
echo.

cd /d "%~dp0"

echo 检查依赖...
pip show uiautomation >nul 2>&1
if errorlevel 1 (
    echo 正在安装 uiautomation...
    pip install uiautomation
)

pip show pywin32 >nul 2>&1
if errorlevel 1 (
    echo 正在安装 pywin32...
    pip install pywin32
)

echo.
echo 使用前请确保:
echo 1. 微信 PC 客户端已启动并登录
echo 2. 微信窗口未最小化
echo.
echo 启动服务中...
echo.

python adapters\run_wechat_service.py

pause
