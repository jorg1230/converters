@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual...
    py -m venv .venv
    if errorlevel 1 (
        python -m venv .venv
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo No se pudo crear el entorno virtual. Verifica que Python este instalado.
    pause
    exit /b 1
)

echo Instalando dependencias de la aplicacion...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo No se pudieron instalar las dependencias de la aplicacion.
    pause
    exit /b 1
)

echo Instalando PyInstaller...
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 (
    echo No se pudo instalar PyInstaller.
    pause
    exit /b 1
)

echo Creando ejecutable...
".venv\Scripts\python.exe" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name ConvertidorImagenes ^
    --collect-all pillow_heif ^
    convertir_imagenes.py

if errorlevel 1 (
    echo No se pudo crear el ejecutable.
    pause
    exit /b 1
)

echo.
echo Ejecutable creado correctamente:
echo %cd%\dist\ConvertidorImagenes.exe
echo.
pause

endlocal
