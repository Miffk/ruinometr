@echo off
rem Запуск локального Ruiner: http://127.0.0.1:8000
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -m venv .venv || python -m venv .venv || exit /b 1
  .venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
)
rem Свой парсер реплеев. Без него разбор работает, но без AFK, карты и сигналов из реплея.
if not exist parser\target\ruiner-parser.jar (
  where java >nul 2>nul
  if errorlevel 1 (
    echo Java не найдена: парсер реплеев не собран, разбор пойдёт без него. Нужен JDK 21+.
  ) else (
    echo Собираю парсер реплеев, первый раз это пара минут...
    call parser\mvnw.cmd -q -f parser\pom.xml package -DskipTests
  )
)
start "" http://127.0.0.1:8000
.venv\Scripts\python.exe -m uvicorn ruiner.app:app --host 127.0.0.1 --port 8000
