@echo off
setlocal enabledelayedexpansion
title CATT setup
color 07

set "BASE=%~dp0"
set "TARGET=%BASE%CATT"
set "ZIP=%BASE%catt-download.zip"

echo.
echo   ================================================
echo    CATT setup
echo   ================================================
echo.
echo   This will:
echo     1. check your current Python installation
echo     2. download CATT from GitHub into this folder
echo     3. create a venv for it
echo     4. install packages CATT needs
echo     5. open the command builder in your default browser
echo.
echo   It downloads ~200 MB of Python packages and
echo   needs an internet connection.
echo.
echo   Installing into: %TARGET%
echo.
pause

REM ------------------------------------------------------------------
REM 1. Find a usable Python
REM ------------------------------------------------------------------
echo.
echo   [1/5] Looking for Python.

set "PY="
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
) else (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    echo.
    echo   Python is not installed, or Windows is intercepting the
    echo   'python' command with its Microsoft Store shortcut.
    echo.
    echo   Install Python from:  https://www.python.org/downloads/
    echo.
    echo   IMPORTANT: on the first screen of the installer, tick
    echo   "Add python.exe to PATH" before clicking Install.
    echo.
    echo   Then run this file again.
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%V in ('%PY% -c "import sys;print('%%d.%%d'%%sys.version_info[:2])"') do set "PYVER=%%V"
for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
    set "PYMAJOR=%%a"
    set "PYMINOR=%%b"
)

echo         Found Python !PYVER!

if not "!PYMAJOR!"=="3" goto :badversion
if !PYMINOR! LSS 9 goto :badversion

if !PYMINOR! GEQ 14 (
    echo.
    echo         Note: Python !PYVER! is newer than anything CATT has
    echo         been tested against. If the install fails, Python 3.12
    echo         is the safe choice.
    echo.
)
goto :versionok

:badversion
echo.
echo   CATT needs Python 3.9 or newer. You have !PYVER!.
echo   Install a current version from https://www.python.org/downloads/
echo.
pause
exit /b 1

:versionok

REM ------------------------------------------------------------------
REM 2. Download CATT
REM ------------------------------------------------------------------
echo.
echo   [2/5] Downloading CATT from GitHub.

if exist "%TARGET%\main.py" (
    echo         Already downloaded. Keeping the existing copy.
    goto :havefiles
)

where curl.exe >nul 2>&1
if errorlevel 1 goto :usepowershell

curl.exe -L --fail --silent --show-error -o "%ZIP%" "https://codeload.github.com/mgbpm/CATT/zip/refs/heads/master"
if errorlevel 1 goto :usepowershell
goto :unzip

:usepowershell
echo         Using PowerShell to download.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri 'https://codeload.github.com/mgbpm/CATT/zip/refs/heads/master' -OutFile '%ZIP%' } catch { exit 1 }"
if errorlevel 1 (
    echo.
    echo   Could not download CATT. Check your internet connection.
    echo.
    pause
    exit /b 1
)

:unzip
echo         Extracting.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue'; Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%BASE%' -Force"
if errorlevel 1 (
    echo   Could not extract the download.
    pause
    exit /b 1
)

if exist "%BASE%CATT-master" (
    move "%BASE%CATT-master" "%TARGET%" >nul
)
del "%ZIP%" >nul 2>&1

if not exist "%TARGET%\main.py" (
    echo.
    echo   Something went wrong: main.py is not where it should be.
    echo   Expected: %TARGET%\main.py
    echo.
    pause
    exit /b 1
)

:havefiles

REM ------------------------------------------------------------------
REM 3. Copy the builder files in
REM ------------------------------------------------------------------
copy /Y "%BASE%catt_ui.py" "%TARGET%\" >nul
copy /Y "%BASE%catt-builder.html" "%TARGET%\" >nul
copy /Y "%BASE%requirements-catt.txt" "%TARGET%\" >nul
if not exist "%TARGET%\catt_ui.py" (
    echo.
    echo   catt_ui.py and catt-builder.html must sit next to this
    echo   file. Unzip the whole download and try again.
    echo.
    pause
    exit /b 1
)

REM ------------------------------------------------------------------
REM 4. Create the environment and install packages
REM ------------------------------------------------------------------
echo.
echo   [3/5] Creating a private Python environment.

cd /d "%TARGET%"

if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if errorlevel 1 (
        echo.
        echo   Could not create the environment. If Python was installed
        echo   from the Microsoft Store, reinstall it from python.org
        echo   instead
        echo.
        pause
        exit /b 1
    )
) else (
    echo         Environment already exists.
)

set "VPY=%TARGET%\.venv\Scripts\python.exe"

echo.
echo   [4/5] Installing packages.
echo.

"%VPY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%VPY%" -m pip install -r requirements-catt.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo   Package installation failed. The message above says why.
    echo.
    echo   The usual cause is a corporate proxy blocking pypi.org.
    echo.
    pause
    exit /b 1
)

"%VPY%" -c "import pandas,numpy,sklearn,yaml,requests,dateparser,genshi,pytz" 2>nul
if errorlevel 1 (
    echo.
    echo   The packages installed but will not import. Something is odd
    echo   with this Python installation.
    echo.
    pause
    exit /b 1
)

REM ------------------------------------------------------------------
REM 5. Shortcut for next time, then launch
REM ------------------------------------------------------------------
> "%BASE%Start CATT.bat" echo @echo off
>>"%BASE%Start CATT.bat" echo title CATT
>>"%BASE%Start CATT.bat" echo cd /d "%%~dp0CATT"
>>"%BASE%Start CATT.bat" echo if not exist ".venv\Scripts\python.exe" ^(
>>"%BASE%Start CATT.bat" echo    echo CATT is not set up yet. Run "Install CATT.bat" first. It's kinda impressive that this happened.
>>"%BASE%Start CATT.bat" echo    pause
>>"%BASE%Start CATT.bat" echo    exit /b 1
>>"%BASE%Start CATT.bat" echo ^)
>>"%BASE%Start CATT.bat" echo echo Starting CATT. Keep this window open while you work.
>>"%BASE%Start CATT.bat" echo echo Close it when you are done.
>>"%BASE%Start CATT.bat" echo echo.
>>"%BASE%Start CATT.bat" echo ".venv\Scripts\python.exe" catt_ui.py
>>"%BASE%Start CATT.bat" echo pause

echo.
echo   [5/5] Done.
echo.
echo   ================================================
echo    Setup finished
echo   ================================================
echo.
echo   From now on, to start the program, double-click "Start CATT.bat" in
echo   %BASE%
echo.
echo   Opening the builder now. Keep this window open
echo   while you use it as closing it stops CATT.
echo.
echo   Nothing has been downloaded from ClinVar yet. Use
echo   the "Download all source data" recipe first; it
echo   takes a while and pulls several gigabytes.
echo.

"%VPY%" catt_ui.py

echo.
echo   CATT has stopped.
pause
