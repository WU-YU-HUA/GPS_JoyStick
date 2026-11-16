@echo off
setlocal
pushd "%~dp0"
set "GPS_BUILD_CONDA="
if defined CONDA_EXE if exist "%CONDA_EXE%" set "GPS_BUILD_CONDA=%CONDA_EXE%"
if not defined GPS_BUILD_CONDA for /f "delims=" %%C in ('where conda 2^>nul') do if not defined GPS_BUILD_CONDA set "GPS_BUILD_CONDA=%%C"
if not defined GPS_BUILD_CONDA if exist "%USERPROFILE%\anaconda3\condabin\conda.bat" set "GPS_BUILD_CONDA=%USERPROFILE%\anaconda3\condabin\conda.bat"
if not defined GPS_BUILD_CONDA if exist "%USERPROFILE%\miniconda3\condabin\conda.bat" set "GPS_BUILD_CONDA=%USERPROFILE%\miniconda3\condabin\conda.bat"
if not defined GPS_BUILD_CONDA (
    echo [ERROR] Conda was not found. Run this file from an Anaconda Prompt.
    set "GPS_BUILD_EXIT=1"
    goto finish
)

if /i "%~1"=="--check" goto check
echo Installing build dependencies in the iphone-gps environment...
call "%GPS_BUILD_CONDA%" run --no-capture-output -n iphone-gps python -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
echo Building the single-file EXE...
call "%GPS_BUILD_CONDA%" run --no-capture-output -n iphone-gps powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1"
if errorlevel 1 goto failed
set "GPS_BUILD_EXIT=0"
goto finish

:check
echo Checking the iphone-gps environment. No installation or build will run.
call "%GPS_BUILD_CONDA%" run --no-capture-output -n iphone-gps python -c "import sys, PySide6, PyInstaller; print(sys.executable); print('Environment OK')"
set "GPS_BUILD_EXIT=%ERRORLEVEL%"
goto finish

:failed
set "GPS_BUILD_EXIT=1"
echo [ERROR] Build failed. Review the output above.

:finish
popd
if /i not "%~1"=="--check" pause
exit /b %GPS_BUILD_EXIT%
