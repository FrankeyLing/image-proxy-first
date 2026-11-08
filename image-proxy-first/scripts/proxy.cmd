@echo off
setlocal
"%~dp0..\bin\windows-x64\image-proxy.exe" %*
set "proxy_result=%errorlevel%"
if not "%proxy_result%"=="78" exit /b %proxy_result%
if exist "%~dp0..\.venv\Scripts\python.exe" (
  "%~dp0..\.venv\Scripts\python.exe" "%~dp0proxy_fallback.py" %*
) else (
  python "%~dp0proxy_fallback.py" %*
)
exit /b %errorlevel%
