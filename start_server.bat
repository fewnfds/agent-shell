@echo off
setlocal EnableExtensions EnableDelayedExpansion

echo.
echo Agent Shell will initialize the local runtime and start from this source clone.
set "INITIALIZE_CONFIRMATION="
set /p "INITIALIZE_CONFIRMATION=Continue with initialization? [y/n]: "
if /I not "!INITIALIZE_CONFIRMATION!"=="y" (
  echo Initialization cancelled.
  exit /b 0
)
echo.

set "SCRIPT_DIR=%~dp0"
set "RUNTIME_DIR=%SCRIPT_DIR%runtime"
set "APP_RUNTIME_DIR=%RUNTIME_DIR%\app"
set "PYTHON_HOME_FILE=%APP_RUNTIME_DIR%\python-home.txt"
set "BOOTSTRAP_SCRIPT=%SCRIPT_DIR%packaging\windows\bootstrap_runtime.ps1"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
set "PYTHON_EXE="
set "PYTHON_FLAGS=-I -B -X utf8"
set "SOURCE_APP_DIR=%SCRIPT_DIR%server\src"
set "SOURCE_FRONTEND_PREPARER=%SCRIPT_DIR%packaging\development\prepare_source_frontend.ps1"
set "EFFECTIVE_HOST="
set "EFFECTIVE_PORT="
set "OCCUPYING_PID="
set "PORT_FOUND="
set "PORT_STALE="
set "PORT_UNBINDABLE="
set "PORT_ACTION="

if exist "%SOURCE_APP_DIR%\agent_shell\__main__.py" (
  call :prepare_runtime
) else if not exist "%PYTHON_HOME_FILE%" (
  call :prepare_runtime
)
if errorlevel 1 goto runtime_failed

set /p PYTHON_HOME=<"%PYTHON_HOME_FILE%"
if not defined PYTHON_HOME goto runtime_failed
set "PYTHON_EXE=runtime\app\!PYTHON_HOME!\python.exe"
if not exist "%SCRIPT_DIR%!PYTHON_EXE!" (
  call :prepare_runtime
  if errorlevel 1 goto runtime_failed
  set /p PYTHON_HOME=<"%PYTHON_HOME_FILE%"
  set "PYTHON_EXE=runtime\app\!PYTHON_HOME!\python.exe"
)
if not exist "%SCRIPT_DIR%!PYTHON_EXE!" goto runtime_failed

set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE="
set "PATH=%SCRIPT_DIR%runtime\app\!PYTHON_HOME!;%PATH%"
if exist "%SOURCE_APP_DIR%\agent_shell\__main__.py" (
  set "PYTHONPATH=%SOURCE_APP_DIR%"
  set "PYTHONNOUSERSITE=1"
  set "PYTHON_FLAGS=-s -P -B -X utf8"
  if not exist "%SOURCE_FRONTEND_PREPARER%" goto source_frontend_failed
  "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%SOURCE_FRONTEND_PREPARER%" -ProjectRoot "%SCRIPT_DIR%."
  if errorlevel 1 goto source_frontend_failed
)

pushd "%SCRIPT_DIR%"
for /f "tokens=1,2 delims=|" %%H in ('!PYTHON_EXE! !PYTHON_FLAGS! -m agent_shell --home "%SCRIPT_DIR%." --prepare-launch-settings') do (
  set "EFFECTIVE_HOST=%%H"
  set "EFFECTIVE_PORT=%%I"
)
popd

if not defined EFFECTIVE_PORT (
  echo.
  echo Agent Shell settings could not be loaded. Read the error message above.
  echo Settings are read from data\config\agent-shell.env.
  pause
  exit /b 2
)

call :check_port
if defined PORT_FOUND (
  if defined PORT_UNBINDABLE goto port_unbindable
  if defined PORT_STALE (
    echo Port !EFFECTIVE_PORT! is reported in use by stale PID !OCCUPYING_PID!.
    echo Windows no longer shows that PID in the process table.
  ) else (
    echo Port !EFFECTIVE_PORT! is already in use by PID !OCCUPYING_PID!.
  )
  echo.
  echo 1. Close PID !OCCUPYING_PID! and start on port !EFFECTIVE_PORT!
  echo 2. Start on a different port
  echo 3. Do not start
  echo.
  set /p PORT_ACTION=Select an option [1/2/3]:

  if /I "!PORT_ACTION!"=="1" goto port_kill
  if /I "!PORT_ACTION!"=="2" goto port_change
  goto port_exit
)

:after_port_prompt
pushd "%SCRIPT_DIR%"
"!PYTHON_EXE!" !PYTHON_FLAGS! -m agent_shell --home "%SCRIPT_DIR%." --port !EFFECTIVE_PORT! --prepare-dependencies
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" pause
goto end

:port_kill
echo Closing PID !OCCUPYING_PID!...
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "try { Stop-Process -Id !OCCUPYING_PID! -Force -ErrorAction Stop; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 taskkill /PID !OCCUPYING_PID! /T /F >nul 2>&1

echo Waiting for port !EFFECTIVE_PORT! to be released...
for /L %%I in (1,1,10) do (
  ping -n 2 127.0.0.1 >nul
  call :check_port
  if not defined PORT_FOUND goto after_port_prompt
)

echo Port !EFFECTIVE_PORT! is still busy.
if defined PORT_STALE (
  echo Windows reports a stale listener for PID !OCCUPYING_PID!, but that PID cannot be closed because it no longer exists.
  echo This usually clears after Windows releases the socket, or after a reboot.
)
echo.
echo 1. Start on a different port
echo 2. Do not start
echo.
set "KILL_FALLBACK="
set /p KILL_FALLBACK=Select an option [1/2]:
if /I "!KILL_FALLBACK!"=="1" goto port_change
exit /b 1

:port_change
echo.
set "NEW_PORT="
set /p NEW_PORT=Enter a new port [1-65535]:
call :validate_new_port
if not defined PORT_VALID (
  echo Enter a whole number from 1 to 65535.
  goto port_change
)
set "EFFECTIVE_PORT=!NEW_PORT!"
call :check_port
if defined PORT_FOUND (
  if defined PORT_UNBINDABLE (
    echo Port !EFFECTIVE_PORT! cannot be bound. It may be reserved by Windows.
  ) else (
    echo Port !EFFECTIVE_PORT! is also in use by PID !OCCUPYING_PID!.
  )
  goto port_change
)
goto after_port_prompt

:port_unbindable
echo Port !EFFECTIVE_PORT! cannot be bound on !EFFECTIVE_HOST!.
echo Windows may have reserved it even though no process is listening.
echo.
echo 1. Start on a different port
echo 2. Do not start
echo.
set "PORT_ACTION="
set /p PORT_ACTION=Select an option [1/2]:
if /I "!PORT_ACTION!"=="1" goto port_change
goto port_exit

:port_exit
echo Not starting Agent Shell.
exit /b 0

:validate_new_port
set "PORT_VALID="
for /f "delims=" %%V in ('"%POWERSHELL_EXE%" -NoProfile -NonInteractive -Command "$port = 0; if ([int]::TryParse($env:NEW_PORT, [ref]$port) -and $port -ge 1 -and $port -le 65535) { Write-Output 1 }"') do set "PORT_VALID=%%V"
goto :eof

:prepare_runtime
if not exist "%POWERSHELL_EXE%" (
  echo Agent Shell requires the Windows PowerShell component included with supported Windows editions.
  exit /b 1
)
if not exist "%BOOTSTRAP_SCRIPT%" (
  echo Agent Shell runtime builder is missing: packaging\windows\bootstrap_runtime.ps1
  exit /b 1
)
echo Preparing the self-contained Agent Shell runtime...
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP_SCRIPT%" -ProjectRoot "%SCRIPT_DIR%."
exit /b %ERRORLEVEL%

:runtime_failed
echo.
echo Agent Shell could not prepare its self-contained runtime.
echo Check the network connection and the message above, then run start_server.bat again.
pause
exit /b 1

:source_frontend_failed
echo.
echo Agent Shell could not prepare the source frontend.
echo Check Node.js 22, the network connection, and the message above.
pause
exit /b 1

:check_port
set "OCCUPYING_PID="
set "PORT_FOUND="
set "PORT_STALE="
set "PORT_UNBINDABLE="
for /f "tokens=5" %%P in ('netstat -ano -p tcp ^| findstr /R /C:":!EFFECTIVE_PORT! .*LISTENING"') do (
  set "OCCUPYING_PID=%%P"
  set "PORT_FOUND=1"
  tasklist /FI "PID eq %%P" 2>nul | findstr /R /C:"^[a-zA-Z].*[ ]%%P[ ]" >nul
  if errorlevel 1 set "PORT_STALE=1"
  goto :eof
)
"%SCRIPT_DIR%!PYTHON_EXE!" !PYTHON_FLAGS! -m agent_shell --home "%SCRIPT_DIR%." --port !EFFECTIVE_PORT! --probe-listen-settings >nul 2>&1
if errorlevel 1 (
  set "PORT_FOUND=1"
  set "PORT_UNBINDABLE=1"
)
goto :eof

:end
exit /b %EXIT_CODE%
