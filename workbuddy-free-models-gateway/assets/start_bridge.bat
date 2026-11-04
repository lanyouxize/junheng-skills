@echo off
setlocal EnableDelayedExpansion
REM Self-contained start of workbuddy_to_api on port 3000.
REM NO_PROXY must be set so a local HTTP proxy does not intercept 127.0.0.1.
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost

REM Locate a python interpreter on PATH (do NOT hardcode a machine-specific path).
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (where py >nul 2>nul && set "PY=py")
if not defined PY (
  echo [ERR] python not found on PATH. Install Python 3.10+ and retry.
  pause
  exit /b 1
)

REM Locate WorkBuddy.exe: standard C: install, or D: when LOCALAPPDATA points to C:.
set "WBEXE="
if exist "%LOCALAPPDATA%\Programs\WorkBuddy\WorkBuddy.exe" (
  set "WBEXE=%LOCALAPPDATA%\Programs\WorkBuddy\WorkBuddy.exe"
)
if not defined WBEXE (
  for /d %%d in (D:\Users\*) do (
    if exist "%%d\AppData\Local\Programs\WorkBuddy\WorkBuddy.exe" (
      set "WBEXE=%%d\AppData\Local\Programs\WorkBuddy\WorkBuddy.exe"
    )
  )
)
if not defined WBEXE (
  if exist "C:\Program Files\WorkBuddy\WorkBuddy.exe" set "WBEXE=C:\Program Files\WorkBuddy\WorkBuddy.exe"
)
if not defined WBEXE (
  echo [ERR] WorkBuddy.exe not found. Set WORKBUDDY_EXE in .env or the env var.
  pause
  exit /b 1
)
set "CLI=!WBEXE:WorkBuddy.exe=resources\app.asar.unpacked\cli\bin\codebuddy!"

set "HERE=%~dp0"
set "WB2API=%HERE%workbuddy_to_api.py"
if not exist "%WB2API%" (
  echo [ERR] workbuddy_to_api.py missing: %WB2API%
  pause
  exit /b 1
)

echo Starting workbuddy_to_api on :3000  (WB=%WBEXE%)
"%PY%" "%WB2API%" --api-key local --workbuddy-exe "!WBEXE!" --cli-script "!CLI!"
