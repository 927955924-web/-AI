@echo off
echo Starting Django Backend Server...
cd /d %~dp0
python manage.py runserver 8000
pause
