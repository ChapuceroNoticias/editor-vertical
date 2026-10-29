@echo off
rem Algunas PCs tienen el PATH de Windows danado (no encuentran ni powershell): se repara para esta ventana
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0;%PATH%"
"%SystemRoot%\System32\chcp.com" 65001 >nul
title Instalando Editor Vertical - El Chapucero
cd /d "%~dp0"
if not exist "%~dp0instalar.ps1" goto :falta
if not exist "%~dp0app\interfaz.py" goto :falta
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1" -Origen "%~dp0."
if errorlevel 1 goto :error
exit /b 0

:falta
echo.
echo  No encuentro los archivos del instalador junto a este archivo.
echo  Primero descomprime TODO el zip: clic derecho sobre el zip, "Extraer todo",
echo  y despues abre Instalar.bat desde la carpeta que se crea.
echo.
pause
exit /b 1

:error
echo.
echo  La instalacion no termino. Toma una foto de esta ventana y mandala.
echo  Detalles en: %LOCALAPPDATA%\EditorVertical\instalacion.log
echo.
pause
exit /b 1
