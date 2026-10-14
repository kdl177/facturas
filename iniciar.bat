@echo off
cd /d "%~dp0"
where python >nul 2>nul || (echo Falta Python 3.11 o superior: https://www.python.org/downloads/ & pause & exit /b 1)
python facturas.py
