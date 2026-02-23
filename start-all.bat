@echo off
echo ======================================
echo  E-Commerce Customer Service System
echo ======================================
echo.

echo Starting Backend Server...
start "Django Backend" cmd /c "cd /d %~dp0backend && python manage.py runserver 8000"

timeout /t 3 /nobreak > nul

echo Starting Frontend Dev Server...
start "Vue Frontend" cmd /c "cd /d %~dp0frontend && npm run dev"

echo.
echo ======================================
echo  Services Started:
echo  - Backend: http://localhost:8000
echo  - Frontend: http://localhost:5173
echo ======================================
echo.
echo Press any key to exit...
pause > nul
