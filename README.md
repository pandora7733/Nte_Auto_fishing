# Nte_Auto_fishing

NTE 자동 낚시 봇 (Windows 전용)

## 필요 사항

- Windows 10/11
- [Python 3](https://www.python.org/downloads/) — 설치할 때 **"Add python.exe to PATH"** 체크

## 다운로드

**방법 1 — ZIP 다운로드**

GitHub 페이지에서 `Code` → `Download ZIP` → 원하는 위치에 압축 해제

**방법 2 — git clone**

```bash
git clone https://github.com/pandora7733/Nte_Auto_fishing.git
```

## 실행

`run_nte_fishing.bat`을 더블클릭하고 관리자 권한(UAC)을 허용하세요.

처음 실행할 때 `venv` 가상환경 생성과 패키지 설치가 자동으로 진행됩니다(1~2분 소요). 이후에는 바로 실행됩니다.

## 바탕화면 바로가기 만들기 (선택)

프로젝트 폴더에서 PowerShell을 열고 실행:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_shortcut.ps1
```

바탕화면·시작 메뉴·프로젝트 폴더에 `NTE_AutoFishing` 바로가기가 생성됩니다. 프로젝트 폴더를 옮겼다면 다시 실행하세요.

## 파일 구성

| 파일 | 설명 |
| --- | --- |
| `index.py` | 메인 프로그램 (GUI) |
| `index_debug.py` | 디버그용 스크립트 |
| `templates/` | 이미지 인식용 템플릿 |
| `run_nte_fishing.bat` | 실행 스크립트 (venv·패키지 자동 설치) |
| `create_shortcut.ps1` | 바로가기 생성 스크립트 |
| `requirements.txt` | 필요한 Python 패키지 목록 |
