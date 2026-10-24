@echo off
cd /d "%~dp0"
title NorthByNorthwest (NXNW) -- Launching...
echo.
echo  ==========================================
echo   NorthByNorthwest (NXNW)
echo   Continuum of Care Master Data Engine
echo   Rogue River Valley
echo  ==========================================
echo.

set PYTHON_EXE=runtime\python\python.exe

:: Confirm setup has been run
if not exist "%PYTHON_EXE%" (
    echo  [ERROR] Setup has not been run yet.
    echo.
    echo  Please double-click setup.bat first, then try again.
    echo.
    pause
    exit /b 1
)

:: Launch app
echo  Starting NXNW app...
echo  Your browser will open automatically to: http://localhost:8501
echo.
start "" http://localhost:8501
"%PYTHON_EXE%" -m streamlit run app.py --server.headless true --server.port 8501
pause
