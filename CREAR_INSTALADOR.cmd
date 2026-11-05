@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto wrongfolder
if not exist "dist\KALA\KALA.exe" goto missingapp
if not exist "prerrequisitos\postgresql-18-windows-x64.exe" goto missingpostgres
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name Preparar_KALA --add-data "preparacion\kala_estructura.sql;." --add-data "preparacion\permisos.sql;." --collect-all psycopg_binary preparacion\preparar_kala.py
if errorlevel 1 goto failed
set "KALA_ISCC="
for %%D in ("%ProgramFiles%\Inno Setup 7" "%ProgramFiles(x86)%\Inno Setup 7" "%ProgramFiles%\Inno Setup 6" "%ProgramFiles(x86)%\Inno Setup 6") do if exist "%%~D\ISCC.exe" set "KALA_ISCC=%%~D\ISCC.exe"
if not defined KALA_ISCC goto compiler
"%KALA_ISCC%" "KALA_Nueva_PC.iss"
if errorlevel 1 goto failed
echo.
echo LISTO: instalador_salida\Instalar_KALA_Nueva_PC_1.0.1.exe
echo Debes probarlo en un Windows nuevo antes de entregar al cliente.
pause
exit /b 0
:wrongfolder
echo Copia este paquete dentro de PapeleriaKALA, junto a iniciar_kala.py y .venv.
goto failed
:missingapp
echo Falta dist\KALA\KALA.exe. Conserva toda la carpeta que ya generaste y probaste.
goto failed
:missingpostgres
echo Falta prerrequisitos\postgresql-18-windows-x64.exe. Consulta LEEME_PRIMERO.md.
goto failed
:compiler
echo Instala Inno Setup o abre KALA_Nueva_PC.iss en Inno Setup y pulsa F9.
goto failed
:failed
echo.
echo No se completo la compilacion. Conserva el error de arriba.
pause
exit /b 1
