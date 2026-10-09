@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

REM 관리자 권한 확인 — 없으면 UAC로 재실행
net session >nul 2>&1
if %errorLevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

REM venv 가상환경이 없으면 자동 생성 (처음 다운로드한 PC에서 최초 1회)
if exist "venv\Scripts\python.exe" goto :venv_ok

set "SYS_PY="
py -3 --version >nul 2>&1 && set "SYS_PY=py -3"
if not defined SYS_PY (
    python --version >nul 2>&1 && set "SYS_PY=python"
)
if not defined SYS_PY (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo https://www.python.org/downloads/ 에서 Python 3을 설치한 뒤 다시 실행하세요.
    echo 설치 시 "Add python.exe to PATH" 옵션을 체크하세요.
    pause
    exit /b 1
)

echo [설치] venv 가상환경을 생성합니다...
%SYS_PY% -m venv venv
if errorlevel 1 (
    echo [오류] venv 생성에 실패했습니다.
    pause
    exit /b 1
)

:venv_ok
if exist "venv\Scripts\pythonw.exe" (
    set "PY=venv\Scripts\pythonw.exe"
) else (
    set "PY=venv\Scripts\python.exe"
)

REM 의존성 빠른 확인 — 없으면 설치
"%PY%" -c "import cv2,mss,pydirectinput,PIL" 1>nul 2>nul
if not errorlevel 1 goto :run

echo [설치] 필요한 패키지를 설치합니다...
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [오류] 패키지 설치에 실패했습니다.
    pause
    exit /b 1
)

:run
start "" "%PY%" "%~dp0index.py"
endlocal
