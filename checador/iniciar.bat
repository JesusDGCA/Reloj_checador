@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Checador
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  Preparando el programa por primera vez. Tarda un par de minutos...
  echo.
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo  No se encontro Python en esta computadora.
    echo  Instalalo desde https://www.python.org/downloads/
    echo  y marca la casilla "Add python.exe to PATH". Luego vuelve a abrir este archivo.
    pause
    exit /b
  )
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 (
    echo  No se pudieron descargar los componentes. Revisa tu conexion a internet.
    rmdir /s /q .venv
    pause
    exit /b
  )
)
".venv\Scripts\python.exe" app.py %*
pause
