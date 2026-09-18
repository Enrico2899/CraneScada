@echo off
REM Crea CraneScada.exe in dist\ usando PyInstaller.
REM Va lanciato SUL PC WINDOWS (non e' possibile compilare un .exe da un
REM ambiente Linux), con il venv del progetto gia' creato (vedi README.md).
REM Uso: build_exe.bat  oppure  build_exe.bat --windowed  (per nascondere la console)

call venv\Scripts\activate
if errorlevel 1 (
    echo Impossibile attivare venv\Scripts\activate.bat - hai gia' creato il venv? (vedi README.md)
    exit /b 1
)

pip install --quiet pyinstaller

set CONSOLE_FLAG=--console
if "%1"=="--windowed" set CONSOLE_FLAG=--windowed

pyinstaller --noconfirm --name CraneScada --onefile %CONSOLE_FLAG% main.py

echo.
echo Fatto. Eseguibile in dist\CraneScada.exe
pause
