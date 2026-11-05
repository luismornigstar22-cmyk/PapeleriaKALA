$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path 'kala_login.py')) { throw 'Falta tu kala_login.py en esta carpeta.' }
python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'No se pudo instalar PyInstaller.' }
python -m PyInstaller --noconfirm --clean --windowed --onedir --name KALA --collect-submodules keyring.backends --collect-data botocore --collect-data reportlab --add-data 'assets;assets' iniciar_kala.py
if ($LASTEXITCODE -ne 0) { throw 'Falló el empaquetado. Conserva el registro para revisión.' }
Write-Host 'Resultado: dist\KALA\KALA.exe. Conserva y distribuye la carpeta KALA completa.'
