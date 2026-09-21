@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python was not found.
        echo Install Python 3 from https://www.python.org/downloads/windows/
        echo During installation, select "Add Python to PATH", then run this file again.
        pause
        exit /b 1
    )
    set "PYTHON_CMD=python"
)

echo Checking Python dependencies...
%PYTHON_CMD% -c "import playwright" >nul 2>&1
if errorlevel 1 (
    echo Installing missing dependencies...
    %PYTHON_CMD% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ERROR: Dependency installation failed.
        pause
        exit /b 1
    )
)

echo.
%PYTHON_CMD% facebook_group_scanner.py %*
if errorlevel 1 (
    echo.
    echo The scanner stopped with an error. Review the message above.
    pause
    exit /b 1
)

endlocal
